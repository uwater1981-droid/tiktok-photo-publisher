"""Write publish records to Notion TikTok发布记录 database.

Each publish (success or failure) creates one row with:
- 标题, 账号, 状态, 发布模式, 图片数, 视频大小, 发布时间
- 描述, TikTok链接, 错误信息, 产品ID, 代理IP
"""

import os
from datetime import datetime, timezone

import requests

from .utils import setup_logging

logger = setup_logging("tiktok-notion")

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
DATABASE_ID = os.environ.get(
    "NOTION_PUBLISH_DB",
    "336e7a31-238f-81ea-8777-ecf31eb3b0a1",
)
NOTION_API = "https://api.notion.com/v1"


def _get_token() -> str:
    token = NOTION_TOKEN
    if not token:
        # Fallback: try loading from config
        from pathlib import Path
        import json
        cfg = Path(__file__).resolve().parents[1] / "config" / "notion.json"
        if cfg.exists():
            token = json.loads(cfg.read_text(encoding="utf-8")).get("token", "")
    if not token:
        raise RuntimeError(
            "Notion token 未配置。设置 NOTION_TOKEN 环境变量或创建 config/notion.json"
        )
    return token


def _text(content: str) -> list[dict]:
    if not content:
        return []
    # Notion rich_text max 2000 chars
    return [{"text": {"content": content[:2000]}}]


def log_publish(
    *,
    title: str,
    account_id: str,
    success: bool,
    mode: str = "browser",
    image_count: int = 0,
    video_size_kb: int = 0,
    description: str = "",
    tiktok_url: str | None = None,
    error: str = "",
    product_id: str = "",
    proxy_ip: str = "",
) -> str | None:
    """Write a publish record to Notion. Returns page URL or None on failure."""
    try:
        token = _get_token()
    except RuntimeError as e:
        logger.warning(f"Notion 记录跳过: {e}")
        return None

    status_map = {
        True: "已发布",
        False: "失败",
    }
    if not success and "handoff" in mode:
        status_name = "人工兜底"
    else:
        status_name = status_map.get(success, "处理中")

    properties = {
        "标题": {"title": _text(title)},
        "账号": {"select": {"name": account_id}},
        "状态": {"select": {"name": status_name}},
        "发布模式": {"select": {"name": mode.split("_")[0]}},  # browser_dry_run -> browser
        "图片数": {"number": image_count},
        "视频大小(KB)": {"number": video_size_kb},
        "发布时间": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        "描述": {"rich_text": _text(description)},
        "产品ID": {"rich_text": _text(product_id)},
        "代理IP": {"rich_text": _text(proxy_ip)},
    }

    if tiktok_url:
        properties["TikTok链接"] = {"url": tiktok_url}
    if error:
        properties["错误信息"] = {"rich_text": _text(error)}

    try:
        resp = requests.post(
            f"{NOTION_API}/pages",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json={
                "parent": {"database_id": DATABASE_ID},
                "properties": properties,
            },
            timeout=15,
        )
        resp.raise_for_status()
        page_url = resp.json().get("url", "")
        logger.info(f"Notion 记录已写入: {page_url}")
        return page_url
    except Exception as e:
        logger.warning(f"Notion 记录写入失败: {e}")
        return None
