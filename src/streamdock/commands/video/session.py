"""Reconnect a running player to the same device after sleep or USB removal."""

import time

from ...hardware import DeviceUnavailable, open_device


def play_on_device(player, *, serial=None, report=print, retry_wait=time.sleep):
    reconnecting = False
    connected = False
    while True:
        try:
            with open_device(serial=serial) as sink:
                # Pin automatic selection too: never resume on a different dock.
                serial = sink.device.serial_number
                connected = True
                player.controls.reset()
                with sink.key_events(player.controls.on_event):
                    if reconnecting:
                        report(
                            f"设备已重连，从 {player.position:.1f}s 恢复"
                            f"（{'保持暂停' if player.paused else '继续播放'}）。"
                        )
                    reconnecting = False
                    return player.run(sink)
        except DeviceUnavailable as exc:
            if not connected:
                # Initial connection errors remain actionable CLI failures.
                raise
            if not reconnecting:
                report(f"{exc}；等待设备 {serial} 重连，Ctrl+C 停止。")
            reconnecting = True
            retry_wait(1)
