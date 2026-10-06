// Pure state helpers, shared by QML and the offline regression tests.
function playerRank(player) {
    var name = (player.dbusName || "").toLowerCase();
    var desktop = (player.desktopEntry || "").toLowerCase();
    if (name.indexOf("neteasecloudmusicgtk4") >= 0) return 0;
    if (/netease|cloudmusic/.test(name + " " + desktop)) return 1;
    return 2;
}

function selectPlayer(players) {
    var sorted = Array.prototype.slice.call(players || []);
    sorted.sort(function(a, b) {
        return playerRank(a) - playerRank(b)
            || Number(b.isPlaying) - Number(a.isPlaying)
            || String(a.dbusName).localeCompare(String(b.dbusName));
    });
    return sorted.length ? sorted[0] : null;
}

function cleanText(value, limit) {
    var text = String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
    var chars = Array.from(text);
    return chars.length > limit ? chars.slice(0, limit - 1).join("") + "…" : text;
}

function clockTime(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
}

function tooltipText(value) {
    return "<qt>" + cleanText(value, 240).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") + "</qt>";
}

function workspaceEvent(current, event) {
    if (event.WorkspacesChanged) return event.WorkspacesChanged.workspaces || [];
    if (event.WorkspaceActivated) {
        var activation = event.WorkspaceActivated;
        var target = current.find(function(w) { return w.id === activation.id; });
        if (!target) return current;
        return current.map(function(w) {
            var next = Object.assign({}, w);
            if (w.output === target.output) next.is_active = w.id === target.id;
            if (activation.focused) next.is_focused = w.id === target.id;
            return next;
        });
    }
    return current;
}

function batteryVisible(device) {
    return Boolean(device && device.ready && device.isLaptopBattery && device.isPresent);
}
