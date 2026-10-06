#!/usr/bin/env python3
"""GTK control center; desktopctl owns persistent state and session checks."""
import argparse
from pathlib import Path
import re
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango


PROFILES = (
    ("balanced", "Balanced", "Workspaces, music and system status"),
    ("focus", "Focus", "Compact status; hide the date and update count"),
    ("performance", "Performance", "Show seconds in the clock"),
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
        self.volume_source = None
        self.audio_pending = False
        self.audio_generation = 0
        self.cpu_sample = None
        self.temperature_sensor = None
        self.temperature_checked = False
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
        self.cpu_sample = None
        if self.refresh_source is not None:
            GLib.source_remove(self.refresh_source)
            self.refresh_source = None
        if self.volume_source is not None:
            GLib.source_remove(self.volume_source)
            self.volume_source = None

    def build(self):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).with_name("panel.css")))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = Gtk.ApplicationWindow(application=self, title="Desktop controls")
        self.window.set_default_size(356, 580)
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
        title = label("Controls", "panel-title")
        title.set_hexpand(True)
        header.append(title)
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
        self.controls = box(True, 12)
        self.controls.add_css_class("panel-content")
        scroll.set_child(self.controls)
        root.append(scroll)

        sound = box(True, 4)
        sound_heading = box()
        sound_title = label("Sound", "section-label")
        sound_title.set_hexpand(True)
        sound_heading.append(sound_title)
        self.volume_value = label("—", "section-detail")
        sound_heading.append(self.volume_value)
        sound.append(sound_heading)
        volume_row = box(spacing=8)
        volume_row.append(icon("audio-volume-high-symbolic", 17))
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume.set_draw_value(False)
        self.volume.set_hexpand(True)
        self.volume.set_sensitive(False)
        self.volume.set_tooltip_text("Output volume")
        self.volume.update_property([Gtk.AccessibleProperty.LABEL], ["Output volume"])
        self.volume.connect("value-changed", self.volume_changed)
        volume_row.append(self.volume)
        self.mute = Gtk.Button.new_from_icon_name("audio-volume-muted-symbolic")
        self.mute.add_css_class("quiet-button")
        self.mute.set_tooltip_text("Mute or unmute output")
        self.mute.set_sensitive(False)
        self.mute.connect("clicked", lambda _button: self.audio_command(
            ["set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]))
        volume_row.append(self.mute)
        sound.append(volume_row)
        self.controls.append(sound)

        devices = box(True, 0)
        devices.add_css_class("device-list")
        for title, glyph, application in (
            ("Sound settings", "audio-card-symbolic", "pavucontrol"),
            ("Network", "network-wireless-symbolic", "nm-connection-editor"),
            ("Bluetooth", "bluetooth-active-symbolic", "blueman-manager"),
        ):
            button = Gtk.Button()
            button.add_css_class("device-card")
            child = box(spacing=12)
            child.append(icon(glyph, 17))
            device_name = label(title, "card-title")
            device_name.set_hexpand(True)
            child.append(device_name)
            child.append(icon("go-next-symbolic", 13))
            button.set_child(child)
            button.connect("clicked", lambda _button, app=application, name=title:
                           self.launch(["niri", "msg", "action", "spawn", "--", app], name))
            devices.append(button)

        awake = box(spacing=12)
        awake.add_css_class("setting-row")
        awake.append(icon("display-brightness-symbolic", 17))
        awake_copy = box(True, 3)
        awake_copy.set_hexpand(True)
        awake_copy.append(label("Keep awake", "card-title"))
        awake.append(awake_copy)
        self.awake = Gtk.Switch()
        self.awake.set_valign(Gtk.Align.CENTER)
        self.awake.set_tooltip_text("Manual locking and locking before sleep still work")
        self.awake.update_property([Gtk.AccessibleProperty.LABEL], ["Keep awake"])
        self.awake.connect("state-set", self.awake_changed)
        awake.append(self.awake)
        devices.append(awake)
        quiet_row = box(spacing=12)
        quiet_row.add_css_class("setting-row")
        quiet_row.append(icon("notifications-disabled-symbolic", 17))
        quiet_title = label("Do not disturb", "card-title")
        quiet_title.set_hexpand(True)
        quiet_row.append(quiet_title)
        self.quiet = Gtk.Switch()
        self.quiet.set_valign(Gtk.Align.CENTER)
        self.quiet.set_sensitive(False)
        self.quiet.set_tooltip_text("Silence desktop notifications")
        self.quiet.update_property([Gtk.AccessibleProperty.LABEL], ["Do not disturb"])
        self.quiet.connect("state-set", self.quiet_changed)
        quiet_row.append(self.quiet)
        devices.append(quiet_row)
        self.controls.append(devices)

        profiles = self.section("Status bar")
        profile_row = box(spacing=3)
        profile_row.add_css_class("profile-segments")
        for profile, title, description in PROFILES:
            button = Gtk.ToggleButton(label=title)
            button.add_css_class("profile-card")
            button.set_hexpand(True)
            button.set_tooltip_text(description)
            button.connect("clicked", self.profile_clicked, profile)
            self.profile_buttons[profile] = button
            profile_row.append(button)
        profile_row.set_homogeneous(True)
        profiles.append(profile_row)

        wallpaper = box(spacing=8)
        wallpaper.add_css_class("setting-row")
        wallpaper.append(icon("preferences-desktop-wallpaper-symbolic", 17))
        wallpaper_copy = box(True, 3)
        wallpaper_copy.set_hexpand(True)
        wallpaper_copy.append(label("Wallpaper", "card-title"))
        self.wallpaper_name = label("Default wallpaper", "card-detail")
        self.wallpaper_name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.wallpaper_name.set_max_width_chars(16)
        wallpaper_copy.append(self.wallpaper_name)
        wallpaper.append(wallpaper_copy)
        change = Gtk.Button(label="Change")
        change.add_css_class("quiet-button")
        change.set_valign(Gtk.Align.CENTER)
        change.connect("clicked", lambda _button: self.perform(
            lambda: self.desktop.wallpaper("choose"), "Choose an image in the file picker…"))
        wallpaper.append(change)
        reset = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        reset.add_css_class("quiet-button")
        reset.set_valign(Gtk.Align.CENTER)
        reset.set_tooltip_text("Restore default wallpaper")
        reset.connect("clicked", lambda _button: self.perform(
            lambda: self.desktop.wallpaper("reset"), "Restoring wallpaper…"))
        wallpaper.append(reset)
        self.controls.append(wallpaper)

        metrics = box(spacing=10)
        metrics.add_css_class("system-summary")
        self.cpu_usage = label("CPU —", "system-metric")
        self.cpu_usage.set_hexpand(True)
        self.memory_usage = label("RAM —", "system-metric")
        self.memory_usage.set_hexpand(True)
        self.temperature = label("", "system-metric")
        self.temperature.set_visible(False)
        for metric in (self.cpu_usage, self.memory_usage, self.temperature):
            metrics.append(metric)
        if self.preview:
            metrics.set_tooltip_text("Preview · illustrative system values")
        self.controls.append(metrics)

        session = box(spacing=6)
        session.add_css_class("session-row")
        shortcuts = self.action_button("Shortcuts", "input-keyboard-symbolic")
        shortcuts.set_hexpand(True)
        shortcuts.connect("clicked", lambda _button: self.launch(
            ["niri", "msg", "action", "show-hotkey-overlay"], "Keyboard shortcuts"))
        session.append(shortcuts)
        lock = Gtk.Button.new_from_icon_name("system-lock-screen-symbolic")
        lock.set_tooltip_text("Lock screen")
        lock.connect("clicked", lambda _button: self.launch(
            ["systemctl", "--user", "start", "dotfiles-niri-lock.service"], "Lock screen"))
        session.append(lock)
        logout = Gtk.Button.new_from_icon_name("system-log-out-symbolic")
        logout.set_tooltip_text("Sign out · Niri will ask for confirmation")
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
        self.status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.status.set_max_width_chars(32)
        self.status.set_lines(2)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_hexpand(True)
        footer.append(self.status)
        footer.append(label("esc  close", "key-hint"))
        root.append(footer)

    def section(self, caption):
        section = box(True, 8)
        heading = box(spacing=10)
        heading.append(label(caption, "section-label"))
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
            self.wallpaper_name.set_label(Path(wallpaper).name if wallpaper else "Default wallpaper")
            self.wallpaper_name.set_tooltip_text(wallpaper or "Default wallpaper")
        except Exception as error:
            self.show_status(str(error), error=True)
        finally:
            self.syncing = False
        self.refresh_audio()
        self.refresh_metrics()
        return GLib.SOURCE_CONTINUE

    def refresh_metrics(self):
        """Small local reads only while this panel is visible; no helper processes."""
        if self.window is None or not self.window.get_visible():
            return
        if self.preview:
            self.cpu_usage.set_label("CPU 6%*")
            self.memory_usage.set_label("RAM 7.2 / 32 GiB*")
            self.temperature.set_label("42°C*")
            self.temperature.set_visible(True)
            return
        try:
            with Path("/proc/stat").open() as source:
                counters = [int(value) for value in source.readline().split()[1:9]]
            if len(counters) < 4:
                raise ValueError("Incomplete CPU counters")
            # guest counters are already included in user/nice; exclude them.
            current = (sum(counters), counters[3] + (counters[4] if len(counters) > 4 else 0))
            if self.cpu_sample is not None:
                total = current[0] - self.cpu_sample[0]
                idle = current[1] - self.cpu_sample[1]
                if total > 0:
                    usage = min(100, max(0, 100 * (total - idle) / total))
                    self.cpu_usage.set_label(f"CPU {usage:.0f}%")
            self.cpu_sample = current
        except (OSError, ValueError, IndexError):
            self.cpu_usage.set_label("CPU —")
            self.cpu_sample = None
        try:
            memory = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                name, value = line.split(":", 1)
                if name in ("MemTotal", "MemAvailable"):
                    memory[name] = int(value.split()[0])
            total = memory["MemTotal"] / 1048576
            used = max(0, memory["MemTotal"] - memory["MemAvailable"]) / 1048576
            self.memory_usage.set_label(f"RAM {used:.1f} / {total:.0f} GiB")
            self.memory_usage.set_tooltip_text("Used memory, excluding reclaimable cache")
        except (OSError, ValueError, KeyError, IndexError):
            self.memory_usage.set_label("RAM —")
        if not self.temperature_checked:
            self.temperature_checked = True
            self.temperature_sensor = self.find_temperature_sensor()
        try:
            if self.temperature_sensor is None:
                return
            temperature = int(self.temperature_sensor.read_text()) / 1000
            if not -20 <= temperature <= 150:
                raise ValueError("Invalid temperature")
            self.temperature.set_label(f"{temperature:.0f}°C")
            self.temperature.set_tooltip_text("CPU temperature")
            self.temperature.set_visible(True)
        except (OSError, ValueError):
            self.temperature.set_visible(False)

    @staticmethod
    def find_temperature_sensor():
        for device in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            try:
                if (device / "name").read_text().strip() in (
                        "coretemp", "k10temp", "zenpower", "cpu_thermal"):
                    sensor = device / "temp1_input"
                    if sensor.is_file():
                        return sensor
            except OSError:
                continue
        for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            try:
                if (zone / "type").read_text().strip() in ("x86_pkg_temp", "cpu-thermal", "cpu_thermal"):
                    return zone / "temp"
            except OSError:
                continue
        return None

    def refresh_audio(self):
        """Never wait for PipeWire on GTK's event loop."""
        if self.busy or self.audio_pending or self.volume_source is not None or self.window is None:
            return
        self.audio_pending = True
        generation = self.audio_generation

        def complete(value, muted, quiet):
            self.audio_pending = False
            if generation != self.audio_generation:
                self.refresh_audio()
                return GLib.SOURCE_REMOVE
            if self.window is None or self.volume_source is not None or self.busy:
                return GLib.SOURCE_REMOVE
            self.syncing = True
            self.quiet.set_sensitive(quiet is not None)
            if quiet is not None:
                self.quiet.set_active(quiet)
                self.quiet.set_state(quiet)
            self.volume.set_sensitive(value is not None)
            self.mute.set_sensitive(value is not None)
            if value is None:
                self.volume_value.set_label("Unavailable")
                self.syncing = False
                return GLib.SOURCE_REMOVE
            self.volume.set_value(value)
            self.volume_value.set_label("Muted" if muted else f"{value:.0f}%")
            self.mute.set_icon_name("audio-volume-muted-symbolic" if muted else
                                    "audio-volume-high-symbolic")
            self.mute.set_tooltip_text("Unmute output" if muted else "Mute output")
            self.syncing = False
            return GLib.SOURCE_REMOVE

        def worker():
            value, muted, quiet = None, False, None
            try:
                result = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                                        capture_output=True, text=True, timeout=3, check=True)
                match = re.search(r"Volume:\s+([0-9.]+)", result.stdout)
                if match:
                    value = min(100, max(0, float(match[1]) * 100))
                    muted = "[MUTED]" in result.stdout
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            try:
                result = subprocess.run(["makoctl", "mode"], capture_output=True,
                                        text=True, timeout=3, check=True)
                quiet = "do-not-disturb" in result.stdout.split()
            except (OSError, subprocess.SubprocessError):
                pass
            GLib.idle_add(complete, value, muted, quiet)

        if self.preview:
            complete(getattr(self.desktop, "volume", 48), getattr(self.desktop, "muted", False),
                     getattr(self.desktop, "quiet", False))
        else:
            threading.Thread(target=worker, daemon=True).start()

    def volume_changed(self, scale):
        if self.syncing:
            return
        self.volume_value.set_label(f"{scale.get_value():.0f}%")
        if self.volume_source is not None:
            GLib.source_remove(self.volume_source)
        self.volume_source = GLib.timeout_add(150, self.commit_volume)

    def commit_volume(self):
        if self.busy:
            return GLib.SOURCE_CONTINUE
        self.volume_source = None
        self.audio_command(["set-volume", "@DEFAULT_AUDIO_SINK@", f"{self.volume.get_value():.0f}%"])
        return GLib.SOURCE_REMOVE

    def audio_command(self, arguments):
        self.audio_generation += 1
        def action():
            if self.preview:
                if arguments[0] == "set-volume":
                    self.desktop.volume = float(arguments[-1].rstrip("%"))
                else:
                    self.desktop.muted = not getattr(self.desktop, "muted", False)
                return
            result = subprocess.run(["wpctl", *arguments], capture_output=True,
                                    text=True, timeout=3, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "Could not update output volume")
        self.perform(action, "Updating sound…")

    def quiet_changed(self, _switch, desired):
        if self.syncing:
            return False
        if desired != self.quiet.get_state():
            self.audio_generation += 1

            def action():
                if self.preview:
                    self.desktop.quiet = desired
                    return
                result = subprocess.run(["makoctl", "mode", "-a" if desired else "-r",
                                         "do-not-disturb"], capture_output=True, text=True,
                                        timeout=3, check=False)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or "Could not update notification mode")
            self.perform(action, "Updating notifications…")
        return True

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
        self.status.set_tooltip_text(message if error else None)
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
        if self.busy or self.volume_source is not None:
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
