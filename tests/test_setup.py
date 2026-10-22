import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
specification = importlib.util.spec_from_file_location("installer_under_test", ROOT / "setup.py")
installer = importlib.util.module_from_spec(specification)
specification.loader.exec_module(installer)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="claude-zh-test-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.local = self.root / "用户 data"
        self.local.mkdir()
        self.config = self.local / "Claude-3p/config.json"
        self.config.parent.mkdir()
        self.original = {"locale": "en-US", "sampleSetting": {"retained": True}}
        installer.pack.write_json(self.config, self.original)
        self.target = self.local / "Programs/Claude"
        self.target.mkdir(parents=True)
        (self.target / "claude.exe").write_bytes(b"fixture-core")
        self.manifest = {"installedFiles": {"claude.exe": installer.pack.sha256(self.target / "claude.exe")}}
        self.package = {"PackageFullName": installer.PACKAGE_VERSION, "PackageFamilyName": installer.PACKAGE_FAMILY, "InstallLocation": str(self.root / "store")}
        self.events = []
        for target, replacement in [
            ("local_path", lambda relative: self.local / relative),
            ("get_package", lambda: self.package),
            ("data_roots", lambda config: {"local-Claude-3p": config.parent}),
            ("install_shortcut", lambda target, backup: self.events.append("shortcut")),
        ]:
            patcher = mock.patch.object(installer, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, replacement in [
            ("check_pack", lambda: self.manifest),
            ("config_path", lambda supplied: self.config),
            ("check_no_processes", lambda: None),
        ]:
            patcher = mock.patch.object(installer.pack, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(installer.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(10**12, 0, 10**12))
        patcher.start()
        self.addCleanup(patcher.stop)

    def arguments(self, check=False):
        return argparse.Namespace(config=None, app=None, check=check)

    def remove(self, package):
        pending = installer.pack.read_json(self.local / "ClaudeZhPatch/pending.json")
        backup = Path(pending["backup"])
        state = installer.pack.read_json(backup / "migration.json")
        self.assertEqual(state["phase"], "prepared")
        installer.verify_backups(backup, state)
        self.assertTrue(self.target.is_dir())
        self.events.append("remove")
        self.package = None

    def install_confirmed(self):
        with mock.patch("builtins.input", return_value="REPLACE"), mock.patch.object(installer, "remove_package", self.remove):
            installer.install(self.arguments())

    def test_cancel_writes_nothing(self):
        with mock.patch("builtins.input", return_value="no"):
            installer.install(self.arguments())
        self.assertFalse((self.local / "ClaudeZhPatch").exists())
        self.assertEqual(installer.pack.read_json(self.config), self.original)

    def test_read_only_check_does_not_prompt_or_write(self):
        with mock.patch("builtins.input", side_effect=AssertionError("不应询问")):
            installer.install(self.arguments(check=True))
        self.assertFalse((self.local / "ClaudeZhPatch").exists())

    def test_backup_precedes_removal_and_preserves_settings(self):
        self.install_confirmed()
        self.assertEqual(self.events, ["remove", "shortcut"])
        expected = {**self.original, "locale": "zh-CN"}
        self.assertEqual(installer.pack.read_json(self.config), expected)
        info = installer.pack.read_json(self.local / "ClaudeZhPatch/last-install.json")
        backup = Path(info["backup"])
        self.assertEqual(installer.pack.read_json(backup / "data/local-Claude-3p/config.json"), self.original)
        self.assertEqual(installer.pack.read_json(backup / "migration.json")["phase"], "complete")

    def test_backup_failure_never_removes_package(self):
        with mock.patch("builtins.input", return_value="REPLACE"), mock.patch.object(installer, "backup_root", side_effect=OSError("locked")), mock.patch.object(installer, "remove_package") as remove:
            with self.assertRaises(OSError):
                installer.install(self.arguments())
            remove.assert_not_called()

    def test_changed_data_never_removes_package(self):
        with mock.patch("builtins.input", return_value="REPLACE"), mock.patch.object(installer, "verify_live_data", side_effect=RuntimeError("changed")), mock.patch.object(installer, "remove_package") as remove:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                installer.install(self.arguments())
            remove.assert_not_called()

    def test_running_application_never_writes_data(self):
        with mock.patch.object(installer.pack, "check_no_processes", side_effect=RuntimeError("running")):
            with self.assertRaisesRegex(RuntimeError, "running"):
                installer.install(self.arguments())
        self.assertFalse((self.local / "ClaudeZhPatch").exists())

    def test_wrong_target_is_not_overwritten(self):
        (self.target / "claude.exe").write_bytes(b"different-version")
        with self.assertRaises(RuntimeError):
            installer.install(self.arguments())
        self.assertFalse((self.local / "ClaudeZhPatch").exists())

    def test_backup_directory_cannot_be_inside_data_root(self):
        with mock.patch.object(installer, "data_roots", return_value={"custom-config": self.local}):
            with self.assertRaisesRegex(RuntimeError, "递归备份"):
                installer.install(self.arguments())
        self.assertFalse((self.local / "ClaudeZhPatch").exists())

    def test_missing_application_is_prepared_before_removal(self):
        shutil.rmtree(self.target)
        original = self.root / "original"
        original.mkdir()
        (original / "claude.exe").write_bytes(b"fixture-core")
        def create_copy(source, target, manifest):
            self.assertTrue((self.local / "ClaudeZhPatch/backups").is_dir())
            self.events.append("copy")
            shutil.copytree(source, target)
        with mock.patch.object(installer.pack, "find_app", return_value=original), mock.patch.object(installer.pack, "check_source"), mock.patch.object(installer.pack, "create_copy", create_copy):
            self.install_confirmed()
        self.assertEqual(self.events, ["copy", "remove", "shortcut"])

    def test_language_restore_preserves_new_settings(self):
        self.install_confirmed()
        installer.pack.write_json(self.config, {"locale": "zh-CN", "newSetting": 42})
        installer.restore_language()
        self.assertEqual(installer.pack.read_json(self.config), {"locale": "en-US", "newSetting": 42})

    def test_resume_after_uninstall_restores_missing_data(self):
        def remove_and_interrupt(package):
            self.remove(package)
            self.config.unlink()
            raise RuntimeError("模拟卸载后中断")
        with mock.patch("builtins.input", return_value="REPLACE"), mock.patch.object(installer, "remove_package", remove_and_interrupt):
            with self.assertRaisesRegex(RuntimeError, "中断"):
                installer.install(self.arguments())
        installer.resume()
        self.assertEqual(installer.pack.read_json(self.config), {**self.original, "locale": "zh-CN"})

    def test_resume_keeps_new_settings(self):
        with mock.patch("builtins.input", return_value="REPLACE"), mock.patch.object(installer, "remove_package", self.remove), mock.patch.object(installer, "install_shortcut", side_effect=RuntimeError("shortcut")):
            with self.assertRaisesRegex(RuntimeError, "shortcut"):
                installer.install(self.arguments())
        installer.pack.write_json(self.config, {"locale": "en-US", "newSetting": 42})
        installer.resume()
        self.assertEqual(installer.pack.read_json(self.config), {"locale": "zh-CN", "newSetting": 42})

    def test_corrupt_backup_blocks_resume(self):
        with mock.patch("builtins.input", return_value="REPLACE"), mock.patch.object(installer, "remove_package", self.remove), mock.patch.object(installer, "install_shortcut", side_effect=RuntimeError("shortcut")):
            with self.assertRaises(RuntimeError):
                installer.install(self.arguments())
        info = installer.pack.read_json(self.local / "ClaudeZhPatch/pending.json")
        (Path(info["backup"]) / "data/local-Claude-3p/config.json").write_text("corrupt", "utf-8")
        with self.assertRaisesRegex(RuntimeError, "备份损坏"):
            installer.resume()

    def test_repeated_install_keeps_data_and_does_not_uninstall(self):
        self.install_confirmed()
        self.events.clear()
        with mock.patch.object(installer, "remove_package", side_effect=AssertionError("不可卸载")):
            installer.install(self.arguments())
        self.assertEqual(self.events, ["shortcut"])
        self.assertEqual(installer.pack.read_json(self.config)["sampleSetting"], {"retained": True})


if __name__ == "__main__":
    unittest.main()
