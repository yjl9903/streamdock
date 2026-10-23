"""Image conversion helpers. All keys here are logical, never hardware slots."""

from io import BytesIO

from PIL import Image

from .device import M18V25E, DeviceProfile


def key_image(image: Image.Image, profile: DeviceProfile = M18V25E) -> Image.Image:
    if image.size != profile.key_image_size:
        raise ValueError(f"按键图片尺寸应为 {profile.key_image_size}，实际为 {image.size}")
    return image.convert("RGB")


def split_canvas(
    image: Image.Image, *, gap: int = 0, profile: DeviceProfile = M18V25E
) -> list[tuple[int, Image.Image]]:
    size = profile.canvas_size(gap)
    if image.size != size:
        raise ValueError(f"画布尺寸应为 {size}，实际为 {image.size}")
    width, height = profile.key_image_size
    tiles = []
    for key in profile.screen_keys:
        row, column = divmod(key - 1, profile.columns)
        left, top = column * (width + gap), row * (height + gap)
        tiles.append((key, key_image(image.crop((left, top, left + width, top + height)), profile)))
    return tiles


def encode_key(image: Image.Image, *, quality: int = 75, profile: DeviceProfile = M18V25E) -> bytes:
    if not isinstance(quality, int) or not 1 <= quality <= 95:
        raise ValueError("JPEG 质量必须是 1..95 的整数")
    with BytesIO() as output:
        key_image(image, profile).save(output, format="JPEG", quality=quality)
        return output.getvalue()


def encode_canvas(
    image: Image.Image, *, gap: int = 0, quality: int = 75, profile: DeviceProfile = M18V25E
) -> list[tuple[int, bytes]]:
    return [
        (key, encode_key(tile, quality=quality, profile=profile))
        for key, tile in split_canvas(image, gap=gap, profile=profile)
    ]
