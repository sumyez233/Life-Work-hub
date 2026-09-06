"""LLM 兜底解析：复杂/多行消息交给 OpenAI 兼容接口的结构化输出。

设计原则：规则优先、LLM 兜底。调用方应在规则结果不可靠时才用本模块，
且必须容忍失败（网络/格式错误一律返回 None，回退规则结果）。
"""
from __future__ import annotations

import json
from datetime import datetime

import httpx

from .config import CFG
from .parser import Parsed

_SYSTEM = (
    "你是个人事务助理的消息解析器。把用户消息解析为记录数组，"
    '只输出 JSON：{"records":[{"kind":"todo|event|ledger",'
    '"title":"简短标题","when":"YYYY-MM-DD HH:MM 或 null",'
    '"priority":0或1,"amount":null或数字,'
    '"category":"餐饮|交通|住房缴费|购物|医疗|其他","note":"原始描述"}]}。\n'
    "规则：\n"
    "1. 带具体时刻的赴约/会议 → event；消费支出 → ledger；其余 → todo\n"
    "2. 多行/编号内容拆成多条，尊重「工作/学习/今日消费」等分节\n"
    "3. 金额识别「美式9.9」「35元」等写法；kind=ledger 时必须给 amount\n"
    "4. 相对时间（明天/周五/下午3点）按给定当前时间换算成绝对时间\n"
    "5. 「X之前/月底前」类截止期限 → when=期限日 23:59\n"
    "6. 标题和 note 精简到 12 字以内，去掉「记得」「大概」「帮忙」等口语词；不要编造用户没写的内容"
)


def enabled() -> bool:
    return bool(CFG.ai.api_key)


def parse(text: str) -> list[Parsed] | None:
    """返回解析结果；任何失败返回 None（调用方回退规则解析）。"""
    if not enabled():
        return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M %A")
    try:
        r = httpx.post(
            f"{CFG.ai.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {CFG.ai.api_key}"},
            json={
                "model": CFG.ai.model,
                "messages": [
                    {"role": "system", "content": f"{_SYSTEM}\n当前时间：{now}"},
                    {"role": "user", "content": text},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
            timeout=30,
        )
        data = r.json()
        records = json.loads(data["choices"][0]["message"]["content"])["records"]
    except Exception:
        return None

    out: list[Parsed] = []
    for rec in records or []:
        kind = rec.get("kind", "todo")
        when = rec.get("when")
        dt = None
        if when:
            try:
                dt = datetime.fromisoformat(str(when))
            except ValueError:
                pass
        try:
            pri = int(rec.get("priority") or 0)
        except (TypeError, ValueError):
            pri = 0
        if kind == "ledger":
            amt = rec.get("amount")
            if not amt:
                continue
            note = rec.get("note") or rec.get("title") or "消费"
            raw_cat = rec.get("category") or ""
            direction = "income" if raw_cat == "收入" or any(
                w in (note + raw_cat) for w in ("工资", "薪水", "收入", "入账", "奖金")
            ) else "expense"
            category = "收入" if direction == "income" else (raw_cat or "其他")
            out.append(Parsed("ledger", title=f"{note} {float(amt):g}元",
                              amount=float(amt), category=category,
                              note=note, direction=direction))
        elif kind == "event":
            if dt is None:
                continue
            out.append(Parsed("event", title=rec.get("title") or "", when=dt, priority=pri))
        else:
            out.append(Parsed("todo", title=rec.get("title") or "", when=dt, priority=pri))
    return out or None
