import asyncio
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch

from apps.video.cache import prepare_cache
from apps.video.cli import create_app
from decklet.runtime import Runtime

from .fakes import FakeSink

APP_DIR = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is not installed")
class VideoExampleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=64x64:rate=10:duration=0.4",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(self.source),
            ],
            check=True,
        )

    async def test_cached_and_uncached_video_complete_with_runtime(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                sink, output = FakeSink(), io.StringIO()

                @contextlib.contextmanager
                def opener(*, serial):
                    yield sink

                args = [str(self.source), "--key", "1"] + ([] if cached else ["--no-cache"])
                app = create_app(args)
                with patch(
                    "apps.video.player.prepare_cache",
                    partial(prepare_cache, directory=self.root / "cache"),
                ):
                    with contextlib.redirect_stdout(output):
                        await asyncio.wait_for(Runtime(app, opener=opener).run(), 5)
                stats = json.loads(output.getvalue().splitlines()[-1])
                self.assertEqual(stats["loops"], 0)
                self.assertGreater(stats["sent_frames"], 0)
                self.assertTrue(sink.sent)
                self.assertTrue(all(slot == 11 for batch in sink.sent for slot, _ in batch))

    async def test_video_app_resumes_after_disconnect_with_original_serial(self):
        first, second, opened, closed = FakeSink(), FakeSink(), [], []

        def remove_after_first_frame(tiles):
            first.connected = False

        first.on_send = remove_after_first_frame

        @contextlib.contextmanager
        def opener(*, serial):
            opened.append(serial)
            try:
                yield first if len(opened) == 1 else second
            finally:
                closed.append(serial)

        app = create_app([str(self.source), "--key", "1", "--no-cache"])
        with contextlib.redirect_stdout(io.StringIO()):
            await asyncio.wait_for(Runtime(app, opener=opener, retry_delay=0.001).run(), 5)
        self.assertEqual(opened, [None, "original-dock"])
        self.assertEqual(closed, opened)
        self.assertTrue(second.sent)

    async def test_cli_preview_and_help_work_outside_checkout_without_device(self):
        output = self.root / "preview.mp4"
        command = [
            sys.executable,
            "-m",
            "decklet",
            "run",
            str(APP_DIR / "app.py"),
            "--",
        ]
        help_result = await asyncio.to_thread(
            subprocess.run, command + ["--help"], cwd=self.root, capture_output=True, text=True
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--preview", help_result.stdout)
        result = await asyncio.to_thread(
            subprocess.run,
            command + [str(self.source), "--preview", str(output)],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.is_file())
