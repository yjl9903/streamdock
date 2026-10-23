import io
import unittest
from unittest.mock import Mock

from PIL import Image

from apps.video.playback import (
    VideoOptions,
    jpeg_tiles,
    play_frames,
    read_exact,
)


class PlaybackTests(unittest.TestCase):
    def test_tiles_preserve_positions_and_logical_keys(self):
        frame = Image.new("RGB", (320, 192))
        for key in range(15):
            row, column = divmod(key, 5)
            frame.paste(
                (key * 16, key * 16, key * 16),
                (column * 64, row * 64, column * 64 + 64, row * 64 + 64),
            )
        tiles = jpeg_tiles(frame, VideoOptions())
        self.assertEqual([slot for slot, _ in tiles], list(range(1, 16)))
        for index, (_, data) in enumerate(tiles):
            with Image.open(io.BytesIO(data)) as tile:
                self.assertEqual(tile.size, (64, 64))
                self.assertEqual(tile.format, "JPEG")
                self.assertLessEqual(abs(tile.getpixel((32, 32))[0] - index * 16), 2)

    def test_single_key_uses_logical_position(self):
        tiles = jpeg_tiles(Image.new("RGB", (64, 64)), VideoOptions(key=11))
        self.assertEqual([slot for slot, _ in tiles], [11])

    def test_slow_device_drops_frames_without_slowing_timeline(self):
        now = [0.0]
        sink = Mock()
        sink.send.side_effect = lambda _: now.__setitem__(0, now[0] + 0.25)
        frames = [Image.new("RGB", (64, 64)) for _ in range(6)]
        stats = play_frames(
            frames,
            sink,
            VideoOptions(fps=10, key=1),
            clock=lambda: now[0],
            sleep=lambda delay: now.__setitem__(0, now[0] + delay),
        )
        self.assertEqual(stats, {"sent_frames": 3, "dropped_frames": 3})
        self.assertAlmostEqual(now[0], 0.75)

    def test_fast_device_waits_until_frame_deadline(self):
        now = [0.0]
        times = []
        sink = Mock()
        sink.send.side_effect = lambda _: times.append(now[0])
        play_frames(
            [Image.new("RGB", (64, 64))] * 3,
            sink,
            VideoOptions(fps=10, key=1),
            clock=lambda: now[0],
            sleep=lambda delay: now.__setitem__(0, now[0] + delay),
        )
        self.assertEqual(times, [0, 0.1, 0.2])

    def test_pipe_short_reads_do_not_truncate_frame(self):
        source = Mock()
        source.read.side_effect = [b"ab", b"c", b"def"]
        self.assertEqual(read_exact(source, 6), b"abcdef")


if __name__ == "__main__":
    unittest.main()
