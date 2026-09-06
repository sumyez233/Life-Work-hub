"""飞书多维表格（Bitable）联动模块（通用版）。

定位：把"任意一张飞书多维表格"变成可被飞书对话、晨报、CLI 查看的轻量数据源。
- 查看更新情况：展示记录总数与最近更新时间（字段名在 config.toml 指定）；
- 联动取数：分页拉取全部记录并缓存到本地 JSON，供其他脚本/工作流复用。

本模块不假设任何业务字段结构；业务语义由使用者自己的表格定义。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .config import CFG

log = logging.getLogger(__name__)


def configured() -> bool:
    return bool(CFG.bitable.app_token and CFG.bitable.table_id)


def _get_token() -> str | None:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = {"app_id": CFG.feishu.app_id, "app_secret": CFG.feishu.app_secret}
    try:
        res = requests.post(url, json=data, timeout=10)
        return res.json().get("tenant_access_token")
    except Exception as e:
        log.error("获取 tenant_access_token 失败: %s", e)
        return None


def fetch_records() -> list[dict[str, Any]] | None:
    """分页拉取多维表格全部记录的 fields；未配置或失败返回 None。"""
    if not configured():
        return None
    token = _get_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    records: list[dict[str, Any]] = []
    page_token = ""
    try:
        while True:
            url = (
                f"https://open.feishu.cn/open-apis/bitable/v1/apps/{CFG.bitable.app_token}"
                f"/tables/{CFG.bitable.table_id}/records?page_size=100"
            )
            if page_token:
                url += f"&page_token={page_token}"
            res = requests.get(url, headers=headers, timeout=20).json()
            data = res.get("data", {})
            records.extend(item.get("fields", {}) for item in data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
    except Exception as e:
        log.error("拉取多维表格记录失败: %s", e)
        return None
    return records


def _latest_updated(records: list[dict[str, Any]]) -> str:
    """按 config 指定的时间字段挑出最新值（按字符串排序的近似处理）。"""
    field = CFG.bitable.updated_field
    if not field:
        return ""
    values: list[str] = []
    for rec in records:
        v = rec.get(field)
        if isinstance(v, dict):
            v = v.get("text") or v.get("link")
        if v:
            values.append(str(v).strip())
    return max(values)[:19] if values else ""


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """生成通用摘要：总量 + 最近更新时间 + 抓取时间。"""
    return {
        "total_records": len(records),
        "latest_updated": _latest_updated(records),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_and_analyze() -> dict[str, Any] | None:
    """兼容命名：拉取并摘要。未配置或失败返回 None。"""
    records = fetch_records()
    if records is None:
        return None
    stats = summarize(records)
    _save_cache(stats)
    return stats


def _save_cache(stats: dict[str, Any]) -> None:
    try:
        cache_path: Path = CFG.bitable.cache_file
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_cached_or_fresh() -> dict[str, Any]:
    cache_path: Path = CFG.bitable.cache_file
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    fresh = fetch_and_analyze()
    if fresh:
        return fresh
    if not configured():
        return {"total_records": 0, "latest_updated": "", "fetched_at": "", "configured": False}
    return {"total_records": 0, "latest_updated": "", "fetched_at": "", "configured": True}


def build_bitable_card() -> dict:
    """构建飞书 Schema 2.0 卡片：更新概况 + 打开多维表格。"""
    stats = fetch_and_analyze() or get_cached_or_fresh()
    configured_ok = stats.get("configured", True)
    total = stats.get("total_records", 0)
    latest = stats.get("latest_updated") or ""
    fetched_at = stats.get("fetched_at") or ""

    if not configured_ok:
        content = (
            "**还没有绑定多维表格**\n"
            "在 config.toml 的 [bitable] 填入 app_token / table_id（可选 updated_field），"
            "即可在飞书里查看表格更新情况。"
        )
        return {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "📊 多维表格联动"},
                "subtitle": {"tag": "plain_text", "content": "接入你自己的多维表格 · 查看更新与联动取数"},
                "template": "blue",
            },
            "body": {"elements": [{"tag": "markdown", "content": content}]},
        }

    latest_line = f"最近更新：**{latest}**" if latest else "最近更新：未配置 updated_field（可在 config.toml 指定时间字段）"
    elements = [
        {
            "tag": "markdown",
            "content": (
                f"**记录总数**\n<font color='blue' size='6'>**{total}**</font> <font color='grey'>条</font>\n\n"
                f"{latest_line}"
            ),
        },
        {"tag": "hr"},
        {"tag": "markdown", "content": f"本地缓存快照：{fetched_at or '暂无'}"},
    ]
    if configured():
        url = f"https://my.feishu.cn/base/{CFG.bitable.app_token}?table={CFG.bitable.table_id}"
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🔗 打开多维表格"},
            "type": "primary_filled",
            "width": "default",
            "size": "medium",
            "multi_url": {"url": url, "pc_url": url, "android_url": url, "ios_url": url},
        })

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 多维表格动态 · {total} 条记录"},
            "subtitle": {"tag": "plain_text", "content": "接入你自己的多维表格 · 查看更新与联动取数"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }
