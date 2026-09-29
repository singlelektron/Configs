#!/usr/bin/env python3
"""Small Niri controls. Configuration is tracked; preferences and images are not."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import urllib.request

PROFILES = ("balanced", "focus", "performance")
BACKGROUND = "#19151c"
PREFIX = "dotfiles-niri-"
MAX_IMAGE_BYTES = 64 * 1024 * 1024


class DesktopError(Exception):
    pass


def xdg(name, fallback):
    value = Path(os.environ.get(name) or Path.home() / fallback).expanduser()
    if not value.is_absolute():
        raise DesktopError(f"{name} must be an absolute path")
    return value


def atomic_write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".desktop-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def command(argv, *, check=True, **kwargs):
    result = subprocess.run(argv, check=False, **kwargs)
    if check and result.returncode:
        raise DesktopError(f"Command failed ({result.returncode}): {shlex.join(argv)}")
    return result


def systemctl(*args, check=True, **kwargs):
    return command(["systemctl", "--user", *args], check=check, **kwargs)


def unit(name):
    return PREFIX + name + ".service"


def image_info(path):
    """Decode enough to reject corrupt/unsupported files before changing selection."""
    from PIL import Image
    if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
        raise DesktopError("Wallpaper must be a readable image under 64 MiB")
    try:
        with Image.open(path) as picture:
            if picture.format not in ("JPEG", "PNG", "WEBP", "BMP", "TIFF"):
                raise DesktopError("Use a static JPEG, PNG, WebP, BMP or TIFF wallpaper")
            if getattr(picture, "is_animated", False):
                raise DesktopError("Use a static wallpaper")
            dimensions = picture.size
            picture.verify()
        # JPEG verify() alone does not detect truncated pixel data.
        with Image.open(path) as picture:
            picture.load()
        return dimensions
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise DesktopError("Cannot decode wallpaper image") from error


def emit(text, tooltip=None, css_class=None):
    value = {"text": text, "tooltip": tooltip or text}
    if css_class:
        value["class"] = css_class
    print(json.dumps(value, ensure_ascii=False))


def niri_peer_pid(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(path)
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        peer_pid, peer_uid, _ = struct.unpack("3i", credentials)
        if peer_uid != os.getuid():
            raise DesktopError("Niri socket belongs to another user")
        return peer_pid


class Desktop:
    def __init__(self):
        self.config = xdg("XDG_CONFIG_HOME", ".config")
        self.state = xdg("XDG_STATE_HOME", ".local/state") / "dotfiles/niri/settings.json"
        self.data = xdg("XDG_DATA_HOME", ".local/share") / "dotfiles/wallpapers"

    def runtime(self):
        value = os.environ.get("XDG_RUNTIME_DIR")
        if not value or not Path(value).is_absolute():
            raise DesktopError("A logged-in user session with XDG_RUNTIME_DIR is required")
        return Path(value) / "dotfiles-niri"

    def settings(self):
        try:
            value = json.loads(self.state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        profile = value.get("bar_profile")
        wallpaper = value.get("wallpaper")
        return {"bar_profile": profile if profile in PROFILES else "balanced",
                "wallpaper": wallpaper if isinstance(wallpaper, str) else None}

    def save(self, **updates):
        value = self.settings()
        value.update(updates)
        atomic_write(self.state, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def require_session(self):
        path = os.environ.get("NIRI_SOCKET")
        if not path:
            raise DesktopError("This action requires a full niri-session; GNOME is unchanged")
        result = systemctl("show", "--property=MainPID", "--value", "niri.service",
                           capture_output=True, text=True, check=False)
        try:
            main_pid = int(result.stdout.strip()) if result.returncode == 0 else 0
            if main_pid <= 0 or main_pid != niri_peer_pid(path):
                raise DesktopError("Desktop controls require the main niri-session, not a nested compositor")
        except (OSError, ValueError) as error:
            raise DesktopError("Cannot identify the main niri-session") from error

    def restart(self, name):
        # try-restart never starts an inactive component, including outside Niri.
        systemctl("--no-block", "try-restart", unit(name))

    def menu_select(self, title, choices):
        result = command(["fuzzel", "--dmenu", "--prompt", title + ": "],
                         input="\n".join(choices) + "\n", text=True,
                         capture_output=True, check=False)
        if result.returncode:
            return None
        choice = result.stdout.rstrip("\n")
        return choice if choice in choices else None

    def bar(self, profile):
        if profile == "menu":
            labels = {"均衡": "balanced", "专注": "focus", "性能": "performance"}
            choice = self.menu_select("信息布局", labels)
            if not choice:
                return
            profile = labels[choice]
        if profile not in PROFILES:
            raise DesktopError("Unknown Waybar profile")
        self.save(bar_profile=profile)
        self.restart("waybar")

    def waybar(self):
        profile = self.settings()["bar_profile"]
        value = json.loads((self.config / "waybar" / f"{profile}.json").read_text())
        self.filter_hardware(value)
        destination = self.runtime() / "waybar.json"
        atomic_write(destination, json.dumps(value, ensure_ascii=False))
        os.execvp("waybar", ["waybar", "--config", str(destination),
                            "--style", str(self.config / "waybar/style.css")])

    @staticmethod
    def filter_hardware(value, sysfs=Path("/sys/class")):
        battery = any(p.read_text().strip() == "Battery"
                      for p in (sysfs / "power_supply").glob("*/type"))
        backlight = any((sysfs / "backlight").glob("*"))
        for key in ("modules-left", "modules-center", "modules-right"):
            value[key] = [m for m in value.get(key, [])
                          if not (m.split("#")[0] == "battery" and not battery)
                          and not (m.split("#")[0] == "backlight" and not backlight)]

    def wallpaper_metadata(self):
        return json.loads((self.config / "niri/wallpaper.json").read_text())

    def fetch_wallpaper(self):
        metadata = self.wallpaper_metadata()
        target = self.data / "default.jpg"
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == metadata["sha256"]:
            image_info(target)
            return
        if not metadata["url"].startswith("https://"):
            raise DesktopError("Default wallpaper source must use HTTPS")
        self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".wallpaper-", dir=self.data)
        try:
            request = urllib.request.Request(metadata["url"], headers={"User-Agent": "dotfiles-wallpaper/1"})
            with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=30) as response:
                total = 0
                digest = hashlib.sha256()
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise DesktopError("Wallpaper download exceeds 64 MiB")
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != metadata["sha256"]:
                raise DesktopError("Wallpaper checksum changed; existing cache was preserved")
            if image_info(Path(temporary)) != (metadata["width"], metadata["height"]):
                raise DesktopError("Unexpected wallpaper dimensions")
            os.replace(temporary, target)
            print(f"Default wallpaper ready: {metadata['width']}x{metadata['height']}")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def wallpaper(self, action, path=None):
        if action == "fetch":
            self.fetch_wallpaper()
            return
        if action == "choose":
            result = command(["zenity", "--file-selection", "--title=更换壁纸",
                              "--file-filter=图片 | *.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"],
                             text=True, capture_output=True, check=False)
            if result.returncode:
                return
            path = result.stdout.rstrip("\n")
            action = "set"
        if action == "set":
            if not path:
                raise DesktopError("Provide a wallpaper file")
            image = Path(path).expanduser().resolve(strict=True)
            image_info(image)
            self.save(wallpaper=str(image))
        elif action == "reset":
            self.save(wallpaper=None)
        else:
            raise DesktopError("Unknown wallpaper action")
        self.restart("wallpaper")

    def selected_wallpaper(self):
        selected = self.settings()["wallpaper"]
        candidates = ([Path(selected)] if selected else []) + [self.data / "default.jpg"]
        for candidate in candidates:
            try:
                image_info(candidate)
                return candidate
            except (DesktopError, OSError):
                continue
        return None

    def wallpaper_run(self):
        selected = self.selected_wallpaper()
        argv = ["swaybg", "--color", BACKGROUND]
        if selected:
            argv.extend(["--image", str(selected), "--mode", "fill"])
        os.execvp("swaybg", argv)

    def session_start(self):
        self.require_session()
        self.runtime().mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.runtime() / "presentation").unlink(missing_ok=True)
        # niri --session imports its own environment. Never replace it with a
        # nested compositor's socket/display or import a full shell environment.
        systemctl("daemon-reload")
        systemctl("start", *(unit(name) for name in
                  ("waybar", "mako", "wallpaper", "idle", "session-events", "polkit")))

    def presentation(self, action):
        flag = self.runtime() / "presentation"
        if action == "status":
            enabled = flag.exists()
            emit("常亮 ON" if enabled else "常亮 OFF",
                 "网课常亮：暂停空闲锁屏与熄屏；手动锁屏和睡前锁屏仍有效",
                 "active" if enabled else "inactive")
            return
        self.require_session()
        if flag.exists():
            systemctl("start", unit("idle"))
            flag.unlink()
        else:
            systemctl("stop", unit("idle"))
            atomic_write(flag, "on\n")
            command(["niri", "msg", "action", "power-on-monitors"])

    @staticmethod
    def idle(events=False):
        lock = shlex.join(["systemctl", "--user", "start", unit("lock")])
        wake = "niri msg action power-on-monitors"
        if events:
            args = ["before-sleep", lock, "lock", lock, "after-resume", wake]
        else:
            args = ["timeout", "300", lock, "timeout", "600",
                    "niri msg action power-off-monitors", "resume", wake]
        os.execvp("swayidle", ["swayidle", "-w", *args])

    def lock(self):
        self.require_session()
        os.execvp("swaylock", ["swaylock", "--daemonize", "--config", str(self.config / "swaylock/config")])

    def menu(self):
        self.require_session()
        options = ("信息布局", "更换壁纸", "恢复默认壁纸", "网课常亮开关", "锁屏",
                   "声音设置", "网络设置", "蓝牙设置", "快捷键帮助", "退出 Niri")
        choice = self.menu_select("桌面", options)
        if choice == "信息布局":
            self.bar("menu")
        elif choice == "更换壁纸":
            self.wallpaper("choose")
        elif choice == "恢复默认壁纸":
            self.wallpaper("reset")
        elif choice == "网课常亮开关":
            self.presentation("toggle")
        elif choice == "锁屏":
            systemctl("start", unit("lock"))
        elif choice in ("声音设置", "网络设置", "蓝牙设置"):
            application = {"声音设置": "pavucontrol", "网络设置": "nm-connection-editor",
                           "蓝牙设置": "blueman-manager"}[choice]
            command(["niri", "msg", "action", "spawn", "--", application])
        elif choice == "快捷键帮助":
            command(["niri", "msg", "action", "show-hotkey-overlay"])
        elif choice == "退出 Niri":
            command(["niri", "msg", "action", "quit"])


def metrics(kind):
    if kind == "gpu":
        if not shutil.which("nvidia-smi"):
            emit("")
            return
        try:
            result = command(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True,
                             check=False, timeout=3)
            if result.returncode:
                emit("")
                return
            cards = [[int(part.strip()) for part in line.split(",")]
                     for line in result.stdout.strip().splitlines()]
            if not cards or any(len(card) != 4 for card in cards):
                emit("")
                return
            load, used, total, temperature = cards[0]
            emit(f"GPU {load}% · {used / 1024:.1f}G · {temperature}°C",
                 "\n".join(f"GPU {i}: {c[0]}% · VRAM {c[1]}/{c[2]} MiB · {c[3]}°C"
                           for i, c in enumerate(cards)))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            emit("")
    else:
        readings = []
        for sensor in Path("/sys/class/thermal").glob("thermal_zone*"):
            try:
                label = (sensor / "type").read_text().strip()
                temperature = int((sensor / "temp").read_text()) / 1000
                if label in ("x86_pkg_temp", "cpu-thermal", "cpu_thermal") and 0 < temperature < 150:
                    readings.append(temperature)
            except (OSError, ValueError):
                continue
        emit(f"CPU {max(readings):.0f}°C" if readings else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("session-start", "waybar", "wallpaper-run", "idle", "session-events", "lock", "menu"):
        sub.add_parser(action)
    sub.add_parser("bar").add_argument("profile", choices=(*PROFILES, "menu"))
    wall = sub.add_parser("wallpaper")
    wall.add_argument("operation", choices=("choose", "set", "reset", "fetch"))
    wall.add_argument("path", nargs="?")
    sub.add_parser("presentation").add_argument("operation", choices=("toggle", "status"))
    sub.add_parser("metrics").add_argument("kind", choices=("gpu", "hardware"))
    args = parser.parse_args()
    try:
        desktop = Desktop()
        if args.action == "bar":
            desktop.bar(args.profile)
        elif args.action == "wallpaper":
            desktop.wallpaper(args.operation, args.path)
        elif args.action == "presentation":
            desktop.presentation(args.operation)
        elif args.action == "metrics":
            metrics(args.kind)
        elif args.action in ("idle", "session-events"):
            desktop.idle(events=args.action == "session-events")
        else:
            getattr(desktop, args.action.replace("-", "_"))()
        return 0
    except (DesktopError, OSError, ValueError, ImportError) as error:
        print(f"Desktop: {error}", file=sys.stderr)
        if os.environ.get("NIRI_SOCKET") and shutil.which("notify-send"):
            command(["notify-send", "桌面操作失败", str(error)], check=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
