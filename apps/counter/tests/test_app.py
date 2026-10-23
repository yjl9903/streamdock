import asyncio
import contextlib
import unittest
from pathlib import Path
from types import SimpleNamespace

from decklet.loader import load_script
from decklet.runtime import Runtime

APP_DIR = Path(__file__).resolve().parents[1]


class FakeSink:
    def __init__(self):
        self.device = SimpleNamespace(serial_number="counter-dock")
        self.sent = []

    @contextlib.contextmanager
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
        pass

    def send(self, tiles):
        self.sent.append(tiles)


class CounterExampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_script_runs_and_updates_image_through_public_events(self):
        sink, presses = FakeSink(), []

        @contextlib.contextmanager
        def opener(*, serial):
            yield sink

        with load_script(APP_DIR / "app.py", []) as (app, path):

            @app.on_connect
            async def connect(ctx):
                await ctx.display.flush()
                sink.emit(1, 1)
                sink.emit(1, 0)
                sink.emit(1, 1)

            @app.on_key(1)
            async def after_increment(ctx, event):
                presses.append(event)
                await ctx.display.flush()
                if len(presses) == 2:
                    sink.emit(18, 1)

            await asyncio.wait_for(Runtime(app, opener=opener, script_dir=path.parent).run(), 3)
        self.assertEqual(len(presses), 2)
        self.assertEqual(len(sink.sent), 3)
        self.assertTrue(all(batch[0][0] == 11 for batch in sink.sent))
        self.assertEqual(len({batch[0][1] for batch in sink.sent}), 3)
