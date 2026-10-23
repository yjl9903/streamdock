"""Registration and handlers for video-related CLI commands."""

import argparse
import json
import math
from functools import partial
from pathlib import Path


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


def register(commands) -> None:
    play = commands.add_parser("play", help="在 15 个按键屏拼接播放，或导出离线预览（无音频）")
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
    play.add_argument("--serial", help="多台设备时选择序列号")
    cache_options = play.add_mutually_exclusive_group()
    cache_options.add_argument(
        "--no-cache", action="store_true", help="禁用 JPEG 帧缓存，使用实时解码"
    )
    cache_options.add_argument(
        "--rebuild-cache", action="store_true", help="重新生成视频的 JPEG 帧缓存"
    )
    play.set_defaults(handler=partial(run_play, parser=play))


def run_play(args: argparse.Namespace, *, parser: argparse.ArgumentParser) -> int:
    if args.loop and args.preview:
        parser.error("--loop 仅用于设备播放，不能与 --preview 同时使用")
    if args.rebuild_cache and args.preview:
        parser.error("--rebuild-cache 仅用于设备播放，不能与 --preview 同时使用")

    from .playback import VideoOptions, export_preview

    options = VideoOptions(args.fps, args.start, args.seconds, args.key, args.quality, gap=args.gap)
    if args.preview:
        export_preview(args.video, args.preview, options)
        print(f"预览已保存：{args.preview.resolve()}")
    else:
        from .player import VideoPlayer
        from .session import play_on_device

        player = VideoPlayer(
            args.video, options, loop=args.loop, report=lambda message: print(message, flush=True)
        )
        if not args.no_cache:
            player.prepare_cache(force=args.rebuild_cache)
        mode = "循环播放" if args.loop else "播放"
        print(f"开始{mode}（无音频），Ctrl+C 停止。", flush=True)
        print("底部按键：左＝快退10秒，中＝暂停/继续，右＝快进10秒。", flush=True)
        stats = play_on_device(player, serial=args.serial, report=player.report)
        print(json.dumps(stats, ensure_ascii=False))
    return 0
