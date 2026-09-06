"""本地文件直传手机飞书模块。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import requests

from .config import CFG

log = logging.getLogger(__name__)

INBOX_DIR: Path = CFG.transfer.inbox_dir


def _get_token() -> str | None:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = {"app_id": CFG.feishu.app_id, "app_secret": CFG.feishu.app_secret}
    try:
        res = requests.post(url, json=data, timeout=10)
        return res.json().get("tenant_access_token")
    except Exception as e:
        log.error("获取 tenant_access_token 失败: %s", e)
        return None


def find_file(keyword: str) -> Path | None:
    """在常用目录中模糊搜索文件。"""
    keyword = keyword.strip().strip("'\"")
    # 1. 绝对路径或当前相对路径
    p = Path(keyword)
    if p.is_file():
        return p

    # 2. 在配置的搜索目录中匹配
    clean_kw = keyword.lower()
    for d in CFG.transfer.search_dirs:
        dir_path = Path(d)
        if not dir_path.is_dir():
            continue
        try:
            # 优先检查直接子文件
            for f in dir_path.iterdir():
                if f.is_file() and clean_kw in f.name.lower():
                    return f
            # 再检查一层子目录（如常用子文件夹）
            for sub in dir_path.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    for f in sub.iterdir():
                        if f.is_file() and clean_kw in f.name.lower():
                            return f
        except Exception:
            continue
    return None


def send_file(file_path: str | Path, chat_id: str | None = None) -> tuple[bool, str]:
    """上传本地文件并推送到指定会话（默认推送至当前会话或 report_chat）。"""
    path = Path(file_path)
    if not path.is_file():
        return False, f"未找到文件: {file_path}"

    target_chat = chat_id or CFG.feishu.report_chat
    if not target_chat:
        return False, "未配置接收消息的 chat_id"

    token = _get_token()
    if not token:
        return False, "获取飞书凭据失败"

    file_name = path.name
    # 1. 上传文件获取 file_key
    upload_url = "https://open.feishu.cn/open-apis/im/v1/files"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"file_type": "stream", "file_name": file_name}

    try:
        with open(path, "rb") as f:
            files = {"file": (file_name, f, "application/octet-stream")}
            res = requests.post(upload_url, headers=headers, data=data, files=files, timeout=60).json()

        if res.get("code") != 0:
            return False, f"文件上传失败: {res.get('msg')}"

        file_key = res["data"]["file_key"]

        # 2. 推送到聊天
        send_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        headers["Content-Type"] = "application/json; charset=utf-8"
        body = {
            "receive_id": target_chat,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key})
        }
        send_res = requests.post(send_url, headers=headers, json=body, timeout=15).json()
        if send_res.get("code") == 0:
            return True, f"已发送「{file_name}」到飞书"
        return False, f"消息推送失败: {send_res.get('msg')}"
    except Exception as e:
        return False, f"传输异常: {e}"


def download_message_resource(
    message_id: str,
    file_key: str,
    file_name: str,
    res_type: str = "file"
) -> tuple[bool, str, Path | None]:
    """从飞书下载用户发送的文件或图片到本地收件箱（默认项目内 inbox/，可在 config.toml 覆盖）。"""
    token = _get_token()
    if not token:
        return False, "获取飞书凭据失败", None

    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type={res_type}"
    headers = {"Authorization": f"Bearer {token}"}

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    target_path = INBOX_DIR / file_name

    # 如果同名文件存在，追加时间戳后缀避免覆盖
    if target_path.exists():
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        stem, suffix = target_path.stem, target_path.suffix
        target_path = INBOX_DIR / f"{stem}_{ts}{suffix}"

    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=60)
        if resp.status_code != 200:
            return False, f"下载失败 HTTP {resp.status_code}: {resp.text[:100]}", None

        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        return True, "下载成功", target_path
    except Exception as e:
        return False, f"下载出错: {e}", None
