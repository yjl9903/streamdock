"""Arguments and App wiring for the standalone video example."""

import argparse
import asyncio
import json
import math
import threading
from pathlib import Path

from decklet import App, Context, KeyEvent


def nonnegative(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("必须是非负有限数值")
    return number


def positive(value: str) -> float:
    number = nonnegative(value)
    if number == 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


def pixel_gap(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("间距必须是非负整数像素")
    return number


def create_app(argv: list[str] | None = None) -> App:
    play = argparse.ArgumentParser(description="Decklet 视频应用（无音频）")
    play.add_argument(
        "video", type=Path, metavar="VIDEO", help="本地视频路径（支持 FFmpeg 可解码的视频格式）"
    )
    play.add_argument("--fps", type=int, choices=range(1, 31), default=10, metavar="1..30")
    play.add_argument("--start", type=nonnegative, default=0, help="从第几秒开始")
    play.add_argument("--seconds", type=positive, help="只播放指定秒数")
    play.add_argument("--loop", action="store_true", help="循环播放整个视频或所选片段，Ctrl+C 停止")
    play.add_argument(
        "--key", type=int, choices=range(1, 16), metavar="1..15", help="仅在一个逻辑按键上播放"
    )
    play.add_argument(
        "--gap",
        type=pixel_gap,
        default=0,
        metavar="PIXELS",
        help="拼接裁图时跳过的水平/垂直按键间距，默认 0 像素；单键播放忽略",
    )
    play.add_argument("--quality", type=int, choices=range(1, 96), default=75, metavar="1..95")
    play.add_argument("--preview", type=Path, metavar="OUTPUT.mp4", help="生成离线预览，不连接硬件")
    cache_options = play.add_mutually_exclusive_group()
    cache_options.add_argument(
        "--no-cache", action="store_true", help="禁用 JPEG 帧缓存，使用实时解码"
    )
    cache_options.add_argument(
        "--rebuild-cache", action="store_true", help="重新生成视频的 JPEG 帧缓存"
    )
    args = play.parse_args(argv)
    parser = play
    if args.loop and args.preview:
        parser.error("--loop 仅用于设备播放，不能与 --preview 同时使用")
    if args.rebuild_cache and args.preview:
        parser.error("--rebuild-cache 仅用于设备播放，不能与 --preview 同时使用")

    from .playback import VideoOptions, export_preview

    options = VideoOptions(args.fps, args.start, args.seconds, args.key, args.quality, gap=args.gap)
    if args.preview:
        export_preview(args.video, args.preview, options)
        print(f"预览已保存：{args.preview.resolve()}")
        raise SystemExit(0)

    from .player import VideoPlayer

    app = App()
    player = None
    playback_task = None

    @app.on_start
    async def start(ctx: Context):
        nonlocal player
        player = await asyncio.to_thread(
            VideoPlayer,
            args.video,
            options,
            loop=args.loop,
            report=lambda message: print(message, flush=True),
        )
        if not args.no_cache:
            cancel = threading.Event()
            build = asyncio.create_task(
                asyncio.to_thread(
                    player.prepare_cache,
                    force=args.rebuild_cache,
                    cancel=cancel,
                )
            )
            try:
                await asyncio.shield(build)
            except asyncio.CancelledError:
                cancel.set()
                await asyncio.gather(build, return_exceptions=True)
                raise
        print("开始播放（无音频），Ctrl+C 停止。", flush=True)
        print("底部按键：左＝快退10秒，中＝暂停/继续，右＝快进10秒。", flush=True)

    @app.on_key()
    async def key(ctx: Context, event: KeyEvent):
        if ctx.connected:
            player.controls.on_event(event)

    @app.on_connect
    async def connect(ctx: Context):
        nonlocal playback_task
        player.controls.reset()

        async def playback():
            stats = await player.run(DisplayOutput(ctx))
            print(json.dumps(stats, ensure_ascii=False))
            ctx.stop()

        playback_task = ctx.create_task(playback(), name="video-playback")

    @app.on_disconnect
    async def disconnect(ctx: Context):
        if playback_task is not None and not playback_task.done():
            if not playback_task.cancelling():
                playback_task.cancel()
            await asyncio.gather(playback_task, return_exceptions=True)
        player.controls.reset()

    return app


class DisplayOutput:
    """Only public framework APIs are needed to present a cached video frame."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    async def check_connection(self):
        if not self.ctx.connected:
            # The runtime reconnects. on_connect resumes the existing player state.
            raise asyncio.CancelledError

    async def send(self, tiles):
        await self.check_connection()
        self.ctx.display.set_jpegs(tiles)
        await self.ctx.display.flush()
