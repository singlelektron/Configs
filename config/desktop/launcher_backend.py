"""Launch installed desktop entries without reimplementing their Exec syntax."""
import os
from pathlib import Path
import shutil

import gi

gi.require_version("GioUnix", "2.0")
from gi.repository import GioUnix, GLib


def launch_application(desktop_id, context, callback):
    """Call callback(error) on the GTK main thread; None means launch accepted."""
    original_path = None
    terminal = False
    try:
        if (not isinstance(desktop_id, str) or not desktop_id.endswith(".desktop")
                or "/" in desktop_id or "\0" in desktop_id):
            raise ValueError("Select an installed application")
        try:
            application = GioUnix.DesktopAppInfo.new(desktop_id)
        except TypeError as error:  # PyGObject represents a NULL constructor this way.
            raise ValueError("Application is unavailable; refresh the application list") from error
        if application is None or not application.should_show():
            raise ValueError("Application is unavailable; refresh the application list")
        if application.get_boolean("Terminal"):
            original_path = GLib.environ_getenv(context.get_environment(), "PATH")
            path = os.defpath if original_path is None else original_path
            if shutil.which("kitty", path=path) is None:
                raise ValueError("Kitty is required to open this terminal application")
            terminal_dir = Path(__file__).resolve().parent / "terminal-bin"
            if ":" in str(terminal_dir) or not os.access(terminal_dir / "xdg-terminal-exec", os.X_OK):
                raise ValueError("The launcher terminal helper is unavailable; redeploy the desktop")
            # Only this launch uses the adapter. It restores PATH before Kitty
            # runs, leaving GNOME and application child processes unaffected.
            context.setenv("PATH", str(terminal_dir) + ":" + path)
            terminal = True
    except (ValueError, OSError, GLib.Error) as error:
        callback(error)
        return

    def complete(error):
        if terminal:
            if original_path is None:
                context.unsetenv("PATH")
            else:
                context.setenv("PATH", original_path)
        callback(error)

    def finished(app, result):
        try:
            app.launch_uris_finish(result)
        except GLib.Error as error:
            complete(error)
        else:
            complete(None)

    try:
        application.launch_uris_async([], context, None, finished)
    except GLib.Error as error:
        complete(error)
