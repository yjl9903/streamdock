import shutil
import subprocess
import tempfile
import time
import unittest
from itertools import islice
from pathlib import Path

from streamdock.commands.video.playback import VideoOptions, decode_frames, playback_frames


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
class DecoderIntegrationTests(unittest.TestCase):
    def test_early_close_unblocks_ffmpeg_without_kill_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "sample.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=white:s=160x120:r=30:d=2",
                    "-c:v",
                    "libx264",
                    str(video),
                ],
                check=True,
            )
            with decode_frames(video, VideoOptions(gap=32)) as frames:
                next(frames)
                # Let the producer fill its pipe, as happens during pause/seek.
                time.sleep(0.05)
                before_close = time.monotonic()
            self.assertLess(time.monotonic() - before_close, 1.5)

    def test_resampling_letterbox_and_invalid_media(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "sample.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=white:s=80x60:r=30:d=1",
                    "-c:v",
                    "libx264",
                    str(video),
                ],
                check=True,
            )
            with decode_frames(video, VideoOptions(fps=8)) as frames:
                decoded = list(frames)
            self.assertEqual(len(decoded), 8)
            self.assertEqual(decoded[0].size, (320, 192))
            self.assertEqual(decoded[0].getpixel((0, 96)), (0, 0, 0))
            self.assertGreater(decoded[0].getpixel((160, 96))[0], 245)
            # A one-second source at 2 fps must restart twice to yield five frames.
            with playback_frames(video, VideoOptions(fps=2), loop=True) as frames:
                repeated = list(islice(frames, 5))
            self.assertEqual(len(repeated), 5)
            self.assertEqual(repeated[0].tobytes(), repeated[4].tobytes())
            with playback_frames(video, VideoOptions(fps=2)) as frames:
                self.assertEqual(len(list(frames)), 2)
            with self.assertRaisesRegex(RuntimeError, "没有可播放"):
                with decode_frames(video, VideoOptions(start=5)) as frames:
                    list(frames)
            invalid = Path(directory) / "broken.mp4"
            invalid.write_bytes(b"not a video")
            with self.assertRaisesRegex(RuntimeError, "视频解码失败"):
                with decode_frames(invalid, VideoOptions()) as frames:
                    list(frames)


if __name__ == "__main__":
    unittest.main()
