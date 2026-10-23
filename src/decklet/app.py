"""Application registration and runtime context."""

import asyncio
import inspect
import math
from pathlib import Path
from typing import TYPE_CHECKING

from .device import DeviceInfo
from .display import Display

if TYPE_CHECKING:
    from .runtime import Runtime


class App:
    def __init__(self):
        self._handlers = {name: [] for name in ("start", "connect", "disconnect", "stop")}
        self._keys = []
        self._timers = []

    @staticmethod
    def _check(callback):
        if not inspect.iscoroutinefunction(callback):
            raise TypeError("处理函数必须使用 async def")
        return callback

    def _register(self, name, callback):
        self._handlers[name].append(self._check(callback))
        return callback

    def on_start(self, callback):
        return self._register("start", callback)

    def on_connect(self, callback):
        return self._register("connect", callback)

    def on_disconnect(self, callback):
        return self._register("disconnect", callback)

    def on_stop(self, callback):
        return self._register("stop", callback)

    def on_key(self, key: int | None = None, *, action: str = "press"):
        if key is not None and (type(key) is not int or key < 1):
            raise ValueError("按键编号必须是正整数")
        if action not in ("press", "release"):
            raise ValueError("action 必须是 press 或 release")

        def register(callback):
            self._keys.append((key, action, self._check(callback)))
            return callback

        return register

    def every(self, seconds: float):
        """Run periodically, serially with events; missed ticks are coalesced."""
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("定时间隔必须是正有限数值")

        def register(callback):
            self._timers.append((seconds, self._check(callback)))
            return callback

        return register


class Context:
    def __init__(self, runtime: "Runtime", *, script_dir: Path, args: list[str]):
        self._runtime = runtime
        self.script_dir = script_dir
        self.args = list(args)
        self.device: DeviceInfo | None = None
        self.display = Display()
        self.connected = False
        self._tasks: set[asyncio.Task] = set()
        self._closing = False

    def stop(self) -> None:
        """Request shutdown; await display.flush() first if a final image must be sent."""
        self._runtime._stop.set()

    def create_task(self, coroutine, *, name: str | None = None) -> asyncio.Task:
        """Track a background coroutine, propagate failures and cancel it on exit."""
        if self._closing:
            coroutine.close()
            raise RuntimeError("应用正在退出，不能创建后台任务")
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task):
        self._tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None and not self._runtime._failure.done():
                self._runtime._failure.set_result(error)
