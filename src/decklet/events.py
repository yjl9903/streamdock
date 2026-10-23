"""Stable input events independent of the bundled SDK."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class KeyEvent:
    key: int
    action: Literal["press", "release"]
    timestamp: float
