"""TikTok Content Posting API client.

Handles:
- Photo carousel init (POST /v2/post/publish/content/init/)
- Publish status polling (POST /v2/post/publish/status/fetch/)
- Per-account sliding window rate limiter (6 req/min)
"""

import time
from collections import defaultdict, deque
from datetime import datetime

import requests

from .utils import setup_logging

logger = setup_logging("tiktok-api")

API_BASE = "https://open.tiktokapis.com"
INIT_URL = f"{API_BASE}/v2/post/publish/content/init/"
STATUS_URL = f"{API_BASE}/v2/post/publish/status/fetch/"

# TikTok rate limit: 6 requests per minute per user
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 6

# Status polling
DEFAULT_POLL_INTERVAL = 5  # seconds
DEFAULT_MAX_POLLS = 60  # 5 minutes max

TERMINAL_STATUSES = {"PUBLISH_COMPLETE", "FAILED"}
PROCESSING_STATUSES = {"PROCESSING_DOWNLOAD", "PROCESSING_UPLOAD", "SEND_TO_USER_INBOX"}


class TikTokAPIError(Exception):
    def __init__(self, message: str, error_code: str = "", http_status: int = 0):
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status


class TikTokRateLimitError(TikTokAPIError):
    pass


class TikTokPublishTimeout(TikTokAPIError):
    pass


# Per-account rate limiter
_request_timestamps: dict[str, deque] = defaultdict(lambda: deque(maxlen=RATE_LIMIT_MAX))


def _wait_for_rate_limit(account_key: str):
    """Block until a request slot is available for the account."""
    timestamps = _request_timestamps[account_key]
    while len(timestamps) >= RATE_LIMIT_MAX:
        oldest = timestamps[0]
        elapsed = time.time() - oldest
        if elapsed < RATE_LIMIT_WINDOW:
            wait_time = RATE_LIMIT_WINDOW - elapsed + 0.5
            logger.info(f"限速等待 {wait_time:.1f}s (账号: {account_key})")
            time.sleep(wait_time)
        timestamps.popleft()
    timestamps.append(time.time())


def _make_request(
    access_token: str,
    url: str,
    body: dict,
    *,
    account_key: str = "default",
    retry_on_429: bool = True,
    max_retries: int = 3,
) -> dict:
    """Make authenticated request to TikTok API with rate limiting."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    for attempt in range(max_retries + 1):
        _wait_for_rate_limit(account_key)

        resp = requests.post(url, json=body, headers=headers, timeout=30)

        if resp.status_code == 429 and retry_on_429 and attempt < max_retries:
            backoff = 15 * (2 ** attempt)  # 15s, 30s, 60s
            logger.warning(f"429 限速，等待 {backoff}s 后重试 (attempt {attempt + 1})")
            time.sleep(backoff)
            continue

        if resp.status_code == 429:
            raise TikTokRateLimitError(
                f"超过限速，{max_retries} 次重试后仍失败",
                error_code="rate_limit_exceeded",
                http_status=429,
            )

        if resp.status_code >= 500 and attempt < max_retries:
            logger.warning(f"服务器错误 {resp.status_code}，10s 后重试")
            time.sleep(10)
            continue

        if resp.status_code >= 400:
            raise TikTokAPIError(
                f"API 错误 (HTTP {resp.status_code}): {resp.text}",
                http_status=resp.status_code,
            )

        data = resp.json()
        error = data.get("error", {})
        if isinstance(error, dict) and error.get("code") not in ("ok", None):
            raise TikTokAPIError(
                f"API 业务错误: {error}",
                error_code=error.get("code", ""),
            )

        return data

    raise TikTokAPIError("请求失败，已耗尽重试次数")


def init_photo_post(
    access_token: str,
    *,
    title: str,
    description: str,
    photo_urls: list[str],
    photo_cover_index: int = 0,
    privacy_level: str = "PUBLIC_TO_EVERYONE",
    disable_comment: bool = False,
    disable_duet: bool = False,
    disable_stitch: bool = False,
    account_key: str = "default",
) -> dict:
    """Initialize a photo carousel publish.

    Args:
        access_token: Valid OAuth access token
        title: Post title (max 90 chars)
        description: Post description (max 4000 chars)
        photo_urls: List of publicly accessible image URLs (JPEG/WebP, max 35)
        photo_cover_index: Which image is the cover (0-indexed)
        privacy_level: PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, SELF_ONLY
        disable_comment: Disable comments
        disable_duet: Disable duets
        disable_stitch: Disable stitches
        account_key: For rate limiter keying

    Returns:
        dict with publish_id for status polling
    """
    if not photo_urls:
        raise ValueError("至少需要 1 张图片 URL")
    if len(photo_urls) > 35:
        raise ValueError(f"最多 35 张图片，当前 {len(photo_urls)} 张")
    if len(title) > 90:
        logger.warning(f"标题超过 90 字符，将被截断: {title[:50]}...")
        title = title[:90]

    body = {
        "post_info": {
            "title": title,
            "description": description,
            "privacy_level": privacy_level,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_images": photo_urls,
            "photo_cover_index": photo_cover_index,
        },
        "post_mode": "DIRECT_POST",
        "media_type": "PHOTO",
    }

    logger.info(f"初始化图文发布: {len(photo_urls)} 张图片, 标题: {title[:30]}...")
    result = _make_request(access_token, INIT_URL, body, account_key=account_key)

    publish_id = result.get("data", {}).get("publish_id")
    if not publish_id:
        raise TikTokAPIError(f"未返回 publish_id: {result}")

    logger.info(f"发布已初始化: publish_id={publish_id}")
    return {"publish_id": publish_id, "raw_response": result}


def poll_status(
    access_token: str,
    publish_id: str,
    *,
    max_attempts: int = DEFAULT_MAX_POLLS,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    account_key: str = "default",
) -> dict:
    """Poll publish status until terminal state.

    Returns:
        dict with status, publish_id, and details
    """
    logger.info(f"开始轮询发布状态: {publish_id}")

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            time.sleep(poll_interval)

        result = _make_request(
            access_token,
            STATUS_URL,
            {"publish_id": publish_id},
            account_key=account_key,
        )

        status = result.get("data", {}).get("status", "UNKNOWN")
        fail_reason = result.get("data", {}).get("fail_reason", "")

        logger.info(f"  轮询 {attempt}/{max_attempts}: status={status}")

        if status == "PUBLISH_COMPLETE":
            return {
                "status": "PUBLISH_COMPLETE",
                "publish_id": publish_id,
                "success": True,
                "attempts": attempt,
            }

        if status == "FAILED":
            return {
                "status": "FAILED",
                "publish_id": publish_id,
                "success": False,
                "fail_reason": fail_reason,
                "attempts": attempt,
            }

        if status not in PROCESSING_STATUSES:
            logger.warning(f"  未知状态: {status}")

    raise TikTokPublishTimeout(
        f"发布超时: {max_attempts * poll_interval}s 后仍未完成 (publish_id={publish_id})",
        error_code="publish_timeout",
    )
