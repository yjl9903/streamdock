"""Interactive player; only the playback thread decodes or writes images."""

import json
import math
import shutil
import subprocess
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from .cache import frame_range, prepare_cache
from .controls import VideoControls
from .playback import VideoOptions, decode_frames, jpeg_tiles


def video_duration(path: Path) -> float:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"找不到视频文件：{path}")
    executable = shutil.which("ffprobe")
    if executable is None:
        raise RuntimeError("找不到 ffprobe，请安装完整的 FFmpeg")
    try:
        result = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("视频信息读取超时") from exc
    if result.returncode:
        raise RuntimeError(f"视频信息读取失败：{result.stderr.strip()}")
    metadata = json.loads(result.stdout)
    if not metadata.get("streams"):
        raise RuntimeError("文件中没有视频轨道")
    for candidate in (
        metadata["streams"][0].get("duration"),
        metadata.get("format", {}).get("duration"),
    ):
        try:
            duration = float(candidate)
        except (ValueError, TypeError):
            continue
        if math.isfinite(duration) and duration > 0:
            return duration
    raise RuntimeError("无法确定视频时长，不能进行交互播放")


class VideoPlayer:
    SEEK_SECONDS = 10

    def __init__(
        self,
        path: Path,
        options: VideoOptions,
        *,
        loop=False,
        controls=None,
        clock=time.monotonic,
        report=print,
    ):
        self.path = path
        self.options = options
        self.loop = loop
        self.controls = controls if controls is not None else VideoControls()
        self.clock = clock
        self.report = report
        self.start = options.start
        self.duration = self.end = video_duration(path)
        if options.seconds is not None:
            self.end = min(self.end, self.start + options.seconds)
        if self.start >= self.end:
            raise RuntimeError("起始位置超出视频时长，请检查 --start")
        self.position = self.start
        self.paused = False
        self.cache = None
        self.stats = {"sent_frames": 0, "dropped_frames": 0, "loops": 0}

    def prepare_cache(self, *, force=False):
        self.cache = prepare_cache(
            self.path, self.options, self.duration, force=force, report=self.report
        )
        first, end = frame_range(self.start, self.end, self.options.fps, self.cache.count)
        if first >= end:
            raise RuntimeError("所选片段内没有可播放的缓存帧，请调整 --start / --seconds")
        self.start = first / self.options.fps
        self.end = min(self.end, end / self.options.fps)
        self.position = self.start

    def run(self, sink):
        interval = 1 / self.options.fps
        pending = None
        anchor = None
        pause_started = None
        preview = False

        with ExitStack() as resources, ExitStack() as decoders:
            cached = (
                resources.enter_context(self.cache.reader()) if self.cache is not None else None
            )

            def seek(target):
                nonlocal frames, offset, index, anchor, pending, preview
                # Keep a complete final sampling interval available when seeking.
                target = max(self.start, min(target, max(self.start, self.end - interval)))
                decoders.close()
                if cached is not None:
                    first, end = frame_range(target, self.end, self.options.fps, self.cache.count)
                    target = first / self.options.fps
                    frames = cached.frames(first, end)
                    decoders.callback(frames.close)
                else:
                    frames = decoders.enter_context(
                        decode_frames(
                            self.path,
                            replace(self.options, start=target, seconds=self.end - target),
                        )
                    )
                self.position = offset = target
                index = 0
                anchor = None
                pending = None
                preview = self.paused

            def apply(action):
                nonlocal anchor, pause_started
                if action == "pause":
                    now = self.clock()
                    self.paused = not self.paused
                    if self.paused:
                        pause_started = now
                    elif anchor is not None:
                        anchor += now - pause_started
                    self.report(f"{'暂停' if self.paused else '继续'}：{self.position:.1f}s")
                elif action in ("rewind", "forward"):
                    delta = -self.SEEK_SECONDS if action == "rewind" else self.SEEK_SECONDS
                    seek(self.position + delta)
                    self.report(f"{'快退' if delta < 0 else '快进'}至 {self.position:.1f}s")

            frames = None
            offset = self.start
            index = 0
            seek(self.position)
            while True:
                sink.check_connection()
                action = self.controls.get()
                if action is not None:
                    apply(action)
                    continue
                if self.paused and not preview:
                    action = self.controls.get(timeout=0.1)
                    if action is not None:
                        apply(action)
                    continue
                if pending is None:
                    try:
                        pending = next(frames)
                    except StopIteration:
                        # Hold the final frame for its full interval, including
                        # when the next loop can start immediately from cache.
                        remaining = (
                            0 if anchor is None else anchor + index * interval - self.clock()
                        )
                        if remaining > 0:
                            action = self.controls.get(timeout=remaining)
                            sink.check_connection()
                            if action is not None:
                                apply(action)
                                continue
                        if not self.loop:
                            break
                        self.stats["loops"] += 1
                        seek(self.start)
                        continue
                    if anchor is None:
                        anchor = self.clock()
                        if self.paused:
                            pause_started = anchor
                deadline = anchor + index * interval
                if not self.paused:
                    remaining = deadline - self.clock()
                    if remaining > 0:
                        action = self.controls.get(timeout=remaining)
                        sink.check_connection()
                        if action is not None:
                            apply(action)
                            continue
                self.position = offset + index * interval
                if not self.paused and self.clock() >= deadline + interval:
                    self.stats["dropped_frames"] += 1
                else:
                    sink.send(pending if cached is not None else jpeg_tiles(pending, self.options))
                    self.stats["sent_frames"] += 1
                pending = None
                index += 1
                preview = False
        return dict(self.stats)
