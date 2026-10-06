#!/usr/bin/env python3
"""GTK application picker using the same visual language as Desktop controls."""
import argparse
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from launcher_model import Application, search_applications


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0)
    if style:
        widget.add_css_class(style)
    return widget


def box(vertical=False, spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                   spacing=spacing)


def discover_applications():
    """Use the desktop database, including exported Flatpak applications."""
    applications = {}
    icons = {}
    for info in Gio.AppInfo.get_all():
        desktop_id = info.get_id()
        if not desktop_id or not info.should_show():
            continue
        applications[desktop_id] = Application(
            desktop_id=desktop_id,
            name=info.get_display_name() or info.get_name() or desktop_id,
            description=info.get_description() or "",
            generic_name=getattr(info, "get_generic_name", lambda: "")() or "",
            executable=Path(info.get_executable() or "").name,
            keywords=(tuple(getattr(info, "get_keywords", lambda: ())() or ()) +
                      tuple(filter(None, (getattr(info, "get_categories", lambda: "")() or "").split(";")))),
        )
        icons[desktop_id] = info.get_icon()
    return list(applications.values()), icons


class ApplicationPicker(Gtk.Application):
    def __init__(self, desktop):
        self.desktop = desktop
        self.preview = getattr(desktop, "preview", False)
        app_id = "io.github.dotfiles.AppLauncher" + (".Preview" if self.preview else "")
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None
        self.busy = False
        self.scroll_frame = None
        self.connect("activate", self.activate_picker)

    def activate_picker(self, _application):
        if self.window is None:
            self.applications, self.icons = (preview_applications() if self.preview else
                                             discover_applications())
            self.build()
        self.window.present()
        self.search.grab_focus()
        self.search.select_region(0, -1)

    def build(self):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).with_name("panel.css")))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = Gtk.ApplicationWindow(application=self, title="Applications")
        self.window.set_default_size(480, 560)
        self.window.set_decorated(False)
        self.window.add_css_class("desktop-panel")
        self.window.add_css_class("app-picker")
        self.window.connect("close-request", self.close_requested)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.key_pressed)
        self.window.add_controller(keys)

        root = box(True, 0)
        self.window.set_child(root)
        header = box(spacing=16)
        header.add_css_class("panel-header")
        title = label("Applications", "panel-title")
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

        search_area = box(True, 12)
        search_area.add_css_class("launcher-search-area")
        self.search = Gtk.SearchEntry()
        self.search.add_css_class("launcher-search")
        self.search.set_placeholder_text("Search applications…")
        self.search.set_search_delay(0)
        self.search.set_hexpand(True)
        self.search.connect("search-changed", lambda _entry: self.update_results())
        self.search.connect("activate", lambda _entry: self.launch_selected())
        search_area.append(self.search)
        heading = box(spacing=10)
        self.results_heading = label("All applications", "section-label")
        heading.append(self.results_heading)
        self.count = label("", "section-detail")
        self.count.set_hexpand(True)
        self.count.set_xalign(1)
        heading.append(self.count)
        search_area.append(heading)
        root.append(search_area)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.add_css_class("launcher-results")
        self.scroll.get_vadjustment().connect("changed", lambda _adjustment: self.reveal_selection())
        self.results = Gtk.ListBox()
        self.results.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.results.set_activate_on_single_click(True)
        self.results.add_css_class("launcher-list")
        self.results.connect("row-activated", lambda _list, row: self.launch(row.application))
        self.results.connect("row-selected", lambda _list, _row: self.scroll_to_selection())
        empty = box(True, 12)
        empty.add_css_class("launcher-empty")
        empty_icon = Gtk.Image.new_from_icon_name("system-search-symbolic")
        empty_icon.set_pixel_size(24)
        empty.append(empty_icon)
        self.empty_title = label("No matching applications", "card-title")
        self.empty_title.set_xalign(0.5)
        empty.append(self.empty_title)
        hint = label("Try a name, category or keyword.", "card-detail")
        hint.set_xalign(0.5)
        empty.append(hint)
        self.results.set_placeholder(empty)
        self.scroll.set_child(self.results)
        root.append(self.scroll)

        footer = box(spacing=10)
        footer.add_css_class("panel-footer")
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        footer.append(self.spinner)
        self.status = label("", "status")
        self.status.set_hexpand(True)
        self.status.set_wrap(True)
        self.status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.status.set_max_width_chars(40)
        self.status.set_lines(2)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        footer.append(self.status)
        footer.append(label("↑↓ select   ↵ open   esc close", "key-hint"))
        root.append(footer)
        self.update_results()

    def update_results(self):
        self.results.remove_all()
        matches = search_applications(self.applications, self.search.get_text())
        for application in matches:
            row = Gtk.ListBoxRow()
            row.application = application
            row.add_css_class("application-card")
            contents = box(spacing=12)
            image = Gtk.Image.new_from_gicon(self.icons.get(application.desktop_id) or
                                             Gio.ThemedIcon.new("application-x-executable-symbolic"))
            image.set_pixel_size(28)
            image.set_valign(Gtk.Align.CENTER)
            contents.append(image)
            copy = box(True, 3)
            copy.set_hexpand(True)
            title = label(application.name, "card-title")
            title.set_ellipsize(Pango.EllipsizeMode.END)
            copy.append(title)
            description = application.description or application.generic_name or application.executable
            detail = label(description or application.desktop_id, "card-detail")
            detail.set_ellipsize(Pango.EllipsizeMode.END)
            copy.append(detail)
            contents.append(copy)
            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.set_pixel_size(13)
            arrow.add_css_class("launcher-open-icon")
            contents.append(arrow)
            row.set_child(contents)
            row.set_tooltip_text(application.name + "\n" + (description or application.desktop_id))
            self.results.append(row)
        self.results.select_row(self.results.get_row_at_index(0))
        self.results_heading.set_label("Matches" if self.search.get_text().strip() else
                                       "All applications")
        self.count.set_label(str(len(matches)))
        self.empty_title.set_label("No matching applications" if self.applications else
                                   "No applications available")
        self.show_status("Preview · launches are simulated" if self.preview else
                         "")

    def scroll_to_selection(self):
        self.reveal_selection()
        # A search creates fresh rows. Their bounds are final only after GTK's
        # layout phase, so repeat once after the frame instead of racing an idle.
        frame = self.results.get_frame_clock()
        if frame is not None and self.scroll_frame is None:
            def after_layout(clock):
                clock.disconnect(self.scroll_frame[1])
                self.scroll_frame = None
                self.reveal_selection()
            self.scroll_frame = (frame, frame.connect_after("after-paint", after_layout))
            self.results.queue_draw()

    def reveal_selection(self):
        row = self.results.get_selected_row()
        if row is not None:
            valid, bounds = row.compute_bounds(self.results)
            if valid:
                adjustment = self.scroll.get_vadjustment()
                top = bounds.get_y()
                bottom = top + bounds.get_height()
                current = adjustment.get_value()
                visible_height = adjustment.get_page_size()
                if top < current:
                    adjustment.set_value(top)
                elif bottom > current + visible_height:
                    adjustment.set_value(bottom - visible_height)

    def key_pressed(self, _controller, keyval, _keycode, state):
        modifiers = (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK |
                     Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.SHIFT_MASK)
        if state & modifiers:
            return False
        if keyval == Gdk.KEY_Escape:
            self.window.close()
            return True
        focus = self.window.get_focus()
        in_search = focus is not None and (focus == self.search or focus.is_ancestor(self.search))
        in_results = focus is not None and (focus == self.results or focus.is_ancestor(self.results))
        if not self.busy and keyval in (Gdk.KEY_Up, Gdk.KEY_Down) and (in_search or in_results):
            row = self.results.get_selected_row()
            index = row.get_index() if row else -1
            next_row = self.results.get_row_at_index(max(0, index + (1 if keyval == Gdk.KEY_Down else -1)))
            if next_row is not None:
                self.results.select_row(next_row)
                if in_results:
                    next_row.grab_focus()
            return True
        return False

    def launch_selected(self):
        selected = self.results.get_selected_row()
        if selected is not None:
            self.launch(selected.application)

    def launch(self, application):
        if self.busy:
            return
        self.busy = True
        self.search.set_sensitive(False)
        self.results.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.show_status(f"Opening {application.name}…")
        context = Gdk.Display.get_default().get_app_launch_context()

        def complete(error):
            self.busy = False
            self.search.set_sensitive(True)
            self.results.set_sensitive(True)
            self.spinner.stop()
            self.spinner.set_visible(False)
            if error is not None:
                self.show_status(str(error) or "Could not open this application.", error=True)
                self.search.grab_focus()
            elif self.preview:
                self.show_status(f"Preview · would open {application.name}")
                self.search.grab_focus()
            else:
                self.window.close()
            return GLib.SOURCE_REMOVE

        try:
            self.desktop.launch_application(application.desktop_id, context, complete)
        except Exception as error:
            complete(error)

    def show_status(self, message, *, error=False):
        self.status.set_label(message)
        self.status.set_tooltip_text(message if error else None)
        if error:
            self.status.add_css_class("error")
        else:
            self.status.remove_css_class("error")

    def close_requested(self, _window):
        if self.busy:
            self.show_status("Opening application…")
            return True
        if self.scroll_frame is not None:
            self.scroll_frame[0].disconnect(self.scroll_frame[1])
            self.scroll_frame = None
        self.window = None
        return False


def run(desktop):
    """Launch one picker after desktopctl verifies the Niri session."""
    return ApplicationPicker(desktop).run([])


def preview_applications():
    fixtures = (
        ("chrome.desktop", "Google Chrome", "Browse the web", "google-chrome"),
        ("kitty.desktop", "Kitty", "Fast, feature-rich terminal", "kitty"),
        ("nvim.desktop", "Neovim", "Edit code and Markdown notes", "nvim"),
        ("nautilus.desktop", "Files", "Access and organize files", "org.gnome.Nautilus"),
        ("papers.desktop", "Document Viewer", "Read documents and research papers", "org.gnome.Papers"),
        ("steam.desktop", "Steam", "Games and community", "steam"),
        ("settings.desktop", "Settings", "Configure devices and preferences", "preferences-system"),
        ("blueman.desktop", "Bluetooth Manager", "Connect wireless devices", "bluetooth"),
        ("calculator.desktop", "Calculator", "Scientific calculations", "org.gnome.Calculator"),
        ("music.desktop", "Music", "Listen to your collection", "multimedia-audio-player"),
    )
    return ([Application(app_id, name, description) for app_id, name, description, _icon in fixtures],
            {app_id: Gio.ThemedIcon.new(icon_name) for app_id, _name, _detail, icon_name in fixtures})


class PreviewDesktop:
    """Preview launches never execute a command or change files/preferences."""
    preview = True

    def launch_application(self, _desktop_id, _context, complete):
        complete(None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", required=True,
                        help="open a safe preview with in-memory applications")
    parser.parse_args()
    raise SystemExit(run(PreviewDesktop()))
