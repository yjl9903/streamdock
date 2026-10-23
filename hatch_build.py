"""Bundle only the reviewed native library for the wheel's target platform."""

import json
import platform
import runpy
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class SDKBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        sync = runpy.run_path(str(root / "scripts/update_sdk.py"))
        sdk = root / "src/streamdock/_vendor/mirabox"
        config_path = root / "scripts/sdk/config.json"
        sync["verify"](sdk, config_path)
        if self.target_name != "wheel":
            return
        config = json.loads(config_path.read_text())
        system, machine = platform.system(), platform.machine().lower()
        try:
            target = config["platforms"][system][machine]
        except KeyError:
            raise RuntimeError(f"No reviewed SDK binary for {system}/{machine}") from None
        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{target['tag']}"
        if version != "editable":
            relative = f"streamdock/_vendor/mirabox/Transport/TransportDLL/{target['library']}"
            build_data["force_include"][str(root / "src" / relative)] = relative
