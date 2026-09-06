"""命令行入口。常用命令：

  python -m lifehub.cli add "明天下午3点开会"   # 快速录入
  python -m lifehub.cli todos                  # 看待办
  python -m lifehub.cli done 3                 # 完成 #3
  python -m lifehub.cli report                 # 立即发一次晨报
  python -m lifehub.cli serve                  # 启动常驻服务（含定时晨报）
  python -m lifehub.cli bot                    # 启动飞书对话机器人
"""
from __future__ import annotations

import argparse
import sys

# Windows 控制台默认 GBK，强制 UTF-8 以正常显示中文与符号
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from . import db, parser, report, reminders
from .config import CFG

_LOCK_HANDLES: dict[str, object] = {}


def _acquire_lock(name: str) -> bool:
    """跨平台文件锁实现单实例互斥，避免多个 bot/serve 实例并发运行导致消息重复。"""
    import os
    import sys
    from pathlib import Path
    from .config import ROOT

    lock_dir = ROOT / "data"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / f"{name}.lock"
    fd = None
    try:
        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_HANDLES[name] = fd
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        return True
    except (OSError, PermissionError):
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        return False


def _release_lock(name: str) -> None:
    """释放指定名称的实例锁（进程退出时会自动释放，此函数供显式释放与测试用）。"""
    import os
    fd = _LOCK_HANDLES.pop(name, None)
    if fd is not None:
        try:
            os.close(fd)
        except Exception:
            pass


def _cmd_add(text: str) -> None:
    p = parser.parse(text)
    if p.kind == "event":
        eid = db.add_event(p.title, db.fmt_when(p.when), source="cli")  # type: ignore[arg-type]
        print(f"已记日程 ✓ #{eid} {p.title} @ {p.when:%m-%d %H:%M}")
    elif p.kind == "ledger":
        lid = db.add_ledger(p.amount, p.category, p.note, source="cli",
                            kind=p.direction or "expense")  # type: ignore[arg-type]
        tag = "收入" if p.direction == "income" else p.category
        print(f"已记{tag} #{lid} {p.amount:g} 元")
    else:
        tid = db.add_todo(p.title, p.when.date().isoformat() if p.when else None,
                          p.priority, source="cli")
        print(f"已记待办 ✓ #{tid} {p.title}" + (f"（截止 {p.when:%m-%d}）" if p.when else ""))


def _cmd_todos() -> None:
    rows = db.list_todos()
    if not rows:
        print("（没有打开的待办）")
        return
    for r in rows:
        due = r["due"][:10] if r["due"] else "—"
        pri = "❗" if r["priority"] else "  "
        print(f"#{r['id']:<3} {pri} [{due}] {r['title']}")


def _cmd_serve() -> None:
    import threading

    import uvicorn
    from apscheduler.schedulers.background import BackgroundScheduler

    db.init_db()
    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    hh, mm = map(int, CFG.hub.report_time.split(":"))
    sched.add_job(report.send_report, "cron", hour=hh, minute=mm, id="morning_report")
    sched.add_job(reminders.check_and_push, "interval", minutes=1, id="reminders",
                  max_instances=1, coalesce=True)
    sched.start()
    print(f"lifehub 服务已启动：http://localhost:{CFG.hub.port}"
          f"（晨报每日 {hh:02d}:{mm:02d} · 日程提前 {CFG.hub.remind_before} 分钟提醒）", flush=True)
    uvicorn.run("lifehub.api:app", host="127.0.0.1", port=CFG.hub.port, log_level="info")


def main() -> None:
    ap = argparse.ArgumentParser(prog="lifehub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="一句话录入")
    p_add.add_argument("text")
    sub.add_parser("todos", help="看待办")
    p_done = sub.add_parser("done", help="完成待办")
    p_done.add_argument("tid", type=int)
    sub.add_parser("report", help="立即发送晨报")
    p_rem = sub.add_parser("remind", help="立即扫描一次日程提醒（测试用）")
    p_rem.add_argument("--all", action="store_true", help="忽略去重，强制推送")
    sub.add_parser("chats", help="查看应用机器人所在的群")
    sub.add_parser("preview", help="只打印晨报不发送")
    sub.add_parser("serve", help="启动常驻服务（含定时晨报）")
    sub.add_parser("bot", help="启动飞书对话机器人")
    sub.add_parser("bitable", help="查看多维表格大盘统计")
    p_send = sub.add_parser("send", help="直传文件到手机飞书")
    p_send.add_argument("file_path", help="本地文件路径或关键字")
    args = ap.parse_args()

    if args.cmd == "add":
        _cmd_add(args.text)
    elif args.cmd == "todos":
        _cmd_todos()
    elif args.cmd == "done":
        print("✓ 已完成" if db.complete_todo(args.tid) else "没找到这条待办")
    elif args.cmd == "bitable":
        from . import bitable
        s = bitable.fetch_and_analyze() or bitable.get_cached_or_fresh()
        if not s.get("configured", True):
            print("✗ 未配置多维表格：请在 config.toml [bitable] 填入 app_token / table_id")
        else:
            line = f"📊 多维表格：共 {s['total_records']} 条记录"
            if s.get("latest_updated"):
                line += f"，最近更新 {s['latest_updated']}"
            print(line)
            if s.get("fetched_at"):
                print(f"  缓存快照：{s['fetched_at']}")
    elif args.cmd == "send":
        from . import transfer
        target = transfer.find_file(args.file_path)
        if not target:
            print(f"✗ 未在常用目录找到: {args.file_path}")
        else:
            ok, msg = transfer.send_file(target)
            print(("✓ " if ok else "✗ ") + msg)
    elif args.cmd == "remind":
        if args.all:
            import sqlite3
            c = db.connect()
            c.execute("DELETE FROM reminders_sent")
            c.commit()
            c.close()
        pushed = reminders.check_and_push()
        print("已推送：" + "、".join(pushed) if pushed else "未来 {} 分钟内没有待提醒的日程".format(CFG.hub.remind_before))
    elif args.cmd == "chats":
        from .push import list_chats
        items, msg = list_chats()
        if not items:
            print(f"✗ {msg}")
        else:
            for cid, name in items:
                print(f"{cid}  {name}")
            print("\n把目标群的 chat_id 填到 config.toml → feishu.report_chat 可固定晨报群")
    elif args.cmd == "report":
        ok, msg = report.send_report()
        print(("✓ " if ok else "✗ ") + msg)
        if not ok:
            print(report.build_report())
    elif args.cmd == "preview":
        print(report.build_report())
    elif args.cmd == "serve":
        if not _acquire_lock("serve"):
            print("[WARN] 已有 serve 服务在后台运行中，请勿重复启动！", flush=True)
            sys.exit(0)
        _cmd_serve()
    elif args.cmd == "bot":
        if not _acquire_lock("bot"):
            print("[WARN] 已有 bot 机器人在后台运行中，请勿重复启动！", flush=True)
            sys.exit(0)
        from . import bot
        bot.start()


if __name__ == "__main__":
    main()
