"""CLI entry point for user applications."""

import argparse
import asyncio
import signal
from pathlib import Path

from ..loader import load_script
from ..runtime import Runtime


def register(commands):
    parser = commands.add_parser("run", help="运行导出 app: App 的 Python 脚本")
    parser.add_argument("--serial", help="选择设备序列号（放在脚本路径前）")
    parser.add_argument("script", type=Path, metavar="SCRIPT.py")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="-- 后的参数传给脚本")
    parser.set_defaults(handler=run_script)


def run_script(args):
    script_args = args.args[1:] if args.args[:1] == ["--"] else args.args
    with load_script(args.script, script_args) as (app, path):

        async def run():
            runtime = Runtime(app, serial=args.serial, script_dir=path.parent, args=script_args)
            loop = asyncio.get_running_loop()
            previous = signal.getsignal(signal.SIGTERM)
            installed = False
            try:
                try:
                    loop.add_signal_handler(signal.SIGTERM, runtime.context.stop)
                    installed = True
                except (NotImplementedError, RuntimeError):
                    pass
                await runtime.run()
            finally:
                if installed:
                    loop.remove_signal_handler(signal.SIGTERM)
                    signal.signal(signal.SIGTERM, previous)

        asyncio.run(run())
    return 0
