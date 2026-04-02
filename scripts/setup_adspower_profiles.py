#!/usr/bin/env python3
"""Batch create AdsPower browser profiles for TikTok accounts.

Creates one browser profile per TikTok account with:
- Unique fingerprint
- NodeMaven proxy (if configured)
- TikTok-optimized browser settings

Usage:
    python scripts/setup_adspower_profiles.py --count 8
    python scripts/setup_adspower_profiles.py --count 8 --proxy-host xxx --proxy-port xxx
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils import setup_logging

logger = setup_logging()

ADSPOWER_BASE = "http://local.adspower.net:50325"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def create_profile(
    name: str,
    *,
    group_name: str = "TikTok",
    proxy_config: dict | None = None,
) -> dict:
    """Create a single AdsPower browser profile."""
    time.sleep(1)  # Rate limit: 1 req/s

    body = {
        "name": name,
        "group_name": group_name,
        "domain_name": "www.tiktok.com",
        "open_urls": ["https://www.tiktok.com"],
        "repeat_config": [0],  # No repeat fingerprint
        "fingerprint_config": {
            "automatic_timezone": 1,
            "language": ["en-US", "en"],
            "ua": "random",  # Random User-Agent
        },
    }

    if proxy_config:
        body["user_proxy_config"] = proxy_config

    resp = requests.post(
        f"{ADSPOWER_BASE}/api/v1/user/create",
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"创建 profile 失败: {data.get('msg')}")

    profile_id = data["data"]["id"]
    logger.info(f"已创建: {name} -> profile_id={profile_id}")
    return {"name": name, "profile_id": profile_id}


def build_proxy_config(args) -> dict | None:
    """Build AdsPower proxy config from CLI args."""
    if not args.proxy_host:
        return None

    config = {
        "proxy_soft": "other",
        "proxy_type": args.proxy_type,
        "proxy_host": args.proxy_host,
        "proxy_port": str(args.proxy_port),
    }
    if args.proxy_user:
        config["proxy_user"] = args.proxy_user
    if args.proxy_password:
        config["proxy_password"] = args.proxy_password

    return config


def generate_accounts_json(profiles: list[dict], output_path: Path):
    """Generate accounts.json from created profiles."""
    accounts = []
    for i, p in enumerate(profiles, 1):
        accounts.append({
            "account_id": f"tiktok_store_{i:02d}",
            "display_name": p["name"],
            "status": "active",
            "auth_mode": "browser",
            "adspower_profile_id": p["profile_id"],
            "default_publish_times": ["11:00", "19:00"],
            "tags": ["store"],
            "defaults": {
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_comment": False,
            },
        })

    data = {"accounts": accounts}
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"accounts.json 已生成: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="批量创建 AdsPower TikTok 浏览器 profile")
    parser.add_argument("--count", type=int, default=8, help="创建数量")
    parser.add_argument("--prefix", default="TikTok Store", help="Profile 名称前缀")
    parser.add_argument("--group", default="TikTok", help="AdsPower 分组名")

    # NodeMaven proxy settings
    parser.add_argument("--proxy-type", default="socks5", choices=["http", "https", "socks5"],
                        help="代理类型")
    parser.add_argument("--proxy-host", help="NodeMaven 代理地址")
    parser.add_argument("--proxy-port", type=int, help="代理端口")
    parser.add_argument("--proxy-user", help="代理用户名")
    parser.add_argument("--proxy-password", help="代理密码")

    args = parser.parse_args()

    # Test connection
    print("检查 AdsPower 连接...")
    try:
        resp = requests.get(f"{ADSPOWER_BASE}/api/v1/user/list?page=1&page_size=1", timeout=5)
        if resp.status_code != 200 or resp.json().get("code") != 0:
            print(f"[ERROR] AdsPower API 不可用: {resp.text[:200]}")
            sys.exit(1)
        print("[OK] AdsPower 已连接\n")
    except Exception as e:
        print(f"[ERROR] 无法连接 AdsPower: {e}")
        print("请确保 AdsPower 已启动并登录")
        sys.exit(1)

    proxy_config = build_proxy_config(args)
    if proxy_config:
        print(f"代理: {proxy_config['proxy_type']}://{proxy_config['proxy_host']}:{proxy_config['proxy_port']}")
    else:
        print("代理: 无 (建议配置 NodeMaven)")

    print(f"即将创建 {args.count} 个 profile (前缀: {args.prefix})\n")

    profiles = []
    for i in range(1, args.count + 1):
        name = f"{args.prefix} {i:02d}"
        try:
            p = create_profile(name, group_name=args.group, proxy_config=proxy_config)
            profiles.append(p)
        except Exception as e:
            print(f"[FAIL] {name}: {e}")

    if profiles:
        accounts_file = CONFIG_DIR / "accounts.json"
        generate_accounts_json(profiles, accounts_file)
        print(f"\n[OK] 创建完成: {len(profiles)}/{args.count} 个 profile")
        print(f"     accounts.json: {accounts_file}")
        print(f"\n下一步: 在 AdsPower 中逐个打开 profile，手动登录 TikTok")
    else:
        print("\n[FAIL] 未创建任何 profile")
        sys.exit(1)


if __name__ == "__main__":
    main()
