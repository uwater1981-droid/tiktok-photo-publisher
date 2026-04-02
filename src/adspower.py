"""AdsPower Local API client.

Manages browser profiles via AdsPower's Local API:
- Start/stop browser profiles
- Get debug port for DrissionPage connection
- Query profile status
"""

import time

import requests

from .utils import setup_logging

logger = setup_logging("adspower")

# AdsPower Local API defaults
ADSPOWER_BASE = "http://local.adspower.net:50325"

# API rate limit: 1 request/second
_last_request_time = 0.0


def _rate_limit():
    """Enforce 1 req/s rate limit for AdsPower API."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_request_time = time.time()


def _api_get(path: str, params: dict | None = None, base_url: str = ADSPOWER_BASE) -> dict:
    """Make GET request to AdsPower Local API."""
    _rate_limit()
    url = f"{base_url}{path}"
    # Bypass system proxy — AdsPower runs locally
    resp = requests.get(url, params=params or {}, timeout=30, proxies={"http": None, "https": None})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"AdsPower API 错误: {data.get('msg', 'unknown')} (code={data.get('code')})")
    return data


def start_browser(
    profile_id: str,
    *,
    headless: bool = False,
    base_url: str = ADSPOWER_BASE,
) -> dict:
    """Start an AdsPower browser profile.

    Args:
        profile_id: AdsPower profile/user ID
        headless: Run without GUI
        base_url: AdsPower API address

    Returns:
        dict with keys:
        - debug_port: str (e.g., "12345")
        - selenium_address: str (e.g., "127.0.0.1:12345")
        - puppeteer_ws: str (WebSocket URL)
        - webdriver_path: str
    """
    params = {
        "user_id": profile_id,
        "headless": 1 if headless else 0,
        "ip_tab": 0,  # Don't open IP detection tab
        "cdp_mask": 1,  # Mask CDP detection
    }

    logger.info(f"启动 AdsPower 浏览器: profile={profile_id}, headless={headless}")
    data = _api_get("/api/v1/browser/start", params, base_url=base_url)

    ws_data = data.get("data", {}).get("ws", {})
    return {
        "debug_port": data["data"].get("debug_port", ""),
        "selenium_address": ws_data.get("selenium", ""),
        "puppeteer_ws": ws_data.get("puppeteer", ""),
        "webdriver_path": data["data"].get("webdriver", ""),
    }


def stop_browser(
    profile_id: str,
    *,
    base_url: str = ADSPOWER_BASE,
):
    """Stop an AdsPower browser profile."""
    logger.info(f"关闭 AdsPower 浏览器: profile={profile_id}")
    _api_get("/api/v1/browser/stop", {"user_id": profile_id}, base_url=base_url)


def check_browser_status(
    profile_id: str,
    *,
    base_url: str = ADSPOWER_BASE,
) -> dict:
    """Check if a browser profile is running."""
    _rate_limit()
    url = f"{base_url}/api/v1/browser/active"
    resp = requests.get(url, params={"user_id": profile_id}, timeout=10)
    data = resp.json()
    return {
        "profile_id": profile_id,
        "active": data.get("data", {}).get("status") == "Active",
    }


def list_profiles(
    *,
    page: int = 1,
    page_size: int = 100,
    base_url: str = ADSPOWER_BASE,
) -> list[dict]:
    """List all AdsPower profiles."""
    data = _api_get(
        "/api/v1/user/list",
        {"page": page, "page_size": page_size},
        base_url=base_url,
    )
    return data.get("data", {}).get("list", [])
