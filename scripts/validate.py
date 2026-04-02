#!/usr/bin/env python3
"""Smoke test: publish a single test image to one account (private mode).

Usage:
    python scripts/validate.py --account tiktok_store_01 --image test.jpg
    python scripts/validate.py --account tiktok_store_01 --image test.jpg --mode browser
    python scripts/validate.py --account tiktok_store_01 --image test.jpg --mode api
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publisher import publish
from src.utils import setup_logging

logger = setup_logging()


def main():
    parser = argparse.ArgumentParser(description="TikTok 发布冒烟测试")
    parser.add_argument("--account", required=True, help="账号 ID")
    parser.add_argument("--image", required=True, help="测试图片路径")
    parser.add_argument("--mode", choices=["api", "browser", "auto"], default="auto", help="发布模式")
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"[ERROR] 图片不存在: {args.image}")
        sys.exit(1)

    print(f"冒烟测试: 账号={args.account}, 图片={args.image}, 模式={args.mode}")
    print("注意: 将以 SELF_ONLY (仅自己可见) 模式发布\n")

    result = publish(
        args.account,
        "Smoke test - please ignore",
        "This is an automated test post.",
        [args.image],
        privacy_level="SELF_ONLY",
        dry_run=args.dry_run,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("success"):
        print("\n[OK] 冒烟测试通过")
    else:
        print(f"\n[FAIL] 冒烟测试失败: {result.get('error', '')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
