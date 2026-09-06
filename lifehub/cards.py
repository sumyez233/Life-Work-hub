"""飞书卡片：功能 / 总览 / 待办 / 日程 / 记账 / 晨报。统一 schema 2.0 视觉。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from . import db
from .config import CFG

_WEEKDAY = "一二三四五六日"

# 底部导航：每个看板共用，按钮回调 cmd=open
_NAV = (
    ("overview", "总览"),
    ("todos", "待办"),
    ("bitable", "大盘"),
    ("ledger", "记账"),
    ("menu", "说明"),
)


def _today() -> date:
    return date.today()


def _wd(d: date | None = None) -> str:
    d = d or _today()
    return f"周{_WEEKDAY[d.weekday()]}"


def _ymd(d: date | None = None) -> str:
    d = d or _today()
    return f"{d:%m-%d} {_wd(d)}"


def _money(n: float) -> str:
    if abs(n) < 0.005:
        return "0"
    if n == int(n):
        return f"{int(n)}"
    return f"{n:.1f}".rstrip("0").rstrip(".")


def _btn(label: str, value: dict, filled: bool = False, danger: bool = False) -> dict:
    if danger:
        btype = "danger"
    elif filled:
        btype = "primary_filled"
    else:
        btype = "default"
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": btype,
        "size": "small",
        "width": "default",
        "value": value,
        "behaviors": [{"type": "callback", "value": value}],
    }


def _nav(active: str) -> dict:
    return {
        "tag": "column_set",
        "flex_mode": "stretch",
        "background_style": "default",
        "horizontal_spacing": "8px",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [_btn(label, {"cmd": "open", "board": key}, filled=(key == active))],
            }
            for key, label in _NAV
        ],
    }


def _metrics(pairs: list[tuple[str, str]]) -> dict:
    """pairs: (value, label) — 2 或 4 格，移动端自动折成 2×2。"""
    cols = []
    for value, label in pairs:
        cols.append({
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_align": "top",
            "elements": [{
                "tag": "markdown",
                "text_align": "center",
                "content": f"**{value}**\n<font color='grey'>{label}</font>",
            }],
        })
    return {
        "tag": "column_set",
        "flex_mode": "bisect",
        "background_style": "grey",
        "horizontal_spacing": "8px",
        "margin": "0px 0px 4px 0px",
        "columns": cols,
    }


def _md(content: str) -> dict:
    return {"tag": "markdown", "content": content}


def _hr() -> dict:
    return {"tag": "hr"}


def _item_row(title_md: str, btn: dict | None = None) -> dict:
    left = {
        "tag": "column",
        "width": "weighted",
        "weight": 4,
        "vertical_align": "center",
        "elements": [_md(title_md)],
    }
    cols = [left]
    if btn:
        cols.append({
            "tag": "column",
            "width": "auto",
            "vertical_align": "center",
            "elements": [btn],
        })
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "default",
        "horizontal_spacing": "8px",
        "columns": cols,
    }


def _card(title: str, subtitle: str, template: str, elements: list[dict],
          icon: str | None = None) -> dict:
    header: dict = {
        "title": {"tag": "plain_text", "content": title},
        "subtitle": {"tag": "plain_text", "content": subtitle},
        "template": template,
    }
    if icon:
        header["icon"] = {"tag": "standard_icon", "token": icon}
    body_elements = list(elements)
    body_elements.append(_hr())
    # 导航放在内容后，保证每个看板结构一致
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "fill"},
        "header": header,
        "body": {
            "padding": "12px",
            "vertical_spacing": "8px",
            "elements": body_elements,
        },
    }


def _with_nav(card: dict, active: str) -> dict:
    card["body"]["elements"].append(_nav(active))
    return card


# ---------- 待办分组 ----------

def _todo_groups() -> list[tuple[str, list]]:
    today = _today()
    groups: dict[str, list] = {
        "逾期": [], "今日": [], "优先": [], "近7天": [], "以后": [], "收集箱": [],
    }
    for t in db.list_todos():
        if t["due"]:
            try:
                d = date.fromisoformat(t["due"][:10])
            except ValueError:
                d = today
            if d < today:
                groups["逾期"].append((t, d))
            elif d == today:
                groups["今日"].append((t, d))
            elif (d - today).days <= 7:
                groups["近7天"].append((t, d))
            else:
                groups["以后"].append((t, d))
        elif t["priority"]:
            groups["优先"].append((t, None))
        else:
            groups["收集箱"].append((t, None))
    order = ["逾期", "今日", "优先", "近7天", "以后", "收集箱"]
    return [(name, groups[name]) for name in order if groups[name]]


def _todo_line(t, d: date | None) -> str:
    bits = [f"**{t['title']}**"]
    if d:
        bits.append(f"<font color='grey'>{d:%m-%d}</font>")
    if t["priority"]:
        bits.append("<font color='red'>优先</font>")
    return " · ".join(bits)


def _todo_rows(items: list, board: str, limit: int = 8) -> list[dict]:
    out: list[dict] = []
    for t, d in items[:limit]:
        out.append(_item_row(
            _todo_line(t, d),
            _btn("完成", {"cmd": "done", "id": int(t["id"]), "board": board}, filled=True),
        ))
    if len(items) > limit:
        out.append(_md(f"<font color='grey'>另有 {len(items) - limit} 条未展开</font>"))
    return out


# ---------- 各看板 ----------

def build_menu_card() -> dict:
    elements: list[dict] = [
        _md("**个人电脑中台已就绪** · 随时在手机飞书上发指令操控电脑与生活数据"),
        _hr(),
        _item_row(
            "🧠 **Codex 算力直连**\n<font color='grey'>`codex <任务>` 远程操作电脑执行代码/查文件；长按回复无前缀连续追问</font>",
            _btn("查看说明", {"cmd": "open", "board": "menu"}),
        ),
        _item_row(
            "📁 **文件双向传输**\n<font color='grey'>发 `传 论文` 调电脑文件直传手机；手机发文件自动存入电脑 inbox</font>",
            _btn("收件箱", {"cmd": "open", "board": "menu"}),
        ),
        _item_row(
            "📊 **多维表格联动**\n<font color='grey'>发 `看大盘` 查看已绑定多维表格的记录数与最近更新</font>",
            _btn("看大盘", {"cmd": "open", "board": "bitable"}, filled=True),
        ),
        _item_row(
            "✅ **智能待办打卡**\n<font color='grey'>发 `买美式咖啡` 记录；说 `搞定美式`、`美式做完了` 自动模糊打卡</font>",
            _btn("看待办", {"cmd": "open", "board": "todos"}, filled=True),
        ),
        _item_row(
            "💰 **消费极简记账**\n<font color='grey'>一句话记账：`午饭 35` / `打车 24.5` / `看下账本`</font>",
            _btn("看账本", {"cmd": "open", "board": "ledger"}, filled=True),
        ),
        _item_row(
            "⏰ **日程主动防御**\n<font color='grey'>发 `明天下午3点开会` 录入；会前 30 分钟飞书主动私聊弹窗提醒</font>",
            _btn("看总览", {"cmd": "open", "board": "overview"}),
        ),
        _hr(),
        _md(
            "💡 **常用呼叫短语**\n"
            "• **汇报功能 / 调出说明**：再次呼出本功能说明卡片\n"
            "• **看大盘 / 看待办 / 看账本 / 看总览**：一键呼出交互看板\n"
            "• **传 <关键词>**：全盘搜文件并直接发送到飞书\n"
            "• **搞定 <任务>** / **删掉 <任务>**：人话模糊打卡或撤销\n"
            "• **codex reset**：清空当前话题记忆"
        ),
    ]
    card = _card("功能说明", "lifehub · 个人电脑中台全能力手册", "blue", elements, icon="app_outlined")
    return _with_nav(card, "menu")


def build_overview_card() -> dict:
    today = _today()
    iso = today.isoformat()
    tstats = db.todo_stats()
    money = db.ledger_stats()
    events = db.events_on(iso)
    groups = dict(_todo_groups())
    focus = (groups.get("逾期") or []) + (groups.get("今日") or [])
    recent = db.list_ledger(limit=5)

    elements: list[dict] = [
        _metrics([
            (str(len(focus)), "今日待办"),
            (str(tstats["total"]), "历史任务"),
            (f"¥{_money(money['all_expense'])}", "累计消费"),
            (f"¥{_money(money['all_income'])}", "累计收入"),
        ]),
    ]

    if focus:
        elements.append(_md("**今日要做**"))
        elements.extend(_todo_rows(focus, "overview", limit=6))
    elif tstats["open"]:
        inbox = groups.get("收集箱") or []
        elements.append(_md("**没有日期的待办**"))
        elements.extend(_todo_rows(inbox[:5], "overview", limit=5))
    else:
        elements.append(_md("今日待办是空的。想到什么，直接发给我。"))

    if events:
        lines = ["**今日日程**"]
        for e in events:
            lines.append(f"- **{e['start_at'][11:16]}**  {e['title']}")
        elements.append(_md("\n".join(lines)))

    elements.append(_md(
        f"**历史**  累计完成 {tstats['done']}  ·  历史任务 {tstats['total']}  ·  "
        f"当前打开 {tstats['open']}\n"
        f"累计消费 ¥{_money(money['all_expense'])}  ·  累计收入 ¥{_money(money['all_income'])}"
    ))

    if recent:
        lines = ["**最近记账**"]
        for r in recent:
            sign = "+" if r["kind"] == "income" else "−"
            lines.append(
                f"- {r['note'] or r['category']}  {sign}{_money(r['amount'])}  "
                f"<font color='grey'>{r['category']}</font>"
            )
        elements.append(_md("\n".join(lines)))

    template = "red" if groups.get("逾期") else ("orange" if focus or events else "blue")
    card = _card("总览", _ymd(today), template, elements, icon="member_new_outlined")
    return _with_nav(card, "overview")


def build_todos_card() -> dict:
    groups = _todo_groups()
    flat = {name: items for name, items in groups}
    total = sum(len(v) for v in flat.values())
    overdue_n = len(flat.get("逾期") or [])
    today_n = len(flat.get("今日") or [])

    elements: list[dict] = [
        _metrics([
            (str(overdue_n), "逾期"),
            (str(today_n), "今日"),
            (str(len(flat.get("优先") or [])), "优先"),
            (str(total), "待办"),
        ]),
    ]
    if not groups:
        elements.append(_md("全部清空。想到什么，随手丢给我。"))
    else:
        for name, items in groups:
            elements.append(_md(f"**{name}**  <font color='grey'>{len(items)}</font>"))
            elements.extend(_todo_rows(items, "todos"))

    template = "red" if overdue_n else ("orange" if today_n else "turquoise")
    card = _card(f"待办  ·  {total}", _ymd(), template, elements, icon="todo_outlined")
    return _with_nav(card, "todos")


def build_events_card() -> dict:
    today = _today()
    rows = db.upcoming_events(14)
    today_rows = db.events_on(today.isoformat())
    by_day: dict[str, list] = defaultdict(list)
    for e in rows:
        by_day[e["start_at"][:10]].append(e)
    # 今日即使已过点也列出来（upcoming 从 now 起会漏掉上午的）
    for e in today_rows:
        day = e["start_at"][:10]
        if not any(x["id"] == e["id"] for x in by_day.get(day, [])):
            by_day[day].insert(0, e)

    elements: list[dict] = [
        _metrics([
            (str(len(today_rows)), "今日"),
            (str(len(rows)), "未来14天"),
            (str(db.event_stats()["total"]), "全部"),
            (f"{CFG.hub.remind_before}分", "提前提醒"),
        ]),
    ]
    if not by_day:
        elements.append(_md("接下来两周没有日程。发「明天下午3点开会」即可记上。"))
    else:
        for day in sorted(by_day):
            d = date.fromisoformat(day)
            label = "今天" if d == today else ("明天" if d == today + timedelta(days=1) else f"{d:%m-%d} {_wd(d)}")
            lines = [f"**{label}**"]
            for e in by_day[day]:
                lines.append(
                    f"- **{e['start_at'][11:16]}**  {e['title']}"
                )
            elements.append(_md("\n".join(lines)))

    template = "orange" if today_rows else "violet"
    card = _card("日程", _ymd(), template, elements, icon="calendar_outlined")
    return _with_nav(card, "events")


def build_ledger_card() -> dict:
    money = db.ledger_stats()
    today = _today()
    month_from = today.replace(day=1).isoformat()
    cats = db.ledger_by_category(month_from, today.isoformat(), "expense")
    recent = db.list_ledger(limit=8)

    elements: list[dict] = [
        _metrics([
            (f"¥{_money(money['today_expense'])}", "今日"),
            (f"¥{_money(money['week_expense'])}", "本周"),
            (f"¥{_money(money['month_expense'])}", "本月"),
            (f"¥{_money(money['all_income'])}", "累计收入"),
        ]),
        _md(
            f"累计消费 **¥{_money(money['all_expense'])}**"
            f"  ·  累计收入 **¥{_money(money['all_income'])}**"
        ),
    ]
    if cats:
        lines = ["**本月分类**"]
        for c in cats[:6]:
            lines.append(f"- {c['category']}  ¥{_money(c['s'])}  <font color='grey'>{c['n']} 笔</font>")
        elements.append(_md("\n".join(lines)))
    if recent:
        lines = ["**最近明细**"]
        for r in recent:
            sign = "+" if r["kind"] == "income" else "−"
            lines.append(
                f"- {r['occurred_on'][5:]}  {r['note'] or r['category']}  "
                f"{sign}{_money(r['amount'])}"
            )
        elements.append(_md("\n".join(lines)))
    else:
        elements.append(_md("还没有记账。发「午饭 35」或「工资 8000」。"))

    card = _card("记账", _ymd(), "green", elements, icon="wallet_outlined")
    return _with_nav(card, "ledger")


def build_report_card() -> dict:
    """晨报：给定时推送用，结构与总览接近，但不放导航（避免凌晨误点）。"""
    today = _today()
    iso = today.isoformat()
    events = db.events_on(iso)
    groups = dict(_todo_groups())
    focus = (groups.get("逾期") or []) + (groups.get("今日") or [])
    y = (today - timedelta(days=1)).isoformat()
    spend = db.spend_between(y, y)
    money = db.ledger_stats()

    template = "red" if groups.get("逾期") else ("orange" if focus or events else "turquoise")
    elements: list[dict] = [
        _metrics([
            (str(len(events)), "日程"),
            (str(len(groups.get("今日") or [])), "今日待办"),
            (str(len(groups.get("逾期") or [])), "逾期"),
            (f"¥{_money(spend)}" if spend else "—", "昨日支出"),
        ]),
    ]
    if events:
        lines = ["**今日日程**"]
        lines += [f"- **{e['start_at'][11:16]}**  {e['title']}" for e in events]
        elements.append(_md("\n".join(lines)))
    if focus:
        elements.append(_md("**今日要做**" if not groups.get("逾期") else "**逾期 + 今日**"))
        elements.extend(_todo_rows(focus, "report", limit=6))
    extra = []
    later = groups.get("近7天") or []
    inbox = groups.get("收集箱") or []
    if later:
        extra.append(f"近7天 {len(later)} 条")
    if inbox:
        extra.append(f"收集箱 {len(inbox)} 条")
    extra.append(f"本月已花 ¥{_money(money['month_expense'])}")
    elements.append(_md("<font color='grey'>" + "  ·  ".join(extra) + "</font>"))
    elements.append(_md("<font color='grey'>回复「总览」看累计完成与收支 · 「功能」看全部指令</font>"))
    return _card(f"晨报  ·  {today:%m月%d日} {_wd(today)}", "lifehub", template,
                 elements, icon="newspaper_outlined")


# 兼容旧名
def build_board_card() -> dict:
    return build_todos_card()


def build(name: str) -> dict:
    from . import bitable
    fn = {
        "menu": build_menu_card,
        "overview": build_overview_card,
        "todos": build_todos_card,
        "board": build_todos_card,
        "events": build_events_card,
        "ledger": build_ledger_card,
        "report": build_report_card,
        "bitable": bitable.build_bitable_card,
    }.get(name, build_menu_card)
    return fn()
