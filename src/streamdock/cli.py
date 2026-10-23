"""Root CLI: register commands, dispatch handlers and report errors."""

import argparse
import json
import sys
from dataclasses import asdict

from .commands.video.cli import register as register_video_commands
from .device import M18V25E


def show_info(args: argparse.Namespace) -> int:
    profile = asdict(M18V25E)
    profile["logical_keys"] = [
        list(range(row * M18V25E.columns + 1, (row + 1) * M18V25E.columns + 1))
        for row in range(M18V25E.rows)
    ]
    print(
        json.dumps(
            {
                "profile": profile,
                "hardware_verified": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def show_devices(args: argparse.Namespace) -> int:
    from .hardware import describe_devices

    print(json.dumps(describe_devices(), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="streamdock",
        description="streamdock 控制",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info", help="输出设备参考资料及按键布局（JSON）").set_defaults(
        handler=show_info
    )
    devices = commands.add_parser("devices", help="枚举已连接设备")
    devices.set_defaults(handler=show_devices)
    register_video_commands(commands)
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("\n已停止播放。", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
