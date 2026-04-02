"""Account management for TikTok publisher."""

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"

VALID_STATUSES = {"active", "paused", "needs_reauth"}
VALID_AUTH_MODES = {"api", "drissionpage", "auto"}


def load_accounts() -> list[dict]:
    if not ACCOUNTS_FILE.exists():
        raise FileNotFoundError(f"账号配置文件不存在: {ACCOUNTS_FILE}")
    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    return data.get("accounts", [])


def get_account(account_id: str) -> dict:
    for account in load_accounts():
        if account["account_id"] == account_id:
            return account
    raise ValueError(f"账号不存在: {account_id}")


def get_active_accounts() -> list[dict]:
    return [a for a in load_accounts() if a.get("status") == "active"]


def get_accounts_by_tag(tag: str) -> list[dict]:
    return [
        a for a in get_active_accounts()
        if tag in a.get("tags", [])
    ]


def validate_account(account: dict) -> list[str]:
    errors = []
    if not account.get("account_id"):
        errors.append("缺少 account_id")
    if account.get("status") not in VALID_STATUSES:
        errors.append(f"无效 status: {account.get('status')}, 可选: {VALID_STATUSES}")
    if account.get("auth_mode") not in VALID_AUTH_MODES:
        errors.append(f"无效 auth_mode: {account.get('auth_mode')}, 可选: {VALID_AUTH_MODES}")
    return errors


def update_account_status(account_id: str, status: str):
    if status not in VALID_STATUSES:
        raise ValueError(f"无效 status: {status}")
    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    for account in data.get("accounts", []):
        if account["account_id"] == account_id:
            account["status"] = status
            ACCOUNTS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return
    raise ValueError(f"账号不存在: {account_id}")
