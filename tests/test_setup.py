from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import claude_zh as pack


class ResourceTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="claude-zh-test-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "app"
        self.config = self.root / "user/config.json"
        self.storage = self.root / "state"
        self.catalog = self.root / "pack/zh-CN.json"
        self.catalog.parent.mkdir(parents=True)
        self.catalog.write_text('{"hello":"你好 {name}"}', "utf-8")
        self.config.parent.mkdir()
        self.config.write_text('{"locale":"en-US","apiKey":"sample-secret","model":"model-a"}', "utf-8")
        self.bundle = "resources/bundle.js"
        self.originals = {
            "claude.exe": b"official-executable",
            "resources/app.asar": b"official-asar",
            "resources/en-US.json": b'{"hello":"Hello {name}"}',
            self.bundle: ("const languages=" + pack.LANGUAGES + ";const fallback=" + pack.LANGUAGES + ";").encode(),
        }
        for relative, content in self.originals.items():
            target = self.app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.manifest = {
            "version": "3.1623.4.0", "bundlePath": self.bundle,
            "sourceFiles": {relative: pack.sha256(self.app / relative) for relative in self.originals},
            "catalogs": {"desktop": {
                "sourcePath": "en-US.json", "path": "zh-CN.json", "entries": 1,
                "sha256": pack.sha256(self.catalog),
            }},
        }

    def install(self):
        return pack.install_resources(self.app, self.config, self.storage, self.manifest, self.catalog.parent)

    def restore(self, backup):
        return pack.restore_resources(self.app, self.storage, backup, self.manifest, self.catalog.parent)

    def test_install_then_restore_keeps_core_and_new_settings(self):
        backup = self.install()
        self.assertEqual(pack.read_json(self.config)["locale"], "zh-CN")
        self.assertEqual((self.app / "resources/zh-CN.json").read_bytes(), self.catalog.read_bytes())
        for relative in ("claude.exe", "resources/app.asar"):
            self.assertEqual((self.app / relative).read_bytes(), self.originals[relative])
        current = pack.read_json(self.config)
        current["apiKey"] = "new-secret"
        current["model"] = "model-b"
        pack.write_json(self.config, current)
        self.restore(backup)
        self.assertEqual(pack.read_json(self.config), {"locale": "en-US", "apiKey": "new-secret", "model": "model-b"})
        self.assertFalse((self.app / "resources/zh-CN.json").exists())
        self.assertEqual((self.app / self.bundle).read_bytes(), self.originals[self.bundle])

    def test_write_failure_rolls_back_every_file_and_config(self):
        original = self.config.read_bytes()
        writer = pack.write_resource
        calls = 0

        def fail_once(path, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PermissionError("simulated failure")
            return writer(path, content)

        with mock.patch.object(pack, "write_resource", side_effect=fail_once):
            with self.assertRaises(PermissionError):
                self.install()
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual((self.app / self.bundle).read_bytes(), self.originals[self.bundle])
        self.assertFalse((self.app / "resources/zh-CN.json").exists())

    def test_permission_probe_failure_writes_no_backup_or_config(self):
        before = self.config.read_bytes()
        with mock.patch.object(pack, "probe_writes", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.install()
        self.assertFalse(self.storage.exists())
        self.assertEqual(self.config.read_bytes(), before)

    def test_updated_core_stops_before_any_write(self):
        (self.app / "claude.exe").write_bytes(b"new-version")
        with self.assertRaisesRegex(RuntimeError, "版本|源文件"):
            self.install()
        self.assertFalse(self.storage.exists())

    def test_reinstall_keeps_original_restore_point(self):
        backup = self.install()
        self.assertEqual(self.install(), backup)
        self.restore(backup)
        self.assertEqual(pack.read_json(self.config)["locale"], "en-US")

    def test_restore_rejects_damaged_backup_before_writes(self):
        backup = self.install()
        (backup / "files" / self.bundle).write_bytes(b"damaged")
        before = (self.app / self.bundle).read_bytes()
        with self.assertRaisesRegex(RuntimeError, "备份"):
            self.restore(backup)
        self.assertEqual((self.app / self.bundle).read_bytes(), before)
        self.assertEqual(pack.read_json(self.config)["locale"], "zh-CN")

    def test_restore_rejects_conflicting_resource(self):
        backup = self.install()
        (self.app / self.bundle).write_bytes(b"other-patch")
        with self.assertRaisesRegex(RuntimeError, "变化|冲突|源文件"):
            self.restore(backup)
        self.assertEqual((self.app / self.bundle).read_bytes(), b"other-patch")

    def test_restore_removes_locale_if_original_had_none(self):
        pack.write_json(self.config, {"model": "model-a"})
        backup = self.install()
        self.restore(backup)
        self.assertEqual(pack.read_json(self.config), {"model": "model-a"})

    def test_restore_rejects_paths_outside_resource_allowlist(self):
        backup = self.install()
        state = pack.read_json(backup / "state.json")
        state["files"]["../outside"] = {"original": None, "installed": "fake"}
        pack.write_json(backup / "state.json", state)
        with self.assertRaisesRegex(RuntimeError, "清单|路径"):
            self.restore(backup)

    def test_restore_recovers_partial_bundle_after_interrupted_install(self):
        backup = self.install()
        state = pack.read_json(backup / "state.json")
        state["phase"] = "prepared"
        pack.write_json(backup / "state.json", state)
        (self.app / self.bundle).write_bytes(b"partial-write")
        self.restore(backup)
        self.assertEqual((self.app / self.bundle).read_bytes(), self.originals[self.bundle])
        self.assertEqual(pack.read_json(self.config)["locale"], "en-US")

    def test_legacy_install_record_is_preserved_without_reusing_migration(self):
        legacy = {"target": "old-copy", "backup": "old-migration"}
        pack.write_json(self.storage / "last-install.json", legacy)
        backup = self.install()
        self.assertEqual(pack.read_json(backup / "previous-install-record.json"), legacy)
        self.restore(backup)
        self.assertEqual(pack.read_json(self.config)["locale"], "en-US")


if __name__ == "__main__":
    unittest.main()
