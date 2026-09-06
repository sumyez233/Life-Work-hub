"""飞书 → Codex CLI 直通执行器。

设计要点：
- 支持飞书话题 Thread 级多轮连续会话（通过 codex exec resume <session_id> 自动续聊）；
- 默认读取 config.toml [codex].sandbox（Windows 推荐 danger-full-access 避免命名管道与目录锁）；
- 只在 [codex].allowed_chats 白名单会话内响应；
- 同一 bot 进程同一时间只跑一个 Codex 任务，避免并发抢锁；
- 全程无窗口（CREATE_NO_WINDOW），超时用 taskkill /T 连带子进程清理。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import tempfile
import json
from pathlib import Path

from .config import CFG, ROOT

_lock = threading.Lock()
# 飞书话题/会话 -> Codex session_id 持久化映射
_SESSIONS_FILE = ROOT / "data" / "codex_sessions.json"


def _load_sessions() -> dict[str, str]:
    if _SESSIONS_FILE.exists():
        try:
            return json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_sessions(sessions: dict[str, str]) -> None:
    try:
        _SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SESSIONS_FILE.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] Failed to persist codex sessions: {e}", flush=True)


_thread_sessions: dict[str, str] = _load_sessions()


def enabled_for(chat_id: str | None) -> bool:
    """该会话是否允许触发 Codex。"""
    if not CFG.codex.enabled:
        return False
    if not CFG.codex.allowed_chats:
        return False
    return (chat_id or "") in CFG.codex.allowed_chats


def busy() -> bool:
    return _lock.locked()


def get_session(thread_key: str) -> str | None:
    return _thread_sessions.get(thread_key)


def set_session(thread_key: str, session_id: str) -> None:
    _thread_sessions[thread_key] = session_id
    _save_sessions(_thread_sessions)


def clear_session(thread_key: str) -> bool:
    res = _thread_sessions.pop(thread_key, None) is not None
    if res:
        _save_sessions(_thread_sessions)
    return res


def execute(prompt: str, session_id: str | None = None) -> tuple[bool, str, str | None]:
    """同步执行一次 Codex 任务，返回 (ok, 文本, session_id)。供测试与后台线程复用。"""
    exe = shutil.which("codex")
    if not exe:
        return False, "本机未找到 codex CLI（codex exec 不可用）", None

    # 用 -o 抓取 agent 的最终回复
    fd, out_path = tempfile.mkstemp(suffix=".md", prefix="lifehub_codex_")
    os.close(fd)
    out_file = Path(out_path)

    try:
        is_danger = (CFG.codex.sandbox == "danger-full-access")
        if session_id:
            # 连续多轮续聊：codex exec resume -o <out> <session_id> <prompt>
            args = [exe, "exec", "resume"]
            if is_danger:
                args.append("--dangerously-bypass-approvals-and-sandbox")
            else:
                args += ["--sandbox", CFG.codex.sandbox]
            args += ["-o", str(out_file), session_id, prompt]
        else:
            # 新开会话：codex exec --color never ...
            args = [exe, "exec", "--color", "never"]
            if is_danger:
                args.append("--dangerously-bypass-approvals-and-sandbox")
            else:
                args += ["--sandbox", CFG.codex.sandbox]
            args += ["-C", str(CFG.codex.workdir), "-o", str(out_file)]
            if CFG.codex.model:
                args += ["-m", CFG.codex.model]
            args.append(prompt)

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            cwd=str(CFG.codex.workdir),
            env={**os.environ, "NO_COLOR": "1"},
        )
        try:
            out, err = proc.communicate(timeout=CFG.codex.timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            return False, (f"执行超时（>{CFG.codex.timeout_seconds}s），已强制终止。"
                           f"如需更长时间请在 config.toml [codex].timeout_seconds 调大。"), session_id

        combined = (out or "") + "\n" + (err or "")
        captured_sid = session_id
        if sid_match := re.search(r"session id:\s*([0-9a-fA-F-]+)", combined):
            captured_sid = sid_match.group(1)

        if out_file.exists() and out_file.stat().st_size:
            text = out_file.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return True, text, captured_sid

        if proc.returncode != 0:
            tail = (err or out).strip().splitlines()[-8:]
            return False, "Codex 退出码 {}\n{}".format(proc.returncode, "\n".join(tail)), captured_sid
        # 无 -o 输出时退回 stdout 尾巴
        tail = (out or "（无输出）").strip()
        return True, tail[-CFG.codex.max_output_chars:], captured_sid
    finally:
        try:
            out_file.unlink(missing_ok=True)
        except Exception:
            pass


def start(prompt: str, on_done, session_id: str | None = None) -> bool:
    """后台线程执行；完成后回调 on_done(ok: bool, text: str, session_id: str | None)。

    返回 False 表示已有任务在跑、本次未接收。
    """
    if not _lock.acquire(blocking=False):
        return False

    def worker() -> None:
        try:
            ok, text, sid = execute(prompt, session_id=session_id)
            on_done(ok, text, sid)
        except Exception as e:
            try:
                on_done(False, f"Codex 任务内部异常：{e}", session_id)
            except Exception:
                pass
        finally:
            _lock.release()

    threading.Thread(target=worker, daemon=True, name="lifehub-codex").start()
    return True


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except Exception:
        pass
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass
