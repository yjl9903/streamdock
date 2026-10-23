"""Bounded-memory video decoding, JPEG tiling and real-time scheduling."""

import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from ...device import M18V25E


@dataclass(frozen=True)
class VideoOptions:
    fps: int = 10
    start: float = 0
    seconds: float | None = None
    key: int | None = None
    quality: int = 75
    gap: int = 0

    def __post_init__(self):
        if self.gap < 0:
            raise ValueError("按键间距不能为负数")

    @property
    def size(self) -> tuple[int, int]:
        return (64, 64) if self.key is not None else (320 + 4 * self.gap, 192 + 2 * self.gap)


def input_command(path: Path, options: VideoOptions) -> list[str]:
    path = path.expanduser()
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("找不到 ffmpeg；macOS 可运行 brew install ffmpeg")
    if not path.is_file():
        raise FileNotFoundError(f"找不到视频文件：{path}；请传入存在的本地视频路径")
    width, height = options.size
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        str(options.start),
        "-i",
        str(path.resolve()),
    ]
    if options.seconds is not None:
        command += ["-t", str(options.seconds)]
    command += [
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps={options.fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
    ]
    return command


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def read_exact(stream, length: int) -> bytes:
    """Pipes may return short reads; only EOF terminates a frame."""
    chunks = bytearray()
    while len(chunks) < length:
        chunk = stream.read(length - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


@contextmanager
def decode_frames(path: Path, options: VideoOptions):
    command = input_command(path, options) + ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        try:

            def frames():
                width, height = options.size
                length = width * height * 3
                count = 0
                while True:
                    data = read_exact(process.stdout, length)
                    if not data:
                        break
                    if len(data) != length:
                        raise RuntimeError("ffmpeg 输出了不完整的视频帧")
                    count += 1
                    yield Image.frombytes("RGB", (width, height), data)
                if process.wait() != 0:
                    errors.seek(0)
                    raise RuntimeError(
                        f"视频解码失败：{errors.read().decode(errors='replace').strip()}"
                    )
                if count == 0:
                    raise RuntimeError("视频没有可播放的帧，请检查文件和 --start")

            yield frames()
        finally:
            # Release FFmpeg's blocked pipe writer before waiting for shutdown.
            # Otherwise terminate() may wait for the 3-second kill fallback on seek.
            process.stdout.close()
            stop_process(process)


@contextmanager
def playback_frames(path: Path, options: VideoOptions, *, loop: bool = False):
    """Repeat the selected clip, closing the active decoder on cancellation."""

    def repeat():
        while True:
            with decode_frames(path, options) as frames:
                yield from frames
            if not loop:
                return

    frames = repeat()
    try:
        yield frames
    finally:
        frames.close()


def jpeg_tiles(frame: Image.Image, options: VideoOptions) -> list[tuple[int, bytes]]:
    """Return hardware slots and JPEG bytes; map logical keys exactly once."""
    if frame.size != options.size:
        raise ValueError(f"帧尺寸应为 {options.size}，实际为 {frame.size}")
    tiles = []
    keys = [options.key] if options.key is not None else range(1, 16)
    for key in keys:
        row, column = divmod(key - 1, 5)
        left, top = column * (64 + options.gap), row * (64 + options.gap)
        tile = frame if options.key is not None else frame.crop((left, top, left + 64, top + 64))
        with BytesIO() as output:
            tile.save(output, format="JPEG", quality=options.quality)
            tiles.append((M18V25E.image_slots[row][column], output.getvalue()))
    return tiles


def play_frames(frames, sink, options: VideoOptions, *, clock=time.monotonic, sleep=time.sleep):
    started = None
    sent = dropped = 0
    interval = 1 / options.fps
    for index, frame in enumerate(frames):
        now = clock()
        if started is None:
            started = now
        deadline = started + index * interval
        if now >= deadline + interval:
            dropped += 1
            continue
        if now < deadline:
            sleep(deadline - now)
        sink.send(jpeg_tiles(frame, options))
        sent += 1
    return {"sent_frames": sent, "dropped_frames": dropped}


def export_preview(path: Path, destination: Path, options: VideoOptions) -> None:
    """Export the fitted picture with key boundaries or masked physical gaps."""
    if destination.exists():
        raise FileExistsError(f"预览已存在，不覆盖：{destination}")
    command = input_command(path, options)
    if options.key is None:
        if options.gap:
            for column in range(4):
                left = 64 + column * (64 + options.gap)
                command[-1] += f",drawbox=x={left}:y=0:w={options.gap}:h=ih:color=black:t=fill"
            for row in range(2):
                top = 64 + row * (64 + options.gap)
                command[-1] += f",drawbox=x=0:y={top}:w=iw:h={options.gap}:color=black:t=fill"
        else:
            command[-1] += ",drawgrid=width=64:height=64:thickness=1:color=gray"
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        output = Path(directory) / "preview.mp4"
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command + [str(output)], stderr=errors)
            try:
                if process.wait() != 0:
                    errors.seek(0)
                    raise RuntimeError(
                        f"预览生成失败：{errors.read().decode(errors='replace').strip()}"
                    )
            finally:
                stop_process(process)
        # Check empty/out-of-range videos before publishing the preview.
        with decode_frames(output, VideoOptions(key=options.key, gap=options.gap)) as frames:
            next(frames)
        import os

        os.link(output, destination)
