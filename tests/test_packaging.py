import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import apd


ROOT = Path(apd.__file__).resolve().parent


class PackagingTests(unittest.TestCase):
    def test_versions_are_consistent(self):
        with (ROOT / "pyproject.toml").open("rb") as stream:
            self.assertEqual(tomllib.load(stream)["project"]["version"], apd.VERSION)
        for path in (ROOT / "plugin.json", ROOT / ".codex-plugin" / "plugin.json"):
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], apd.VERSION)
        self.assertEqual(apd.VERSION, "0.3.2")

    def test_wheel_installed_qml_from_an_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wheels = root / "wheels"
            installed = root / "installed"
            build = subprocess.run([sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-cache-dir",
                                    "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheels), str(ROOT)],
                                   cwd=root, capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            wheel = next(wheels.glob(f"apd-{apd.VERSION}-*.whl"))
            install = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
                                      "--no-deps", "--target", str(installed), str(wheel)],
                                     cwd=root, capture_output=True, text=True, timeout=60)
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            code = '''
from pathlib import Path
import importlib.metadata
from PySide6.QtGui import QGuiApplication
import apd
import apd_gui
assert apd.VERSION == importlib.metadata.version("apd") == "0.3.2"
assert Path(apd_gui.__file__).is_relative_to(Path.cwd() / "installed"), apd_gui.__file__
app = QGuiApplication([])
with apd_gui.qml_resource() as path:
    assert path.is_relative_to(Path.cwd() / "installed"), path
    assert path.is_file(), path
    engine, monitor = apd_gui.create_engine(Path.cwd(), path)
    assert engine.rootObjects(), "Installed QML failed to load"
    engine.rootObjects()[0].close()
print("INSTALLED_QML=PASS")
'''
            env = dict(os.environ, PYTHONPATH=str(installed), QT_QPA_PLATFORM="offscreen", QSG_RHI_BACKEND="software")
            load = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(load.returncode, 0, load.stdout + load.stderr)
            self.assertIn("INSTALLED_QML=PASS", load.stdout)


if __name__ == "__main__":
    unittest.main()
