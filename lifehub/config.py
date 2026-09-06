"""lifehub 配置加载。"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Feishu:
    webhook: str = ""
    app_id: str = ""
    app_secret: str = ""
    keyword: str = "中台"
    report_chat: str = ""   # 晨报推送目标群的 chat_id（留空则自动选择）


@dataclass
class Hub:
    db: Path = ROOT / "data" / "hub.db"
    report_time: str = "08:00"
    port: int = 8420
    remind_before: int = 30   # 事件开始前多少分钟推送提醒


@dataclass
class AI:
    """LLM 解析配置（OpenAI 兼容接口：DeepSeek/Kimi/智谱/OpenAI 均可）。"""
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


@dataclass
class Bitable:
    app_token: str = ""   # 留空则该功能不启用；真实值放 config.toml
    table_id: str = ""
    cache_file: Path = ROOT / "data" / "bitable_cache.json"
    updated_field: str = ""   # 可选：记录"最近更新时间"的字段名，用于展示更新动态


@dataclass
class Transfer:
    inbox_dir: Path = ROOT / "inbox"   # 手机上行文件收件箱；默认项目内 inbox/
    search_dirs: list[str] = field(default_factory=list)  # 下行文件检索目录，留空则直传关闭


@dataclass
class Codex:
    """飞书 → Codex CLI 直通配置。

    enabled: 总开关（默认关，显式开启才有意义）。
    allowed_chats: 允许触发的会话 ID（私聊/群聊），留空则任何会话都不可用。
    workdir: Codex 执行时的工作根目录（-C）。
    model: 留空用 CLI 默认模型。
    sandbox: read-only / workspace-write / danger-full-access。
    timeout_seconds: 单次任务超时，超时强制终止。
    max_output_chars: 回传飞书的文本上限。
    """
    enabled: bool = False
    allowed_chats: list[str] = field(default_factory=list)
    workdir: Path = ROOT
    model: str = ""
    sandbox: str = "read-only"
    timeout_seconds: int = 600
    max_output_chars: int = 4000


@dataclass
class Config:
    feishu: Feishu = field(default_factory=Feishu)
    hub: Hub = field(default_factory=Hub)
    ai: AI = field(default_factory=AI)
    bitable: Bitable = field(default_factory=Bitable)
    transfer: Transfer = field(default_factory=Transfer)
    codex: Codex = field(default_factory=Codex)


def load(path: Path | None = None) -> Config:
    p = path or (ROOT / "config.toml")
    cfg = Config()
    if p.exists():
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
        if "feishu" in raw:
            f = raw["feishu"]
            cfg.feishu = Feishu(
                webhook=f.get("webhook", ""),
                app_id=f.get("app_id", ""),
                app_secret=f.get("app_secret", ""),
                keyword=f.get("keyword", "中台"),
                report_chat=f.get("report_chat", ""),
            )
        if "hub" in raw:
            h = raw["hub"]
            db = Path(h.get("db", "data/hub.db"))
            if not db.is_absolute():
                db = ROOT / db
            cfg.hub = Hub(
                db=db,
                report_time=h.get("report_time", "08:00"),
                port=int(h.get("port", 8420)),
                remind_before=int(h.get("remind_before", 30)),
            )
        if "ai" in raw:
            a = raw["ai"]
            cfg.ai = AI(
                api_key=a.get("api_key", ""),
                base_url=a.get("base_url", "https://api.deepseek.com"),
                model=a.get("model", "deepseek-chat"),
            )
        if "bitable" in raw:
            b = raw["bitable"]
            cf = Path(b.get("cache_file", "data/bitable_cache.json"))
            if not cf.is_absolute():
                cf = ROOT / cf
            cfg.bitable = Bitable(
                app_token=b.get("app_token", ""),
                table_id=b.get("table_id", ""),
                cache_file=cf,
                updated_field=b.get("updated_field", ""),
            )
        if "transfer" in raw:
            t = raw["transfer"]
            inbox = Path(t.get("inbox_dir", "inbox"))
            if not inbox.is_absolute():
                inbox = ROOT / inbox
            cfg.transfer = Transfer(
                inbox_dir=inbox,
                search_dirs=list(t.get("search_dirs", [])),
            )
        if "codex" in raw:
            cx = raw["codex"]
            wd = Path(cx.get("workdir", "."))
            if not wd.is_absolute():
                wd = ROOT / wd
            cfg.codex = Codex(
                enabled=bool(cx.get("enabled", False)),
                allowed_chats=list(cx.get("allowed_chats", [])),
                workdir=wd,
                model=cx.get("model", ""),
                sandbox=cx.get("sandbox", "read-only"),
                timeout_seconds=int(cx.get("timeout_seconds", 600)),
                max_output_chars=int(cx.get("max_output_chars", 4000)),
            )
    return cfg


CFG = load()
