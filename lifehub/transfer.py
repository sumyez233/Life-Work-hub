"""本地文件直传手机飞书模块。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import requests

from .config import CFG

log = logging.getLogger(__name__)

INBOX_DIR: Path = CFG.transfer.inbox_dir


def _get_token() -> str | None:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = {"app_id": CFG.feishu.app_id, "app_secret": CFG.feishu.app_secret}
    try:
        res = requests.post(url, json=data, timeout=10)
        return res.json().get("tenant_access_token")
    except Exception as e:
        log.error("获取 tenant_access_token 失败: %s", e)
        return None


import datetime

_IGNORE_DIRS = {".git", ".venv", "node_modules", "__pycache__", "$RECYCLE.BIN", "System Volume Information", ".idea", ".vscode"}

# 保存每个会话最近一次搜索产生的候选文件列表：chat_id -> list[Path]
_PENDING_CANDIDATES: dict[str, list[Path]] = {}


def get_candidates(chat_id: str) -> list[Path]:
    """获取会话当前的待确认文件列表。"""
    return _PENDING_CANDIDATES.get(chat_id, [])


def set_candidates(chat_id: str, candidates: list[Path]) -> None:
    """设置会话当前的待确认文件列表。"""
    _PENDING_CANDIDATES[chat_id] = candidates


def clear_candidates(chat_id: str) -> None:
    """清空会话当前的待确认文件列表。"""
    _PENDING_CANDIDATES.pop(chat_id, None)


def search_files(keyword: str, max_results: int = 5, max_depth: int = 4) -> list[Path]:
    """在常用项目目录中深度递归搜索文件，按最新修改时间（mtime）倒序返回。"""
    keyword = keyword.strip().strip("'\"")
    if not keyword:
        return []

    # 1. 如果是绝对路径或相对路径且就是现有文件，直接返回唯一项
    p = Path(keyword)
    try:
        if p.is_file():
            return [p]
    except Exception:
        pass

    clean_kw = keyword.lower()
    matches: list[Path] = []
    seen: set[Path] = set()

    for d in CFG.transfer.search_dirs:
        root_dir = Path(d)
        if not root_dir.is_dir():
            continue
        try:
            # 限制遍历深度，避免无休止扫描整个巨型磁盘
            root_parts_len = len(root_dir.parts)
            for root, dirs, files in os.walk(root_dir):
                # 过滤无用/巨型隐藏目录
                dirs[:] = [sub for sub in dirs if sub not in _IGNORE_DIRS and not sub.startswith(".")]
                cur_depth = len(Path(root).parts) - root_parts_len
                if cur_depth >= max_depth:
                    dirs.clear()  # 不再深入

                for fname in files:
                    if clean_kw in fname.lower():
                        full_path = Path(root) / fname
                        if full_path not in seen:
                            seen.add(full_path)
                            matches.append(full_path)
        except Exception as e:
            log.warning("遍历目录 %s 异常: %s", d, e)
            continue

    # 按修改时间（mtime）倒序排列：最新的文件排在最前
    def _mtime_key(item: Path) -> float:
        try:
            return item.stat().st_mtime
        except Exception:
            return 0.0

    matches.sort(key=_mtime_key, reverse=True)
    return matches[:max_results]


def format_candidate_list(keyword: str, candidates: list[Path]) -> str:
    """将候选文件格式化为飞书提示文案。"""
    lines = [f"🔍 找到 {len(candidates)} 个与「{keyword}」相关的文件（已按最新修改排序）："]
    for i, path in enumerate(candidates, 1):
        try:
            mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
            size_kb = path.stat().st_size / 1024
            size_str = f"{size_kb / 1024:.1f}MB" if size_kb >= 1024 else f"{size_kb:.0f}KB"
        except Exception:
            mtime = "未知时间"
            size_str = ""
        lines.append(f"{i}. 📄 {path.name}\n   🕒 {mtime} | {size_str}\n   📂 {path.parent}")
    lines.append("\n💡 请直接回复序号（如「1」或「/send 1」）立刻推送该文件。")
    return "\n".join(lines)


def find_file(keyword: str) -> Path | None:
    """单文件快速查找（优先最新修改文件）。"""
    res = search_files(keyword, max_results=1)
    return res[0] if res else None


def send_file(file_path: str | Path, chat_id: str | None = None) -> tuple[bool, str]:
    """上传本地文件并推送到指定会话（默认推送至当前会话或 report_chat）。"""
    path = Path(file_path)
    if not path.is_file():
        return False, f"未找到文件: {file_path}"

    target_chat = chat_id or CFG.feishu.report_chat
    if not target_chat:
        return False, "未配置接收消息的 chat_id"

    token = _get_token()
    if not token:
        return False, "获取飞书凭据失败"

    file_name = path.name
    # 1. 上传文件获取 file_key
    upload_url = "https://open.feishu.cn/open-apis/im/v1/files"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"file_type": "stream", "file_name": file_name}

    try:
        with open(path, "rb") as f:
            files = {"file": (file_name, f, "application/octet-stream")}
            res = requests.post(upload_url, headers=headers, data=data, files=files, timeout=60).json()

        if res.get("code") != 0:
            return False, f"文件上传失败: {res.get('msg')}"

        file_key = res["data"]["file_key"]

        # 2. 推送到聊天
        send_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        headers["Content-Type"] = "application/json; charset=utf-8"
        body = {
            "receive_id": target_chat,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key})
        }
        send_res = requests.post(send_url, headers=headers, json=body, timeout=15).json()
        if send_res.get("code") == 0:
            return True, f"已发送「{file_name}」到飞书"
        return False, f"消息推送失败: {send_res.get('msg')}"
    except Exception as e:
        return False, f"传输异常: {e}"


def download_message_resource(
    message_id: str,
    file_key: str,
    file_name: str,
    res_type: str = "file"
) -> tuple[bool, str, Path | None]:
    """从飞书下载用户发送的文件或图片到本地收件箱（默认项目内 inbox/，可在 config.toml 覆盖）。"""
    token = _get_token()
    if not token:
        return False, "获取飞书凭据失败", None

    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type={res_type}"
    headers = {"Authorization": f"Bearer {token}"}

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    target_path = INBOX_DIR / file_name

    # 如果同名文件存在，追加时间戳后缀避免覆盖
    if target_path.exists():
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        stem, suffix = target_path.stem, target_path.suffix
        target_path = INBOX_DIR / f"{stem}_{ts}{suffix}"

    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=60)
        if resp.status_code != 200:
            return False, f"下载失败 HTTP {resp.status_code}: {resp.text[:100]}", None

        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        return True, "下载成功", target_path
    except Exception as e:
        return False, f"下载出错: {e}", None
