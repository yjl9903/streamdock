"""Atomic, on-disk JPEG frame caches with indexed random access."""

import hashlib
import json
import math
import os
import sqlite3
import struct
import tempfile
import time
import zlib
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from PIL import __version__ as pillow_version

from ...device import M18V25E
from .playback import VideoOptions, decode_frames, jpeg_tiles

DEFAULT_CACHE_DIR = Path(".cache/videos")
# Bump whenever the encoded frame format or rendering semantics change.
CACHE_VERSION = 1


def cache_identity(path: Path, options: VideoOptions) -> dict:
    source = path.expanduser().resolve()
    stat = source.stat()
    # Clip boundaries and looping do not change the full-video JPEG cache.
    settings = asdict(
        replace(options, start=0, seconds=None, gap=0 if options.key is not None else options.gap)
    )
    return {
        "version": CACHE_VERSION,
        "source": str(source),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "settings": settings,
        "image_slots": M18V25E.image_slots,
        "pillow": pillow_version,
    }


def identity_json(identity: dict) -> str:
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def frame_range(start: float, end: float, fps: int, count: int) -> tuple[int, int]:
    return (max(0, math.ceil(start * fps - 1e-7)), min(count, math.ceil(end * fps - 1e-7)))


def pack_tiles(tiles) -> bytes:
    return b"".join(struct.pack(">I", len(jpeg)) + jpeg for _, jpeg in tiles)


def unpack_tiles(data: bytes, slots: tuple[int, ...]) -> list[tuple[int, bytes]]:
    offset = 0
    tiles = []
    for slot in slots:
        if offset + 4 > len(data):
            raise RuntimeError("视频缓存帧不完整，请使用 --rebuild-cache")
        length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if length < 4 or offset + length > len(data):
            raise RuntimeError("视频缓存 JPEG 长度无效，请使用 --rebuild-cache")
        jpeg = data[offset : offset + length]
        if not (jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")):
            raise RuntimeError("视频缓存 JPEG 损坏，请使用 --rebuild-cache")
        tiles.append((slot, jpeg))
        offset += length
    if offset != len(data):
        raise RuntimeError("视频缓存帧格式无效，请使用 --rebuild-cache")
    return tiles


def connect_readonly(path: Path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


@dataclass(frozen=True)
class FrameCache:
    path: Path
    fps: int
    count: int
    slots: tuple[int, ...]

    @contextmanager
    def reader(self):
        connection = None
        try:
            connection = connect_readonly(self.path)
            yield CacheReader(connection, self.slots)
        except sqlite3.Error as exc:
            raise RuntimeError("视频缓存读取失败，请使用 --rebuild-cache") from exc
        finally:
            if connection is not None:
                connection.close()


class CacheReader:
    def __init__(self, connection, slots):
        self.connection = connection
        self.slots = slots

    def frames(self, first: int, end: int):
        cursor = self.connection.execute(
            "SELECT idx, payload, checksum FROM frames WHERE idx >= ? AND idx < ? ORDER BY idx",
            (first, end),
        )
        expected = first
        try:
            for index, payload, checksum in cursor:
                if index != expected or zlib.crc32(payload) != checksum:
                    raise RuntimeError("视频缓存帧校验失败，请使用 --rebuild-cache")
                expected += 1
                yield unpack_tiles(payload, self.slots)
            if expected != end:
                raise RuntimeError("视频缓存缺少帧，请使用 --rebuild-cache")
        except sqlite3.Error as exc:
            raise RuntimeError("视频缓存读取失败，请使用 --rebuild-cache") from exc
        finally:
            cursor.close()


def expected_slots(options: VideoOptions) -> tuple[int, ...]:
    if options.key is None:
        return tuple(slot for row in M18V25E.image_slots for slot in row)
    row, column = divmod(options.key - 1, 5)
    return (M18V25E.image_slots[row][column],)


def load_cache(path: Path, identity: dict, options: VideoOptions) -> FrameCache | None:
    if not path.is_file():
        return None
    connection = None
    try:
        connection = connect_readonly(path)
        metadata = dict(connection.execute("SELECT name, value FROM metadata"))
        if metadata.get("identity") != identity_json(identity):
            return None
        count = int(metadata["count"])
        actual, first, last = connection.execute(
            "SELECT count(*), min(idx), max(idx) FROM frames"
        ).fetchone()
        if count <= 0 or (actual, first, last) != (count, 0, count - 1):
            return None
        return FrameCache(path, options.fps, count, expected_slots(options))
    except (OSError, sqlite3.Error, ValueError, KeyError):
        return None
    finally:
        if connection is not None:
            connection.close()


def prepare_cache(
    path: Path,
    options: VideoOptions,
    duration: float,
    *,
    directory: Path = DEFAULT_CACHE_DIR,
    force=False,
    report=print,
) -> FrameCache:
    identity = cache_identity(path, options)
    cache_key = hashlib.sha256(identity_json(identity).encode()).hexdigest()
    destination = directory / f"{cache_key}.sqlite3"
    if not force:
        existing = load_cache(destination, identity, options)
        if existing is not None:
            report(
                f"复用视频缓存：{existing.count} 帧，{destination.stat().st_size / 1024**2:.1f} MiB"
            )
            return existing

    directory.mkdir(parents=True, exist_ok=True)
    report("首次生成视频缓存…" if not force else "重新生成视频缓存…")
    source_options = replace(options, start=0, seconds=None)
    with tempfile.TemporaryDirectory(prefix=".building-", dir=directory) as temporary:
        staging = Path(temporary) / "frames.sqlite3"
        try:
            connection = sqlite3.connect(staging)
        except sqlite3.Error as exc:
            raise RuntimeError(f"无法创建视频缓存：{exc}；可使用 --no-cache 实时播放") from exc
        try:
            connection.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE frames (idx INTEGER PRIMARY KEY, payload BLOB NOT NULL, checksum INTEGER NOT NULL)"
            )
            count = 0
            last_report = time.monotonic()
            with decode_frames(path, source_options) as frames:
                for frame in frames:
                    payload = pack_tiles(jpeg_tiles(frame, source_options))
                    connection.execute(
                        "INSERT INTO frames VALUES (?, ?, ?)", (count, payload, zlib.crc32(payload))
                    )
                    count += 1
                    if count % 100 == 0:
                        connection.commit()
                    now = time.monotonic()
                    if now - last_report >= 2:
                        report(
                            f"缓存进度：{min(99, count / (duration * options.fps) * 100):.0f}%（{count} 帧）"
                        )
                        last_report = now
            if not count:
                raise RuntimeError("没有可缓存的视频帧")
            if cache_identity(path, options) != identity:
                raise RuntimeError("生成缓存期间源视频发生变化，请重试")
            connection.executemany(
                "INSERT INTO metadata VALUES (?, ?)",
                [("identity", identity_json(identity)), ("count", str(count))],
            )
            connection.commit()
        except sqlite3.Error as exc:
            raise RuntimeError(f"视频缓存写入失败：{exc}；可使用 --no-cache 实时播放") from exc
        finally:
            connection.close()
        # Readers only see complete caches. Interrupted rebuilds retain the old file.
        os.replace(staging, destination)
    report(f"视频缓存已生成：{count} 帧，{destination.stat().st_size / 1024**2:.1f} MiB")
    return FrameCache(destination, options.fps, count, expected_slots(options))
