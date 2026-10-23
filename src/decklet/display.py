"""Bounded desired display state, consumed by the runtime's single USB writer."""

import asyncio
from io import BytesIO

from PIL import Image

from .device import M18V25E, DeviceProfile
from .rendering import key_image, split_canvas


class Display:
    """Use on the application event loop. Setters snapshot images immediately.

    Updates merge per key; at most one pending image per key is retained.
    ``flush`` waits until this revision (or a newer one) has been submitted to USB.
    It does not promise simultaneous physical refresh or device acknowledgement.
    """

    def __init__(self, profile: DeviceProfile = M18V25E, *, quality: int = 75):
        if not isinstance(quality, int) or not 1 <= quality <= 95:
            raise ValueError("JPEG 质量必须是 1..95 的整数")
        self.profile = profile
        self.quality = quality
        self._images: dict[int, tuple[int, Image.Image | bytes]] = {}
        self._sent: dict[int, int] = {}
        self._revision = 0
        self._changed = asyncio.Event()
        self._progress = asyncio.Event()
        self._closed = False

    def _validate_key(self, key: int):
        if not isinstance(key, int) or isinstance(key, bool) or key not in self.profile.screen_keys:
            raise ValueError(f"按键 {key} 没有可用屏幕")

    def _update(self, tiles):
        if self._closed:
            raise RuntimeError("画面已关闭")
        self._revision += 1
        for key, image in tiles:
            self._images[key] = (self._revision, image)
        self._changed.set()

    def set_key(self, key: int, image: Image.Image) -> None:
        self._validate_key(key)
        self._update([(key, key_image(image, self.profile))])

    def set_canvas(self, image: Image.Image, *, gap: int = 0) -> None:
        self._update(split_canvas(image, gap=gap, profile=self.profile))

    def set_jpegs(self, tiles) -> None:
        """Submit pre-encoded JPEGs by logical key, e.g. from a video cache."""
        checked = []
        for key, data in tiles:
            self._validate_key(key)
            data = bytes(data)
            with Image.open(BytesIO(data)) as image:
                if image.format != "JPEG" or image.size != self.profile.key_image_size:
                    raise ValueError("JPEG 格式或按键尺寸无效")
                image.verify()
            checked.append((key, data))
        self._update(checked)

    def clear(self, key: int | None = None) -> None:
        keys = self.profile.screen_keys if key is None else (key,)
        for item in keys:
            self._validate_key(item)
        image = Image.new("RGB", self.profile.key_image_size)
        self._update([(item, image) for item in keys])

    async def flush(self) -> None:
        target = {key: revision for key, (revision, _) in self._images.items()}
        while any(self._sent.get(key, 0) < revision for key, revision in target.items()):
            if self._closed:
                raise RuntimeError("画面已关闭，未完成发送")
            self._progress.clear()
            await self._progress.wait()

    def _pending(self):
        self._changed.clear()
        return {
            key: value for key, value in self._images.items() if self._sent.get(key, 0) < value[0]
        }

    def _acknowledge(self, batch):
        self._sent.update({key: revision for key, (revision, _) in batch.items()})
        self._progress.set()

    def _reconnect(self):
        self._sent.clear()
        self._changed.set()

    def _close(self):
        self._closed = True
        self._progress.set()
