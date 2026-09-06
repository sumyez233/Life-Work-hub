"""主动提醒引擎：事件开始前 N 分钟推送到默认群，带去重（重启不重复轰炸）。"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from .config import CFG
from .report import send_to_default_channel


def check_and_push() -> list[str]:
    """扫描即将开始的日程并推送提醒。返回本次推送的日程名列表。"""
    now = datetime.now()
    horizon = now + timedelta(minutes=CFG.hub.remind_before)
    rows = db.events_between(db.fmt_when(now), db.fmt_when(horizon))
    pushed: list[str] = []
    for e in rows:
        ref = f"event:{e['id']}:{e['start_at']}"
        if db.reminder_sent(ref):
            continue
        start = datetime.strptime(e["start_at"], "%Y-%m-%d %H:%M")
        mins = max(1, round((start - now).total_seconds() / 60))
        when = f"约 {mins} 分钟后" if mins > 1 else "现在"
        text = (f"⏰ 提醒：{when} —— {e['title']}\n"
                f"🕒 {start:%H:%M} 开始，别忘了准备一下")
        ok, _ = send_to_default_channel(text)
        if ok:
            db.mark_reminder(ref)
            pushed.append(e["title"])
    return pushed
