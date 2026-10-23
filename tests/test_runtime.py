import asyncio
import threading
import unittest
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from decklet import App
from decklet.hardware import DeviceUnavailable
from decklet.runtime import Runtime


class FakeSink:
    def __init__(self):
        self.device = SimpleNamespace(serial_number="original-dock")
        self.callback = None
        self.connected = True
        self.sent = []
        self.threads = []
        self.on_send = None

    @contextmanager
    def key_events(self, callback):
        self.callback = callback
        try:
            yield
        finally:
            self.callback = None

    def emit(self, key, state):
        self.callback(
            None, SimpleNamespace(key=key, state=state, event_type=SimpleNamespace(value="button"))
        )

    def check_connection(self):
        self.threads.append(threading.get_ident())
        if not self.connected:
            raise DeviceUnavailable("USB removed")

    def send(self, tiles):
        self.check_connection()
        if self.on_send:
            self.on_send(tiles)
        self.sent.append(tiles)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def opener(self, sink):
        @contextmanager
        def open_fake(*, serial):
            self.operations.append(("open", threading.get_ident(), serial))
            try:
                yield sink
            finally:
                self.operations.append(("close", threading.get_ident(), serial))

        return open_fake

    def setUp(self):
        self.operations = []

    async def run_runtime(self, app, sink, **kwargs):
        runtime = Runtime(app, opener=self.opener(sink), retry_delay=0.001, **kwargs)
        await asyncio.wait_for(runtime.run(), 3)
        return runtime

    async def test_lifecycle_mapping_deduplication_and_single_usb_thread(self):
        app, sink, events = App(), FakeSink(), []

        @app.on_start
        async def start(ctx):
            events.append("start")
            self.assertEqual(ctx.device.screen_keys, tuple(range(1, 16)))
            ctx.display.set_key(1, Image.new("RGB", (64, 64), "red"))
            ctx.display.set_key(11, Image.new("RGB", (64, 64), "blue"))
            await ctx.display.flush()
            # Identical pixels should not cause another native write.
            ctx.display.set_key(1, Image.new("RGB", (64, 64), "red"))
            await ctx.display.flush()

        @app.on_connect
        async def connect(ctx):
            events.append("connect")
            sink.emit(1, 1)
            sink.emit(1, 1)
            sink.emit(1, 0)

        @app.on_key(1)
        async def press(ctx, event):
            events.append(event.action)

        @app.on_key(1, action="release")
        async def release(ctx, event):
            events.append(event.action)
            ctx.stop()

        @app.on_stop
        async def stop(ctx):
            events.append("stop")

        await self.run_runtime(app, sink)
        self.assertEqual(events, ["start", "connect", "press", "release", "stop"])
        self.assertEqual([[slot for slot, _ in tiles] for tiles in sink.sent], [[11, 1]])
        threads = {thread for _, thread, _ in self.operations} | set(sink.threads)
        self.assertEqual(len(threads), 1)
        self.assertNotIn(threading.get_ident(), threads)
        self.assertIsNone(sink.callback)

    async def test_reconnect_preserves_state_pins_serial_and_redraws_all_keys(self):
        app, first, second = App(), FakeSink(), FakeSink()
        opened, lifecycle = [], []
        old_callback = None

        @contextmanager
        def opener(*, serial):
            opened.append(serial)
            if len(opened) == 2:
                raise DeviceUnavailable("not yet")
            yield first if len(opened) == 1 else second

        @app.on_start
        async def start(ctx):
            lifecycle.append("start")
            ctx.display.set_key(1, Image.new("RGB", (64, 64), "red"))

        @app.on_connect
        async def connect(ctx):
            nonlocal old_callback
            lifecycle.append("connect")
            await ctx.display.flush()
            if len(opened) == 1:
                old_callback = first.callback
                first.emit(1, 1)
                first.connected = False
            else:
                old_callback(
                    None,
                    SimpleNamespace(key=1, state=1, event_type=SimpleNamespace(value="button")),
                )
                second.emit(1, 1)

        @app.on_disconnect
        async def disconnect(ctx):
            lifecycle.append("disconnect")
            self.assertFalse(ctx.connected)
            ctx.display.set_key(2, Image.new("RGB", (64, 64), "blue"))

        @app.on_key(1)
        async def key(ctx, event):
            if len(opened) > 1:
                lifecycle.append("new-press")
                ctx.stop()

        runtime = Runtime(app, opener=opener, retry_delay=0.001, report=lambda _: None)
        await asyncio.wait_for(runtime.run(), 3)
        self.assertEqual(opened, [None, "original-dock", "original-dock"])
        self.assertEqual(lifecycle, ["start", "connect", "disconnect", "connect", "new-press"])
        self.assertEqual({slot for tiles in second.sent for slot, _ in tiles}, {11, 12})

    async def test_updates_during_slow_send_merge_per_key_without_blocking_events(self):
        app, sink = App(), FakeSink()
        entered, release = threading.Event(), threading.Event()

        def slow(tiles):
            if not entered.is_set():
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("test writer was not released")

        sink.on_send = slow

        @app.on_start
        async def start(ctx):
            ctx.display.set_key(1, Image.new("RGB", (64, 64), "red"))

        @app.on_connect
        async def connect(ctx):
            while not entered.is_set():
                await asyncio.sleep(0.001)
            ctx.display.set_key(2, Image.new("RGB", (64, 64), "green"))
            ctx.display.set_key(1, Image.new("RGB", (64, 64), "blue"))
            release.set()
            await ctx.display.flush()
            ctx.stop()

        try:
            await self.run_runtime(app, sink)
        finally:
            release.set()
        latest = dict(tile for batch in sink.sent for tile in batch)
        self.assertEqual(set(latest), {11, 12})
        with Image.open(BytesIO(latest[11])) as image:
            self.assertGreater(image.getpixel((32, 32))[2], 240)

    async def test_background_failure_cancels_tasks_and_runs_all_cleanup_hooks(self):
        app, sink, events = App(), FakeSink(), []

        @app.on_start
        async def start(ctx):
            async def forever():
                try:
                    await asyncio.Event().wait()
                finally:
                    events.append("cancelled")

            async def fail():
                await asyncio.sleep(0)
                raise ValueError("user background failure")

            ctx.create_task(forever())
            ctx.create_task(fail())

        @app.on_stop
        async def stop(ctx):
            events.append("stop")

        with self.assertRaisesRegex(ValueError, "user background failure"):
            await self.run_runtime(app, sink)
        self.assertEqual(events, ["cancelled", "stop"])
        self.assertEqual([item[0] for item in self.operations], ["open", "close"])

    async def test_initial_failure_does_not_retry_or_start_user_code(self):
        calls = []

        @contextmanager
        def missing(*, serial):
            calls.append(serial)
            raise DeviceUnavailable("missing")
            yield

        runtime = Runtime(App(), opener=missing)
        with self.assertRaises(DeviceUnavailable):
            await asyncio.wait_for(runtime.run(), 1)
        self.assertEqual(calls, [None])

    async def test_flush_inside_handler_survives_disconnect_without_deadlocking(self):
        app, first, second, calls = App(), FakeSink(), FakeSink(), []
        first.connected = False

        @contextmanager
        def opener(*, serial):
            calls.append(serial)
            yield first if len(calls) == 1 else second

        @app.on_start
        async def start(ctx):
            ctx.display.clear(1)
            await ctx.display.flush()
            ctx.stop()

        runtime = Runtime(app, opener=opener, retry_delay=0.001, report=lambda _: None)
        await asyncio.wait_for(runtime.run(), 2)
        self.assertEqual(calls, [None, "original-dock"])
        self.assertEqual(len(second.sent), 1)

    async def test_cancellation_during_native_send_closes_after_write_and_runs_cleanup(self):
        app, sink, entered, release = App(), FakeSink(), threading.Event(), threading.Event()
        stopped = []

        def slow(tiles):
            entered.set()
            release.wait(2)

        sink.on_send = slow

        @app.on_start
        async def start(ctx):
            ctx.display.clear(1)

        @app.on_stop
        async def stop(ctx):
            stopped.append(True)

        runtime = Runtime(app, opener=self.opener(sink))
        task = asyncio.create_task(runtime.run())
        try:
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0.01)
            self.assertEqual([item[0] for item in self.operations], ["open"])
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        self.assertEqual([item[0] for item in self.operations], ["open", "close"])
        self.assertEqual(stopped, [True])

    async def test_handler_and_cleanup_failures_are_both_reported(self):
        app, sink, stopped = App(), FakeSink(), []

        @app.on_start
        async def start(ctx):
            raise ValueError("bad user code")

        @app.on_stop
        async def first_stop(ctx):
            raise RuntimeError("bad cleanup")

        @app.on_stop
        async def second_stop(ctx):
            stopped.append(True)

        with self.assertRaises(ExceptionGroup) as caught:
            await self.run_runtime(app, sink)
        self.assertEqual(
            [str(exc) for exc in caught.exception.exceptions], ["bad user code", "bad cleanup"]
        )
        self.assertEqual(stopped, [True])

    async def test_timer_and_key_callbacks_do_not_overlap_and_timer_stops_on_exit(self):
        app, sink, active, counts = App(), FakeSink(), [], []

        @app.every(0.001)
        async def tick(ctx):
            self.assertEqual(active, [])
            active.append("timer")
            sink.emit(1, 1)
            await asyncio.sleep(0.01)
            active.clear()
            counts.append(1)

        @app.on_key(1)
        async def key(ctx, event):
            self.assertEqual(active, [])
            ctx.stop()

        await self.run_runtime(app, sink)
        self.assertEqual(counts, [1])
