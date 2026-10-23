from contextlib import contextmanager
from types import SimpleNamespace

from decklet.hardware import DeviceUnavailable


class FakeSink:
    def __init__(self):
        self.device = SimpleNamespace(serial_number="original-dock")
        self.callback = None
        self.connected = True
        self.sent = []
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
        if not self.connected:
            raise DeviceUnavailable("USB removed")

    def send(self, tiles):
        self.check_connection()
        if self.on_send:
            self.on_send(tiles)
        self.sent.append(tiles)
