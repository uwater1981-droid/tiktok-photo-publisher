"""Shared utilities for TikTok publisher."""

import hashlib
import io
import logging
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
ROOT_DIR = Path(__file__).resolve().parents[1]
HANDOFF_DIR = ROOT_DIR / "handoff"
SCREENSHOTS_DIR = ROOT_DIR / "screenshots"


def setup_logging(name: str = "tiktok-publisher", level: int = logging.INFO) -> logging.Logger:
    logging.basicConfig(format=LOG_FORMAT, level=level)
    return logging.getLogger(name)


def convert_to_jpeg(image_path: str) -> tuple[bytes, str]:
    """Convert image to JPEG bytes. Returns (jpeg_bytes, original_format).

    TikTok only accepts JPEG and WebP. PNG must be converted.
    """
    img = Image.open(image_path)
    original_format = img.format or "UNKNOWN"

    if original_format in ("JPEG", "WEBP"):
        return Path(image_path).read_bytes(), original_format

    # Convert PNG/other to JPEG
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue(), original_format


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def validate_images(image_paths: list[str], max_count: int = 35) -> list[str]:
    """Validate image paths. Returns list of error messages (empty = valid)."""
    errors = []
    if not image_paths:
        errors.append("至少需要 1 张图片")
    if len(image_paths) > max_count:
        errors.append(f"最多 {max_count} 张图片，当前 {len(image_paths)} 张")
    for path in image_paths:
        if not Path(path).exists():
            errors.append(f"图片不存在: {path}")
    return errors


def build_handoff(
    account_id: str,
    title: str,
    description: str,
    image_paths: list[str],
    error: str,
    screenshot_path: str | None = None,
    video_path: str | None = None,
) -> Path:
    """Generate a manual handoff package when automation fails."""
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    handoff_file = HANDOFF_DIR / f"tiktok-{account_id}-{timestamp}.json"
    handoff_data = {
        "account_id": account_id,
        "title": title,
        "description": description,
        "image_paths": image_paths,
        "video_path": video_path,
        "error": error,
        "screenshot": screenshot_path,
        "created_at": datetime.now().isoformat(),
        "instructions": [
            "1. 打开 tiktok.com/upload 并登录该账号",
            f"2. 上传视频: {video_path or '需先用 video_maker 生成'}",
            f"3. 填写标题: {title}",
            f"4. 填写描述: {description}",
            "5. 点击发布",
        ],
    }
    handoff_file.write_text(
        json.dumps(handoff_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return handoff_file


def take_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")
