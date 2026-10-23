import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from streamdock.commands.video.playback import (
    VideoOptions,
    decode_frames,
    export_preview,
    jpeg_tiles,
)


class GapTests(unittest.TestCase):
    def test_crops_skip_gap_pixels_and_keep_slot_mapping(self):
        options = VideoOptions(gap=8, quality=95)
        self.assertEqual(options.size, (352, 208))
        frame = Image.new("RGB", options.size, "magenta")
        for index in range(15):
            row, column = divmod(index, 5)
            left, top = column * 72, row * 72
            frame.paste((index * 16,) * 3, (left, top, left + 64, top + 64))
        tiles = jpeg_tiles(frame, options)
        self.assertEqual(
            [slot for slot, _ in tiles], [11, 12, 13, 14, 15, 6, 7, 8, 9, 10, 1, 2, 3, 4, 5]
        )
        for index, (_, data) in enumerate(tiles):
            with Image.open(io.BytesIO(data)) as tile:
                self.assertEqual(tile.size, (64, 64))
                for low, high in tile.getextrema():
                    self.assertLessEqual(abs(low - index * 16), 2)
                    self.assertLessEqual(abs(high - index * 16), 2)

    def test_single_key_ignores_gap(self):
        frame = Image.new("RGB", (64, 64), "red")
        self.assertEqual(VideoOptions(key=8, gap=8).size, (64, 64))
        self.assertEqual(
            jpeg_tiles(frame, VideoOptions(key=8)), jpeg_tiles(frame, VideoOptions(key=8, gap=8))
        )

    def test_negative_gap_rejected(self):
        with self.assertRaises(ValueError):
            VideoOptions(gap=-1)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_preview_masks_gaps_and_preserves_visible_regions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            output = Path(directory) / "preview.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=white:s=352x208:r=10:d=0.3",
                    "-c:v",
                    "libx264",
                    str(source),
                ],
                check=True,
            )
            options = VideoOptions(gap=8)
            export_preview(source, output, options)
            with decode_frames(output, options) as frames:
                frame = next(frames)
            self.assertEqual(frame.size, (352, 208))
            for x in (68, 140, 212, 284):
                self.assertLess(max(frame.getpixel((x, 32))), 15)
            for y in (68, 140):
                self.assertLess(max(frame.getpixel((32, y))), 15)
            for row in range(3):
                for column in range(5):
                    self.assertGreater(min(frame.getpixel((column * 72 + 32, row * 72 + 32))), 240)


if __name__ == "__main__":
    unittest.main()
