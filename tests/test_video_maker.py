import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from src import video_maker


class VideoMakerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.commands: list[tuple[list[str], dict]] = []

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _make_image(self, name: str, *, noisy: bool) -> str:
        path = self.tmp_path / name
        if noisy:
            grid = np.indices((96, 96)).sum(axis=0) % 2
            pixels = np.repeat(
                np.where(grid[..., None] == 0, 0, 255).astype(np.uint8),
                3,
                axis=2,
            )
            image = Image.fromarray(pixels, mode="RGB")
        else:
            image = Image.new("RGB", (96, 96), (250, 250, 250))
        image.save(path)
        return str(path)

    def _fake_ffmpeg(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.commands.append((cmd, kwargs))
        output_path = Path(cmd[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x00\x00\x00\x18ftypisom" + (b"\x00" * (1024 * 1024)))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def test_resolve_bgm_prefers_explicit_then_default(self) -> None:
        explicit = self.tmp_path / "custom.mp3"
        default = self.tmp_path / "default.mp3"
        explicit.write_bytes(b"custom")
        default.write_bytes(b"default")

        with mock.patch.object(video_maker, "DEFAULT_BGM_PATH", default, create=True):
            self.assertEqual(video_maker._resolve_bgm(str(explicit)), str(explicit))
            explicit.unlink()
            self.assertEqual(video_maker._resolve_bgm(None), str(default))

    def test_sort_images_scene_first_orders_by_variance(self) -> None:
        flat = self._make_image("flat.jpg", noisy=False)
        scene = self._make_image("scene.jpg", noisy=True)

        ordered = video_maker._sort_images_scene_first([flat, scene])

        self.assertEqual(ordered, [scene, flat])
        self.assertGreater(video_maker._color_variance(scene), video_maker._color_variance(flat))

    def test_ensure_minimum_slides_duplicates_from_reversed_list(self) -> None:
        self.assertEqual(
            video_maker._ensure_minimum_slides(["a", "b"], min_slides=3),
            ["a", "b", "b"],
        )
        self.assertEqual(
            video_maker._ensure_minimum_slides(["a"], min_slides=3),
            ["a", "a", "a"],
        )

    def test_render_kenburns_clip_uses_effect_specific_filters(self) -> None:
        image_path = self._make_image("source.jpg", noisy=True)
        zoom_clip = self.tmp_path / "zoom.mp4"
        pan_clip = self.tmp_path / "pan.mp4"

        with mock.patch("src.video_maker.subprocess.run", side_effect=self._fake_ffmpeg):
            video_maker._render_kenburns_clip(image_path, str(zoom_clip), 4.0, 0)
            video_maker._render_kenburns_clip(image_path, str(pan_clip), 4.0, 1)

        zoom_filter = self.commands[0][0][self.commands[0][0].index("-vf") + 1]
        pan_filter = self.commands[1][0][self.commands[1][0].index("-vf") + 1]

        self.assertIn("min(zoom+0.0005,1.08)", zoom_filter)
        self.assertIn("iw/2-(iw/zoom/2)", zoom_filter)
        self.assertIn("z='1.08'", pan_filter)
        self.assertIn("on", pan_filter)
        self.assertTrue(zoom_clip.exists())
        self.assertTrue(pan_clip.exists())
        self.assertTrue(all(kwargs["timeout"] == 300 for _, kwargs in self.commands))

    def test_images_to_video_sorts_scene_images_before_preparing(self) -> None:
        flat = self._make_image("flat.jpg", noisy=False)
        scene = self._make_image("scene.jpg", noisy=True)
        prepare_order: list[str] = []

        def fake_prepare(src_path: str, output_path: str) -> str:
            prepare_order.append(src_path)
            shutil.copy2(src_path, output_path)
            return output_path

        def fake_render(_image_path: str, output_clip_path: str, _duration: float, _effect_index: int) -> str:
            Path(output_clip_path).write_bytes(b"clip")
            return output_clip_path

        output_path = self.tmp_path / "slideshow.mp4"
        with mock.patch.object(video_maker, "_prepare_image", side_effect=fake_prepare), \
                mock.patch.object(video_maker, "_render_kenburns_clip", side_effect=fake_render), \
                mock.patch.object(video_maker, "_resolve_bgm", return_value=None), \
                mock.patch("src.video_maker.subprocess.run", side_effect=self._fake_ffmpeg):
            video_maker.images_to_video([flat, scene], str(output_path))

        self.assertEqual(prepare_order[0], scene)
        self.assertEqual(prepare_order[1], flat)

    def test_images_to_video_enforces_minimum_duration_and_audio_flags(self) -> None:
        img_a = self._make_image("a.jpg", noisy=True)
        img_b = self._make_image("b.jpg", noisy=False)
        bgm = self.tmp_path / "default_bgm.mp3"
        bgm.write_bytes(b"bgm")
        output_path = self.tmp_path / "slideshow.mp4"

        with mock.patch.object(video_maker, "DEFAULT_BGM_PATH", bgm, create=True), \
                mock.patch("src.video_maker.subprocess.run", side_effect=self._fake_ffmpeg):
            result = video_maker.images_to_video(
                [img_a, img_b],
                str(output_path),
                duration_per_image=3.0,
                transition_duration=0.5,
            )

        self.assertEqual(result, str(output_path))
        self.assertEqual(len(self.commands), 6)
        expected_duration = (15.0 + (5 - 1) * 0.5) / 5

        render_commands = [cmd for cmd, _ in self.commands[:-1]]
        for cmd in render_commands:
            self.assertIn("-t", cmd)
            self.assertAlmostEqual(float(cmd[cmd.index("-t") + 1]), expected_duration)

        final_cmd = self.commands[-1][0]
        filter_graph = final_cmd[final_cmd.index("-filter_complex") + 1]
        last_video_input = max(
            idx for idx, token in enumerate(final_cmd)
            if token == "-i" and final_cmd[idx + 1].endswith(".mp4")
        )
        audio_index = final_cmd.index("-stream_loop")

        self.assertGreater(audio_index, last_video_input)
        self.assertEqual(final_cmd[audio_index + 1], "-1")
        self.assertEqual(final_cmd[audio_index + 2], "-i")
        self.assertEqual(final_cmd[audio_index + 3], str(bgm))
        self.assertIn("transition=fade", filter_graph)
        self.assertIn("transition=slideleft", filter_graph)
        self.assertIn("-af", final_cmd)
        self.assertEqual(final_cmd[final_cmd.index("-af") + 1], "volume=0.3")
        self.assertIn("-c:a", final_cmd)
        self.assertEqual(final_cmd[final_cmd.index("-c:a") + 1], "aac")
        self.assertEqual(final_cmd[final_cmd.index("-b:a") + 1], "128k")
        self.assertIn("-shortest", final_cmd)
        self.assertEqual(final_cmd[final_cmd.index("-crf") + 1], "18")
        self.assertEqual(self.commands[-1][1]["timeout"], 300)

    def test_images_to_video_cycles_all_requested_transitions(self) -> None:
        image_paths = [
            self._make_image(f"img_{index}.jpg", noisy=index % 2 == 0)
            for index in range(5)
        ]
        bgm = self.tmp_path / "default_bgm.mp3"
        bgm.write_bytes(b"bgm")
        output_path = self.tmp_path / "cycle.mp4"

        with mock.patch.object(video_maker, "DEFAULT_BGM_PATH", bgm, create=True), \
                mock.patch("src.video_maker.subprocess.run", side_effect=self._fake_ffmpeg):
            video_maker.images_to_video(image_paths, str(output_path))

        filter_graph = self.commands[-1][0][self.commands[-1][0].index("-filter_complex") + 1]
        self.assertIn("transition=fade", filter_graph)
        self.assertIn("transition=slideleft", filter_graph)
        self.assertIn("transition=slideright", filter_graph)
        self.assertIn("transition=dissolve", filter_graph)


if __name__ == "__main__":
    unittest.main()
