"""Offscreen pointer tests using the production card and a mock audio service.

Does not load PipeWire, touch session settings, or alter real playback/devices.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    runner = "/usr/lib/qt6/bin/qmltestrunner"
    if not Path(runner).is_file():
        runner = shutil.which("qmltestrunner6") or shutil.which("qmltestrunner-qt6") or runner
    if not Path(runner).is_file():
        print("SKIP volume pointer tests: Qt Quick Test is not installed.")
        return
    tests = Path(__file__).resolve().parent
    source = tests.parent / "desktop-island"
    with tempfile.TemporaryDirectory(prefix="island-volume-ui-") as temporary:
        root = Path(temporary)
        components, cases = root / "components", root / "cases"
        components.mkdir()
        cases.mkdir()
        for name in ("VolumeCard.qml", "Icon.qml", "IconButton.qml", "InkLabel.qml", "logic.js"):
            shutil.copyfile(source / name, components / name)
        shutil.copyfile(tests / "fixtures/VolumeState.qml", components / "DesktopState.qml")
        shutil.copyfile(tests / "fixtures/tst_volume.qml", cases / "tst_volume.qml")
        (components / "qmldir").write_text("singleton DesktopState 1.0 DesktopState.qml\n"
            "VolumeCard 1.0 VolumeCard.qml\nInkLabel 1.0 InkLabel.qml\n"
            "Icon 1.0 Icon.qml\nIconButton 1.0 IconButton.qml\n")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="",
                   QT_QUICK_CONTROLS_STYLE="Basic")
        subprocess.run([runner, "-input", str(cases)], env=env, check=True, timeout=20)


if __name__ == "__main__":
    main()
