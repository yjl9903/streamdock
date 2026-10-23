"""One application loop, serialized handlers, and one device I/O worker."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from pathlib import Path

from .app import App, Context
from .device import DeviceInfo
from .events import KeyEvent
from .hardware import DeviceUnavailable, open_device
from .rendering import encode_key


class _DeviceIO:
    """All methods, including open/close and encoding, run on the same worker."""

    def __init__(self, opener):
        self.opener = opener
        self.resources = ExitStack()
        self.sink = None
        self.sent_images = {}

    def open(self, serial, callback):
        try:
            self.sink = self.resources.enter_context(self.opener(serial=serial))
            self.resources.enter_context(self.sink.key_events(callback))
            return DeviceInfo(serial=self.sink.device.serial_number)
        except BaseException:
            self.close()
            raise

    def send(self, batch, profile, quality):
        self.sink.check_connection()
        encoded = {
            key: image
            if isinstance(image, bytes)
            else encode_key(image, quality=quality, profile=profile)
            for key, (_, image) in batch.items()
        }
        tiles = []
        for key, data in encoded.items():
            if self.sent_images.get(key) != data:
                row, column = divmod(key - 1, profile.columns)
                tiles.append((profile.image_slots[row][column], data))
        if tiles:
            self.sink.send(tiles)
        self.sent_images.update(encoded)

    def close(self):
        try:
            self.resources.close()
        finally:
            self.sink = None
            self.sent_images.clear()


class Runtime:
    def __init__(
        self,
        app: App,
        *,
        serial: str | None = None,
        script_dir: Path | None = None,
        args: list[str] | None = None,
        opener=open_device,
        retry_delay: float = 1,
        report=print,
    ):
        if not isinstance(app, App):
            raise TypeError("脚本必须导出 app: App")
        self.app = app
        self.serial = serial
        self.retry_delay = retry_delay
        self.report = report
        self._io = _DeviceIO(opener)
        self._stop = asyncio.Event()
        self._events = asyncio.Queue(maxsize=1024)
        self._generation = 0
        self._pressed = set()
        self._started = False
        self._used = False
        self._timers = []
        self._timer_pending = set()
        self.context = Context(
            self, script_dir=(script_dir or Path.cwd()).resolve(), args=args or []
        )

    async def _worker(self, function, *args):
        return await self._loop.run_in_executor(self._executor, function, *args)

    def _input(self, generation, key, state, timestamp):
        if generation != self._generation or not self.context.connected or self._stop.is_set():
            return
        if key not in self.context.device.input_keys or state not in (0, 1):
            return
        if state == 1:
            if key in self._pressed:
                return
            self._pressed.add(key)
        else:
            if key not in self._pressed:
                return
            self._pressed.remove(key)
        event = KeyEvent(key, "press" if state else "release", timestamp)
        try:
            self._events.put_nowait(("key", generation, event))
        except asyncio.QueueFull:
            if not self._failure.done():
                self._failure.set_result(RuntimeError("输入事件队列已满；请缩短处理函数执行时间"))

    def _sdk_callback(self, generation, device, event):
        if getattr(event.event_type, "value", None) == "button":
            self._loop.call_soon_threadsafe(
                self._input, generation, event.key, event.state, time.monotonic()
            )

    async def _devices(self):
        connected_once = False
        try:
            while not self._stop.is_set():
                self._generation += 1
                generation = self._generation
                try:
                    info = await self._worker(
                        self._io.open, self.serial, partial(self._sdk_callback, generation)
                    )
                except DeviceUnavailable:
                    if not connected_once:
                        raise
                    await asyncio.sleep(self.retry_delay)
                    continue
                connected_once = True
                self.serial = info.serial
                self.context.device = info
                self.context.connected = True
                self._pressed.clear()
                display = self.context.display
                display._reconnect()
                await self._events.put(("connect", generation, None))
                try:
                    while not self._stop.is_set():
                        batch = display._pending()
                        await self._worker(self._io.send, batch, info.profile, display.quality)
                        display._acknowledge(batch)
                        # Check connection even when the application is idle.
                        try:
                            await asyncio.wait_for(display._changed.wait(), timeout=0.1)
                        except TimeoutError:
                            pass
                except DeviceUnavailable as exc:
                    self.context.connected = False
                    self._generation += 1
                    self._pressed.clear()
                    await self._worker(self._io.close)
                    self.report(f"{exc}；等待设备 {self.serial} 重连，Ctrl+C 停止。")
                    # Reconnect independently of dispatch: a running handler may be
                    # awaiting display.flush(), which needs a live connection.
                    await self._events.put(("disconnect", generation, None))
                    await asyncio.sleep(self.retry_delay)
        finally:
            self.context.connected = False
            self._generation += 1
            # Cancellation cannot interrupt native work. Closing is queued behind it.
            await self._worker(self._io.close)

    async def _lifecycle(self, name):
        for callback in self.app._handlers[name]:
            await callback(self.context)

    async def _timer(self, interval, callback):
        while True:
            await asyncio.sleep(interval)
            if callback not in self._timer_pending:
                self._timer_pending.add(callback)
                await self._events.put(("timer", 0, callback))

    async def _dispatch(self):
        while not self._stop.is_set():
            kind, generation, payload = await self._events.get()
            if kind == "connect":
                if not self._started:
                    self._started = True
                    await self._lifecycle("start")
                    if self._stop.is_set():
                        continue
                    self._timers = [
                        asyncio.create_task(self._timer(interval, callback))
                        for interval, callback in self.app._timers
                    ]
                if generation == self._generation and self.context.connected:
                    await self._lifecycle("connect")
            elif kind == "disconnect":
                await self._lifecycle("disconnect")
            elif kind == "timer":
                try:
                    await payload(self.context)
                finally:
                    self._timer_pending.discard(payload)
            elif generation == self._generation and self.context.connected:
                for key, action, callback in self.app._keys:
                    if (key is None or key == payload.key) and action == payload.action:
                        await callback(self.context, payload)

    async def run(self):
        if self._used:
            raise RuntimeError("每个 Runtime 只能运行一次")
        self._used = True
        self._loop = asyncio.get_running_loop()
        self._failure = self._loop.create_future()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decklet-usb")
        tasks = [
            asyncio.create_task(self._devices()),
            asyncio.create_task(self._dispatch()),
            asyncio.create_task(self._stop.wait()),
        ]
        failures = []
        cancelled = None
        try:
            await asyncio.wait([*tasks, self._failure], return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError as exc:
            cancelled = exc
        finally:
            self._stop.set()
            self.context._closing = True
            self.context.display._close()
            pending = [*tasks, *self._timers, *self.context._tasks]
            for task in pending:
                if not task.done() and not task.cancelling():
                    task.cancel()
            results = await asyncio.gather(*pending, return_exceptions=True)
            self._executor.shutdown(wait=True)
            failures.extend(result for result in results if isinstance(result, Exception))
            if self._started:
                # Every cleanup hook gets a chance even when another one fails.
                for callback in self.app._handlers["stop"]:
                    try:
                        await callback(self.context)
                    except Exception as exc:
                        failures.append(exc)
            if self._failure.done() and self._failure.result() not in failures:
                failures.append(self._failure.result())
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise ExceptionGroup("应用运行及清理失败", failures)
        if cancelled is not None:
            raise cancelled


async def run_app(
    app: App,
    *,
    serial: str | None = None,
    script_dir: Path | None = None,
    args: list[str] | None = None,
):
    """Run an App from an existing asyncio application, without the CLI."""
    await Runtime(app, serial=serial, script_dir=script_dir, args=args).run()
