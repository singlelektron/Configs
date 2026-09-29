#!/usr/bin/env python3
"""GTK control center; desktopctl owns persistent state and session checks."""
import argparse
from pathlib import Path
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango


PROFILES = (
    ("balanced", "Balanced", "Everyday essentials", "view-grid-symbolic"),
    ("focus", "Focus", "Space to concentrate", "view-fullscreen-symbolic"),
    ("performance", "Performance", "Hardware at a glance", "utilities-system-monitor-symbolic"),
)


def label(text, style=None, *, wrap=False):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_wrap(wrap)
    if style:
        widget.add_css_class(style)
    return widget


def icon(name, size=22):
    widget = Gtk.Image.new_from_icon_name(name)
    widget.set_pixel_size(size)
    return widget


def box(vertical=False, spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                   spacing=spacing)


class ControlCenter(Gtk.Application):
    def __init__(self, desktop):
        self.desktop = desktop
        self.preview = getattr(desktop, "preview", False)
        app_id = "io.github.dotfiles.DesktopPanel" + (".Preview" if self.preview else "")
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None
        self.busy = False
        self.syncing = False
        self.refresh_source = None
        self.profile_buttons = {}
        self.connect("activate", self.activate_panel)
        self.connect("shutdown", self.stop_refresh)

    def activate_panel(self, _application):
        if self.window is None:
            self.build()
            self.refresh_source = GLib.timeout_add_seconds(2, self.refresh)
        self.refresh()
        self.window.present()

    def stop_refresh(self, _application):
        if self.refresh_source is not None:
            GLib.source_remove(self.refresh_source)
            self.refresh_source = None

    def build(self):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).with_name("panel.css")))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = Gtk.ApplicationWindow(application=self, title="Desktop controls")
        self.window.set_default_size(680, 700)
        self.window.set_decorated(False)
        self.window.add_css_class("desktop-panel")
        self.window.connect("close-request", self.close_requested)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.key_pressed)
        self.window.add_controller(keys)

        root = box(True, 0)
        self.window.set_child(root)
        header = box(spacing=16)
        header.add_css_class("panel-header")
        titles = box(True, 4)
        titles.set_hexpand(True)
        titles.append(label("ROSE  /  NIRI", "eyebrow"))
        titles.append(label("Control center", "panel-title"))
        header.append(titles)
        self.close_button = Gtk.Button.new_from_icon_name("window-close-symbolic")
        self.close_button.set_tooltip_text("Close · Esc")
        self.close_button.add_css_class("close-button")
        self.close_button.set_valign(Gtk.Align.CENTER)
        self.close_button.connect("clicked", lambda _button: self.window.close())
        header.append(self.close_button)
        handle = Gtk.WindowHandle()
        handle.set_child(header)
        root.append(handle)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.controls = box(True, 18)
        self.controls.add_css_class("panel-content")
        scroll.set_child(self.controls)
        root.append(scroll)

        profiles = self.section("STATUS BAR", "Information density")
        profile_row = box(spacing=10)
        for profile, title, description, glyph in PROFILES:
            button = Gtk.ToggleButton()
            button.add_css_class("profile-card")
            button.set_hexpand(True)
            child = box(True, 7)
            image = icon(glyph)
            image.set_halign(Gtk.Align.START)
            child.append(image)
            child.append(label(title, "card-title"))
            child.append(label(description, "card-detail", wrap=True))
            button.set_child(child)
            button.connect("clicked", self.profile_clicked, profile)
            self.profile_buttons[profile] = button
            profile_row.append(button)
        profile_row.set_homogeneous(True)
        profiles.append(profile_row)

        awake = box(spacing=14)
        awake.add_css_class("setting-row")
        awake.append(icon("display-brightness-symbolic"))
        awake_copy = box(True, 4)
        awake_copy.set_hexpand(True)
        awake_copy.append(label("Keep awake", "card-title"))
        awake_copy.append(label("Pause idle lock and screen timeout", "card-detail", wrap=True))
        awake.append(awake_copy)
        self.awake = Gtk.Switch()
        self.awake.set_valign(Gtk.Align.CENTER)
        self.awake.set_tooltip_text("Manual locking and locking before sleep still work")
        self.awake.connect("state-set", self.awake_changed)
        awake.append(self.awake)
        self.controls.append(awake)

        connections = self.section("CONNECTIONS", "Devices & audio")
        device_row = box(spacing=10)
        device_row.set_homogeneous(True)
        for title, glyph, application in (
            ("Sound", "audio-volume-high-symbolic", "pavucontrol"),
            ("Network", "network-wireless-symbolic", "nm-connection-editor"),
            ("Bluetooth", "bluetooth-active-symbolic", "blueman-manager"),
        ):
            button = Gtk.Button()
            button.add_css_class("device-card")
            child = box(spacing=10)
            child.append(icon(glyph, 20))
            child.append(label(title, "card-title"))
            button.set_child(child)
            button.connect("clicked", lambda _button, app=application, name=title:
                           self.launch(["niri", "msg", "action", "spawn", "--", app], name))
            device_row.append(button)
        connections.append(device_row)

        appearance = self.section("APPEARANCE", "Your workspace")
        wallpaper = box(spacing=12)
        wallpaper.add_css_class("setting-row")
        wallpaper.append(icon("preferences-desktop-wallpaper-symbolic"))
        wallpaper_copy = box(True, 4)
        wallpaper_copy.set_hexpand(True)
        wallpaper_copy.append(label("Wallpaper", "card-title"))
        self.wallpaper_name = label("Default artwork", "card-detail")
        self.wallpaper_name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.wallpaper_name.set_max_width_chars(28)
        wallpaper_copy.append(self.wallpaper_name)
        wallpaper.append(wallpaper_copy)
        change = Gtk.Button(label="Change…")
        change.add_css_class("accent-button")
        change.set_valign(Gtk.Align.CENTER)
        change.connect("clicked", lambda _button: self.perform(
            lambda: self.desktop.wallpaper("choose"), "Choose an image in the file picker…"))
        wallpaper.append(change)
        reset = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        reset.set_valign(Gtk.Align.CENTER)
        reset.set_tooltip_text("Restore default wallpaper")
        reset.connect("clicked", lambda _button: self.perform(
            lambda: self.desktop.wallpaper("reset"), "Restoring wallpaper…"))
        wallpaper.append(reset)
        appearance.append(wallpaper)

        session = box(spacing=10)
        session.add_css_class("session-row")
        shortcuts = self.action_button("Shortcuts", "input-keyboard-symbolic")
        shortcuts.set_hexpand(True)
        shortcuts.connect("clicked", lambda _button: self.launch(
            ["niri", "msg", "action", "show-hotkey-overlay"], "Keyboard shortcuts"))
        session.append(shortcuts)
        lock = self.action_button("Lock", "system-lock-screen-symbolic")
        lock.connect("clicked", lambda _button: self.launch(
            ["systemctl", "--user", "start", "dotfiles-niri-lock.service"], "Lock screen"))
        session.append(lock)
        logout = self.action_button("Sign out", "system-log-out-symbolic")
        logout.set_tooltip_text("Niri will ask for confirmation")
        logout.connect("clicked", lambda _button: self.launch(
            ["niri", "msg", "action", "quit"], "Sign out"))
        session.append(logout)
        self.controls.append(session)

        footer = box(spacing=10)
        footer.add_css_class("panel-footer")
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        footer.append(self.spinner)
        self.status = label("Preview · changes stay in memory" if self.preview else "Ready", "status")
        self.status.set_wrap(True)
        self.status.set_hexpand(True)
        footer.append(self.status)
        footer.append(label("ESC  CLOSE", "key-hint"))
        root.append(footer)

    def section(self, caption, subtitle):
        section = box(True, 10)
        heading = box(spacing=10)
        heading.append(label(caption, "section-label"))
        detail = label(subtitle, "section-detail")
        detail.set_hexpand(True)
        detail.set_xalign(1)
        heading.append(detail)
        section.append(heading)
        self.controls.append(section)
        return section

    @staticmethod
    def action_button(title, glyph):
        button = Gtk.Button()
        child = box(spacing=8)
        child.set_halign(Gtk.Align.CENTER)
        child.append(icon(glyph, 18))
        child.append(label(title))
        button.set_child(child)
        return button

    def refresh(self):
        if self.busy:
            return GLib.SOURCE_CONTINUE
        try:
            settings = self.desktop.settings()
            enabled = (self.desktop.presentation_enabled if self.preview else
                       (self.desktop.runtime() / "presentation").exists())
            self.syncing = True
            for name, button in self.profile_buttons.items():
                button.set_active(settings["bar_profile"] == name)
            self.awake.set_active(enabled)
            self.awake.set_state(enabled)
            wallpaper = settings["wallpaper"]
            self.wallpaper_name.set_label(Path(wallpaper).name if wallpaper else "Default artwork")
            self.wallpaper_name.set_tooltip_text(wallpaper or "C · rooftop sunset")
        except Exception as error:
            self.show_status(str(error), error=True)
        finally:
            self.syncing = False
        return GLib.SOURCE_CONTINUE

    def profile_clicked(self, _button, profile):
        if not self.syncing:
            self.perform(lambda: self.desktop.bar(profile), "Updating status bar…")

    def awake_changed(self, _switch, desired):
        if self.syncing:
            return False
        if desired != self.awake.get_state():
            self.perform(lambda: self.desktop.presentation("on" if desired else "off"),
                         "Updating idle settings…")
        return True  # Commit the switch only after the operation succeeds.

    def show_status(self, message, *, error=False):
        self.status.set_label(message)
        if error:
            self.status.add_css_class("error")
        else:
            self.status.remove_css_class("error")

    def perform(self, action, message, *, close=False):
        if self.busy:
            return
        self.busy = True
        self.controls.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.show_status(message)

        def worker():
            error = None
            try:
                action()
            except Exception as problem:
                error = str(problem)
            GLib.idle_add(complete, error)

        def complete(error):
            self.busy = False
            self.controls.set_sensitive(True)
            self.spinner.stop()
            self.spinner.set_visible(False)
            self.refresh()
            self.show_status(error or ("Preview · changes stay in memory" if self.preview else "Ready"),
                             error=error is not None)
            if close and error is None and not self.preview:
                self.window.close()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=worker, daemon=True).start()

    def launch(self, argv, description):
        def action():
            if self.preview:
                return
            result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=15)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or f"Could not open {description.lower()}")
        self.perform(action, f"Opening {description.lower()}…", close=True)

    def close_requested(self, _window):
        if self.busy:
            self.show_status("Finish or cancel the current action before closing.")
            return True
        self.window = None
        self.stop_refresh(self)
        return False

    def key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.window.close()
            return True
        return False


def run(desktop):
    """Launch a single-instance panel after the caller has checked the session."""
    return ControlCenter(desktop).run([])


class PreviewDesktop:
    """Safe visual inspection: no files, processes, services or preferences change."""
    preview = True

    def __init__(self):
        self.values = {"bar_profile": "balanced", "wallpaper": None}
        self.presentation_enabled = False

    def settings(self):
        return self.values.copy()

    def bar(self, profile):
        self.values["bar_profile"] = profile

    def wallpaper(self, action):
        self.values["wallpaper"] = "/preview/Evening skyline.png" if action == "choose" else None

    def presentation(self, action):
        if action == "toggle":
            self.presentation_enabled = not self.presentation_enabled
        else:
            self.presentation_enabled = action == "on"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", required=True,
                        help="open a safe preview with in-memory controls")
    parser.parse_args()
    raise SystemExit(run(PreviewDesktop()))
