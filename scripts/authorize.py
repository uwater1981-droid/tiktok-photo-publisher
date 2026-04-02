#!/usr/bin/env python3
"""Interactive OAuth authorization for TikTok accounts.

Usage:
    python scripts/authorize.py --account tiktok_store_01
    python scripts/authorize.py --all-active
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.oauth import authorize, check_health
from src.accounts import get_active_accounts, get_account
from src.utils import setup_logging

logger = setup_logging()


def main():
    parser = argparse.ArgumentParser(description="TikTok OAuth 授权")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--account", help="指定账号 ID")
    target.add_argument("--all-active", action="store_true", help="逐个授权所有活跃账号")
    args = parser.parse_args()

    if args.account:
        accounts = [get_account(args.account)]
    else:
        accounts = get_active_accounts()

    for account in accounts:
        account_id = account["account_id"]
        health = check_health(account_id)

        if health.get("healthy") and not health.get("needs_reauth"):
            print(f"[SKIP] {account_id}: Token 健康，无需重新授权")
            continue

        print(f"\n[AUTH] 正在授权: {account_id} ({account.get('display_name', '')})")
        print("       请在浏览器中完成 TikTok 登录和授权...")

        try:
            token_data = authorize(account_id)
            print(f"[OK]   {account_id}: 授权成功 (open_id={token_data.get('open_id', '')[:10]}...)")
        except Exception as e:
            print(f"[FAIL] {account_id}: {e}")

        if len(accounts) > 1:
            input("按 Enter 继续下一个账号...")


if __name__ == "__main__":
    main()
