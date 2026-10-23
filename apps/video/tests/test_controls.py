import math
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from apps.video.controls import VideoControls
from apps.video.playback import VideoOptions
from apps.video.player import VideoPlayer
from decklet import KeyEvent
from decklet.hardware import DeviceUnavailable


class ScheduledControls:
    """Deterministic event delivery without real-time waits."""

    def __init__(self, now, events=()):
        self.now = now
        self.events = list(events)

    async def get(self, timeout=0):
        end = self.now[0] + timeout
        if self.events and self.events[0][0] <= end + 1e-9:
            when, action = self.events.pop(0)
            self.now[0] = max(self.now[0], when)
            return action
        self.now[0] = end
        return None


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalized_events_map_to_video_actions(self):
        controls = VideoControls()
        controls.on_event(KeyEvent(1, "press", 0))
        controls.on_event(KeyEvent(16, "release", 0))
        self.assertIsNone(await controls.get())
        for key, action in [(16, "rewind"), (17, "pause"), (18, "forward")]:
            controls.on_event(KeyEvent(key, "press", 0))
            self.assertEqual(await controls.get(), action)
        controls.on_event(KeyEvent(17, "press", 0))
        controls.reset()
        self.assertIsNone(await controls.get())


class InteractivePlayerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = [0.0]
        self.starts = []
        self.closes = []
        self.sent = []

    @contextmanager
    def decode(self, path, options):
        self.starts.append(options.start)
        try:
            yield iter(
                [Image.new("RGB", options.size)] * math.ceil(options.seconds * options.fps - 1e-9)
            )
        finally:
            self.closes.append(options.start)

    async def run_player(self, duration, options, *, events=(), loop=False, sink_action=None):
        controls = ScheduledControls(self.now, events)
        with (
            patch("apps.video.player.video_duration", return_value=duration),
            patch("apps.video.player.decode_frames", self.decode),
        ):
            player = VideoPlayer(
                Path("test.mp4"),
                options,
                loop=loop,
                controls=controls,
                clock=lambda: self.now[0],
                report=lambda _: None,
            )
            sink = Mock(send=AsyncMock(), check_connection=AsyncMock())

            def send(tiles):
                self.sent.append((self.now[0], player.position, player.paused))
                if sink_action:
                    sink_action()

            sink.send.side_effect = send
            return await player.run(sink)

    async def test_pause_freezes_timeline_without_dropping_resumed_frames(self):
        stats = await self.run_player(
            0.3, VideoOptions(key=1), events=[(0.05, "pause"), (1.05, "pause")]
        )
        self.assertEqual(stats["dropped_frames"], 0)
        for actual, expected in zip([row[0] for row in self.sent], [0, 1.1, 1.2]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(len(self.sent), 3)

    async def test_paused_seek_previews_target_and_respects_clip_bounds(self):
        await self.run_player(
            30,
            VideoOptions(start=5, seconds=12, key=1),
            events=[
                (0.05, "pause"),
                (0.15, "forward"),
                (0.25, "forward"),
                (0.35, "rewind"),
                (0.45, "rewind"),
                (0.55, "pause"),
            ],
        )
        for actual, expected in zip(self.starts, [5, 15, 16.9, 6.9, 5]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(len(self.starts), 5)
        self.assertEqual(len([row for row in self.sent if row[2]]), 4)
        self.assertEqual(self.closes, self.starts)
        self.assertTrue(all(5 <= row[1] < 17 for row in self.sent))

    async def test_slow_sink_skips_late_frames(self):
        stats = await self.run_player(
            0.6,
            VideoOptions(key=1),
            sink_action=lambda: self.now.__setitem__(0, self.now[0] + 0.25),
        )
        self.assertEqual(stats, {"sent_frames": 3, "dropped_frames": 3, "loops": 0})

    async def test_loop_reopens_decoder_and_interrupt_closes_current_decoder(self):
        def interrupt():
            if len(self.sent) == 5:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            await self.run_player(0.2, VideoOptions(key=1), loop=True, sink_action=interrupt)
        self.assertEqual(self.starts, [0, 0, 0])
        self.assertEqual(self.closes, self.starts)

    def test_out_of_range_start_rejected_before_playback(self):
        with patch("apps.video.player.video_duration", return_value=2):
            with self.assertRaisesRegex(RuntimeError, "起始位置"):
                VideoPlayer(Path("test.mp4"), VideoOptions(start=2))

    async def test_reconnect_restarts_at_position_and_preserves_pause_and_clip_bounds(self):
        with (
            patch("apps.video.player.video_duration", return_value=30),
            patch("apps.video.player.decode_frames", self.decode),
        ):
            player = VideoPlayer(
                Path("test.mp4"),
                VideoOptions(start=5, seconds=12, key=1),
                controls=ScheduledControls(self.now),
                clock=lambda: self.now[0],
                report=lambda _: None,
            )
            sink = Mock(send=AsyncMock(), check_connection=AsyncMock())

            def disconnect(tiles):
                if sink.send.call_count == 3:
                    player.paused = True
                    raise DeviceUnavailable("sleep")

            sink.send.side_effect = disconnect
            with self.assertRaises(DeviceUnavailable):
                await player.run(sink)
            position = player.position
            self.now[0] += 300
            player.controls = ScheduledControls(self.now, [(self.now[0] + 0.2, "pause")])
            resumed = Mock(send=AsyncMock(), check_connection=AsyncMock())
            displayed = []
            resumed.send.side_effect = lambda tiles: displayed.append(
                (player.position, player.paused)
            )
            stats = await player.run(resumed)
        self.assertEqual(self.starts, [5, position])
        self.assertEqual(displayed[0], (position, True))
        self.assertEqual((player.start, player.end), (5, 17))
        self.assertEqual(stats["dropped_frames"], 0)
        self.assertEqual(stats["sent_frames"], 2 + len(displayed))
        self.assertEqual(self.starts, self.closes)
