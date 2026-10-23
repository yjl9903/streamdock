"""Check wheel contents against the vendored SDK manifest, without loading USB code."""

import argparse
import json
import platform
import zipfile
from hashlib import sha256
from pathlib import Path


def check(wheel: Path):
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "scripts/sdk/config.json").read_text())
    target = config["platforms"][platform.system()][platform.machine().lower()]
    if not wheel.name.endswith(f"-py3-none-{target['tag']}.whl"):
        raise ValueError(f"Unexpected wheel platform: {wheel.name}")
    prefix = "streamdock/_vendor/mirabox/"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Wheel contains duplicate paths")
        if any(name.startswith("StreamDock/") for name in names):
            raise ValueError("Wheel contains a conflicting public SDK namespace")
        record = json.loads(archive.read(prefix + "SOURCE.json"))
        local_record = json.loads((root / "src" / prefix / "SOURCE.json").read_text())
        if record != local_record:
            raise ValueError("Wheel contains stale SDK provenance")
        expected = {
            prefix + name: digest
            for name, digest in record["vendored_sha256"].items()
            if not name.startswith("Transport/TransportDLL/")
            or name.endswith("/" + target["library"])
        }
        actual = {
            name: sha256(archive.read(name)).hexdigest()
            for name in names
            if name.startswith(prefix) and name != prefix + "SOURCE.json"
        }
        if expected != actual:
            raise ValueError("Wheel SDK files do not match the recorded hashes/platform")
        (metadata,) = [name for name in names if name.endswith(".dist-info/WHEEL")]
        if "Root-Is-Purelib: false" not in archive.read(metadata).decode():
            raise ValueError("Native SDK wheel incorrectly declares itself pure Python")
    print(f"Verified {wheel.name}: private SDK, license, provenance, platform library")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    check(parser.parse_args().wheel)
