"""Load a local script once, retaining its import path for lazy sibling imports."""

import importlib.util
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from .app import App


@contextmanager
def load_script(path: Path, args: list[str]):
    path = path.expanduser().resolve(strict=True)
    if path.suffix != ".py" or not path.is_file():
        raise ValueError("应用脚本必须是 .py 文件")
    name = f"_decklet_app_{uuid.uuid4().hex}"
    # Give each app its own package so `from .cli import ...` works without
    # colliding with helper modules belonging to another application.
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)]
    )
    module = importlib.util.module_from_spec(spec)
    previous_path, previous_argv = sys.path[:], sys.argv
    previous_modules = set(sys.modules)
    sys.path.insert(0, str(path.parent))
    sys.argv = [str(path), *args]
    sys.modules[name] = module
    try:
        # Read source directly: editing twice in one second must not reuse stale bytecode.
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        app = getattr(module, "app", None)
        if not isinstance(app, App):
            raise TypeError(f"{path} 必须导出 app = App()")
        yield app, path
    finally:
        sys.argv = previous_argv
        sys.path[:] = previous_path
        sys.modules.pop(name, None)
        for imported in set(sys.modules) - previous_modules:
            filename = getattr(sys.modules.get(imported), "__file__", None)
            if filename and Path(filename).resolve().is_relative_to(path.parent):
                sys.modules.pop(imported, None)
