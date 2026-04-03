#!/usr/bin/env python3
"""Auto-publish different content to all active TikTok accounts.

Each account gets a unique product + caption + hashtag combination.
Designed to be called by a scheduler every 2 hours.

Usage:
    python scripts/auto_publish.py
    python scripts/auto_publish.py --dry-run
    python scripts/auto_publish.py --accounts tiktok_sa_02 tiktok_sa_03
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.accounts import get_active_accounts
from src.brand_template import create_branded_slides
from src.content_pool import generate_content, log_publish_local
from src.video_maker import images_to_video
from src import adspower
from src.notion_log import log_publish as notion_log
from src.utils import setup_logging

logger = setup_logging("auto-publish")

CHROMEDRIVER = None  # Auto-detected


def _find_chromedriver() -> str:
    import glob, os
    base = os.path.expandvars(os.environ.get("ADSPOWER_DIR", "%APPDATA%/adspower_global/cwd_global"))
    matches = sorted(glob.glob(os.path.join(base, "chrome_*", "chromedriver.exe")), reverse=True)
    if matches:
        return matches[0]
    raise FileNotFoundError("未找到 AdsPower chromedriver")


def publish_one(account_id: str, profile_id: str, *, dry_run: bool = False) -> dict:
    """Generate unique content and publish to one account."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    import os, tempfile

    global CHROMEDRIVER
    if not CHROMEDRIVER:
        CHROMEDRIVER = _find_chromedriver()

    branded_dir = None
    video_dir = None

    # 1. Generate content
    content = generate_content(account_id, use_firecrawl=True)
    logger.info(f"[{account_id}] 内容: {content['category']} - {len(content['image_paths'])} 张图片")

    if dry_run:
        return {"success": True, "mode": "dry_run", "account_id": account_id,
                "message": f"Dry run: {content['category']} {content['title'][:30]}"}

    branded_dir = tempfile.mkdtemp(prefix="tiktok_branded_")
    branded_paths = create_branded_slides(
        content["image_paths"], branded_dir,
        title_ar=content["category_ar"],
        subtitle_ar=content.get('feature_ar', '')[:35],
        title_en=content["category_en"],
        category_en=content["category_en"].upper(),
    )
    logger.info(f"[{account_id}] branded: {len(branded_paths)} slides")

    # 2. Generate video
    video_dir = tempfile.mkdtemp(prefix="tiktok_auto_")
    video_path = os.path.join(video_dir, "slideshow.mp4")
    images_to_video(branded_paths, video_path, duration_per_image=4.0)
    logger.info(f"[{account_id}] 视频: {os.path.getsize(video_path)/1024:.0f} KB")

    browser_started = False
    try:
        # 3. Start browser
        browser_info = adspower.start_browser(profile_id)
        browser_started = True
        time.sleep(5)

        opts = Options()
        opts.debugger_address = browser_info["selenium_address"]
        driver = webdriver.Chrome(service=Service(CHROMEDRIVER), options=opts)
        driver.set_page_load_timeout(25)
        driver.set_script_timeout(8)
        driver.set_window_size(1440, 900)

        # 4. Navigate to upload
        driver.get("https://www.tiktok.com/creator#/upload?scene=creator_center")
        time.sleep(12)

        # Handle draft popup
        driver.execute_script('''
            document.querySelectorAll("button").forEach(function(b){
                if (b.textContent.trim() === "Discard") b.click();
            });
        ''')
        time.sleep(2)

        # 5. Upload video
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        if not inputs:
            raise RuntimeError("未找到上传控件")
        inputs[0].send_keys(os.path.abspath(video_path))
        logger.info(f"[{account_id}] 上传中...")
        time.sleep(20)

        # 6. Fill caption (keyboard method - proven to work)
        # Find and focus the description editor
        focused = driver.execute_script('''
            var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, null, false);
            while (walker.nextNode()) {
                var el = walker.currentNode;
                if (el.getAttribute && (el.getAttribute("contenteditable") === "true" ||
                    el.classList.contains("public-DraftEditor-content")) &&
                    el.getBoundingClientRect().width > 100) {
                    el.focus(); el.click();
                    var sel = window.getSelection();
                    var range = document.createRange();
                    range.selectNodeContents(el);
                    sel.removeAllRanges(); sel.addRange(range);
                    return true;
                }
            }
            return false;
        ''')
        if focused:
            ActionChains(driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
            time.sleep(0.3)
            full_desc = f"{content['caption_ar']}\n\n{content['hashtags']}\n\n{content['caption_en']}"
            ActionChains(driver).send_keys(full_desc[:3900]).perform()
            time.sleep(1)
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(1)
        logger.info(f"[{account_id}] 描述已填写")

        # 7. Dismiss popups
        for t in ["Not now", "Got it", "Cancel"]:
            driver.execute_script(
                'var t=arguments[0]; document.querySelectorAll("button").forEach(function(b){if(b.textContent.trim()===t)b.click()})', t)
            time.sleep(0.5)

        # 8. Click Post via React (proven method)
        driver.execute_script('''
            var btns = document.querySelectorAll("button");
            for (var b of btns) {
                if (b.textContent.trim() === "Post" && !b.disabled) {
                    b.scrollIntoView({block: "center"});
                    b.focus();
                    var key = Object.keys(b).find(function(k){return k.startsWith("__reactFiber")});
                    if (key) {
                        var f = b[key], c = f;
                        while (c) {
                            if (c.memoizedProps && c.memoizedProps.onClick) {
                                c.memoizedProps.onClick({preventDefault:function(){},stopPropagation:function(){},nativeEvent:new MouseEvent("click"),target:b});
                                break;
                            }
                            c = c["return"];
                        }
                    }
                    b.dispatchEvent(new MouseEvent("click", {bubbles: true}));
                    b.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));
                }
            }
        ''')
        logger.info(f"[{account_id}] Post 已触发")
        time.sleep(15)

        # 9. Verify
        url = driver.current_url
        success = "content" in url or driver.execute_script(
            'return !document.querySelector("button")?.textContent?.includes("Post")'
        )

        # 10. Log
        log_publish_local(account_id, content["product_id"], content["category"], success)

        # 11. Archive to G drive
        _archive(account_id, content, video_path, branded_paths=branded_paths)

        result = {
            "success": True,
            "mode": "browser",
            "account_id": account_id,
            "product_id": content["product_id"],
            "category": content["category"],
            "message": f"{content['title'][:40]}",
        }

        # 12. Notion log
        notion_log(
            title=content["title"],
            account_id=account_id,
            success=True,
            mode="browser",
            image_count=len(content["image_paths"]),
            description=f"{content['category']} - {content['caption_en'][:60]}",
            product_id=content["product_id"],
        )

        return result

    except Exception as e:
        logger.error(f"[{account_id}] 发布失败: {e}")
        log_publish_local(account_id, content.get("product_id", ""), content.get("category", ""), False)
        return {
            "success": False,
            "mode": "browser",
            "account_id": account_id,
            "error": str(e)[:200],
        }

    finally:
        if browser_started:
            try:
                adspower.stop_browser(profile_id)
            except Exception:
                pass
        import shutil
        if branded_dir:
            shutil.rmtree(branded_dir, ignore_errors=True)
        if video_dir:
            shutil.rmtree(video_dir, ignore_errors=True)


def _archive(account_id: str, content: dict, video_path: str, branded_paths: list[str] | None = None):
    """Archive content to G drive."""
    import os
    from datetime import datetime
    import shutil
    archive_base = os.environ.get("TIKTOK_ARCHIVE_DIR", "G:/TikTok发布归档")
    date = datetime.now().strftime("%Y-%m-%d_%H%M")
    archive_dir = Path(archive_base) / f"{date}_{account_id}_{content['category']}"
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for img in content.get("image_paths", []):
            if os.path.exists(img):
                shutil.copy2(img, archive_dir)
        if branded_paths:
            branded_dir = archive_dir / "branded"
            branded_dir.mkdir(exist_ok=True)
            for img in branded_paths:
                if os.path.exists(img):
                    shutil.copy2(img, branded_dir)
        if os.path.exists(video_path):
            shutil.copy2(video_path, archive_dir / "slideshow.mp4")
        meta = {k: v for k, v in content.items() if k != "image_paths"}
        (archive_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"归档失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="自动发布不同内容到所有TikTok账号")
    parser.add_argument("--accounts", nargs="+", help="指定账号ID")
    parser.add_argument("--stagger", type=float, default=30.0, help="账号间延迟秒数")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.accounts:
        from src.accounts import get_account
        accounts = [get_account(a) for a in args.accounts]
    else:
        accounts = get_active_accounts()

    logger.info(f"开始自动发布: {len(accounts)} 个账号")

    results = []
    for i, acc in enumerate(accounts):
        aid = acc["account_id"]
        pid = acc.get("adspower_profile_id", "")
        if not pid:
            logger.warning(f"跳过 {aid}: 无 adspower_profile_id")
            continue

        if i > 0:
            logger.info(f"等待 {args.stagger}s...")
            time.sleep(args.stagger)

        logger.info(f"[{i+1}/{len(accounts)}] {aid}")
        result = publish_one(aid, pid, dry_run=args.dry_run)
        results.append(result)
        status = "OK" if result.get("success") else "FAIL"
        logger.info(f"  {status}: {result.get('message', result.get('error', ''))}")

    # Summary
    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    logger.info(f"\n完成: {ok}/{len(results)} 成功, {fail} 失败")

    print(json.dumps({"total": len(results), "success": ok, "failed": fail, "results": results},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
