"""Thin adapter around the bundled, pinned official SDK."""

import time
from contextlib import contextmanager


def load_sdk():
    """Load SDK classes and the native library without enumerating USB devices."""
    try:
        from streamdock._vendor.mirabox.DeviceManager import DeviceManager
        from streamdock._vendor.mirabox.Devices.StreamDockM18 import StreamDockM18
    except (ImportError, OSError, AttributeError) as exc:
        raise RuntimeError(f"官方 SDK / 原生通信库加载失败：{exc}") from exc
    return DeviceManager, StreamDockM18


def enumerate_devices():
    DeviceManager, StreamDockM18 = load_sdk()
    return DeviceManager().enumerate(), StreamDockM18


def describe_devices():
    devices, m18_class = enumerate_devices()
    try:
        return [
            {
                "driver": type(device).__name__,
                "serial": device.serial_number,
                "vendor_id": f"{device.vendor_id:04x}",
                "product_id": f"{device.product_id:04x}",
                "runtime_supported": isinstance(device, m18_class),
            }
            for device in devices
        ]
    finally:
        for device in devices:
            device.close(notify=False)


class DeviceUnavailable(RuntimeError):
    """A transient device failure that the application runtime can recover from."""


class DeviceSink:
    def __init__(self, device):
        self.device = device
        self._last_wall = time.time()
        self._last_tick = time.monotonic()
        self._next_probe = self._last_tick + 1
        self._initial_error = device.transport.get_last_error()

    def check_connection(self):
        wall, tick = time.time(), time.monotonic()
        gap = max(wall - self._last_wall, tick - self._last_tick)
        self._last_wall, self._last_tick = wall, tick
        # Wall time also advances on platforms whose monotonic clock excludes sleep.
        # Reopen before sending or dropping overdue frames after a long suspension.
        if gap > 2:
            raise DeviceUnavailable("检测到睡眠或运行中断，需要重新连接 USB")
        if tick < self._next_probe:
            return
        self._next_probe = tick + 1
        found = self.device.transport.enumerate_devices(
            vendor_id=self.device.vendor_id,
            product_id=self.device.product_id,
        )
        if not any(item["path"] == self.device.path for item in found):
            raise DeviceUnavailable("设备已断开")
        error = self.device.transport.get_last_error()
        if error and error != self._initial_error:
            raise DeviceUnavailable(f"USB 通信失败：{error}")

    @contextmanager
    def key_events(self, callback):
        previous = self.device.key_callback
        self.device.set_key_callback(callback)
        try:
            yield
        finally:
            self.device.set_key_callback(previous)

    def send(self, tiles):
        for slot, jpeg in tiles:
            self.check_connection()
            deadline = time.monotonic() + 3
            while not self.device.transport.can_write():
                self.check_connection()
                if time.monotonic() >= deadline:
                    raise DeviceUnavailable("设备不可写或已断开")
                time.sleep(0.005)
            result = self.device.transport.set_key_image_stream(jpeg, slot)
            if result != 0:
                raise DeviceUnavailable(f"图片发送失败（槽位 {slot}，返回值 {result}）")
        self.device.refresh()


@contextmanager
def open_device(serial: str | None = None):
    devices, m18_class = enumerate_devices()
    selected = None
    try:
        candidates = [
            device
            for device in devices
            if isinstance(device, m18_class) and (serial is None or device.serial_number == serial)
        ]
        if not candidates:
            raise DeviceUnavailable("未发现匹配的 M18 设备；检查 USB 连接及 --serial")
        if len(candidates) > 1:
            raise RuntimeError("发现多台 M18 设备，请使用 --serial 选择")
        device = candidates[0]
        selected = device
        if not device.open():
            raise DeviceUnavailable("无法打开设备；请退出占用设备的 Mirabox StreamDock 软件后重试")
        # Avoid init(): it clears all icons and forces brightness to 100%.
        device.set_device()
        device.wakeScreen()
        yield DeviceSink(device)
    finally:
        for device in devices:
            try:
                if device is selected:
                    device.transport.clear_task_queue()
            finally:
                device.close(notify=False)
