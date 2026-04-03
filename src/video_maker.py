"""Convert images to TikTok-ready slideshow video using FFmpeg.

Creates a vertical video (1080x1920) with:
- Each image displayed for a configurable duration
- Smooth fade transitions between images
- Optional background music
- TikTok-optimized encoding (H.264, AAC)
"""

import os
import subprocess
import tempfile
import shutil
from pathlib import Path

from PIL import Image

from src.utils import setup_logging

logger = setup_logging()

# TikTok vertical video specs
TIKTOK_WIDTH = 1080
TIKTOK_HEIGHT = 1920
FPS = 30


def _prepare_image(src_path: str, output_path: str) -> str:
    """Resize and pad image to fit TikTok 9:16 vertical format.

    - Resizes to fit within 1080x1920
    - Centers on black background
    - Converts to RGB JPEG
    """
    img = Image.open(src_path).convert("RGB")

    # Calculate scale to fit within target while maintaining aspect ratio
    scale = min(TIKTOK_WIDTH / img.width, TIKTOK_HEIGHT / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Blurred background fill (instead of black bars)
    from PIL import ImageFilter
    ratio_fill = max(TIKTOK_WIDTH / img.width, TIKTOK_HEIGHT / img.height) * 1.15
    bg = img.resize(
        (int(img.width * ratio_fill), int(img.height * ratio_fill)),
        Image.LANCZOS,
    ).filter(ImageFilter.GaussianBlur(radius=25))
    bx = (bg.width - TIKTOK_WIDTH) // 2
    by = (bg.height - TIKTOK_HEIGHT) // 2
    canvas = bg.crop((bx, by, bx + TIKTOK_WIDTH, by + TIKTOK_HEIGHT))

    # Overlay sharp image centered
    x = (TIKTOK_WIDTH - new_w) // 2
    y = (TIKTOK_HEIGHT - new_h) // 2
    canvas.paste(img, (x, y))

    canvas.save(output_path, "JPEG", quality=95)
    return output_path


def images_to_video(
    image_paths: list[str],
    output_path: str,
    *,
    duration_per_image: float = 3.0,
    transition_duration: float = 0.5,
    bg_music_path: str | None = None,
    bg_color: tuple[int, int, int] = (0, 0, 0),
) -> str:
    """Convert a list of images to a TikTok slideshow video.

    Args:
        image_paths: List of image file paths
        output_path: Output video file path (.mp4)
        duration_per_image: Seconds each image is shown
        transition_duration: Seconds for fade transition
        bg_music_path: Optional background music file
        bg_color: Background color for letterboxing

    Returns:
        Path to generated video file
    """
    if not image_paths:
        raise ValueError("No images provided")

    tmpdir = tempfile.mkdtemp(prefix="tiktok_slideshow_")

    try:
        # Step 1: Prepare all images (resize + pad to 1080x1920)
        prepared = []
        for i, img_path in enumerate(image_paths):
            out = os.path.join(tmpdir, f"img_{i:03d}.jpg")
            _prepare_image(img_path, out)
            prepared.append(out)
            logger.info(f"Prepared image {i+1}/{len(image_paths)}: {img_path}")

        # Step 2: Build FFmpeg filter graph
        n = len(prepared)
        total_duration = n * duration_per_image

        if n == 1:
            # Single image: just make a static video
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", prepared[0],
                "-t", str(duration_per_image),
                "-vf", f"scale={TIKTOK_WIDTH}:{TIKTOK_HEIGHT}",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-r", str(FPS),
                "-movflags", "+faststart",
            ]
        else:
            # Multiple images: use xfade transitions
            inputs = []
            for p in prepared:
                inputs.extend(["-loop", "1", "-t", str(duration_per_image), "-i", p])

            # Build xfade filter chain
            # Each xfade takes two inputs and produces one output
            filter_parts = []
            offset = duration_per_image - transition_duration

            if n == 2:
                filter_parts.append(
                    f"[0:v][1:v]xfade=transition=fade:duration={transition_duration}:offset={offset},format=yuv420p[v]"
                )
            else:
                # First transition
                filter_parts.append(
                    f"[0:v][1:v]xfade=transition=fade:duration={transition_duration}:offset={offset}[v1]"
                )
                # Middle transitions
                for i in range(2, n - 1):
                    prev_offset = offset + (i - 1) * (duration_per_image - transition_duration)
                    filter_parts.append(
                        f"[v{i-1}][{i}:v]xfade=transition=fade:duration={transition_duration}:offset={prev_offset}[v{i}]"
                    )
                # Last transition
                last_offset = offset + (n - 2) * (duration_per_image - transition_duration)
                filter_parts.append(
                    f"[v{n-2}][{n-1}:v]xfade=transition=fade:duration={transition_duration}:offset={last_offset},format=yuv420p[v]"
                )

            filter_graph = ";".join(filter_parts)

            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_graph,
                "-map", "[v]",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-r", str(FPS),
                "-movflags", "+faststart",
            ]

        # Add audio: insert -i before output, add -map for audio stream
        if bg_music_path and os.path.exists(bg_music_path):
            audio_input_idx = len(image_paths)  # audio is the next input after images
            cmd.extend(["-i", bg_music_path])
            cmd.extend(["-map", f"{audio_input_idx}:a"])
            cmd.extend(["-c:a", "aac", "-b:a", "128k", "-shortest"])

        cmd.append(output_path)

        logger.info(f"Running FFmpeg: {' '.join(cmd[:10])}...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg failed: {result.stderr[-500:]}")
            raise RuntimeError(f"FFmpeg failed: {result.stderr[-200:]}")

        size = os.path.getsize(output_path)
        logger.info(f"Video created: {output_path} ({size / 1024 / 1024:.1f} MB)")
        return output_path

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
