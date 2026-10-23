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
)
