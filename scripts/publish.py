#!/usr/bin/env python3
"""CLI entry point for TikTok photo carousel publishing.

Usage:
    # Single account
    python scripts/publish.py --account tiktok_store_01 \
        --title "Spring Collection" \
        --description "Check out our latest..." \
        --images photos/1.jpg photos/2.jpg

    # All active accounts
    python scripts/publish.py --all-active \
        --title "Spring Collection" \
        --images photos/*.jpg

    # By tag
    python scripts/publish.py --tag resort \
        --title "Spring Collection" \
        --images photos/*.jpg

    # Dry run
    python scripts/publish.py --all-active --dry-run \
        --title "Test" --images test.jpg
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publisher import publish
from src.batch import batch_publish
from src.utils import setup_logging

logger = setup_logging()


def main():
    parser = argparse.ArgumentParser(description="TikTok 图文发布工具")

    # Target selection (mutually exclusive)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--account", help="指定单个账号 ID")
    target.add_argument("--accounts", nargs="+", help="指定多个账号 ID")
    target.add_argument("--tag", help="按标签发布到所有匹配的活跃账号")
    target.add_argument("--all-active", action="store_true", help="发布到所有活跃账号")

    # Content
    parser.add_argument("--title", required=True, help="帖子标题")
    parser.add_argument("--description", default="", help="帖子描述")
    parser.add_argument("--images", nargs="+", required=True, help="图片文件路径")

    # Options
    parser.add_argument("--privacy", default="PUBLIC_TO_EVERYONE",
                        choices=["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
                        help="隐私设置")
    parser.add_argument("--no-comments", action="store_true", help="禁止评论")
    parser.add_argument("--headless", action="store_true", help="浏览器无头模式")
    parser.add_argument("--max-concurrent", type=int, default=4, help="最大并发数")
    parser.add_argument("--stagger", type=float, default=5.0, help="账号间延迟秒数")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不实际发布）")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    args = parser.parse_args()

    # Single account
    if args.account:
        result = publish(
            args.account,
            args.title,
            args.description,
            args.images,
            privacy_level=args.privacy,
            disable_comment=args.no_comments,
            headless=args.headless,
            dry_run=args.dry_run,
        )
    else:
        # Batch
        account_ids = args.accounts if args.accounts else None
        result = batch_publish(
            args.title,
            args.description,
            args.images,
            account_ids=account_ids,
            tag=args.tag,
            all_active=args.all_active,
            max_concurrent=args.max_concurrent,
            stagger_seconds=args.stagger,
            privacy_level=args.privacy,
            headless=args.headless,
            dry_run=args.dry_run,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result.get("success"):
            print(f"\n[OK] {result.get('message', '发布成功')}")
        else:
            print(f"\n[FAIL] {result.get('error', result.get('message', '发布失败'))}")

        # Batch details
        if "results" in result:
            print(f"\n总计: {result.get('total', 0)} | "
                  f"成功: {result.get('succeeded', 0)} | "
                  f"失败: {result.get('failed', 0)}")
            for r in result.get("results", []):
                status = "OK" if r.get("success") else "FAIL"
                print(f"  {r.get('account_id', '?')}: [{status}] {r.get('mode', '?')} - {r.get('message', r.get('error', ''))}")

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
