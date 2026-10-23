import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager, nullcontext
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from apps.video.cache import prepare_cache
from apps.video.playback import VideoOptions
from apps.video.player import VideoPlayer
from apps.video.tests.test_controls import ScheduledControls


class FrameCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "video.bin"
        self.source.write_bytes(b"source video")
        self.directory = self.root / "cache"
        self.options = VideoOptions(fps=2, gap=32)

    def build(self, options=None, force=False):
        options = options or self.options
        frames = [Image.new("RGB", options.size, color) for color in ("red", "green", "blue")]
        with patch("apps.video.cache.decode_frames", return_value=nullcontext(iter(frames))):
            return prepare_cache(
                self.source,
                options,
                1.5,
                directory=self.directory,
                force=force,
                report=lambda _: None,
            )

    def test_reuse_and_random_access_do_not_decode_or_encode(self):
        cache = self.build()
        with (
            patch(
                "apps.video.cache.decode_frames",
                side_effect=AssertionError("decoded"),
            ),
            patch("apps.video.cache.jpeg_tiles", side_effect=AssertionError("encoded")),
        ):
            reused = prepare_cache(
                self.source,
                replace(self.options, start=0.5, seconds=0.5),
                1.5,
                directory=self.directory,
                report=lambda _: None,
            )
            self.assertEqual(reused.path, cache.path)
            with reused.reader() as reader:
                frames = list(reader.frames(1, 3))
        self.assertEqual(len(frames), 2)
        self.assertEqual([slot for slot, _ in frames[0]], list(range(1, 16)))
        with Image.open(BytesIO(frames[-1][0][1])) as image:
            self.assertEqual(image.size, (64, 64))
            self.assertGreater(image.getpixel((32, 32))[2], 245)

    def test_source_and_render_changes_produce_separate_caches(self):
        original = self.build().path
        paths = {original}
        for settings in [dict(fps=5), dict(gap=8), dict(quality=50), dict(key=8)]:
            paths.add(self.build(replace(self.options, **settings)).path)
        self.assertEqual(len(paths), 5)
        self.source.write_bytes(b"changed source video")
        self.assertNotIn(self.build().path, paths)

    def test_single_key_ignores_gap_in_cache_identity(self):
        first = self.build(replace(self.options, key=8, gap=0))
        second = self.build(replace(self.options, key=8, gap=32))
        self.assertEqual(first.path, second.path)

    def test_interrupted_rebuild_keeps_complete_cache_and_removes_partial_file(self):
        cache = self.build()
        before = cache.path.read_bytes()

        @contextmanager
        def interrupted(path, options):
            def frames():
                yield Image.new("RGB", options.size)
                raise KeyboardInterrupt

            yield frames()

        with patch("apps.video.cache.decode_frames", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                prepare_cache(
                    self.source,
                    self.options,
                    1.5,
                    directory=self.directory,
                    force=True,
                    report=lambda _: None,
                )
        self.assertEqual(cache.path.read_bytes(), before)
        self.assertEqual(list(self.directory.iterdir()), [cache.path])

    def test_partial_or_invalid_cache_is_rebuilt_and_payload_corruption_is_detected(self):
        cache = self.build()
        cache.path.write_bytes(b"incomplete SQLite database")
        cache = self.build()
        with closing(sqlite3.connect(cache.path)) as connection:
            connection.execute("UPDATE frames SET payload = ? WHERE idx = 1", (b"corrupt",))
            connection.commit()
        with cache.reader() as reader:
            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                list(reader.frames(1, 2))
        rebuilt = self.build(force=True)
        with rebuilt.reader() as reader:
            self.assertEqual(len(list(reader.frames(0, 3))), 3)

    def test_source_changed_during_build_is_not_published(self):
        @contextmanager
        def changing_source(path, options):
            def frames():
                yield Image.new("RGB", options.size)
                self.source.write_bytes(b"changed during conversion")

            yield frames()

        with patch("apps.video.cache.decode_frames", changing_source):
            with self.assertRaisesRegex(RuntimeError, "发生变化"):
                prepare_cache(
                    self.source, self.options, 1.5, directory=self.directory, report=lambda _: None
                )
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_player_pause_seek_and_loop_only_read_cached_jpegs(self):
        cache = self.build()
        now = [0.0]
        controls = ScheduledControls(
            now, [(0.1, "pause"), (0.2, "forward"), (0.3, "rewind"), (0.4, "pause")]
        )
        with (
            patch("apps.video.player.video_duration", return_value=1.5),
            patch(
                "apps.video.player.decode_frames",
                side_effect=AssertionError("decoded"),
            ),
            patch("apps.video.player.jpeg_tiles", side_effect=AssertionError("encoded")),
        ):
            player = VideoPlayer(
                self.source,
                self.options,
                loop=True,
                controls=controls,
                clock=lambda: now[0],
                report=lambda _: None,
            )
            player.cache = cache
            sink = Mock(send=AsyncMock(), check_connection=AsyncMock())

            def stop_after_loop(tiles):
                self.assertEqual(len(tiles), 15)
                if sink.send.call_count == 6:
                    raise KeyboardInterrupt

            sink.send.side_effect = stop_after_loop
            with self.assertRaises(KeyboardInterrupt):
                await player.run(sink)
            self.assertEqual(sink.send.call_count, 6)

    async def test_cached_loop_holds_last_frame_for_full_interval(self):
        cache = self.build()
        now = [0.0]
        times = []
        with patch("apps.video.player.video_duration", return_value=1.5):
            player = VideoPlayer(
                self.source,
                self.options,
                loop=True,
                controls=ScheduledControls(now),
                clock=lambda: now[0],
            )
        player.cache = cache
        sink = Mock(send=AsyncMock(), check_connection=AsyncMock())

        def send(tiles):
            times.append(now[0])
            if len(times) == 5:
                raise KeyboardInterrupt

        sink.send.side_effect = send
        with self.assertRaises(KeyboardInterrupt):
            await player.run(sink)
        self.assertEqual(times, [0, 0.5, 1, 1.5, 2])

    async def test_cached_resume_starts_at_saved_position_without_transcoding(self):
        cache = self.build()
        now = [300.0]
        with (
            patch("apps.video.player.video_duration", return_value=1.5),
            patch(
                "apps.video.player.decode_frames",
                side_effect=AssertionError("decoded"),
            ),
            patch("apps.video.player.jpeg_tiles", side_effect=AssertionError("encoded")),
        ):
            player = VideoPlayer(
                self.source, self.options, controls=ScheduledControls(now), clock=lambda: now[0]
            )
            player.cache = cache
            player.position = 0.5
            sink = Mock(send=AsyncMock(), check_connection=AsyncMock())
            positions = []
            sink.send.side_effect = lambda tiles: positions.append(player.position)
            stats = await player.run(sink)
        self.assertEqual(positions, [0.5, 1.0])
        self.assertEqual(stats["dropped_frames"], 0)
