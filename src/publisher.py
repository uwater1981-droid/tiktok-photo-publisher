"""Unified TikTok publisher with dual-track dispatch.

Strategy per account auth_mode:
- "api": Only use TikTok Content Posting API
- "browser": Only use AdsPower + DrissionPage
- "auto" (default): Try API first, fallback to browser
"""

from .accounts import get_account
from .oauth import OAuthUnavailable
from . import publisher_api
from . import publisher_browser
from .utils import setup_logging

logger = setup_logging("tiktok-publisher")


def publish(
    account_id: str,
    title: str,
    description: str,
    image_paths: list[str],
    *,
    privacy_level: str = "PUBLIC_TO_EVERYONE",
    disable_comment: bool = False,
    headless: bool = False,
    close_browser: bool = True,
    dry_run: bool = False,
) -> dict:
    """Publish photo carousel to TikTok.

    Dispatches to API or browser mode based on account config.
    In "auto" mode, tries API first and falls back to browser.

    Args:
        account_id: Account ID from config/accounts.json
        title: Post title
        description: Post description
        image_paths: Local image file paths
        privacy_level: TikTok privacy setting
        disable_comment: Disable comments
        headless: Run browser without GUI (browser mode only)
        close_browser: Close browser after publishing (browser mode only)
        dry_run: Skip actual publishing

    Returns:
        dict with success, mode, message, and mode-specific fields
    """
    account = get_account(account_id)
    mode = account.get("auth_mode", "auto")

    logger.info(f"发布到 {account_id} (mode={mode}): {title[:30]}... ({len(image_paths)} 张图片)")

    if mode == "api":
        return publisher_api.publish(
            account_id, title, description, image_paths,
            privacy_level=privacy_level,
            disable_comment=disable_comment,
            dry_run=dry_run,
        )

    if mode == "browser":
        return publisher_browser.publish(
            account_id, title, description, image_paths,
            headless=headless,
            close_browser=close_browser,
            dry_run=dry_run,
        )

    # mode == "auto": try API first, fallback to browser on any failure
    try:
        result = publisher_api.publish(
            account_id, title, description, image_paths,
            privacy_level=privacy_level,
            disable_comment=disable_comment,
            dry_run=dry_run,
        )
        if result.get("success"):
            return result
        logger.warning(f"API 发布失败，降级到浏览器模式: {result.get('error')}")
    except OAuthUnavailable as e:
        logger.info(f"OAuth 不可用，降级到浏览器模式: {e}")
    except Exception as e:
        logger.warning(f"API 异常，降级到浏览器模式: {e}")

    # Fallback to browser
    return publisher_browser.publish(
        account_id, title, description, image_paths,
        headless=headless,
        close_browser=close_browser,
        dry_run=dry_run,
    )
