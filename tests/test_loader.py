import asyncio
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from decklet.cli import main
from decklet.loader import load_script


class LoaderTests(unittest.TestCase):
    def test_sibling_imports_arguments_and_source_tracebacks_outside_cwd(self):
        before_path, before_argv, cwd = list(sys.path), sys.argv, Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unique_lazy_helper.py").write_text("value = 42\n")
            (root / "relative_helper.py").write_text("value = 43\n")
            script = root / "my app.py"
            script.write_text("""from decklet import App
import sys
app = App()
assert sys.argv[1:] == ['--city', 'Shanghai']
@app.on_start
async def start(ctx):
    from unique_lazy_helper import value
    from .relative_helper import value as relative_value
    assert value == 42
    assert relative_value == 43
""")
            with load_script(script, ["--city", "Shanghai"]) as (app, path):
                self.assertEqual(path, script.resolve())
                asyncio.run(app._handlers["start"][0](None))
            self.assertNotIn("unique_lazy_helper", sys.modules)
            script.write_text("raise ValueError('broken script')\n")
            with self.assertRaisesRegex(ValueError, "broken script"):
                with load_script(script, []):
                    pass
        self.assertEqual(sys.path, before_path)
        self.assertIs(sys.argv, before_argv)
        self.assertEqual(Path.cwd(), cwd)

    def test_invalid_script_fails_before_hardware_and_reports_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "bad.py"
            script.write_text("app = object()\n")
            error = io.StringIO()
            with patch("decklet.commands.run.Runtime", side_effect=AssertionError("USB")):
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(["run", str(script)]), 1)
            self.assertIn(str(script), error.getvalue())
            self.assertIn("app = App()", error.getvalue())

    def test_cli_passes_script_arguments_and_serial_separately(self):
        class FakeRuntime:
            def __init__(self, app, **kwargs):
                self.context = type("Context", (), {"stop": lambda self: None})()
                seen.update(kwargs)

            async def run(self):
                pass

        seen = {}
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "app.py"
            script.write_text("from decklet import App\napp = App()\n")
            with patch("decklet.commands.run.Runtime", FakeRuntime):
                self.assertEqual(
                    main(
                        ["run", "--serial", "dock", str(script), "--", "--serial", "script-option"]
                    ),
                    0,
                )
            self.assertEqual(seen["script_dir"], script.parent.resolve())
        self.assertEqual(seen["serial"], "dock")
        self.assertEqual(seen["args"], ["--serial", "script-option"])
