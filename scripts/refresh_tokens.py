#!/usr/bin/env python3
"""Batch refresh OAuth tokens and health check.

Usage:
    python scripts/refresh_tokens.py              # Refresh expiring tokens
    python scripts/refresh_tokens.py --check-only  # Just show status
    python scripts/refresh_tokens.py --force        # Force refresh all
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.oauth import refresh_all_tokens, check_health
from src.accounts import get_active_accounts
from src.utils import setup_logging

logger = setup_logging()


def main():
    parser = argparse.ArgumentParser(description="TikTok OAuth 令牌管理")
    parser.add_argument("--check-only", action="store_true", help="仅检查状态，不刷新")
    parser.add_argument("--force", action="store_true", help="强制刷新所有令牌")
    parser.add_argument("--hours", type=int, default=12, help="刷新即将在N小时内过期的令牌")
    args = parser.parse_args()

    accounts = get_active_accounts()
    print(f"活跃账号: {len(accounts)} 个\n")

    if args.check_only:
        for account in accounts:
            health = check_health(account["account_id"])
            status = "OK" if health.get("healthy") else "WARN"
            if health.get("needs_reauth"):
                status = "CRITICAL"
            days_left = health.get("refresh_token_days_left", "?")
            print(f"  [{status}] {account['account_id']}: "
                  f"access={'expired' if health.get('access_token_expired') else 'valid'}, "
                  f"refresh={days_left}天")
            if health.get("needs_reauth"):
                print(f"         !! refresh_token 将在 {days_left} 天后过期，请重新授权")
        return

    if args.force:
        print("强制刷新所有令牌...")
        result = refresh_all_tokens(hours_threshold=999999)
    else:
        print(f"刷新即将在 {args.hours} 小时内过期的令牌...")
        result = refresh_all_tokens(hours_threshold=args.hours)

    print(f"\n结果: 已刷新={result['refreshed']}, 失败={result['failed']}, 跳过={result['skipped']}")

    if result.get("alerts"):
        print("\n告警:")
        for alert in result["alerts"]:
            print(f"  !! {alert}")


if __name__ == "__main__":
    main()
