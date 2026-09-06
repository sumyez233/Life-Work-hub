"""一句话解析器：把「明天下午3点开会」「午饭35」「买牛奶」变成结构化记录。

现阶段是纯规则实现（无 LLM 也能用）；之后填入 LLM key 可升级为
「规则优先、LLM 兜底」，接口不变（返回 Parsed）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

_WEEK = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0, "天": 0}
_CATEGORY = [
    (("早饭", "午饭", "晚饭", "吃", "餐", "外卖", "咖啡", "美式", "拿铁", "奶茶", "水果"), "餐饮"),
    (("打车", "地铁", "公交", "加油", "停车", "机票", "火车"), "交通"),
    (("房租", "水电", "网费", "话费", "物业"), "住房缴费"),
    (("买", "购物", "超市"), "购物"),
    (("药", "医院", "挂号"), "医疗"),
]
_ITEM_PAT = re.compile(r"^(?:\d+\s*[.、．)]|[-*•·])\s*(.+)$")
_SPEND_WORDS = {"今日消费", "消费", "支出", "今日支出", "花费", "开销"}
_INCOME_WORDS = ("工资", "薪水", "收入", "入账", "到账", "奖金", "报销")


def _guess_category(note: str) -> str:
    return next((cat for keys, cat in _CATEGORY if any(k in note for k in keys)), "其他")


@dataclass
class Parsed:
    kind: str                      # todo / event / ledger
    title: str = ""
    when: datetime | None = None   # todo 的截止 或 日程的开始
    priority: int = 0
    amount: float | None = None
    category: str = "其他"
    note: str = ""
    direction: str = "expense"     # ledger: expense / income
    unmatched: list[str] = field(default_factory=list)


def _day_offset(text: str, when: dict) -> None:
    m = re.search(r"(大后天|后天|明天|今天|今晚|明晚)", text)
    if m:
        when["day"] = {"今天": 0, "今晚": 0, "明天": 1, "明晚": 1,
                       "后天": 2, "大后天": 3}[m.group(1)]
    m = re.search(r"(?:下?)(?:周|星期|礼拜)([一二三四五六日天])", text)
    if m:
        target = (_WEEK[m.group(1)] - 1) % 7   # 周日=0 约定 -> Python 周一=0
        offset = (target - date.today().weekday()) % 7
        if "下周" in text:
            offset += 7
        when["day"] = offset
    m = re.search(r"(\d{1,2})[号日]", text)
    if m:
        d = date.today().replace(day=min(int(m.group(1)), 28))
        if d < date.today():
            # 简单处理：过了本月则归到下月
            d = (d.replace(day=28) + timedelta(days=7)).replace(
                day=min(int(m.group(1)), 28))
        when["date"] = d


def _day_time(text: str, when: dict) -> None:
    m = re.search(r"(上午|早上|中午|下午|傍晚|晚上|晚)?\s*(\d{1,2})[点时:：]\s*(半|\d{1,2})?分?", text)
    if not m:
        return
    hour = int(m.group(2))
    minute = 30 if m.group(3) == "半" else int(m.group(3) or 0)
    period = m.group(1)
    if period in ("下午", "傍晚", "晚上", "晚") and hour < 12:
        hour += 12
    if period in ("中午",) and hour < 11:
        hour = 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return
    when["time"] = (hour, minute)


def _when_of(text: str) -> datetime | None:
    when: dict = {}
    _day_offset(text, when)
    _day_time(text, when)
    if "time" in when:
        day = when.get("date") or date.today() + timedelta(days=when.get("day", 0))
        h, mnt = when["time"]
        return datetime(day.year, day.month, day.day, h, mnt)
    if "day" in when:
        d = date.today() + timedelta(days=when["day"])
        return datetime(d.year, d.month, d.day, 9, 0)   # 只有日期没有时刻 → 默认 09:00
    if "date" in when:
        d = when["date"]
        return datetime(d.year, d.month, d.day, 9, 0)
    return None


def _clean_title(text: str) -> str:
    t = re.sub(r"(大后天|后天|明天|今天|今晚|明晚|下周?([一二三四五六日天])|下?周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天]|\d{1,2}[号日]|(上午|早上|中午|下午|傍晚|晚上|晚)?\s*\d{1,2}[点时:：](半|\d{1,2})?分?|提醒我|记得|帮我|一下|!+|！+|重要|紧急)", "", text)
    t = re.sub(r"\s+", " ", t).strip(" ，。,.")
    return t


def _ledger_direction(note: str) -> str:
    return "income" if any(w in note for w in _INCOME_WORDS) else "expense"


def _parse_ledger(text: str) -> Parsed | None:
    m = re.search(r"(.+?)\s*(\d+(?:\.\d+)?)\s*(?:元|块|¥|￥)", text)
    if not m:
        m = re.search(r"(.+?)\s+(\d+(?:\.\d+)?)\s*$", text)
        if not m:
            m = re.search(
                r"(工资|薪水|收入|入账|到账|奖金|报销)\s*(\d+(?:\.\d+)?)", text)
            if not m:
                return None
    note, amt = m.group(1).strip(), float(m.group(2))
    if amt <= 0 or not note:
        return None
    direction = _ledger_direction(note)
    category = "收入" if direction == "income" else _guess_category(note)
    return Parsed(kind="ledger", title=f"{note} {amt:g}元", amount=amt,
                  category=category, note=note, direction=direction)


def parse(text: str) -> Parsed:
    """主入口：一句话 -> 结构化记录。"""
    text = text.strip()
    if not text:
        raise ValueError("空内容")

    p = _parse_ledger(text)
    if p:
        return p

    when = _when_of(text)
    title = _clean_title(text)
    priority = 1 if re.search(r"(重要|紧急|!!|！!)", text) else 0

    if when and re.search(r"\d{1,2}[点时:：]", text):
        return Parsed(kind="event", title=title or text, when=when, priority=priority)
    return Parsed(kind="todo", title=title or text, when=when, priority=priority)


def _is_section_header(line: str) -> str | None:
    """返回节类型（todo/spend/event），不是节标题则 None。"""
    key = line.rstrip("：:").strip()
    if key in _SPEND_WORDS:
        return "spend"
    if key in ("日程", "安排", "今日日程", "今日安排"):
        return "event"
    if key in ("工作", "任务", "学习", "学习任务", "待办", "生活", "兼职", "兼职工作", "其他"):
        return "todo"
    # 短行且以节词结尾（如「文献阅读工作」），也认作节标题
    if len(key) <= 10 and not re.search(r"\d", key):
        for w in ("兼职工作", "兼职", "工作", "任务", "学习", "待办"):
            if key.endswith(w):
                return "todo"
        for w in _SPEND_WORDS:
            if key.endswith(w):
                return "spend"
    return None


def parse_multi(text: str) -> list[Parsed]:
    """多行分节解析：兼容一整段日程/待办/消费贴进来的用法。

    规则：
    - 空行跳过；节标题行（工作/学习/今日消费等）切换当前节
    - 「1.」「-」开头的行、或普通文本行，按当前节解析为 待办/日程/账目
    - 消费节内，行末或行中的数字视为金额（如「美式9.9」→ 餐饮 9.9 元）
    - 自动剔除 @机器人 等占位符
    """
    text = re.sub(r"@_user_\d+", "", text)
    out: list[Parsed] = []
    mode = "todo"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        sec = _is_section_header(line)
        if sec:
            mode = sec
            continue
        m = _ITEM_PAT.match(line)
        content = m.group(1).strip() if m else line
        if not content:
            continue
        if mode == "spend":
            p = _parse_ledger(content)
            if p is None:
                mm = re.search(r"^(.+?)(\d+(?:\.\d+)?)\s*$", content)
                if mm and mm.group(1).strip():
                    note = mm.group(1).strip(" ，,。.")
                    amt = float(mm.group(2))
                    direction = _ledger_direction(note)
                    cat = "收入" if direction == "income" else _guess_category(note)
                    p = Parsed(kind="ledger", title=f"{note} {amt:g}元", amount=amt,
                               category=cat, note=note, direction=direction)
            if p is None:                      # 消费节里没有金额的行按待办处理
                p = parse(content)
        else:
            p = parse(content)
        out.append(p)
    return out
