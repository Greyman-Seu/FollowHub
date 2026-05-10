import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skill" / "rcli" / "scripts" / "rcli.py"


def load_rcli_module():
    assert SCRIPT_PATH.exists(), f"missing script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_rcli", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RcliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_rcli_module()

    def test_default_install_bin_dir_uses_local_user_bin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"HOME": tmpdir}, clear=False):
                bin_dir = self.module.default_install_bin_dir()
        self.assertEqual(bin_dir, Path(tmpdir) / ".local" / "bin")

    def test_find_rclone_binary_checks_local_install_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            local_bin = Path(tmpdir) / ".local" / "bin"
            local_bin.mkdir(parents=True, exist_ok=True)
            binary = local_bin / "rclone"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)

            with mock.patch.dict(os.environ, {"HOME": tmpdir}, clear=False):
                with mock.patch.object(self.module.shutil, "which", return_value=None):
                    found = self.module.find_rclone_binary()

        self.assertEqual(found, binary)

    def test_install_help_text_prefers_non_root_install(self):
        text = self.module.install_help_text()
        self.assertIn("~/.local/bin", text)
        self.assertIn("python3", text)
        self.assertNotIn("sudo apt-get", text)
        self.assertNotIn("sudo bash", text)


if __name__ == "__main__":
    unittest.main()
