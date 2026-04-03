"""Branded image template generator for TikTok.

Creates 1080x1920 vertical images with:
- Product photo as background (blurred fill + sharp center)
- Brand bar top (logo + category)
- Info bar bottom (Arabic title + English subtitle + CTA)
- RAQM engine for proper Arabic rendering
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path

from .utils import setup_logging

logger = setup_logging("brand-template")

BRAND_COLOR = (184, 110, 75)  # Terracotta
DARK_BG = (30, 25, 20)
W, H = 1080, 1920


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)


def _make_background(product_img: Image.Image) -> Image.Image:
    """Create 1080x1920 background: blurred fill + sharp product centered."""
    # Blurred full-bleed background
    ratio_fill = max(W / product_img.width, H / product_img.height) * 1.15
    bg = product_img.resize(
        (int(product_img.width * ratio_fill), int(product_img.height * ratio_fill)),
        Image.LANCZOS,
    ).filter(ImageFilter.GaussianBlur(radius=30))
    left = (bg.width - W) // 2
    top = (bg.height - H) // 2
    canvas = bg.crop((left, top, left + W, top + H))

    # Sharp product image centered (with padding for bars)
    max_product_w, max_product_h = 960, 1200
    ratio_fit = min(max_product_w / product_img.width, max_product_h / product_img.height)
    product = product_img.resize(
        (int(product_img.width * ratio_fit), int(product_img.height * ratio_fit)),
        Image.LANCZOS,
    )
    px = (W - product.width) // 2
    py = 220 + (max_product_h - product.height) // 2
    canvas.paste(product, (px, py))

    return canvas


def _add_bars(canvas: Image.Image) -> Image.Image:
    """Add semi-transparent brand bars top + bottom."""
    rgba = canvas.convert("RGBA")

    # Top bar
    bar_top = Image.new("RGBA", (W, 190), (*DARK_BG, 210))
    rgba.paste(bar_top, (0, 0), bar_top)

    # Bottom bar
    bar_bottom = Image.new("RGBA", (W, 380), (*DARK_BG, 195))
    rgba.paste(bar_bottom, (0, H - 380), bar_bottom)

    # Accent lines
    for y in [190, H - 380]:
        line = Image.new("RGBA", (W, 5), (*BRAND_COLOR, 255))
        rgba.paste(line, (0, y), line)

    return rgba


def _add_badge(canvas: Image.Image) -> Image.Image:
    rgba = canvas if canvas.mode == 'RGBA' else canvas.convert('RGBA')
    badge = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    bx, by = W - 60, 210
    bw, bh = 220, 70
    red = (200, 35, 35, 240)
    gold = (235, 195, 80, 255)
    r = bh // 2
    x0, y0 = bx - bw, by
    x1, y1 = bx, by + bh
    draw.rounded_rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], radius=r + 3, fill=gold)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=red)
    # Use Chinese font for badge text (Segoe UI doesn't have CJK glyphs)
    f_cn = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 28, layout_engine=ImageFont.Layout.RAQM)
    draw.text((x0 + 16, y0 + bh // 2), "⭐", fill=gold, font=f_cn, anchor="lm")
    draw.text(((x0 + x1) // 2 + 10, y0 + bh // 2), "好物推荐", fill="white", font=f_cn, anchor="mm")
    rgba = Image.alpha_composite(rgba, badge)
    return rgba


def create_branded_slide(
    product_img_path: str,
    *,
    title_ar: str = "",
    subtitle_ar: str = "",
    title_en: str = "",
    category_en: str = "HOME & KITCHEN",
    cta_ar: str = "تابعونا للمزيد",
    cta_en: str = "Follow for more",
    slide_number: int = 0,
    total_slides: int = 0,
) -> Image.Image:
    """Create one branded 1080x1920 slide from a product image."""
    product_img = Image.open(product_img_path).convert("RGB")

    # Build layers
    canvas = _make_background(product_img)
    canvas = _add_bars(canvas)
    canvas = _add_badge(canvas)

    draw = ImageDraw.Draw(canvas)

    # --- Top bar ---
    f_brand = _font(32)
    f_cat = _font(24, bold=False)
    draw.text((W // 2, 50), "رقية بوتيك", fill="white", font=f_brand, anchor="mt")
    draw.text((W // 2, 95), "RAQIA BOUTIQUE", fill=(200, 180, 160), font=f_cat, anchor="mt")
    draw.text((W // 2, 135), f"— {category_en} —", fill=BRAND_COLOR, font=f_cat, anchor="mt")

    # Slide counter (if multi-slide)
    if total_slides > 1 and slide_number > 0:
        f_counter = _font(22, bold=False)
        draw.text((W - 40, 170), f"{slide_number}/{total_slides}", fill=(180, 170, 160), font=f_counter, anchor="rt")

    # --- Bottom bar ---
    y_base = H - 360
    if title_ar:
        f_ar_xl = _font(56)
        draw.text((W // 2, y_base), title_ar, fill="white", font=f_ar_xl, anchor="mt")
        y_base += 75

    if subtitle_ar:
        f_ar_m = _font(34)
        draw.text((W // 2, y_base), subtitle_ar, fill=(220, 210, 200), font=f_ar_m, anchor="mt")
        y_base += 55

    if title_en:
        f_en_m = _font(28, bold=False)
        draw.text((W // 2, y_base), title_en, fill=(180, 170, 160), font=f_en_m, anchor="mt")
        y_base += 45

    # CTA
    f_cta = _font(26, bold=False)
    draw.text((W // 2, H - 55), f"{cta_ar}  ❤️  {cta_en}", fill=BRAND_COLOR, font=f_cta, anchor="mt")

    return canvas.convert("RGB")


def create_branded_slides(
    image_paths: list[str],
    output_dir: str,
    *,
    title_ar: str = "",
    subtitle_ar: str = "",
    title_en: str = "",
    category_en: str = "HOME & KITCHEN",
) -> list[str]:
    """Create branded slides from multiple product images.

    Returns list of output file paths.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    results = []
    total = len(image_paths)
    for i, img_path in enumerate(image_paths):
        slide = create_branded_slide(
            img_path,
            title_ar=title_ar,
            subtitle_ar=subtitle_ar,
            title_en=title_en,
            category_en=category_en,
            slide_number=i + 1,
            total_slides=total,
        )
        out_path = str(out / f"branded_{i+1:02d}.jpg")
        slide.save(out_path, "JPEG", quality=95)
        results.append(out_path)
        logger.info(f"品牌图 {i+1}/{total}: {out_path}")

    return results
