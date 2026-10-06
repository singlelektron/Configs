pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Mpris
import Quickshell.Services.Pipewire
import Quickshell.Services.UPower
import Quickshell.Networking
import "logic.js" as Logic

QtObject {
    id: state
    readonly property bool preview: Quickshell.env("DOTFILES_SHELL_PREVIEW") === "1"
    readonly property string profile: ["balanced", "focus", "performance"].indexOf(Quickshell.env("DOTFILES_BAR_PROFILE")) >= 0 ? Quickshell.env("DOTFILES_BAR_PROFILE") : "balanced"
    readonly property var features: Logic.profileFeatures(profile)
    readonly property string configRoot: Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")
    property string openPanel: ""
    property var layouts: ({})
    property var workspaces: preview ? [
        { id: 1, idx: 1, name: "read", is_active: true, is_focused: true },
        { id: 2, idx: 2, name: "code", is_active: false },
        { id: 3, idx: 3, name: "study", is_active: false },
        { id: 4, idx: 4, name: "play", is_active: false }
    ] : []
    property bool niriConnected: false
    property date now: new Date()
    property var updates: ({ status: "unknown", count: null, checked_at: null })
    property bool checkingUpdates: false
    property string updateError: ""

    readonly property var player: preview ? null : Logic.selectPlayer(Mpris.players.values)
    readonly property bool hasPlayer: preview || player !== null
    readonly property bool playing: preview || Boolean(player && player.isPlaying)
    readonly property string title: preview ? "春泥棒" : Logic.cleanText(player ? player.trackTitle : "", 120) || "Music"
    readonly property string artist: preview ? "ヨルシカ" : Logic.cleanText(player ? player.trackArtist : "", 120)
    readonly property string playerName: preview ? "NetEase Cloud Music" : Logic.cleanText(player ? player.identity : "", 70)
    readonly property string art: player ? player.trackArtUrl : ""
    readonly property real position: preview ? 86 : player && player.positionSupported ? player.position : 0
    readonly property real duration: preview ? 290 : player && player.lengthSupported ? player.length : 0
    readonly property bool seekable: !preview && Boolean(player && player.canSeek && player.positionSupported && player.lengthSupported && player.length > 0)

    readonly property var outputCandidates: preview ? [] : Logic.audioSinkCandidates(Pipewire.nodes.values)
    readonly property var audioOutputs: preview ? [
        { id: 101, ready: true, nickname: "Preview speakers", description: "Preview speakers" },
        { id: 102, ready: true, nickname: "Preview headphones", description: "Preview headphones" }
    ] : outputCandidates.filter(node => node.ready)
    property int previewOutputId: 101
    readonly property int audioOutputId: preview ? previewOutputId : sink ? sink.id : -1
    property int pendingAudioOutput: -1
    readonly property var sink: preview ? null : Pipewire.defaultAudioSink
    readonly property var audio: sink ? sink.audio : null
    property int previewVolume: 48
    property bool previewMuted: false
    readonly property var audioState: preview ? ({ available: true, reason: "" }) : Logic.audioStatus(Pipewire.ready, sink)
    readonly property bool audioAvailable: audioState.available
    readonly property string audioDevice: preview ? audioOutputs.find(node => node.id === previewOutputId).description : sink ? Logic.cleanText(sink.nickname || sink.description || sink.name, 120) : "No output selected"
    property string audioError: ""
    readonly property string audioMessage: pendingAudioOutput >= 0 ? "Switching output…" : audioState.reason || audioError
    readonly property int volume: preview ? previewVolume : audio ? Math.round(audio.volume * 100) : 0
    readonly property bool muted: preview ? previewMuted : Boolean(audio && audio.muted)
    property real volumeBaseline: NaN
    property bool mutedBaseline: false
    property int volumePulse: 0
    readonly property var battery: preview ? null : UPower.displayDevice
    readonly property bool hasBattery: Logic.batteryVisible(battery)
    readonly property var connectedDevice: preview ? null : Networking.devices.values.find(d => d.connected) || null
    readonly property string networkSymbol: preview ? "wifi" : !connectedDevice ? "offline" : connectedDevice.type === DeviceType.Wifi ? "wifi" : "wired"
    readonly property string networkDescription: {
        if (preview) return "Connected";
        if (!connectedDevice) return "Network disconnected";
        var network = connectedDevice.networks ? connectedDevice.networks.values.find(n => n.connected) : null;
        return network ? Logic.cleanText(network.name, 100) : connectedDevice.name;
    }

    function desktop(action) {
        openPanel = "";
        if (!preview) Quickshell.execDetached(["niri", "msg", "action", "spawn", "--", "/usr/bin/python3", configRoot + "/niri/desktopctl.py", action]);
    }
    function focusWorkspace(workspace) {
        openPanel = "";
        if (preview) { workspaces = Logic.workspaceEvent(workspaces, { WorkspaceActivated: { id: workspace.id, focused: true } }); return; }
        // Named workspaces remain unambiguous when their output changes.
        workspaceAction.exec(["niri", "msg", "--json", "action", "focus-workspace", workspace.name || String(workspace.idx)]);
    }
    function togglePlayback() {
        if (!hasPlayer) desktop("music");
        else if (player && player.canTogglePlaying) player.togglePlaying();
    }
    function previous() { if (player && player.canGoPrevious) player.previous(); }
    function next() { if (player && player.canGoNext) player.next(); }
    function seek(seconds) { if (seekable) player.position = Math.max(0, Math.min(duration, seconds)); }
    function setVolume(value) {
        if (!audioAvailable || !Number.isFinite(value)) return;
        audioError = "";
        try {
            if (preview) { previewVolume = Math.round(Math.max(0, Math.min(1, value)) * 100); volumePulse++; }
            else audio.volume = Math.max(0, Math.min(1, value));
        } catch (error) { audioError = "Could not change output volume"; }
    }
    function toggleMute() {
        if (!audioAvailable) return;
        audioError = "";
        try {
            if (preview) { previewMuted = !previewMuted; volumePulse++; }
            else audio.muted = !audio.muted;
        } catch (error) { audioError = "Could not change mute state"; }
    }
    function selectAudioOutput(id) {
        outputSwitchTimer.stop();
        if (preview) {
            if (audioOutputs.some(node => node.id === id)) previewOutputId = id;
            return;
        }
        audioError = "";
        pendingAudioOutput = id;
        try {
            if (!Logic.requestAudioOutput(Pipewire, audioOutputs, id)) {
                pendingAudioOutput = -1;
                audioError = "That output is no longer available";
                return;
            }
            if (sink && sink.id === id) pendingAudioOutput = -1;
            else outputSwitchTimer.restart();
        } catch (error) {
            pendingAudioOutput = -1;
            audioError = "Could not change output device";
        }
    }
    function trackVolume() {
        if (!audioAvailable) return;
        if (Number.isFinite(volumeBaseline) && (volumeBaseline !== volume || mutedBaseline !== muted)) volumePulse++;
        volumeBaseline = volume; mutedBaseline = muted;
    }
    onSinkChanged: {
        volumeBaseline = NaN; audioError = ""; baselineTimer.restart();
        if (sink && sink.id === pendingAudioOutput) { pendingAudioOutput = -1; outputSwitchTimer.stop(); }
    }
    onVolumeChanged: trackVolume()
    onMutedChanged: trackVolume()

    function refreshUpdates() {
        if (preview) return;
        if (!statusProcess.running) statusProcess.running = true;
    }
    function checkUpdates() {
        if (preview || checkingUpdates) return;
        checkingUpdates = true; updateError = ""; checkProcess.running = true;
    }
    function reviewUpdates() {
        openPanel = "";
        if (!preview) Quickshell.execDetached(["niri", "msg", "action", "spawn", "--", "/usr/bin/python3", configRoot + "/niri/updates.py", "review"]);
    }
    function acceptUpdates(text) {
        try {
            var value = JSON.parse(text);
            if (value && typeof value === "object") updates = value;
        } catch (error) { updateError = "Cannot read update status"; }
    }

    property PwObjectTracker audioTracker: PwObjectTracker { objects: state.outputCandidates }
    property Timer outputSwitchTimer: Timer {
        interval: 2000
        onTriggered: {
            if (state.pendingAudioOutput < 0) return;
            if (!state.sink || state.sink.id !== state.pendingAudioOutput)
                state.audioError = "System did not switch to that output";
            state.pendingAudioOutput = -1;
        }
    }
    property Timer baselineTimer: Timer { interval: 500; onTriggered: { state.volumeBaseline = state.volume; state.mutedBaseline = state.muted; } }
    property Timer clockTimer: Timer { interval: 1000; running: true; repeat: true; onTriggered: state.now = new Date() }
    property Timer positionTimer: Timer {
        interval: 1000; repeat: true
        running: state.openPanel.indexOf("music:") === 0 && Boolean(state.player && state.player.isPlaying)
        onTriggered: if (state.player) state.player.positionChanged()
    }
    property Process workspaceAction: Process {}
    property Process niriEvents: Process {
        command: ["niri", "msg", "--json", "event-stream"]
        running: !state.preview && Quickshell.env("NIRI_SOCKET") !== ""
        stdout: SplitParser {
            onRead: data => {
                try {
                    state.workspaces = Logic.workspaceEvent(state.workspaces, JSON.parse(data));
                    state.niriConnected = true;
                } catch (error) { console.warn("Ignoring malformed Niri event"); }
            }
        }
        stderr: StdioCollector {}
        onExited: { state.niriConnected = false; state.reconnect.restart(); }
    }
    property Timer reconnect: Timer {
        interval: 3000
        onTriggered: if (!state.preview && Quickshell.env("NIRI_SOCKET")) state.niriEvents.running = true
    }
    property Process statusProcess: Process {
        command: ["/usr/bin/python3", state.configRoot + "/niri/updates.py", "status"]
        stdout: StdioCollector { onStreamFinished: state.acceptUpdates(text) }
        stderr: StdioCollector {}
    }
    property Process checkProcess: Process {
        command: ["/usr/bin/python3", state.configRoot + "/niri/updates.py", "check"]
        stdout: StdioCollector { onStreamFinished: if (text.trim()) state.acceptUpdates(text) }
        stderr: StdioCollector { onStreamFinished: if (text.trim()) state.updateError = Logic.cleanText(text, 160) }
        onExited: { state.checkingUpdates = false; state.refreshUpdates(); }
    }
    property Timer updateTimer: Timer { interval: 30000; running: !state.preview; repeat: true; triggeredOnStart: true; onTriggered: state.refreshUpdates() }
    property Timer checkTimer: Timer { interval: 1800000; running: !state.preview; repeat: true; triggeredOnStart: true; onTriggered: state.checkUpdates() }
    property IpcHandler shellControl: IpcHandler {
        target: "island"
        function open(section: string): void {
            if (["music", "updates", "tray", "volume"].indexOf(section) >= 0 && Quickshell.screens.length)
                state.openPanel = section + ":" + Quickshell.screens[0].name;
        }
        function close(): void { state.openPanel = ""; }
        function feedback(): void { state.volumePulse++; }
        function setVolume(percent: real): void { state.setVolume(percent / 100); }
        function toggleMute(): void { state.toggleMute(); }
        function togglePlayback(): void { state.togglePlayback(); }
        function nextTrack(): void { state.next(); }
        function previousTrack(): void { state.previous(); }
        function seekTo(seconds: real): void { state.seek(seconds); }
        function snapshot(): string {
            return JSON.stringify({ preview: state.preview, profile: state.profile, panel: state.openPanel, title: state.title,
                player: state.player ? state.player.dbusName : null, playing: state.playing,
                seekable: state.seekable, workspaces: state.workspaces, volume: state.volume,
                audioAvailable: state.audioAvailable, audioDevice: state.audioDevice, audioMessage: state.audioMessage,
                sinkId: state.sink ? state.sink.id : null,
                outputs: state.audioOutputs.map(node => ({ id: node.id, name: node.nickname || node.description || node.name, description: node.description })), muted: state.muted, features: state.features, layouts: state.layouts,
                network: state.networkDescription, battery: state.hasBattery, updates: state.updates });
        }
    }
    Component.onCompleted: {
        if (preview) updates = { status: "ok", count: 12, checked_at: Math.floor(Date.now() / 1000), packages: [] };
    }
}
