import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from streamdock.commands.video.controls import VideoControls
from streamdock.commands.video.session import play_on_device
from streamdock.hardware import DeviceUnavailable


class SessionTests(unittest.TestCase):
    def test_retries_same_serial_preserves_state_and_rebinds_controls(self):
        player = Mock(position=12.3, paused=True)
        player.controls = VideoControls()
        event = SimpleNamespace(key=17, state=1, event_type=SimpleNamespace(value="button"))
        player.controls.on_event(None, event)
        opened, closed, sinks = [], [], []

        @contextmanager
        def open_fake(*, serial):
            opened.append(serial)
            if len(opened) == 2:
                raise DeviceUnavailable("still asleep")
            sink = Mock()
            sink.device.serial_number = "original-dock"
            sink.key_events.return_value = nullcontext()
            sinks.append(sink)
            try:
                yield sink
            finally:
                closed.append(sink)

        def run(sink):
            self.assertIsNone(player.controls.get())
            # The release event was lost; a fresh press must still work.
            player.controls.on_event(None, event)
            self.assertEqual(player.controls.get(), "pause")
            self.assertEqual((player.position, player.paused), (12.3, True))
            if len(sinks) == 1:
                raise DeviceUnavailable("lost USB")
            return {"sent_frames": 3}

        player.run.side_effect = run
        wait, report = Mock(), Mock()
        with patch("streamdock.commands.video.session.open_device", open_fake):
            result = play_on_device(player, report=report, retry_wait=wait)
        self.assertEqual(result, {"sent_frames": 3})
        self.assertEqual(opened, [None, "original-dock", "original-dock"])
        self.assertEqual(closed, sinks)
        self.assertEqual(wait.call_count, 2)
        self.assertEqual(report.call_count, 2)
        for sink in sinks:
            sink.key_events.assert_called_once_with(player.controls.on_event)

    def test_initial_connection_error_does_not_retry(self):
        wait = Mock()
        with patch(
            "streamdock.commands.video.session.open_device",
            side_effect=DeviceUnavailable("missing"),
        ):
            with self.assertRaisesRegex(DeviceUnavailable, "missing"):
                play_on_device(Mock(), serial="requested", retry_wait=wait)
        wait.assert_not_called()

    def test_decode_errors_are_not_treated_as_disconnects(self):
        sink = Mock()
        sink.key_events.return_value = nullcontext()
        player = Mock()
        player.run.side_effect = RuntimeError("corrupt cache")
        wait = Mock()
        with patch("streamdock.commands.video.session.open_device", return_value=nullcontext(sink)):
            with self.assertRaisesRegex(RuntimeError, "corrupt cache"):
                play_on_device(player, retry_wait=wait)
        wait.assert_not_called()

    def test_ctrl_c_exits_reconnection_wait(self):
        sink = Mock()
        sink.key_events.return_value = nullcontext()
        player = Mock()
        player.run.side_effect = DeviceUnavailable("removed")
        with patch("streamdock.commands.video.session.open_device", return_value=nullcontext(sink)):
            with self.assertRaises(KeyboardInterrupt):
                play_on_device(
                    player, report=Mock(), retry_wait=Mock(side_effect=KeyboardInterrupt)
                )
