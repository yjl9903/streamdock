"""Reproduce the private SDK from a reviewed upstream commit and local patches.

Only the Python standard library and Git (for patch application) are required.
No upstream code is executed. Installation and ordinary builds never download SDKs.
"""

import argparse
import io
import json
import re
import subprocess
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts/sdk/config.json"
DESTINATION = ROOT / "src/streamdock/_vendor/mirabox"


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def runtime_files(directory: Path) -> dict[str, bytes]:
    result = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError(f"Unexpected symlink: {path}")
        if path.is_file() and str(relative) != "SOURCE.json":
            result[relative.as_posix()] = path.read_bytes()
    return result


def verify(directory: Path, config_path: Path, *, check_inputs: bool = True):
    record = json.loads((directory / "SOURCE.json").read_text())
    actual = {name: digest(data) for name, data in runtime_files(directory).items()}
    if actual != record["vendored_sha256"]:
        changed = sorted(
            name
            for name in actual.keys() | record["vendored_sha256"].keys()
            if actual.get(name) != record["vendored_sha256"].get(name)
        )
        raise ValueError(f"Vendored SDK differs from recorded files: {', '.join(changed)}")
    if check_inputs:
        config = json.loads(config_path.read_text())
        inputs = {"config.json": digest(config_path.read_bytes())}
        inputs.update(
            {name: digest((config_path.parent / name).read_bytes()) for name in config["patches"]}
        )
        if inputs != record["inputs_sha256"]:
            raise ValueError("SDK configuration/patches changed; regenerate with update_sdk.py")
    return record


def read_upstream(revision: str, config: dict, source: Path | None) -> dict[str, bytes]:
    """Read only allowlisted regular files; never extract archive paths to disk."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("--revision must be a full, lowercase 40-character commit SHA")
    if source is not None:
        actual = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", f"{revision}^{{commit}}"],
            text=True,
        ).strip()
        if actual != revision:
            raise ValueError("Local source does not contain the requested commit")
        # Git archive reads committed blobs, ignoring local modifications/untracked files.
        data = subprocess.check_output(["git", "-C", str(source), "archive", revision])
        prefix = ""
    else:
        url = f"{config['repository']}/archive/{revision}.tar.gz"
        print(f"Downloading {url}", flush=True)
        with urlopen(url, timeout=60) as response:
            data = response.read()
        prefix = f"{config['repository'].rsplit('/', 1)[1]}-{revision}/"
    wanted = {f"{config['source_directory']}/{name}": name for name in config["files"]}
    wanted[config["license"]] = "LICENSE"
    for name in wanted.values():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"Unsafe SDK file path: {name}")
    result = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive:
            if not member.name.startswith(prefix):
                continue
            name = member.name[len(prefix) :]
            if name not in wanted:
                continue
            if not member.isfile() or wanted[name] in result:
                raise ValueError(f"SDK archive has a duplicate or non-regular file: {name}")
            result[wanted[name]] = archive.extractfile(member).read()
    missing = sorted(set(wanted.values()) - result.keys())
    if missing:
        raise ValueError(f"Upstream removed/renamed required SDK files: {', '.join(missing)}")
    return result


def prepare(destination: Path, revision: str, config_path: Path, source: Path | None):
    config = json.loads(config_path.read_text())
    files = read_upstream(revision, config, source)
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    inputs = {"config.json": digest(config_path.read_bytes())}
    for name in config["patches"]:
        patch = (config_path.parent / name).resolve()
        inputs[name] = digest(patch.read_bytes())
        for options in (["--check"], []):
            subprocess.run(
                ["git", "apply", "--whitespace=nowarn", *options, str(patch)],
                cwd=destination,
                check=True,
                capture_output=True,
                text=True,
            )
    # Fail if an upgrade introduces absolute imports that the patch did not cover.
    for path in destination.rglob("*.py"):
        compile(path.read_bytes(), str(path.relative_to(destination)), "exec")
        if re.search(
            r"^\s*(?:from\s+StreamDock(?:\.|\s)|import\s+StreamDock\b)",
            path.read_text(),
            re.MULTILINE,
        ):
            raise ValueError(f"Unpatched public SDK import: {path.relative_to(destination)}")
    record = {
        "schema": 1,
        "repository": config["repository"],
        "revision": revision,
        "upstream_sha256": {name: digest(data) for name, data in sorted(files.items())},
        "inputs_sha256": inputs,
        "vendored_sha256": {
            name: digest(data) for name, data in runtime_files(destination).items()
        },
    }
    (destination / "SOURCE.json").write_bytes(json_bytes(record))


def synchronize(
    revision: str,
    config_path: Path = CONFIG,
    destination: Path = DESTINATION,
    source: Path | None = None,
    *,
    check: bool = False,
):
    if destination.exists():
        # Do not silently overwrite hand edits. Patch/config changes are allowed inputs.
        verify(destination, config_path, check_inputs=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sdk-sync-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "next"
        staging.mkdir()
        prepare(staging, revision, config_path, source)
        verify(staging, config_path)
        if check:
            if (
                not destination.exists()
                or runtime_files(staging) != runtime_files(destination)
                or (staging / "SOURCE.json").read_bytes()
                != (destination / "SOURCE.json").read_bytes()
            ):
                raise ValueError(
                    "Vendored SDK is not reproducible from the selected commit and patches"
                )
            return
        previous = Path(temporary) / "previous"
        if destination.exists():
            destination.rename(previous)
        try:
            staging.rename(destination)
        except BaseException:
            if previous.exists():
                previous.rename(destination)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="reviewed, full upstream commit SHA")
    parser.add_argument(
        "--source", type=Path, help="optional local upstream Git checkout (committed blobs only)"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--verify", action="store_true", help="offline check of bundled file and patch hashes"
    )
    modes.add_argument(
        "--check", action="store_true", help="reproduce and compare without updating"
    )
    args = parser.parse_args(argv)
    if args.verify and (args.revision or args.source):
        parser.error("--verify does not accept --revision or --source")
    try:
        if args.verify:
            record = verify(DESTINATION, CONFIG)
            print(f"Verified SDK {record['revision']}")
        else:
            revision = args.revision
            if not revision and args.check:
                revision = json.loads((DESTINATION / "SOURCE.json").read_text())["revision"]
            if not revision:
                parser.error(
                    "updates require --revision; use --check to reproduce the recorded commit"
                )
            synchronize(revision, source=args.source, check=args.check)
            print(f"{'Reproduced' if args.check else 'Updated'} SDK {revision}")
    except (
        OSError,
        ValueError,
        KeyError,
        SyntaxError,
        tarfile.TarError,
        subprocess.CalledProcessError,
    ) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        parser.exit(1, f"SDK sync failed: {detail}\n")


if __name__ == "__main__":
    main()
