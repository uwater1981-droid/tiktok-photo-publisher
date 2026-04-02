"""API-based TikTok publisher using Content Posting API.

Flow:
1. Get OAuth access token (auto-refresh)
2. Upload images to CDN (get public URLs)
3. Call TikTok init photo post API
4. Poll publish status until complete
"""

from .oauth import get_access_token, OAuthUnavailable
from .cdn import upload as cdn_upload
from .api_client import init_photo_post, poll_status, TikTokAPIError
from .utils import setup_logging, validate_images

logger = setup_logging("tiktok-api-publisher")


def publish(
    account_id: str,
    title: str,
    description: str,
    image_paths: list[str],
    *,
    privacy_level: str = "PUBLIC_TO_EVERYONE",
    disable_comment: bool = False,
    dry_run: bool = False,
) -> dict:
    """Publish photo carousel via TikTok Content Posting API.

    Args:
        account_id: Account ID (must have OAuth token)
        title: Post title (max 90 chars)
        description: Post description
        image_paths: Local image file paths
        privacy_level: PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, SELF_ONLY
        dry_run: Skip actual publishing

    Returns:
        dict with success, mode, publish_id, status, etc.
    """
    # Validate images
    errors = validate_images(image_paths)
    if errors:
        return {"success": False, "mode": "api", "error": "; ".join(errors)}

    if dry_run:
        return {
            "success": True,
            "mode": "api_dry_run",
            "message": f"Dry run: 将通过 API 发布 {len(image_paths)} 张图片到 {account_id}",
        }

    try:
        # 1. Get OAuth token
        access_token, open_id = get_access_token(account_id)
        logger.info(f"已获取 OAuth token: {account_id}")

        # 2. Upload images to CDN
        photo_urls = cdn_upload(image_paths)
        logger.info(f"已上传 {len(photo_urls)} 张图片到 CDN")

        # 3. Init publish
        result = init_photo_post(
            access_token,
            title=title,
            description=description,
            photo_urls=photo_urls,
            privacy_level=privacy_level,
            disable_comment=disable_comment,
            account_key=account_id,
        )

        publish_id = result["publish_id"]

        # 4. Poll status
        status = poll_status(
            access_token,
            publish_id,
            account_key=account_id,
        )

        return {
            "success": status.get("success", False),
            "mode": "api",
            "publish_id": publish_id,
            "status": status.get("status"),
            "message": f"API 发布{'成功' if status.get('success') else '失败'}: {status.get('status')}",
            "fail_reason": status.get("fail_reason", ""),
        }

    except OAuthUnavailable as e:
        logger.warning(f"OAuth 不可用: {e}")
        raise  # Let unified publisher handle fallback

    except TikTokAPIError as e:
        logger.error(f"API 发布失败: {e}")
        return {
            "success": False,
            "mode": "api",
            "error": str(e),
            "error_code": getattr(e, "error_code", ""),
        }
