"""Cloudflare R2 image CDN service.

Uploads local images to R2 with public URLs for TikTok API.
- PNG auto-converts to JPEG
- SHA256 content hash for deduplication
- Cleanup of expired images
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

from .utils import convert_to_jpeg, content_hash, setup_logging

logger = setup_logging("tiktok-cdn")

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"


def _load_cdn_config() -> dict:
    cdn_file = CONFIG_DIR / "cdn.json"
    if not cdn_file.exists():
        raise FileNotFoundError(
            f"CDN 配置文件不存在: {cdn_file}\n"
            "请按照 .env.example 创建此文件"
        )
    return json.loads(cdn_file.read_text(encoding="utf-8"))


def _get_s3_client(config: dict):
    return boto3.client(
        "s3",
        endpoint_url=config["r2_endpoint_url"],
        aws_access_key_id=config["r2_access_key_id"],
        aws_secret_access_key=config["r2_secret_access_key"],
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 2},
        ),
        region_name="auto",
    )


def upload(
    local_paths: list[str],
    *,
    job_id: str = "",
    date: str = "",
) -> list[str]:
    """Upload local images to R2, converting PNG to JPEG if needed.

    Returns list of public URLs in same order as input paths.
    """
    config = _load_cdn_config()
    client = _get_s3_client(config)
    bucket = config["r2_bucket_name"]
    base_url = config["r2_public_url_base"].rstrip("/")
    prefix = config.get("upload_prefix", "tiktok/carousel/")

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    urls = []
    for path in local_paths:
        image_bytes, original_format = convert_to_jpeg(path)
        file_hash = content_hash(image_bytes)

        ext = "jpg" if original_format != "WEBP" else "webp"
        key = f"{prefix}{date}/{file_hash}.{ext}"

        content_type = "image/jpeg" if ext == "jpg" else "image/webp"

        logger.info(f"上传: {Path(path).name} -> {key} ({len(image_bytes)} bytes, 原格式: {original_format})")

        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=image_bytes,
            ContentType=content_type,
        )

        public_url = f"{base_url}/{key}"
        urls.append(public_url)

    logger.info(f"上传完成: {len(urls)} 张图片")
    return urls


def cleanup(*, days: int = 7) -> int:
    """Remove images older than TTL from bucket.

    Returns number of objects deleted.
    """
    config = _load_cdn_config()
    client = _get_s3_client(config)
    bucket = config["r2_bucket_name"]
    prefix = config.get("upload_prefix", "tiktok/carousel/")

    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    deleted = 0

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            last_modified = obj["LastModified"].timestamp()
            if last_modified < cutoff:
                client.delete_object(Bucket=bucket, Key=obj["Key"])
                deleted += 1

    logger.info(f"清理完成: 删除 {deleted} 个过期对象 (>{days}天)")
    return deleted
