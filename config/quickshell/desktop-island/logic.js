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

function profileFeatures(profile) {
    return {
        search: profile !== "focus",
        updates: true,
        updateCount: profile !== "focus",
        network: profile !== "focus",
        date: profile !== "focus",
        seconds: profile === "performance",
        volumePercent: profile === "performance"
    };
}

function audioStatus(ready, sink) {
    if (!ready) return { available: false, reason: "Audio service unavailable" };
    if (!sink) return { available: false, reason: "No audio output device" };
    if (!sink.ready) return { available: false, reason: "Connecting to audio output…" };
    if (!sink.audio || !Number.isFinite(sink.audio.volume)) return { available: false, reason: "Audio output cannot be controlled" };
    return { available: true, reason: "" };
}

function volumeStep(current, angleDelta, pixelDelta) {
    var delta = angleDelta || pixelDelta;
    return Math.max(0, Math.min(1, current + (delta > 0 ? 0.05 : delta < 0 ? -0.05 : 0)));
}

function audioSinkCandidates(nodes) {
    return Array.prototype.filter.call(nodes || [], function(node) {
        return Boolean(node && node.audio && node.isSink && !node.isStream);
    });
}

function requestAudioOutput(service, outputs, id) {
    var output = outputs.find(function(node) { return node.id === id && node.ready; });
    if (!output) return false;
    service.preferredDefaultAudioSink = output;
    return true;
}
