"""Reference profile; this module does not probe connected hardware."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceProfile:
    model: str
    driver: str
    rows: int
    columns: int
    key_image_size: tuple[int, int]
    background_image_size: tuple[int, int]
    image_format: str
    image_slots: tuple[tuple[int, ...], ...]
    input_keys: tuple[int, ...] = ()

    @property
    def screen_keys(self) -> tuple[int, ...]:
        return tuple(range(1, self.rows * self.columns + 1))

    def canvas_size(self, gap: int = 0) -> tuple[int, int]:
        if not isinstance(gap, int) or gap < 0:
            raise ValueError("间距必须是非负整数像素")
        width, height = self.key_image_size
        return (
            self.columns * width + (self.columns - 1) * gap,
            self.rows * height + (self.rows - 1) * gap,
        )


# Rows are ordered from top to bottom, columns from left to right.
# The official SDK maps logical keys 1..15 to these image slots itself.
# Do not pass these hardware slots to its public set_key_image method.
M18V25E = DeviceProfile(
    model="M18V25E",
    driver="StreamDockM18",
    rows=3,
    columns=5,
    key_image_size=(64, 64),
    background_image_size=(480, 272),
    image_format="JPEG",
    image_slots=((11, 12, 13, 14, 15), (6, 7, 8, 9, 10), (1, 2, 3, 4, 5)),
    input_keys=tuple(range(1, 19)),
)


@dataclass(frozen=True)
class DeviceInfo:
    """Device capabilities, without a native SDK handle."""

    serial: str
    profile: DeviceProfile = M18V25E

    @property
    def model(self) -> str:
        return self.profile.model

    @property
    def rows(self) -> int:
        return self.profile.rows

    @property
    def columns(self) -> int:
        return self.profile.columns

    @property
    def key_image_size(self) -> tuple[int, int]:
        return self.profile.key_image_size

    @property
    def screen_keys(self) -> tuple[int, ...]:
        return self.profile.screen_keys

    @property
    def input_keys(self) -> tuple[int, ...]:
        return self.profile.input_keys
