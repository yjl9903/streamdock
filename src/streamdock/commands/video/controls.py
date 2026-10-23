"""Translate M18 bottom-button events into thread-safe playback commands."""

from queue import Empty, Queue
from threading import Lock


class VideoControls:
    # Logical keys decoded by the official SDK: left, middle, right.
    BINDINGS = {16: "rewind", 17: "pause", 18: "forward"}

    def __init__(self):
        self._commands = Queue()
        self._pressed = set()
        self._lock = Lock()

    def on_event(self, device, event):
        if getattr(event.event_type, "value", None) != "button":
            return
        key = event.key
        if key not in self.BINDINGS:
            return
        with self._lock:
            if event.state == 0:
                self._pressed.discard(key)
            elif event.state == 1 and key not in self._pressed:
                self._pressed.add(key)
                self._commands.put(self.BINDINGS[key])

    def get(self, timeout=0):
        try:
            return self._commands.get(timeout=max(0, timeout))
        except Empty:
            return None

    def reset(self):
        """Discard stale presses/releases when replacing a USB connection."""
        with self._lock:
            self._pressed.clear()
            while self.get() is not None:
                pass
