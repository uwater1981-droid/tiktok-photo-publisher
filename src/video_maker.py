"""Convert images to TikTok-ready slideshow video using FFmpeg."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from src.utils import setup_logging

logger = setup_logging()

# TikTok vertical video specs
TIKTOK_WIDTH = 1080
TIKTOK_HEIGHT = 1920
FPS = 30
MIN_SLIDES = 3
MIN_VIDEO_DURATION = 15.0
FFMPEG_TIMEOUT_SECONDS = 300
TRANSITIONS = ["fade", "slideleft", "slideright", "dissolve"]
DEFAULT_BGM_PATH = Path(__file__).resolve().parents[1] / "assets" / "music" / "default_bgm.mp3"


def _prepare_image(src_path: str, output_path: str) -> str:
    """Resize and pad image to fit TikTok 9:16 vertical format."""
    img = Image.open(src_path).convert("RGB")

    scale = min(TIKTOK_WIDTH / img.width, TIKTOK_HEIGHT / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Keep the blurred fill behavior so portrait videos do not show hard bars.
    from PIL import ImageFilter

    ratio_fill = max(TIKTOK_WIDTH / img.width, TIKTOK_HEIGHT / img.height) * 1.15
    bg = img.resize(
        (int(img.width * ratio_fill), int(img.height * ratio_fill)),
        Image.LANCZOS,
    ).filter(ImageFilter.GaussianBlur(radius=25))
    bx = (bg.width - TIKTOK_WIDTH) // 2
    by = (bg.height - TIKTOK_HEIGHT) // 2
    canvas = bg.crop((bx, by, bx + TIKTOK_WIDTH, by + TIKTOK_HEIGHT))

    x = (TIKTOK_WIDTH - new_w) // 2
    y = (TIKTOK_HEIGHT - new_h) // 2
    canvas.paste(img, (x, y))

    canvas.save(output_path, "JPEG", quality=95)
    return output_path


def _color_variance(path: str) -> float:
    """Estimate image variance so detailed scene shots sort ahead of flat slides."""
    with Image.open(path) as img:
        rgb = img.convert("RGB").resize((128, 128), Image.LANCZOS)
        pixels = np.asarray(rgb, dtype=np.float32)
    return float(np.std(pixels))


def _sort_images_scene_first(paths: list[str]) -> list[str]:
    scored = [(path, _color_variance(path)) for path in paths]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [path for path, _score in scored]


def _ensure_minimum_slides(paths: list[str], min_slides: int = MIN_SLIDES) -> list[str]:
    if not paths:
        return []

    expanded = list(paths)
    reversed_paths = list(reversed(paths))
    index = 0

    while len(expanded) < min_slides:
        expanded.append(reversed_paths[index % len(reversed_paths)])
        index += 1

    return expanded


def _resolve_bgm(bg_music_path: str | None) -> str | None:
    if bg_music_path:
        if os.path.exists(bg_music_path):
            return bg_music_path
        logger.warning(f"Background music not found, falling back to default: {bg_music_path}")

    if DEFAULT_BGM_PATH.exists():
        return str(DEFAULT_BGM_PATH)

    logger.warning(f"Default background music not found: {DEFAULT_BGM_PATH}")
    return None


def _run_ffmpeg(cmd: list[str]) -> None:
    logger.info(f"Running FFmpeg: {' '.join(cmd[:12])}...")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        logger.error(f"FFmpeg failed: {result.stderr[-500:]}")
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-200:]}")


def _render_kenburns_clip(
    image_path: str,
    output_clip_path: str,
    duration: float,
    effect_index: int,
) -> str:
    frame_count = max(int(duration * FPS), 1)
    pan_steps = max(frame_count - 1, 1)

    if effect_index % 2 == 0:
        zoompan = (
            "zoompan="
            "z='min(zoom+0.0005,1.08)':"
            "x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':"
            f"d={frame_count}:"
            f"s={TIKTOK_WIDTH}x{TIKTOK_HEIGHT}:"
            f"fps={FPS}"
        )
    else:
        zoompan = (
            "zoompan="
            "z='1.08':"
            f"x='max((iw-iw/zoom)*(1-on/{pan_steps}),0)':"
            "y='ih/2-(ih/zoom/2)':"
            f"d={frame_count}:"
            f"s={TIKTOK_WIDTH}x{TIKTOK_HEIGHT}:"
            f"fps={FPS}"
        )

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        image_path,
        "-t",
        str(duration),
        "-vf",
        f"{zoompan},format=yuv420p",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        output_clip_path,
    ]
    _run_ffmpeg(cmd)
    return output_clip_path


def _build_xfade_filter(clip_count: int, duration_per_image: float, transition_duration: float) -> str:
    if clip_count < 2:
        return "[0:v]format=yuv420p[v]"

    filter_parts: list[str] = []
    offset_step = duration_per_image - transition_duration

    first_transition = TRANSITIONS[0]
    filter_parts.append(
        f"[0:v][1:v]xfade=transition={first_transition}:duration={transition_duration}:offset={offset_step}[v1]"
    )

    for index in range(2, clip_count):
        transition = TRANSITIONS[(index - 1) % len(TRANSITIONS)]
        prev_stream = f"[v{index - 1}]"
        out_stream = "[v]" if index == clip_count - 1 else f"[v{index}]"
        offset = offset_step * index
        tail = ",format=yuv420p" if index == clip_count - 1 else ""
        filter_parts.append(
            f"{prev_stream}[{index}:v]xfade=transition={transition}:duration={transition_duration}:offset={offset}{tail}{out_stream}"
        )

    if clip_count == 2:
        return (
            f"[0:v][1:v]xfade=transition={first_transition}:"
            f"duration={transition_duration}:offset={offset_step},format=yuv420p[v]"
        )

    return ";".join(filter_parts)


def images_to_video(
    image_paths: list[str],
    output_path: str,
    *,
    duration_per_image: float = 3.0,
    transition_duration: float = 0.5,
    bg_music_path: str | None = None,
    bg_color: tuple[int, int, int] = (0, 0, 0),
) -> str:
    """Convert a list of images to a TikTok slideshow video."""
    _ = bg_color  # Kept for signature compatibility.

    if not image_paths:
        raise ValueError("No images provided")
    if duration_per_image <= 0:
        raise ValueError("duration_per_image must be greater than 0")
    if transition_duration < 0:
        raise ValueError("transition_duration must be non-negative")
    if duration_per_image <= transition_duration:
        raise ValueError("duration_per_image must be greater than transition_duration")

    sorted_paths = _sort_images_scene_first(image_paths)
    slide_paths = _ensure_minimum_slides(sorted_paths, min_slides=MIN_SLIDES)
    minimum_duration_per_image = (
        MIN_VIDEO_DURATION + max(len(slide_paths) - 1, 0) * transition_duration
    ) / len(slide_paths)
    duration_per_image = max(duration_per_image, minimum_duration_per_image)
    bgm_path = _resolve_bgm(bg_music_path)

    tmpdir = tempfile.mkdtemp(prefix="tiktok_slideshow_")

    try:
        prepared_images: list[str] = []
        for index, img_path in enumerate(slide_paths):
            prepared_path = os.path.join(tmpdir, f"img_{index:03d}.jpg")
            _prepare_image(img_path, prepared_path)
            prepared_images.append(prepared_path)
            logger.info(f"Prepared image {index + 1}/{len(slide_paths)}: {img_path}")

        rendered_clips: list[str] = []
        for index, prepared_path in enumerate(prepared_images):
            clip_path = os.path.join(tmpdir, f"clip_{index:03d}.mp4")
            _render_kenburns_clip(prepared_path, clip_path, duration_per_image, index)
            rendered_clips.append(clip_path)
            logger.info(f"Rendered Ken Burns clip {index + 1}/{len(prepared_images)}")

        cmd = ["ffmpeg", "-y"]
        for clip_path in rendered_clips:
            cmd.extend(["-i", clip_path])

        if bgm_path:
            cmd.extend(["-stream_loop", "-1", "-i", bgm_path])

        filter_graph = _build_xfade_filter(
            clip_count=len(rendered_clips),
            duration_per_image=duration_per_image,
            transition_duration=transition_duration,
        )

        cmd.extend(
            [
                "-filter_complex",
                filter_graph,
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(FPS),
                "-movflags",
                "+faststart",
            ]
        )

        if bgm_path:
            audio_input_idx = len(rendered_clips)
            cmd.extend(
                [
                    "-map",
                    f"{audio_input_idx}:a",
                    "-af",
                    "volume=0.3",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-shortest",
                ]
            )

        cmd.append(output_path)
        _run_ffmpeg(cmd)

        size = os.path.getsize(output_path)
        logger.info(f"Video created: {output_path} ({size / 1024 / 1024:.1f} MB)")
        return output_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
