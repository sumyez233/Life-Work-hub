"""飞书推送：webhook / 应用机器人 双通道，支持文本与交互卡片。"""
from __future__ import annotations

import json

import httpx

from .config import CFG


def _app_client():
    import lark_oapi as lark

    if not (CFG.feishu.app_id and CFG.feishu.app_secret):
        raise RuntimeError("未配置自建应用凭据（config.toml → feishu.app_id/app_secret）")
    return lark.Client.builder().app_id(CFG.feishu.app_id) \
        .app_secret(CFG.feishu.app_secret).build()


# ---------- 通道一：webhook（群自定义机器人） ----------

def _send_webhook(payload: dict) -> tuple[bool, str]:
    hook = CFG.feishu.webhook
    if not hook:
        return False, "未配置 webhook"
    try:
        r = httpx.post(hook, json=payload, timeout=10)
        data = r.json()
        if data.get("code") in (0, None) and data.get("StatusCode", 0) in (0, "ok", None):
            return True, "已推送（webhook）"
        return False, f"飞书返回异常: {data}"
    except Exception as e:
        return False, f"推送失败: {e}"


def send_text(text: str) -> tuple[bool, str]:
    text = f"【{CFG.feishu.keyword}】{text}"
    return _send_webhook({"msg_type": "text", "content": {"text": text}})


def send_card(card: dict) -> tuple[bool, str]:
    return _send_webhook({"msg_type": "interactive", "card": card})


# ---------- 通道二：应用机器人（进群直发 / 长连接） ----------

def _send_app(msg_type: str, content, chat_id: str) -> tuple[bool, str]:
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    try:
        client = _app_client()
        body = CreateMessageRequestBody.builder() \
            .receive_id(chat_id).msg_type(msg_type) \
            .content(content if isinstance(content, str) else json.dumps(content)).build()
        req = CreateMessageRequest.builder().receive_id_type("chat_id") \
            .request_body(body).build()
        resp = client.im.v1.message.create(req)
    except Exception as e:
        return False, f"推送失败: {e}"
    if resp.success():
        return True, "已推送（应用机器人）"
    return False, f"发送失败: {resp.code} {resp.msg}"


def send_via_app(text: str, chat_id: str) -> tuple[bool, str]:
    return _send_app("text", {"text": text}, chat_id)


def send_card_via_app(card: dict, chat_id: str) -> tuple[bool, str]:
    return _send_app("interactive", card, chat_id)


def list_chats() -> tuple[list[tuple[str, str]], str]:
    """应用机器人所在的群列表，返回 ([(chat_id, 群名)], 说明)。"""
    from lark_oapi.api.im.v1 import ListChatRequest

    try:
        client = _app_client()
        resp = client.im.v1.chat.list(ListChatRequest.builder().page_size(50).build())
    except Exception as e:
        return [], f"连接失败: {e}"
    if not resp.success():
        return [], f"获取群列表失败: {resp.code} {resp.msg}"
    items = [(c.chat_id, c.name or "(未命名/单聊)") for c in (resp.data.items or [])]
    return items, "ok"
