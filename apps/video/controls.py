"""Video actions from the library's normalized key events."""

import asyncio

from decklet import KeyEvent


class VideoControls:
    BINDINGS = {16: "rewind", 17: "pause", 18: "forward"}

    def __init__(self):
        self._commands = asyncio.Queue()

    def on_event(self, event: KeyEvent):
        if event.action == "press" and event.key in self.BINDINGS:
            self._commands.put_nowait(self.BINDINGS[event.key])

    async def get(self, timeout=0):
        if not self._commands.empty():
            return self._commands.get_nowait()
        if timeout <= 0:
            return None
        try:
            return await asyncio.wait_for(self._commands.get(), timeout)
        except TimeoutError:
            return None

    def reset(self):
        while not self._commands.empty():
            self._commands.get_nowait()
