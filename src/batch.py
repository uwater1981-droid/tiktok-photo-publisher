"""Multi-account batch publisher.

Features:
- Same content to N accounts: CDN upload once
- Concurrent publishing with ThreadPoolExecutor
- Configurable stagger delay between accounts
- Per-account results
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .accounts import get_active_accounts, get_accounts_by_tag
from .cdn import upload as cdn_upload
from .publisher import publish
from .utils import setup_logging, validate_images

logger = setup_logging("tiktok-batch")


def batch_publish(
    title: str,
    description: str,
    image_paths: list[str],
    *,
    account_ids: list[str] | None = None,
    tag: str | None = None,
    all_active: bool = False,
    max_concurrent: int = 4,
    stagger_seconds: float = 5.0,
    privacy_level: str = "PUBLIC_TO_EVERYONE",
    headless: bool = False,
    dry_run: bool = False,
) -> dict:
    """Publish same content to multiple TikTok accounts.

    Args:
        title: Post title
        description: Post description
        image_paths: Local image file paths
        account_ids: Specific account IDs to publish to
        tag: Publish to all active accounts with this tag
        all_active: Publish to all active accounts
        max_concurrent: Max parallel publishes
        stagger_seconds: Delay between starting each publish
        privacy_level: TikTok privacy setting
        headless: Run browsers without GUI
        dry_run: Skip actual publishing

    Returns:
        dict with summary and per-account results
    """
    # Resolve target accounts
    if account_ids:
        accounts = [{"account_id": aid} for aid in account_ids]
    elif tag:
        accounts = get_accounts_by_tag(tag)
    elif all_active:
        accounts = get_active_accounts()
    else:
        raise ValueError("必须指定 account_ids, tag, 或 all_active")

    if not accounts:
        return {"success": True, "total": 0, "message": "无目标账号", "results": []}

    # Validate images once
    errors = validate_images(image_paths)
    if errors:
        return {"success": False, "total": 0, "error": "; ".join(errors), "results": []}

    target_ids = [a["account_id"] for a in accounts]
    logger.info(f"批量发布: {len(target_ids)} 个账号, {len(image_paths)} 张图片")

    # Pre-upload to CDN once (for API mode accounts, browser mode uses local files)
    # CDN upload is idempotent due to content-hash keys
    if not dry_run:
        try:
            cdn_urls = cdn_upload(image_paths)
            logger.info(f"CDN 预上传完成: {len(cdn_urls)} 张图片")
        except Exception as e:
            logger.warning(f"CDN 预上传失败 (浏览器模式不受影响): {e}")

    results = []

    def _publish_one(account_id: str, index: int) -> dict:
        if index > 0 and stagger_seconds > 0:
            time.sleep(stagger_seconds * index)
        try:
            return publish(
                account_id, title, description, image_paths,
                privacy_level=privacy_level,
                headless=headless,
                dry_run=dry_run,
            )
        except Exception as e:
            return {"success": False, "mode": "error", "error": str(e)}

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(_publish_one, aid, i): aid
            for i, aid in enumerate(target_ids)
        }

        for future in as_completed(futures):
            account_id = futures[future]
            try:
                result = future.result()
                result["account_id"] = account_id
            except Exception as e:
                result = {"account_id": account_id, "success": False, "error": str(e)}
            results.append(result)
            status = "OK" if result.get("success") else "FAIL"
            logger.info(f"  {account_id}: {status} ({result.get('mode', '?')})")

    succeeded = sum(1 for r in results if r.get("success"))
    failed = len(results) - succeeded

    summary = {
        "success": failed == 0,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }

    logger.info(f"批量发布完成: {succeeded}/{len(results)} 成功")
    return summary
