from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release as builder
import setup as installer


class PackagingTests(unittest.TestCase):
    def test_zip_contains_only_allowlisted_source(self):
        with tempfile.TemporaryDirectory(prefix="claude-zh-test-", dir=ROOT) as directory:
            destination = builder.release(directory)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(set(archive.namelist()), {"claude-desktop-zh-windows/" + name for name in builder.FILES})
                self.assertFalse(any("不上传" in name or name.endswith((".exe", ".asar", ".dll", ".log")) for name in archive.namelist()))
            self.assertTrue(destination.with_suffix(".zip.sha256").is_file())

    def test_export_rejects_unexpected_existing_file(self):
        with tempfile.TemporaryDirectory(prefix="claude-zh-test-", dir=ROOT) as directory:
            exported = Path(directory) / "github-source"
            exported.mkdir()
            (exported / "private.json").write_text("{}", "utf-8")
            with self.assertRaisesRegex(RuntimeError, "白名单"):
                builder.release(directory)


class PackageSelectionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"version": "3.1623.4.0", "packageFamily": "Claude_pzs8sxrjxfjjc"}
        self.current = {"Version": "3.1623.4.0", "PackageFamilyName": "Claude_pzs8sxrjxfjjc", "InstallLocation": str(ROOT / "example-package")}
        self.old = {"Version": "3.1623.3.0", "PackageFamilyName": "AnthropicPBC.Claude_fnn82j28hfe8t", "InstallLocation": str(ROOT / "old-package")}

    def test_selects_supported_package_without_removing_old_service_owner(self):
        packages = [self.old, self.current]
        self.assertEqual(installer.resolve_app(packages, self.manifest), (ROOT / "example-package/app").resolve())
        self.assertEqual(len(packages), 2)

    def test_unknown_new_version_is_refused(self):
        package = dict(self.current, Version="3.1623.5.0")
        with self.assertRaisesRegex(RuntimeError, "未知版本"):
            installer.resolve_app([package], self.manifest)

    def test_arbitrary_app_path_cannot_bypass_registration(self):
        with self.assertRaises(RuntimeError):
            installer.resolve_app([self.current], self.manifest, ROOT / "unregistered")

    def test_different_elevated_user_stops_before_discovery(self):
        arguments = installer.argparse.Namespace(expected_sid="original-user")
        with mock.patch.object(installer, "current_sid", return_value="another-user"), mock.patch.object(installer, "get_packages") as discover:
            with self.assertRaisesRegex(RuntimeError, "账户"):
                installer.execute(arguments)
            discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
