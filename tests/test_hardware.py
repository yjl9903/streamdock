import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streamdock.hardware import DeviceSink, DeviceUnavailable, open_device


class BundledSDKTests(unittest.TestCase):
    def test_private_sdk_loads_outside_checkout_without_changing_import_paths(self):
        source = Path(__file__).resolve().parents[1] / "src"
        env = dict(os.environ, PYTHONPATH=str(source))
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    """
import sys
from streamdock.hardware import load_sdk
before = list(sys.path)
manager, device = load_sdk()
assert manager.__module__.startswith("streamdock._vendor.mirabox.")
assert device.__module__.startswith("streamdock._vendor.mirabox.")
assert "StreamDock" not in sys.modules
assert before == sys.path
""",
                ],
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


class HardwareTests(unittest.TestCase):
    def test_failed_send_does_not_refresh_partial_frame(self):
        device = Mock()
        device.transport.can_write.return_value = True
        device.transport.set_key_image_stream.return_value = 5
        with self.assertRaisesRegex(RuntimeError, "图片发送失败"):
            DeviceSink(device).send([(11, b"jpeg")])
        device.refresh.assert_not_called()

    def test_device_closed_after_playback_failure(self):
        class M18:
            pass

        device = M18()
        device.serial_number = "test"
        device.open = Mock(return_value=True)
        device.close = Mock()
        device.set_device = Mock()
        device.wakeScreen = Mock()
        device.transport = Mock()
        with patch("streamdock.hardware.enumerate_devices", return_value=([device], M18)):
            with self.assertRaisesRegex(RuntimeError, "decode failure"):
                with open_device():
                    raise RuntimeError("decode failure")
        device.close.assert_called_once_with(notify=False)
        device.transport.clear_task_queue.assert_called_once()

    def test_wake_detected_when_monotonic_clock_does_not_advance(self):
        device = Mock()
        with (
            patch("streamdock.hardware.time.time", side_effect=[10, 310]),
            patch("streamdock.hardware.time.monotonic", side_effect=[1, 1.1]),
        ):
            sink = DeviceSink(device)
            with self.assertRaisesRegex(DeviceUnavailable, "睡眠"):
                sink.send([(11, b"jpeg")])
        device.transport.set_key_image_stream.assert_not_called()

    def test_missing_usb_path_detected_while_paused(self):
        device = Mock()
        device.transport.enumerate_devices.return_value = []
        with (
            patch("streamdock.hardware.time.time", side_effect=[0, 1]),
            patch("streamdock.hardware.time.monotonic", side_effect=[0, 1]),
        ):
            sink = DeviceSink(device)
            with self.assertRaisesRegex(DeviceUnavailable, "断开"):
                sink.check_connection()

    def test_async_hid_failure_detected_even_if_device_still_enumerates(self):
        device = Mock()
        device.path = "usb-path"
        device.transport.enumerate_devices.return_value = [{"path": "usb-path"}]
        device.transport.get_last_error.side_effect = ["", "IOHIDDeviceSetReport failed"]
        with (
            patch("streamdock.hardware.time.time", side_effect=[0, 1]),
            patch("streamdock.hardware.time.monotonic", side_effect=[0, 1]),
        ):
            sink = DeviceSink(device)
            with self.assertRaisesRegex(DeviceUnavailable, "USB 通信失败"):
                sink.check_connection()


if __name__ == "__main__":
    unittest.main()
