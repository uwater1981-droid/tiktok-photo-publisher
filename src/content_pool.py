"""Content pool for generating varied TikTok posts.

Manages a pool of product categories, captions, hashtags, and images.
Each publish call gets a unique combination to avoid duplicate content
across accounts and time slots.

Uses Firecrawl to fetch real product images from IKEA SA, Amazon, etc.
Falls back to generated placeholder images when sources unavailable.
"""

import hashlib
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from .utils import setup_logging

logger = setup_logging("content-pool")

ROOT_DIR = Path(__file__).resolve().parents[1]
POOL_DIR = ROOT_DIR / "content" / "pool"
POOL_INDEX = POOL_DIR / "index.json"

FIRECRAWL_KEY = os.environ.get("FIRECRAWL_API_KEY", "fc-e95d5889ee0f408da1da5420c637905a")

# Gulf market product categories (kitchen/home/bathroom)
PRODUCT_CATEGORIES = [
    {
        "category": "kitchen_storage",
        "name_ar": "تنظيم المطبخ",
        "name_en": "Kitchen Storage",
        "ikea_url": "https://www.ikea.com/sa/en/cat/kitchen-storage-organisation-24254/",
        "hashtags_ar": ["#مطبخ", "#تنظيم", "#تخزين", "#ادوات_مطبخ"],
        "hashtags_en": ["#kitchen", "#organization", "#storage", "#kitchenware"],
    },
    {
        "category": "bathroom",
        "name_ar": "إكسسوارات الحمام",
        "name_en": "Bathroom Accessories",
        "ikea_url": "https://www.ikea.com/sa/en/cat/bathroom-accessories-20523/",
        "hashtags_ar": ["#حمام", "#اكسسوارات", "#تنظيم_الحمام"],
        "hashtags_en": ["#bathroom", "#accessories", "#bathroomorganization"],
    },
    {
        "category": "home_decoration",
        "name_ar": "ديكور المنزل",
        "name_en": "Home Decoration",
        "ikea_url": "https://www.ikea.com/sa/en/cat/home-decoration-10760/",
        "hashtags_ar": ["#ديكور", "#منزل", "#تصميم_داخلي"],
        "hashtags_en": ["#homedecor", "#interior", "#homedesign"],
    },
    {
        "category": "laundry",
        "name_ar": "تنظيم الغسيل",
        "name_en": "Laundry & Cleaning",
        "ikea_url": "https://www.ikea.com/sa/en/cat/laundry-cleaning-wa002/",
        "hashtags_ar": ["#غسيل", "#تنظيف", "#تنظيم"],
        "hashtags_en": ["#laundry", "#cleaning", "#homecare"],
    },
    {
        "category": "lighting",
        "name_ar": "إضاءة",
        "name_en": "Lighting",
        "ikea_url": "https://www.ikea.com/sa/en/cat/lighting-li001/",
        "hashtags_ar": ["#اضاءة", "#ديكور", "#منزل"],
        "hashtags_en": ["#lighting", "#homelighting", "#interiordesign"],
    },
]

CAPTION_TEMPLATES_AR = [
    "{product_ar} ✨\n\n{feature_ar}\nجودة عالية وتصميم عصري\n\nتابعونا للمزيد! ❤️",
    "اكتشفوا {product_ar} 🏠\n\n{feature_ar}\nعملي وأنيق لمنزلك\n\nشاركونا رأيكم! 💬",
    "{product_ar} 🌟\n\n{feature_ar}\nالأناقة تبدأ من التفاصيل\n\nاحفظوا هذا المنشور! 📌",
    "جديد! {product_ar} 🎉\n\n{feature_ar}\nمثالي لكل منزل عصري\n\nتابعونا! ❤️",
]

CAPTION_TEMPLATES_EN = [
    "{product_en}\n\n{feature_en}\nHigh quality, modern design\n\nFollow for more!",
    "Discover {product_en}\n\n{feature_en}\nPractical & elegant for your home",
    "{product_en}\n\n{feature_en}\nElegance starts with the details",
    "New! {product_en}\n\n{feature_en}\nPerfect for every modern home",
]

FEATURES_AR = [
    "تصميم أنيق يناسب كل الأذواق",
    "مساحة تخزين واسعة وعملية",
    "سهل التركيب والاستخدام",
    "متوفر بألوان متعددة",
    "مادة عالية الجودة ومتينة",
    "توفير المساحة بشكل ذكي",
]

FEATURES_EN = [
    "Elegant design for every taste",
    "Spacious and practical storage",
    "Easy to install and use",
    "Available in multiple colors",
    "High quality, durable material",
    "Smart space-saving solution",
]


def _fetch_product_images(category: dict, count: int = 4) -> list[str]:
    """Fetch product images from IKEA SA via Firecrawl."""
    import re
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {FIRECRAWL_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "url": category["ikea_url"],
                "formats": ["markdown"],
                "onlyMainContent": True,
            },
            timeout=30,
        )
        data = resp.json()
        if not data.get("success"):
            return []

        md = data["data"].get("markdown", "")
        imgs = re.findall(r'https://www\.ikea\.com/[^)\s"]+\.(jpg|webp)[^)\s"]*', md)
        # Get unique product images with ?f=xl for high res
        seen = set()
        result = []
        for img_match in imgs:
            url = img_match if isinstance(img_match, str) else img_match[0]
            # Reconstruct full URL from regex
            pass

        # Simpler: extract full URLs
        all_urls = re.findall(r'https://www\.ikea\.com/sa/en/images/products/[^)\s"]+\.jpg[^)\s"]*', md)
        for url in all_urls:
            base = url.split("?")[0]
            if base not in seen:
                seen.add(base)
                result.append(base + "?f=xl")
                if len(result) >= count * 3:
                    break

        # Pick random subset
        if len(result) > count:
            result = random.sample(result, count)

        return result[:count]

    except Exception as e:
        logger.warning(f"Firecrawl 抓取失败: {e}")
        return []


def _download_images(urls: list[str], output_dir: Path) -> list[str]:
    """Download images to local files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, url in enumerate(urls):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            path = str(output_dir / f"slide_{i+1}.jpg")
            with open(path, "wb") as f:
                f.write(resp.content)
            paths.append(path)
        except Exception as e:
            logger.warning(f"下载失败 {url[:60]}: {e}")
    return paths


def _generate_placeholder_images(category: dict, count: int = 4) -> list[str]:
    """Generate placeholder product images when real ones unavailable."""
    output_dir = POOL_DIR / category["category"] / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)

    colors = [
        (245, 248, 255), (255, 252, 245), (248, 255, 248), (255, 245, 248),
        (245, 245, 255), (255, 250, 240), (240, 255, 245), (252, 245, 255),
    ]
    accents = [
        (70, 100, 140), (183, 110, 75), (75, 130, 90), (160, 70, 90),
        (90, 90, 160), (140, 100, 60), (60, 130, 100), (130, 70, 130),
    ]

    paths = []
    for i in range(count):
        bg = random.choice(colors)
        accent = random.choice(accents)

        img = Image.new("RGB", (1080, 1080), color=bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 1080, 8], fill=accent)
        draw.rectangle([0, 1072, 1080, 1080], fill=accent)
        draw.rectangle([80, 300, 1000, 780], outline=accent, width=2)
        draw.text((540, 420), category["name_ar"], fill=accent, anchor="mt")
        draw.text((540, 520), category["name_en"], fill=(100, 100, 100), anchor="mt")
        draw.line([300, 580, 780, 580], fill=accent, width=1)
        draw.text((540, 620), "Raqia Boutique", fill=accent, anchor="mt")
        draw.text((540, 680), "رقية بوتيك", fill=(130, 130, 130), anchor="mt")

        path = str(output_dir / f"slide_{i+1}.jpg")
        img.save(path, "JPEG", quality=95)
        paths.append(path)

    return paths


def generate_content(
    account_id: str,
    *,
    category: str | None = None,
    use_firecrawl: bool = True,
) -> dict:
    """Generate a unique content package for publishing.

    Returns:
        dict with: title, description, image_paths, product_id, category, meta
    """
    # Pick category (random if not specified)
    if category:
        cat = next((c for c in PRODUCT_CATEGORIES if c["category"] == category), None)
        if not cat:
            raise ValueError(f"Unknown category: {category}")
    else:
        cat = random.choice(PRODUCT_CATEGORIES)

    # Generate unique product ID
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    product_id = f"{cat['category']}-{account_id}-{ts}"

    # Fetch or generate images
    image_paths = []
    if use_firecrawl:
        urls = _fetch_product_images(cat, count=4)
        if urls:
            output_dir = POOL_DIR / product_id
            image_paths = _download_images(urls, output_dir)

    if len(image_paths) < 3:
        logger.info(f"使用生成图片 (Firecrawl 结果不足: {len(image_paths)})")
        image_paths = _generate_placeholder_images(cat, count=4)

    # Randomize image order (anti-duplicate)
    random.shuffle(image_paths)

    # Pick caption template (different each time via random)
    feature_ar = random.choice(FEATURES_AR)
    feature_en = random.choice(FEATURES_EN)
    tmpl_ar = random.choice(CAPTION_TEMPLATES_AR)
    tmpl_en = random.choice(CAPTION_TEMPLATES_EN)

    caption_ar = tmpl_ar.format(
        product_ar=cat["name_ar"],
        feature_ar=feature_ar,
    )
    caption_en = tmpl_en.format(
        product_en=cat["name_en"],
        feature_en=feature_en,
    )

    # Random subset of hashtags
    tags_ar = random.sample(cat["hashtags_ar"], min(3, len(cat["hashtags_ar"])))
    tags_en = random.sample(cat["hashtags_en"], min(3, len(cat["hashtags_en"])))
    brand_tags = ["#رقية_بوتيك", "#raqiaboutique"]

    hashtags = " ".join(tags_ar + tags_en + brand_tags)
    full_caption = f"{caption_ar}\n\n{hashtags}\n\n---\n\n{caption_en}"

    title = f"{cat['name_en']} - {cat['name_ar']}"
    description = full_caption

    return {
        "title": title,
        "description": description,
        "image_paths": image_paths,
        "product_id": product_id,
        "category": cat["category"],
        "caption_ar": caption_ar,
        "caption_en": caption_en,
        "hashtags": hashtags,
    }


def get_publish_history(account_id: str) -> list[str]:
    """Get recent product IDs published by an account (from Notion or local log)."""
    log_file = ROOT_DIR / "publish_log.jsonl"
    if not log_file.exists():
        return []
    history = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            if entry.get("account_id") == account_id:
                history.append(entry.get("product_id", ""))
        except json.JSONDecodeError:
            continue
    return history[-20:]  # Last 20


def log_publish_local(account_id: str, product_id: str, category: str, success: bool):
    """Append to local publish log for deduplication."""
    log_file = ROOT_DIR / "publish_log.jsonl"
    entry = {
        "account_id": account_id,
        "product_id": product_id,
        "category": category,
        "success": success,
        "timestamp": datetime.now().isoformat(),
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
