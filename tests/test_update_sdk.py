import difflib
import importlib.util
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "update_sdk",
    Path(__file__).resolve().parents[1] / "scripts/update_sdk.py",
)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SDKSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "upstream"
        self.source.mkdir()
        self.git("init", "-q")
        self.package = self.source / "Python-SDK/src/StreamDock"
        self.package.mkdir(parents=True)
        self.before = "from StreamDock.features import value\n"
        (self.package / "__init__.py").write_text(self.before)
        (self.package / "obsolete.py").write_text("value = 1\n")
        (self.source / "Python-SDK/LICENSE").write_text("Upstream test license\n")
        self.revision = self.commit()
        self.config_path = self.root / "config.json"
        self.config = {
            "repository": "https://github.com/MiraboxSpace/StreamDock-Device-SDK",
            "source_directory": "Python-SDK/src/StreamDock",
            "files": ["__init__.py", "obsolete.py"],
            "license": "Python-SDK/LICENSE",
            "patches": ["namespace.patch"],
        }
        self.write_config()
        self.patch_path = self.root / "namespace.patch"
        self.patch_path.write_text(
            "".join(
                difflib.unified_diff(
                    self.before.splitlines(True),
                    ["from streamdock._vendor.mirabox.features import value\n"],
                    fromfile="a/__init__.py",
                    tofile="b/__init__.py",
                )
            )
        )
        self.destination = self.root / "bundled"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args], text=True).strip()

    def commit(self):
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "test: upstream fixture",
        )
        return self.git("rev-parse", "HEAD")

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def update(self, revision=None, **kwargs):
        sync.synchronize(
            revision or self.revision, self.config_path, self.destination, self.source, **kwargs
        )

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.destination.iterdir() if p.is_file()}

    def test_repeat_sync_is_identical_and_records_upstream_and_patched_hashes(self):
        self.update()
        before = self.snapshot()
        self.update()
        self.update(check=True)
        self.assertEqual(self.snapshot(), before)
        record = sync.verify(self.destination, self.config_path)
        self.assertEqual(record["revision"], self.revision)
        self.assertEqual(
            record["upstream_sha256"]["__init__.py"], sync.digest(self.before.encode())
        )
        self.assertNotEqual(
            record["upstream_sha256"]["__init__.py"], record["vendored_sha256"]["__init__.py"]
        )
        self.assertEqual((self.destination / "LICENSE").read_text(), "Upstream test license\n")

    def test_local_source_reads_commit_instead_of_modified_working_tree(self):
        (self.package / "__init__.py").write_text("uncommitted change\n")
        self.update()
        self.assertIn("streamdock._vendor.mirabox", (self.destination / "__init__.py").read_text())

    def test_removed_files_are_removed_after_allowlist_is_updated(self):
        self.update()
        (self.package / "obsolete.py").unlink()
        revision = self.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "removed/renamed"):
            self.update(revision)
        self.assertEqual(self.snapshot(), before)
        self.config["files"].remove("obsolete.py")
        self.write_config()
        self.update(revision)
        self.assertFalse((self.destination / "obsolete.py").exists())

    def test_patch_failure_preserves_previous_sdk(self):
        self.update()
        before = self.snapshot()
        (self.package / "__init__.py").write_text("from StreamDock.changed import value\n")
        revision = self.commit()
        with self.assertRaises(subprocess.CalledProcessError):
            self.update(revision)
        self.assertEqual(self.snapshot(), before)

    def test_hand_edits_are_not_overwritten(self):
        self.update()
        (self.destination / "obsolete.py").write_text("local edit\n")
        with self.assertRaisesRegex(ValueError, "differs from recorded"):
            self.update()
        self.assertEqual((self.destination / "obsolete.py").read_text(), "local edit\n")

    def test_check_reports_new_version_without_replacing_current_sdk(self):
        self.update()
        before = self.snapshot()
        (self.package / "obsolete.py").write_text("value = 2\n")
        revision = self.commit()
        with self.assertRaisesRegex(ValueError, "not reproducible"):
            self.update(revision, check=True)
        self.assertEqual(self.snapshot(), before)

    def test_failed_replacement_restores_previous_directory(self):
        self.update()
        before = self.snapshot()
        rename = Path.rename

        def fail_install(path, target):
            if path.name == "next":
                raise OSError("simulated rename failure")
            return rename(path, target)

        with patch.object(Path, "rename", fail_install):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.update()
        self.assertEqual(self.snapshot(), before)

    def test_offline_verification_detects_patch_changes_and_extra_files(self):
        self.update()
        original = self.patch_path.read_bytes()
        self.patch_path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "patches changed"):
            sync.verify(self.destination, self.config_path)
        self.patch_path.write_bytes(original)
        (self.destination / "extra.py").touch()
        with self.assertRaisesRegex(ValueError, "extra.py"):
            sync.verify(self.destination, self.config_path)

    def test_branch_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "full.*commit SHA"):
            self.update("main")
        self.assertFalse(self.destination.exists())

    def test_new_unpatched_import_is_rejected(self):
        self.update()
        before = self.snapshot()
        (self.package / "obsolete.py").write_text("import StreamDock\n")
        revision = self.commit()
        with self.assertRaisesRegex(ValueError, "Unpatched"):
            self.update(revision)
        self.assertEqual(self.snapshot(), before)

    def test_download_and_local_git_archive_produce_identical_files(self):
        raw = subprocess.check_output(
            [
                "git",
                "-C",
                str(self.source),
                "archive",
                f"--prefix=StreamDock-Device-SDK-{self.revision}/",
                self.revision,
            ]
        )
        with patch.object(sync, "urlopen", return_value=io.BytesIO(raw)):
            downloaded = sync.read_upstream(self.revision, self.config, None)
        self.assertEqual(downloaded, sync.read_upstream(self.revision, self.config, self.source))

    def test_archive_symlinks_are_rejected_without_extracting(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            entry = tarfile.TarInfo(
                f"StreamDock-Device-SDK-{self.revision}/Python-SDK/src/StreamDock/__init__.py",
            )
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            archive.addfile(entry)
        with patch.object(sync, "urlopen", return_value=io.BytesIO(buffer.getvalue())):
            with self.assertRaisesRegex(ValueError, "non-regular"):
                sync.read_upstream(self.revision, self.config, None)


if __name__ == "__main__":
    unittest.main()
