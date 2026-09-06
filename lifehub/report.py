"""每日晨报：卡片版（主）+ 文本版（预览/降级）。"""
from __future__ import annotations

from datetime import date, timedelta

from . import db
from .cards import build_report_card
from .config import CFG
from .push import (send_card, send_card_via_app, send_text, send_via_app,
                   list_chats)


def _todo_line(row) -> str:
    due = row["due"][:10] if row["due"] else ""
    flag = ""
    if due:
        if due < date.today().isoformat():
            flag = "⚠️逾期 "
        elif due == date.today().isoformat():
            flag = "🔔今天 "
    pri = "❗" if row["priority"] else ""
    return f"  {flag}{pri}{row['title']}  (#{row['id']})"


def build_report() -> str:
    today = date.today()
    lines = [f"☀️ 晨报 · {today:%m月%d日 %A}".replace("Monday", "周一").replace(
        "Tuesday", "周二").replace("Wednesday", "周三").replace("Thursday", "周四")
        .replace("Friday", "周五").replace("Saturday", "周六").replace("Sunday", "周日")]

    events = db.events_on(today.isoformat())
    lines.append("\n📅 今日日程")
    if events:
        lines += [f"  {e['start_at'][11:16]}  {e['title']}" for e in events]
    else:
        lines.append("  （无）")

    todos = db.list_todos()
    overdue, todaytd, later, nodue = [], [], [], []
    for t in todos:
        if not t["due"]:
            nodue.append(t)
        elif t["due"][:10] < today.isoformat():
            overdue.append(t)
        elif t["due"][:10] == today.isoformat():
            todaytd.append(t)
        else:
            later.append(t)
    lines.append("\n✅ 待办")
    if overdue:
        lines += [_todo_line(t) for t in overdue]
    if todaytd:
        lines += [_todo_line(t) for t in todaytd]
    if later:
        lines.append("  近期：")
        lines += [_todo_line(t) for t in later[:5]]
    if nodue:
        lines.append(f"  …另有 {len(nodue)} 条无截止日期的待办")
    if not todos:
        lines.append("  （空空如也，加一条？）")

    y_day = (today - timedelta(days=1)).isoformat()
    spend = db.spend_between(y_day, y_day)
    if spend > 0:
        lines.append(f"\n💰 昨日支出：{spend:.2f} 元")

    try:
        from . import bitable
        b_stats = bitable.get_cached_or_fresh()
        if b_stats and b_stats.get("configured", True):
            line = f"\n📊 多维表格：{b_stats['total_records']} 条记录"
            if b_stats.get("latest_updated"):
                line += f"，最近更新 {b_stats['latest_updated']}"
            lines.append(line)
    except Exception:
        pass

    return "\n".join(lines)


def send_to_default_channel(text: str) -> tuple[bool, str]:
    """统一推送出口：提醒等纯文本走这里。"""
    if CFG.feishu.webhook:
        return send_text(text)
    if CFG.feishu.report_chat:
        return send_via_app(text, CFG.feishu.report_chat)
    chats, msg = list_chats()
    if not chats:
        return False, f"没有可用推送通道（webhook 未配；应用机器人不在任何群里）：{msg}"
    if len(chats) == 1:
        return send_via_app(text, chats[0][0])
    names = "、".join(f"{name}({cid})" for cid, name in chats)
    return False, f"机器人在多个群，请用 `python -m lifehub.cli chats` 查看并填入 config.toml 的 feishu.report_chat：{names}"


def send_card_to_default_channel(card: dict) -> tuple[bool, str]:
    """卡片推送出口：晨报、看板等。"""
    if CFG.feishu.webhook:
        return send_card(card)
    if CFG.feishu.report_chat:
        return send_card_via_app(card, CFG.feishu.report_chat)
    chats, msg = list_chats()
    if not chats:
        return False, f"没有可用推送通道：{msg}"
    if len(chats) == 1:
        return send_card_via_app(card, chats[0][0])
    return False, "机器人在多个群，请配置 feishu.report_chat"


def send_report() -> tuple[bool, str]:
    return send_card_to_default_channel(build_report_card())
