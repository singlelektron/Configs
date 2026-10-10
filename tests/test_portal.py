"""Keep the file chooser theme inside its portal process and Niri session."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "gtk_portal", Path(__file__).resolve().parents[1] / "config/xdg-desktop-portal/gtk-portal.py")
portal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(portal)


class GtkPortalTests(unittest.TestCase):
    def test_niri_adds_its_theme_without_discarding_inherited_environment(self):
        inherited = {"XDG_CURRENT_DESKTOP": "GNOME:niri", "XDG_DATA_DIRS": "/custom data:/usr/share",
                     "GTK_THEME": "Adwaita", "WAYLAND_DISPLAY": "wayland-1", "CUSTOM": "preserved"}
        with (mock.patch.dict(os.environ, inherited, clear=True),
              mock.patch.object(portal, "__file__", "/config with spaces/xdg-desktop-portal/gtk-portal.py"),
              mock.patch.object(portal.sys, "argv", ["gtk-portal.py", "--verbose"]),
              mock.patch.object(portal.os, "execv") as execute):
            portal.main()
            self.assertEqual(dict(os.environ), {**inherited, "GTK_THEME": "MoonlitPortal:dark",
                             "XDG_DATA_DIRS": "/config with spaces/xdg-desktop-portal/data:/custom data:/usr/share"})
            execute.assert_called_once_with(portal.PORTAL, [portal.PORTAL, "--verbose"])

    def test_niri_uses_standard_data_paths_when_none_are_inherited(self):
        with (mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "niri"}, clear=True),
              mock.patch.object(portal.os, "execv")):
            portal.main()
            self.assertEqual(os.environ["XDG_DATA_DIRS"],
                             str(Path(portal.__file__).absolute().parent / "data") + ":/usr/local/share:/usr/share")

    def test_other_sessions_keep_their_theme_environment(self):
        for inherited in ({"XDG_CURRENT_DESKTOP": "GNOME", "GTK_THEME": "Adwaita:dark",
                           "XDG_DATA_DIRS": "/gnome data:/usr/share"}, {},
                          {"XDG_CURRENT_DESKTOP": "nested-niri"}):
            with (self.subTest(environment=inherited), mock.patch.dict(os.environ, inherited, clear=True),
                  mock.patch.object(portal.sys, "argv", ["gtk-portal.py"]),
                  mock.patch.object(portal.os, "execv") as execute):
                portal.main()
                self.assertEqual(dict(os.environ), inherited)
                execute.assert_called_once_with(portal.PORTAL, [portal.PORTAL])


if __name__ == "__main__":
    unittest.main()
