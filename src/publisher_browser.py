"""Browser-based TikTok publisher using AdsPower + Selenium.

TikTok web (TikTok Studio) only supports VIDEO upload, not photo carousel.
So the flow is:
1. Convert images to slideshow video via FFmpeg (video_maker)
2. AdsPower starts the account's browser profile (unique fingerprint + proxy)
3. Selenium connects via debug port
4. Navigate to TikTok Studio upload, upload the video
5. Fill caption/description
6. Click publish
7. Verify post appears in content manager

Fallback: generates handoff JSON for manual publishing on failure.
"""

import os
import time
import tempfile
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

from . import adspower
from .accounts import get_account
from .video_maker import images_to_video
from .utils import setup_logging, build_handoff, validate_images

logger = setup_logging("tiktok-browser")

TIKTOK_UPLOAD_URL = "https://www.tiktok.com/upload?lang=en"
SCREENSHOTS_DIR = Path(__file__).resolve().parents[1] / "screenshots"
ARCHIVE_BASE = os.environ.get("TIKTOK_ARCHIVE_DIR", "G:/TikTok发布归档")


def _archive_content(
    account_id: str,
    image_paths: list[str],
    video_path: str | None,
    title: str,
    description: str,
    result: dict,
):
    """Archive images, video, screenshots to G drive."""
    try:
        import shutil, json
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_title = "".join(c for c in title[:30] if c.isalnum() or c in " _-").strip()
        archive_dir = Path(ARCHIVE_BASE) / f"{date_str}_{account_id}_{safe_title}"
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Copy images
        for img in image_paths:
            if os.path.exists(img):
                shutil.copy2(img, archive_dir / Path(img).name)

        # Copy video
        if video_path and os.path.exists(video_path):
            shutil.copy2(video_path, archive_dir / "slideshow.mp4")

        # Copy screenshots
        for key in ("screenshot",):
            path = result.get(key)
            if path and os.path.exists(path):
                shutil.copy2(path, archive_dir / Path(path).name)

        # Write metadata
        meta = {
            "account_id": account_id,
            "title": title,
            "description": description,
            "image_count": len(image_paths),
            "result": {k: v for k, v in result.items() if isinstance(v, (str, bool, int, float, type(None)))},
            "archived_at": datetime.now().isoformat(),
        }
        (archive_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"已归档到: {archive_dir}")
    except Exception as e:
        logger.warning(f"归档失败: {e}")


def _find_adspower_chromedriver() -> str:
    """Auto-detect the latest AdsPower chromedriver path."""
    import glob
    base = os.path.expandvars(
        os.environ.get("ADSPOWER_DIR", "%APPDATA%/adspower_global/cwd_global")
    )
    # Find all chrome_*/chromedriver.exe, pick the latest version
    pattern = os.path.join(base, "chrome_*", "chromedriver.exe")
    matches = sorted(glob.glob(pattern), reverse=True)
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"未找到 AdsPower chromedriver。搜索路径: {pattern}\n"
        "可通过 ADSPOWER_DIR 环境变量指定 AdsPower cwd_global 目录"
    )


def _connect_selenium(selenium_address: str, webdriver_path: str) -> webdriver.Chrome:
    """Connect Selenium to a running AdsPower browser via debug port."""
    opts = Options()
    opts.debugger_address = selenium_address

    if webdriver_path and os.path.exists(webdriver_path):
        driver_path = webdriver_path
    else:
        driver_path = _find_adspower_chromedriver()

    driver = webdriver.Chrome(service=Service(driver_path), options=opts)
    driver.set_script_timeout(15)
    return driver


def _screenshot(driver: webdriver.Chrome, name: str) -> str | None:
    """Take screenshot for debugging/audit."""
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = str(SCREENSHOTS_DIR / f"{name}-{ts}.png")
        driver.save_screenshot(path)
        return path
    except Exception as e:
        logger.warning(f"截图失败: {e}")
        return None


def _js_click_button(driver: webdriver.Chrome, text: str, timeout: int = 10) -> bool:
    """Click a button by its text content using JavaScript.

    Uses executeScript arguments to avoid JS injection from text content.
    """
    for _ in range(timeout):
        clicked = driver.execute_script('''
            var target = arguments[0];
            var buttons = document.querySelectorAll('button');
            for (var b of buttons) {
                if (b.textContent.trim() === target && !b.disabled) {
                    b.scrollIntoView();
                    b.click();
                    return true;
                }
            }
            return false;
        ''', text)
        if clicked:
            return True
        time.sleep(1)
    return False


def _fill_caption(driver: webdriver.Chrome, text: str) -> bool:
    """Fill the caption/description field.

    Uses executeScript arguments to avoid JS injection.
    """
    return driver.execute_script('''
        var caption = arguments[0];
        var editors = document.querySelectorAll(
            '.public-DraftEditor-content, [contenteditable="true"]'
        );
        for (var e of editors) {
            var rect = e.getBoundingClientRect();
            if (rect.width > 100 && rect.height > 10) {
                e.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, caption);
                return true;
            }
        }
        return false;
    ''', text)


def publish(
    account_id: str,
    title: str,
    description: str,
    image_paths: list[str],
    *,
    duration_per_image: float = 3.0,
    headless: bool = False,
    close_browser: bool = True,
    dry_run: bool = False,
) -> dict:
    """Publish images as slideshow video via AdsPower browser.

    Args:
        account_id: Account ID (must have adspower_profile_id)
        title: Post title/caption
        description: Post description (appended to title)
        image_paths: Local image file paths
        duration_per_image: Seconds each image shows in video
        headless: Run browser without GUI
        close_browser: Close browser after publishing
        dry_run: Skip actual publishing

    Returns:
        dict with success, mode, message, etc.
    """
    errors = validate_images(image_paths)
    if errors:
        return {"success": False, "mode": "browser", "error": "; ".join(errors)}

    account = get_account(account_id)
    profile_id = account.get("adspower_profile_id")
    if not profile_id:
        return {
            "success": False,
            "mode": "browser",
            "error": f"账号 {account_id} 缺少 adspower_profile_id",
        }

    # Step 1: Generate slideshow video from images
    video_dir = tempfile.mkdtemp(prefix="tiktok_video_")
    video_path = os.path.join(video_dir, "slideshow.mp4")

    try:
        logger.info(f"生成轮播视频: {len(image_paths)} 张图片 x {duration_per_image}s")
        images_to_video(
            image_paths,
            video_path,
            duration_per_image=duration_per_image,
        )
        video_size = os.path.getsize(video_path)
        logger.info(f"视频已生成: {video_size / 1024:.0f} KB")
    except Exception as e:
        return {"success": False, "mode": "browser", "error": f"视频生成失败: {e}"}

    if dry_run:
        return {
            "success": True,
            "mode": "browser_dry_run",
            "message": f"Dry run: {len(image_paths)} 张图片 → {video_size/1024:.0f}KB 视频 → {account_id}",
            "video_path": video_path,
        }

    driver = None
    browser_started = False

    try:
        # Step 2: Start AdsPower browser
        browser_info = adspower.start_browser(profile_id, headless=headless)
        browser_started = True
        logger.info(f"AdsPower 浏览器已启动: {browser_info['selenium_address']}")
        time.sleep(3)

        # Step 3: Connect Selenium
        driver = _connect_selenium(
            browser_info["selenium_address"],
            browser_info.get("webdriver_path", ""),
        )

        # Step 4: Verify proxy (optional but recommended)
        driver.get("https://api.ipify.org?format=json")
        time.sleep(5)
        try:
            ip_text = driver.find_element(By.TAG_NAME, "body").text
            logger.info(f"代理 IP: {ip_text}")
        except Exception:
            logger.warning("无法验证代理 IP")

        # Step 5: Navigate to TikTok upload
        driver.get(TIKTOK_UPLOAD_URL)
        time.sleep(8)
        _screenshot(driver, f"{account_id}-01-upload-page")

        # Step 6: Find file input and upload video
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        if not inputs:
            raise RuntimeError("未找到文件上传控件")

        abs_video = os.path.abspath(video_path)
        inputs[0].send_keys(abs_video)
        logger.info(f"已上传视频: {abs_video}")

        # Wait for upload to process
        time.sleep(15)
        _screenshot(driver, f"{account_id}-02-video-uploaded")

        # Step 7: Fill caption
        caption = f"{title}\n{description}".strip() if description else title
        if _fill_caption(driver, caption):
            logger.info(f"已填写描述: {caption[:40]}...")
        else:
            logger.warning("未能自动填写描述")

        time.sleep(2)
        _screenshot(driver, f"{account_id}-03-caption-filled")

        # Step 8: Dismiss any popup (copyright check etc.)
        for dismiss_text in ["إلغاء", "Cancel", "Got it", "تجاهل"]:
            try:
                _js_click_button(driver, dismiss_text, timeout=2)
            except Exception:
                pass

        # Step 9: Click publish — try multiple languages
        published = False
        for btn_text in ["نشر", "Post", "Publish", "发布"]:
            if _js_click_button(driver, btn_text, timeout=3):
                published = True
                logger.info(f"已点击发布按钮: {btn_text}")
                break

        if not published:
            _screenshot(driver, f"{account_id}-04-no-publish-btn")
            raise RuntimeError("未找到发布按钮")

        # Step 10: Wait for confirmation
        time.sleep(10)
        final_url = driver.current_url
        final_title = driver.title
        screenshot_path = _screenshot(driver, f"{account_id}-05-published")

        # Verify success: check for content manager redirect + confirmation elements
        success = False
        if "content" in final_url and "upload" not in final_url:
            # Redirected away from upload to content manager — good sign
            success = True
        if not success:
            # Check DOM for post entry (thumbnail with review status)
            has_post = driver.execute_script('''
                return document.querySelector('[class*="content-item"], [class*="video-card"]') !== null;
            ''')
            if has_post:
                success = True
        if not success:
            logger.warning(f"发布后未检测到成功指标: {final_url}")

        result = {
            "success": success,
            "mode": "browser",
            "message": f"已发布 {len(image_paths)} 张图片轮播视频到 {account_id}",
            "screenshot": screenshot_path,
            "url": final_url,
            "video_path": video_path,
        }
        _archive_content(account_id, image_paths, video_path, title, description, result)
        return result

    except Exception as e:
        logger.error(f"浏览器发布失败: {e}")
        screenshot_path = _screenshot(driver, f"{account_id}-error") if driver else None

        handoff_path = build_handoff(
            account_id=account_id,
            title=title,
            description=description,
            image_paths=image_paths,
            error=str(e),
            screenshot_path=screenshot_path,
            video_path=video_path if os.path.exists(video_path) else None,
        )
        logger.info(f"已生成人工操作包: {handoff_path}")

        return {
            "success": False,
            "mode": "browser",
            "error": str(e),
            "handoff": str(handoff_path),
            "screenshot": screenshot_path,
        }

    finally:
        if browser_started and close_browser:
            try:
                adspower.stop_browser(profile_id)
                logger.info("AdsPower 浏览器已关闭")
            except Exception as e:
                logger.warning(f"关闭浏览器失败: {e}")
        # Clean up temp video directory
        import shutil
        if os.path.isdir(video_dir):
            shutil.rmtree(video_dir, ignore_errors=True)
