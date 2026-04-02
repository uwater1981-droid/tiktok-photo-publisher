"""TikTok OAuth 2.0 + PKCE token management.

Handles:
- Interactive OAuth authorization (local callback server)
- Automatic token refresh
- Per-account token storage in tokens/{account_id}.json
"""

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import portalocker
import requests

from .utils import setup_logging

logger = setup_logging("tiktok-oauth")

ROOT_DIR = Path(__file__).resolve().parents[1]
TOKENS_DIR = ROOT_DIR / "tokens"
CONFIG_DIR = ROOT_DIR / "config"

API_BASE = "https://open.tiktokapis.com"
AUTH_BASE = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = f"{API_BASE}/v2/oauth/token/"
REDIRECT_URI = "http://localhost:8921/callback"
SCOPES = "video.publish,user.info.basic"

# Refresh if access token expires within this many seconds
REFRESH_THRESHOLD_SECONDS = 3600  # 1 hour


class OAuthUnavailable(Exception):
    """Raised when no valid OAuth token exists and can't be refreshed."""
    pass


def _load_app_config() -> dict:
    app_file = CONFIG_DIR / "app.json"
    if not app_file.exists():
        raise FileNotFoundError(
            f"TikTok app 配置文件不存在: {app_file}\n"
            "请按照 .env.example 创建此文件"
        )
    return json.loads(app_file.read_text(encoding="utf-8"))


def _token_file(account_id: str) -> Path:
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    return TOKENS_DIR / f"{account_id}.json"


def _load_token(account_id: str) -> dict | None:
    path = _token_file(account_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_token(account_id: str, token_data: dict):
    path = _token_file(account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        portalocker.lock(f, portalocker.LOCK_EX)
        json.dump(token_data, f, ensure_ascii=False, indent=2)
        portalocker.unlock(f)


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge."""
    verifier = secrets.token_urlsafe(64)
    challenge_bytes = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _is_expired(token_data: dict, threshold_seconds: int = 0) -> bool:
    expires_at = token_data.get("access_token_expires_at", "")
    if not expires_at:
        return True
    expiry = datetime.fromisoformat(expires_at)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (expiry - now).total_seconds() < threshold_seconds


def authorize(account_id: str) -> dict:
    """Interactive OAuth flow. Opens browser, waits for callback.

    Returns the saved token dict.
    """
    app = _load_app_config()
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    params = {
        "client_key": app["client_key"],
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTH_BASE}?{urlencode(params)}"

    # Capture the authorization code via local server
    received = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            received["code"] = qs.get("code", [None])[0]
            received["state"] = qs.get("state", [None])[0]
            received["error"] = qs.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization complete. You can close this tab.</h1>")

        def log_message(self, format, *args):
            pass  # Suppress HTTP logs

    server = HTTPServer(("localhost", 8921), CallbackHandler)
    logger.info(f"正在打开浏览器进行 OAuth 授权: {account_id}")
    webbrowser.open(auth_url)

    logger.info("等待回调... (在浏览器中完成授权)")
    server.handle_request()
    server.server_close()

    if received.get("error"):
        raise OAuthUnavailable(f"OAuth 授权失败: {received['error']}")
    if received.get("state") != state:
        raise OAuthUnavailable("OAuth state 不匹配，可能存在 CSRF 攻击")

    code = received.get("code")
    if not code:
        raise OAuthUnavailable("未收到授权码")

    # Exchange code for tokens
    resp = requests.post(TOKEN_URL, data={
        "client_key": app["client_key"],
        "client_secret": app["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    })
    resp.raise_for_status()
    data = resp.json()

    if "error" in data and data.get("error", {}).get("code") != "ok":
        raise OAuthUnavailable(f"Token 交换失败: {data}")

    now = datetime.now(timezone.utc)
    token_data = {
        "open_id": data.get("open_id", ""),
        "access_token": data["access_token"],
        "access_token_expires_at": (
            datetime.fromtimestamp(
                now.timestamp() + data.get("expires_in", 86400),
                tz=timezone.utc,
            ).isoformat()
        ),
        "refresh_token": data["refresh_token"],
        "refresh_token_expires_at": (
            datetime.fromtimestamp(
                now.timestamp() + data.get("refresh_expires_in", 365 * 86400),
                tz=timezone.utc,
            ).isoformat()
        ),
        "scope": data.get("scope", SCOPES),
        "last_refreshed_at": now.isoformat(),
    }
    _save_token(account_id, token_data)
    logger.info(f"OAuth 授权成功: {account_id}")
    return token_data


def refresh_if_needed(account_id: str, *, force: bool = False) -> dict:
    """Refresh access token if expired or near expiry.

    Returns updated token dict.
    Raises OAuthUnavailable if refresh fails.
    """
    token_data = _load_token(account_id)
    if not token_data:
        raise OAuthUnavailable(f"账号 {account_id} 无 OAuth 令牌，请先运行授权")

    if not force and not _is_expired(token_data, REFRESH_THRESHOLD_SECONDS):
        return token_data

    app = _load_app_config()
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise OAuthUnavailable(f"账号 {account_id} 无 refresh_token")

    resp = requests.post(TOKEN_URL, data={
        "client_key": app["client_key"],
        "client_secret": app["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })

    if resp.status_code != 200:
        raise OAuthUnavailable(f"Token 刷新失败 (HTTP {resp.status_code}): {resp.text}")

    data = resp.json()
    if "error" in data and data.get("error", {}).get("code") != "ok":
        raise OAuthUnavailable(f"Token 刷新失败: {data}")

    now = datetime.now(timezone.utc)
    token_data.update({
        "access_token": data["access_token"],
        "access_token_expires_at": (
            datetime.fromtimestamp(
                now.timestamp() + data.get("expires_in", 86400),
                tz=timezone.utc,
            ).isoformat()
        ),
        "refresh_token": data.get("refresh_token", refresh_token),
        "last_refreshed_at": now.isoformat(),
    })

    if "refresh_expires_in" in data:
        token_data["refresh_token_expires_at"] = (
            datetime.fromtimestamp(
                now.timestamp() + data["refresh_expires_in"],
                tz=timezone.utc,
            ).isoformat()
        )

    _save_token(account_id, token_data)
    logger.info(f"Token 已刷新: {account_id}")
    return token_data


def get_access_token(account_id: str) -> tuple[str, str]:
    """Get valid access token for account.

    Returns (access_token, open_id).
    Auto-refreshes if needed.
    """
    token_data = refresh_if_needed(account_id)
    return token_data["access_token"], token_data.get("open_id", "")


def check_health(account_id: str) -> dict:
    """Check token health for an account."""
    token_data = _load_token(account_id)
    if not token_data:
        return {"account_id": account_id, "status": "no_token", "healthy": False}

    access_expired = _is_expired(token_data, 0)
    access_near_expiry = _is_expired(token_data, REFRESH_THRESHOLD_SECONDS)

    refresh_expires_at = token_data.get("refresh_token_expires_at", "")
    refresh_days_left = None
    if refresh_expires_at:
        expiry = datetime.fromisoformat(refresh_expires_at)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        refresh_days_left = (expiry - datetime.now(timezone.utc)).days

    return {
        "account_id": account_id,
        "status": "healthy" if not access_expired else "expired",
        "healthy": not access_expired or not access_near_expiry,
        "access_token_expired": access_expired,
        "access_token_near_expiry": access_near_expiry,
        "refresh_token_days_left": refresh_days_left,
        "needs_reauth": refresh_days_left is not None and refresh_days_left < 30,
        "last_refreshed_at": token_data.get("last_refreshed_at"),
    }


def refresh_all_tokens(*, hours_threshold: int = 12) -> dict:
    """Batch refresh all tokens expiring within threshold.

    Returns summary dict.
    """
    from .accounts import get_active_accounts

    threshold_seconds = hours_threshold * 3600
    results = {"refreshed": 0, "failed": 0, "skipped": 0, "alerts": []}

    for account in get_active_accounts():
        account_id = account["account_id"]
        token_data = _load_token(account_id)
        if not token_data:
            results["skipped"] += 1
            continue

        try:
            if _is_expired(token_data, threshold_seconds):
                refresh_if_needed(account_id, force=True)
                results["refreshed"] += 1
            else:
                results["skipped"] += 1
        except OAuthUnavailable as e:
            results["failed"] += 1
            results["alerts"].append(f"{account_id}: {e}")
            logger.error(f"刷新失败: {account_id} - {e}")

        health = check_health(account_id)
        if health.get("needs_reauth"):
            msg = f"账号 {account_id} refresh_token 将在 {health['refresh_token_days_left']} 天后过期，请重新授权"
            results["alerts"].append(msg)
            logger.warning(msg)

    return results
