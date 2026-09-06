"""飞书长连接机器人：在飞书里给机器人发一句话即录入。

支持：
  「明天下午3点开会」  -> 建日程
  「午饭35」          -> 记账
  「买牛奶」          -> 建待办
  「完成 3」          -> 完成编号 3 的待办
  「看板」            -> 回复待办看板卡片
  「帮助」            -> 用法
多行/复杂消息优先走 LLM 解析（需在 config.toml 配置 api_key），否则规则解析。
"""
from __future__ import annotations

import json
import re
import time
from collections import OrderedDict

from . import ai, cards, codex_runner, db, parser, transfer
from .config import CFG

HELP = (
    "发「功能」打开指令看板。常用：\n"
    "· 总览 / 待办 / 日程 / 记账 / 大盘 / 晨报\n"
    "· 买牛奶 · 明天下午3点开会 · 午饭 35 · 工资 8000\n"
    "· 搞定牛奶 · 传 报告\n"
    "· codex 帮我…（召唤 Codex 执行任务，需白名单）"
)

# 需要请 LLM 兜底的信号：多行、或超出简单规则可靠范围的长句
_AI_MIN_LEN = 24

_CARD_CMDS = {
    "功能": "menu", "功能列表": "menu", "菜单": "menu", "指令": "menu",
    "帮助": "menu", "help": "menu", "?": "menu", "？": "menu",
    "汇报功能": "menu", "调出说明": "menu", "说明": "menu", "使用说明": "menu",
    "功能说明": "menu", "你会做什么": "menu", "你会干嘛": "menu", "能做什么": "menu",
    "指令说明": "menu", "帮助文档": "menu", "手册": "menu", "功能介绍": "menu",
    "玩法": "menu", "怎么用": "menu", "全功能": "menu", "能力": "menu",
    "总览": "overview", "首页": "overview", "概览": "overview",
    "看板": "todos", "待办": "todos", "待办看板": "todos", "板": "todos",
    "日程": "events", "日程看板": "events", "安排": "events",
    "记账": "ledger", "账本": "ledger", "消费": "ledger",
    "账单": "ledger", "支出": "ledger",
    "今天": "report", "晨报": "report", "今日": "report",
    "大盘": "bitable", "台账": "bitable", "多维表格": "bitable",
}


def _text_msg(text: str) -> dict:
    return {"msg_type": "text", "content": {"text": text}}


def _card_msg(card: dict) -> dict:
    return {"msg_type": "interactive", "content": card}


def _match_board(text: str) -> str | None:
    t = text.strip().lower()
    if t in _CARD_CMDS:
        return _CARD_CMDS[t]
    clean = re.sub(r"^(?:请|帮我|麻烦)?(?:看[看下一]|查看|查询|打开|展示|调出|显示|拉出|查下|查一下)?", "", t).strip()
    clean = re.sub(r"(?:卡片|看板|列表|面板|视图)?$", "", clean).strip()
    if clean in _CARD_CMDS:
        return _CARD_CMDS[clean]
    if any(k in t for k in ("汇报功能", "调出说明", "功能说明", "使用说明", "你会做", "你能做", "功能介绍", "怎么用", "看功能", "查功能", "看说明", "帮助")):
        return "menu"
    if any(k in t for k in ("看待办", "查待办", "看下待办", "看看待办", "我的待办", "待办清单", "未完成", "任务清单")):
        return "todos"
    if any(k in t for k in ("看日程", "查日程", "看下日程", "看看日程", "我的日程", "今日日程", "近期日程", "看安排")):
        return "events"
    if any(k in t for k in ("看账", "查账", "看下账", "看看账", "花了多少", "消费记录", "本月支出", "账单")):
        return "ledger"
    if any(k in t for k in ("看总览", "今日总览", "全局总览", "今天怎样", "今日概览", "看看总览")):
        return "overview"
    if any(k in t for k in ("看大盘", "查大盘", "看台账", "查台账", "多维表格", "监控")):
        return "bitable"
    return None


def _file_transfer_match(text: str) -> str | None:
    t = text.strip()
    m = re.match(r"^(?:传文件|发文件|推送文件|发我|传给我|传下|发下|传|发)\s*(.+)$", t)
    if m:
        kw = m.group(1).strip().strip("。！! ")
        if any(kw.startswith(p) for p in ("工资", "奖金", "红包", "邮件", "短信", "消息")):
            return None
        return kw
    return None


def _codex_match(text: str) -> str | None:
    """识别「codex <任务>」式指令；返回提示词，空串表示仅询问用法。"""
    t = text.strip()
    low = t.lower()
    if low in ("codex", "codex help", "codex 帮助", "codex 用法", "codex 怎么用"):
        return ""
    m = re.match(r"^(?:codex|让 codex|找 codex|跑 codex)\s*[:：]?\s+(.+)$", t, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _handle_text(text: str, chat_id: str | None = None) -> dict:
    text = re.sub(r"@_user_\d+", "", text).strip()
    if not text:
        return _text_msg("说点什么吧～发「功能」看用法")
    db.usage_bump("msgs")

    # 1. 尝试文件直传指令
    if file_query := _file_transfer_match(text):
        target = transfer.find_file(file_query)
        if target:
            ok, msg = transfer.send_file(target, chat_id=chat_id)
            if ok:
                return _text_msg(f"✓ 已将「{target.name}」直接推送到飞书！")
            return _text_msg(f"推送文件失败：{msg}")
        return _text_msg(f"✗ 未在常用目录找到：{file_query}")

    # 2. 看板/大盘卡片召回
    board_name = _match_board(text)
    if board_name:
        return _card_msg(cards.build(board_name))

    if m := _complete_match(text):
        return _text_msg(_complete_todo(m))
    if m := _delete_match(text):
        return _text_msg(_delete_any(m))

    # 解析：复杂消息且配置了 LLM → 先试 AI，失败回退规则
    results = None
    if ai.enabled() and ("\n" in text or len(text) > _AI_MIN_LEN):
        results = ai.parse(text)
    if results is None:
        results = parser.parse_multi(text)

    if not results:
        return _text_msg("没认出可记录的内容，随时跟我说话就行～")
    if len(results) == 1:
        counts = {"todo": 0, "event": 0, "ledger": 0}
        lines: list[str] = []
        _store(results[0], counts, lines)
        return _text_msg("记下了：" + lines[0])

    counts = {"todo": 0, "event": 0, "ledger": 0}
    lines = []
    for p in results:
        _store(p, counts, lines)
    tag = {"todo": "待办", "event": "日程", "ledger": "账目"}
    head = "都记下了（" + " · ".join(f"{tag[k]} {v} 条" for k, v in counts.items() if v) + "）"
    return _text_msg(head + "\n" + "\n".join(f"· {line}" for line in lines[:12]))


def _store(p: parser.Parsed, counts: dict, lines: list[str]) -> None:
    db.usage_bump("added")
    if p.kind == "event":
        db.add_event(p.title, db.fmt_when(p.when), source="feishu")
        counts["event"] += 1
        lines.append(f"{p.title}（{p.when:%m-%d %H:%M}）")
    elif p.kind == "ledger":
        db.add_ledger(p.amount, p.category, p.note, source="feishu",
                            kind=p.direction or "expense")
        counts["ledger"] += 1
        mark = "收入" if p.direction == "income" else p.category
        lines.append(f"{p.note or mark} {p.amount:g} 元")
    else:
        db.add_todo(p.title, p.when.date().isoformat() if p.when else None,
                          p.priority, source="feishu")
        counts["todo"] += 1
        due = f"（截止 {p.when:%m-%d}）" if p.when else ""
        pri = "❗" if p.priority else ""
        lines.append(f"{pri}{p.title}{due}")


def _complete_match(text: str) -> str | None:
    t = text.strip()
    # 1. 显式打卡前缀: 完成/搞定/做完/买好/打卡/勾掉 牛奶
    m = re.match(r"^(?:完成|done|搞定|勾掉|做完|买好|打卡)\s*#?(.+?)[了。！! ]*$", t, re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # 2. 尾缀口语完成态: 美式买好了 / 材料完成了 / 课程看完了 / 作业做好了
    m = re.match(r"^(.+?)(?:好了|完了|搞定了|完成了|弄好了|做完了|搞好了)[了。！! ]*$", t)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


def _complete_todo(query: str) -> str:
    res = db.complete_todo_smart(query)
    if res:
        tid, title = res
        db.usage_bump("done")
        return f"✓ 已搞定：{title}，干得漂亮！"
    return f"没找到未完成的「{query}」"


def _delete_match(text: str) -> str | None:
    t = text.strip()
    m = re.match(r"^(?:删掉|删除|删了|不要了|退回)\s*#?(.+?)[了。！! ]*$", t)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


def _delete_any(query: str) -> str:
    res = db.delete_smart(query)
    if res:
        label, title = res
        db.usage_bump("deleted")
        return f"🗑 已删除{label}「{title}」"
    return f"没找到与「{query}」相关的记录"


# 消息去重缓存：防止长连接网络重连时飞书重推导致重复回复
_PROCESSED_MESSAGES: OrderedDict[str, float] = OrderedDict()
_DEDUP_WINDOW = 300.0  # 5 分钟内去重


def _log(msg: str) -> None:
    from pathlib import Path
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now_str}] {msg}"
    print(line, flush=True)
    try:
        log_dir = Path("data")
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "bot.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _is_duplicate_message(msg_id: str) -> bool:
    if not msg_id:
        return False
    now = time.time()
    while _PROCESSED_MESSAGES:
        first_time = next(iter(_PROCESSED_MESSAGES.values()))
        if now - first_time > _DEDUP_WINDOW:
            _PROCESSED_MESSAGES.popitem(last=False)
        else:
            break
    if msg_id in _PROCESSED_MESSAGES:
        return True
    _PROCESSED_MESSAGES[msg_id] = now
    return False


def start() -> None:
    """阻塞运行；Ctrl+C 退出。需要 config.toml 里已填 app_id/app_secret。"""
    if not (CFG.feishu.app_id and CFG.feishu.app_secret):
        raise SystemExit("请先在 config.toml 填写 feishu.app_id / app_secret（见 docs/feishu-setup.md）")

    import lark_oapi as lark
    from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

    client = lark.Client.builder().app_id(CFG.feishu.app_id) \
        .app_secret(CFG.feishu.app_secret).build()

    def reply(message_id: str, payload: dict, chat_id: str | None = None) -> None:
        content = payload["content"]
        if isinstance(content, (dict, list)):
            content = json.dumps(content)
        req = ReplyMessageRequest.builder().message_id(message_id) \
            .request_body(ReplyMessageRequestBody.builder()
                          .content(content)
                          .msg_type(payload["msg_type"]).build()).build()
        resp = client.im.v1.message.reply(req)
        ok = resp.success() if hasattr(resp, "success") else (getattr(resp, "code", -1) == 0)
        code = getattr(resp, "code", None)
        _log(f"[REPLY] type={payload['msg_type']} ok={ok} code={code}")
        if not ok and chat_id:
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
            creq = CreateMessageRequest.builder().receive_id_type("chat_id") \
                .request_body(CreateMessageRequestBody.builder()
                              .receive_id(chat_id)
                              .content(content)
                              .msg_type(payload["msg_type"]).build()).build()
            cresp = client.im.v1.message.create(creq)
            _log(f"[FALLBACK CREATE] code={getattr(cresp, 'code', None)}")

    def _handle_codex(prompt: str, message_id: str, chat_id: str | None, thread_key: str) -> None:
        if not codex_runner.enabled_for(chat_id):
            reply(message_id, _text_msg(
                "🧠 Codex 直通未启用：请把本会话 ID 加入 config.toml [codex].allowed_chats"
                " 并将 enabled 设为 true。"
            ), chat_id=chat_id)
            return

        if prompt == "__RESET__":
            codex_runner.clear_session(thread_key)
            reply(message_id, _text_msg("🧹 已重置本话题的 Codex 会话记忆。发送新任务将开启全新对话！"), chat_id=chat_id)
            return

        if not prompt:
            sid = codex_runner.get_session(thread_key)
            sid_hint = f"\n当前话题活跃会话：{sid[:8]}…" if sid else "\n当前话题尚无活跃会话（发任务将新开）"
            reply(message_id, _text_msg(
                f"用法：codex <任务描述>，例如「codex 帮我看看 todos 表结构」。\n"
                f"回复追问：在已有的 Codex 回复下直接点击「回复」，无需加 codex 前缀即可连续追问！\n"
                f"重置会话：发送「codex reset」或「codex 新会话」\n"
                f"执行沙箱：{CFG.codex.sandbox} · 超时：{CFG.codex.timeout_seconds}s{sid_hint}"
            ), chat_id=chat_id)
            return

        existing_sid = codex_runner.get_session(thread_key)

        def on_done(ok: bool, text: str, new_sid: str | None) -> None:
            if ok and new_sid:
                codex_runner.set_session(thread_key, new_sid)
            body = (text or "（无输出）").strip()
            if len(body) > CFG.codex.max_output_chars:
                body = body[:CFG.codex.max_output_chars] + "\n…（结果过长，已截断）"
            mode_str = f"（会话 {new_sid[:8]}…）" if new_sid else ""
            reply(message_id, _text_msg(
                (f"✅ Codex 完成 {mode_str}：\n" if ok else "❌ Codex 执行失败：\n") + body
            ), chat_id=chat_id)

        if not codex_runner.start(prompt, on_done, session_id=existing_sid):
            reply(message_id, _text_msg(
                "上一条 Codex 任务还在执行，完成后再发新的吧。"
            ), chat_id=chat_id)
            return

        hint = prompt if len(prompt) <= 60 else prompt[:60] + "…"
        if existing_sid:
            status_msg = f"🧠 Codex 接续会话中（{existing_sid[:8]}…）：{hint}\n完成后我会把结果发到这里。"
        else:
            status_msg = f"🧠 已开启全新 Codex 会话：{hint}\n完成后我会把结果发到这里。"

        reply(message_id, _text_msg(status_msg), chat_id=chat_id)

    def on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:  # type: ignore[attr-defined]
        try:
            msg = data.event.message
            if not msg or not getattr(msg, "message_id", None):
                return
            if _is_duplicate_message(msg.message_id):
                _log(f"[DEDUP] 忽略重复推送消息 msg_id={msg.message_id}")
                return

            chat_id = getattr(msg, "chat_id", None)

            # 1. 接收文件消息：自动存入收件箱
            if msg.message_type == "file":
                content_obj = json.loads(msg.content)
                file_key = content_obj.get("file_key")
                file_name = content_obj.get("file_name") or f"file_{msg.message_id}.bin"
                _log(f"[RECV FILE] {file_name} key={file_key}")
                ok, ret_msg, saved_path = transfer.download_message_resource(
                    message_id=msg.message_id,
                    file_key=file_key,
                    file_name=file_name,
                    res_type="file"
                )
                if ok and saved_path:
                    size_kb = saved_path.stat().st_size / 1024
                    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.2f} MB"
                    reply(msg.message_id, _text_msg(
                        f"📥 已成功接收并存入电脑收件箱！\n"
                        f"· 文件：{saved_path.name}\n"
                        f"· 大小：{size_str}\n"
                        f"· 本地路径：{transfer.INBOX_DIR}\\{saved_path.name}\n\n"
                        f"电脑本地工作流现已可直接读取并处理该文件！"
                    ), chat_id=chat_id)
                else:
                    reply(msg.message_id, _text_msg(f"接收文件失败：{ret_msg}"), chat_id=chat_id)
                return

            # 2. 接收图片消息：自动存入收件箱
            if msg.message_type == "image":
                content_obj = json.loads(msg.content)
                image_key = content_obj.get("image_key")
                file_name = f"image_{msg.message_id}.jpg"
                _log(f"[RECV IMAGE] key={image_key}")
                ok, ret_msg, saved_path = transfer.download_message_resource(
                    message_id=msg.message_id,
                    file_key=image_key,
                    file_name=file_name,
                    res_type="image"
                )
                if ok and saved_path:
                    reply(msg.message_id, _text_msg(
                        f"🖼️ 已存入电脑收件箱！\n"
                        f"· 本地路径：{transfer.INBOX_DIR}\\{saved_path.name}"
                    ), chat_id=chat_id)
                else:
                    reply(msg.message_id, _text_msg(f"接收图片失败：{ret_msg}"), chat_id=chat_id)
                return

            if msg.message_type != "text":
                reply(msg.message_id, _text_msg("我暂时只认文字、文件和图片消息～（发「功能」看用法）"), chat_id=chat_id)
                return

            text = re.sub(r"@_user_\d+", "", json.loads(msg.content).get("text", "")).strip()
            root_id = getattr(msg, "root_id", None)
            thread_key = root_id or msg.message_id
            _log(f"[RECV] text={text!r} chat_id={chat_id} root_id={root_id} msg_id={msg.message_id}")

            codex_prompt = _codex_match(text)
            # 如果用户在已有的 Codex 话题 Thread 下点击「回复」，无需强制加 codex 前缀即可接续追问
            if codex_prompt is None and root_id and codex_runner.get_session(root_id):
                codex_prompt = text

            if codex_prompt is not None:
                _handle_codex(codex_prompt, msg.message_id, chat_id, thread_key=thread_key)
                return
            reply(msg.message_id, _handle_text(text, chat_id=chat_id), chat_id=chat_id)
        except Exception as e:
            _log(f"[ERROR] on_message: {e}")
            try:
                reply(data.event.message.message_id, _text_msg(f"处理出错：{e}"), chat_id=chat_id)
            except Exception:
                pass

    def _card_reply(card: dict, toast: dict | None = None):
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse)
        payload: dict = {"card": {"type": "raw", "data": card}}
        if toast:
            payload["toast"] = toast
        return P2CardActionTriggerResponse(payload)

    # 卡片按钮回调：完成待办 / 切换看板
    def on_card(data) -> object:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse)
        try:
            value = (data.event.action.value if data.event and data.event.action else None) or {}
            if not isinstance(value, dict):
                try:
                    value = json.loads(value)
                except Exception:
                    value = {}
            cmd = value.get("cmd")
            board_name = value.get("board") or "todos"
            if cmd == "open":
                return _card_reply(cards.build(str(value.get("board") or "menu")))
            if cmd == "done":
                tid = int(value["id"])
                if db.complete_todo(tid):
                    db.usage_bump("done")
                    return _card_reply(
                        cards.build(str(board_name)),
                        {"type": "success", "content": f"#{tid} 已完成"},
                    )
                return _card_reply(
                    cards.build(str(board_name)),
                    {"type": "error", "content": f"没有待办 #{tid}"},
                )
        except Exception as e:
            print(f"卡片按钮处理出错: {e}")
        return P2CardActionTriggerResponse({})

    def _install_card_patch(client) -> None:
        """修补 SDK bug（larksuite/oapi-sdk-python#126）：CARD 帧被静默丢弃。
        这里复制官方分发逻辑，把卡片回调路由到事件分发器，使按钮可用。"""
        import base64
        import time as _time
        import types as _types
        from lark_oapi.core.const import UTF_8
        from lark_oapi.core.json import JSON
        from lark_oapi.ws.client import (_get_by_key, HEADER_MESSAGE_ID,
                                         HEADER_TRACE_ID, HEADER_SUM,
                                         HEADER_SEQ, HEADER_TYPE)
        from lark_oapi.ws.enum import MessageType
        from lark_oapi.ws.model import Response

        async def _handle_data_frame(self, frame):
            hs = frame.headers
            msg_id = _get_by_key(hs, HEADER_MESSAGE_ID)
            trace_id = _get_by_key(hs, HEADER_TRACE_ID)
            sum_ = _get_by_key(hs, HEADER_SUM)
            seq = _get_by_key(hs, HEADER_SEQ)
            type_ = _get_by_key(hs, HEADER_TYPE)

            pl = frame.payload
            if int(sum_) > 1:                       # 合包
                pl = self._combine(msg_id, int(sum_), int(seq), pl)
                if pl is None:
                    return

            message_type = MessageType(type_)
            resp = Response(code=200)
            try:
                start = int(round(_time.time() * 1000))
                if message_type in (MessageType.EVENT, MessageType.CARD):  # ← 修复点
                    result = self._event_handler._do_without_validation(pl)
                else:
                    return
                end = int(round(_time.time() * 1000))
                header = hs.add()
                header.key = "biz_rt"
                header.value = str(end - start)
                if result is not None:
                    resp.data = base64.b64encode(JSON.marshal(result).encode(UTF_8))
            except Exception as e:
                logger_warn = getattr(client, "_fmt_log", None)
                print(f"帧处理失败: {e}")
                resp = Response(code=500)

            frame.payload = JSON.marshal(resp).encode(UTF_8)
            await self._write_message(frame.SerializeToString())

        client._handle_data_frame = _types.MethodType(_handle_data_frame, client)

    builder = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(on_message)
    # 忽略"进入聊天/已读回执"等无关事件，保持日志干净
    for attr in ("register_p2_im_message_message_read_v1",
                 "register_p2_im_chat_access_event_bot_p2p_chat_entered_v1"):
        m = getattr(builder, attr, None)
        if m:
            m(lambda data: None)
    handler = builder.build()

    # 注册卡片回调处理器并修补 SDK 的 CARD 帧丢弃 bug，让「✓ 编号」按钮生效
    try:
        from lark_oapi.event.callback.processor import P2CardActionTriggerProcessor
        handler._callback_processor_map["p2.card.action.trigger"] = \
            P2CardActionTriggerProcessor(on_card)
        card_patch_ok = True
    except Exception as e:
        card_patch_ok = False
        print(f"卡片回调注册失败（按钮打卡降级为文本）: {e}")

    kwargs = dict(event_handler=handler, log_level=lark.LogLevel.INFO)
    ws = lark.ws.Client(CFG.feishu.app_id, CFG.feishu.app_secret, **kwargs)
    if card_patch_ok:
        try:
            _install_card_patch(ws)
            print("卡片按钮打卡已启用（含 SDK 补丁）")
        except Exception as e:
            print(f"SDK 补丁失败，按钮打卡降级为文本: {e}")
    print("机器人已启动，长连接在线。在飞书里给机器人发消息即可录入（Ctrl+C 退出）")
    ws.start()
