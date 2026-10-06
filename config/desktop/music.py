"""NetEase GTK4 launch and deterministic MPRIS controls for desktopctl."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

DESKTOP_ID = "com.gitee.gmg137.NeteaseCloudMusicGtk4.desktop"
MPRIS_NAME = "NeteaseCloudMusicGtk4"
BINARY = "netease-cloud-music-gtk4"
ACTIONS = ("open", "status", "previous", "play-pause", "next", "stop")


def command(argv, *, timeout=5):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise ValueError("音乐播放器没有及时响应，请稍后重试。") from error


def client_command():
    # The managed launcher is absolute: graphical-session PATH may omit ~/.local/bin.
    local = Path.home() / ".local/bin" / BINARY
    if local.is_file() and os.access(local, os.X_OK):
        return [str(local)]
    executable = shutil.which(BINARY)
    if executable:
        return [executable]
    # GIO handles Flatpak and desktop field codes; never parse Exec with a shell.
    try:
        import gi
        gi.require_version("GioUnix", "2.0")
        from gi.repository import GioUnix
        entry = GioUnix.DesktopAppInfo.new(DESKTOP_ID)
        launcher = shutil.which("gtk4-launch") or shutil.which("gtk-launch")
        if entry and entry.get_executable() and shutil.which(entry.get_executable()) and launcher:
            return [launcher, DESKTOP_ID]
    except (ImportError, ValueError, TypeError):
        pass
    raise ValueError("网易云 GTK4 尚未安装。请在 Configs 仓库运行 python3 scripts/install-music.py --apply。")


def players():
    if not shutil.which("playerctl"):
        raise ValueError("音乐控制需要 playerctl；请安装桌面依赖。")
    result = command(["playerctl", "--list-all"])
    return list(dict.fromkeys(result.stdout.splitlines())) if result.returncode == 0 else []


def selected_player():
    available = players()
    if not available:
        return None

    def rank(player):
        name = player.casefold()
        if "neteasecloudmusicgtk4" in name:
            return 0
        if "netease" in name or "cloudmusic" in name:
            return 1
        return 2

    # Match the island: GTK4, other NetEase clients, then general players.
    # Inspect only the winning tier, so a paused NetEase never yields to video.
    tier = min(map(rank, available))
    candidates = sorted((p for p in available if rank(p) == tier), key=lambda p: (p.casefold(), p))
    if len(candidates) == 1:
        return candidates[0]
    # A stable name order resolves equal playback states independently of D-Bus
    # discovery order. Bound the whole status pass, not just each subprocess.
    deadline = time.monotonic() + 5
    for player in candidates:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("音乐播放器没有及时响应，请稍后重试。")
        result = command(["playerctl", "--player", player, "status"], timeout=remaining)
        if result.returncode == 0 and result.stdout.strip() == "Playing":
            return player
    return candidates[0]


def status(player):
    if not player:
        return {"text": "网易云", "tooltip": "打开网易云 GTK4", "class": "idle"}
    state = command(["playerctl", "--player", player, "status"])
    title = command(["playerctl", "--player", player, "metadata", "xesam:title"])
    artist = command(["playerctl", "--player", player, "metadata", "xesam:artist"])
    title = title.stdout.strip() if title.returncode == 0 else ""
    artist = artist.stdout.strip() if artist.returncode == 0 else ""
    label = " · ".join(p for p in (title, artist) if p) or "网易云"
    return {"text": label, "tooltip": label, "class": state.stdout.strip().lower() or "idle",
            "player": player}


def run(desktop, action="open"):
    if action not in ACTIONS:
        raise ValueError("Unknown music action")
    if action == "open":
        desktop.require_session()
        result = command(["niri", "msg", "action", "spawn", "--", *client_command()])
        if result.returncode:
            raise ValueError("无法启动网易云 GTK4：" + result.stderr.strip())
        return
    player = selected_player()
    if action == "status":
        print(json.dumps(status(player), ensure_ascii=False))
        return
    if not player:
        raise ValueError("没有可控制的音乐播放器；先打开网易云并选择歌曲。")
    result = command(["playerctl", "--player", player, action])
    if result.returncode:
        raise ValueError("音乐控制失败：" + (result.stderr.strip() or action))
