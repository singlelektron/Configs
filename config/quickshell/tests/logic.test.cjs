const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const logic = vm.createContext({});
vm.runInContext(readFileSync(require('node:path').join(__dirname, '../desktop-island/logic.js'), 'utf8'), logic);

test('paused NetEase GTK wins over a browser playing video', () => {
    const browser = { dbusName: 'org.mpris.MediaPlayer2.firefox.instance12', isPlaying: true };
    const netease = { dbusName: 'org.mpris.MediaPlayer2.NeteaseCloudMusicGtk4', isPlaying: false };
    assert.equal(logic.selectPlayer([browser, netease]), netease);
    assert.equal(logic.selectPlayer([netease, browser]), netease);
});
test('native NetEase outranks general players; no players is harmless', () => {
    const browser = { dbusName: 'org.mpris.MediaPlayer2.chromium', isPlaying: true };
    const native = { dbusName: 'org.mpris.MediaPlayer2.netease-cloud-music', isPlaying: false };
    assert.equal(logic.selectPlayer([browser, native]), native);
    assert.equal(logic.selectPlayer([]), null);
    assert.equal(logic.selectPlayer(undefined), null);
});
test('metadata is bounded by Unicode characters and kept as plain data', () => {
    assert.equal(logic.cleanText('春\n\t泥棒\0', 30), '春 泥棒');
    assert.equal(logic.cleanText('<b>title & artist</b>', 50), '<b>title & artist</b>');
    assert.equal(logic.cleanText('😀'.repeat(50), 8), '😀'.repeat(7) + '…');
    assert.equal(logic.tooltipText('<img src="bad"> &'), '<qt>&lt;img src="bad"&gt; &amp;</qt>');
});
test('workspace activation preserves other monitors and replaces objects', () => {
    const original = [{ id: 1, output: 'A', is_active: true, is_focused: true }, { id: 2, output: 'A' }, { id: 3, output: 'B', is_active: true }];
    const next = logic.workspaceEvent(original, { WorkspaceActivated: { id: 2, focused: true } });
    assert.equal(next[0].is_active, false);
    assert.equal(next[1].is_active, true);
    assert.equal(next[1].is_focused, true);
    assert.equal(next[2].is_active, true);
    assert.equal(original[0].is_active, true);
    assert.equal(logic.workspaceEvent(next, { WorkspaceActivated: { id: 999 } }), next);
});
test('aggregate or absent batteries never create a ghost status item', () => {
    assert.equal(logic.batteryVisible(null), false);
    assert.equal(logic.batteryVisible({ ready: true, isPresent: true, isLaptopBattery: false }), false);
    assert.equal(logic.batteryVisible({ ready: true, isPresent: true, isLaptopBattery: true }), true);
});

test('focus keeps updates reachable while performance exposes useful audio and time detail', () => {
    const focus = logic.profileFeatures('focus');
    assert.equal(focus.updates, true);
    assert.equal(focus.updateCount, false);
    assert.equal(focus.search, false);
    assert.equal(focus.network, false);
    assert.equal(focus.date, false);
    const balanced = logic.profileFeatures('balanced');
    assert.equal(balanced.updateCount, true);
    assert.equal(balanced.search, true);
    assert.equal(balanced.seconds, false);
    assert.equal(balanced.volumePercent, false);
    const performance = logic.profileFeatures('performance');
    assert.equal(performance.seconds, true);
    assert.equal(performance.volumePercent, true);
});
test('audio controls require a connected, ready and controllable output', () => {
    const sink = { ready: true, audio: { volume: 0.25 } };
    assert.equal(logic.audioStatus(true, sink).available, true);
    for (const [ready, device] of [[false, sink], [true, null], [true, { ready: false }], [true, { ready: true }], [true, { ready: true, audio: { volume: NaN } }]]) {
        const state = logic.audioStatus(ready, device);
        assert.equal(state.available, false);
        assert.ok(state.reason.length > 0);
    }
});
test('volume wheel ignores horizontal movement, accepts touchpad deltas and respects limits', () => {
    assert.equal(logic.volumeStep(0.25, 0, 0), 0.25);
    assert.equal(logic.volumeStep(0.25, 120, 0), 0.30);
    assert.equal(logic.volumeStep(0.25, 0, -3), 0.20);
    assert.equal(logic.volumeStep(0.99, 120, 0), 1);
    assert.equal(logic.volumeStep(0.01, -120, 0), 0);
});

test('output tracking includes unbound sinks but excludes application streams and microphones', () => {
    const speaker = { id: 1, audio: {}, isSink: true, isStream: false, ready: false };
    const stream = { id: 2, audio: {}, isSink: true, isStream: true };
    const microphone = { id: 3, audio: {}, isSink: false, isStream: false };
    assert.equal(logic.audioSinkCandidates([speaker, stream, microphone]).length, 1);
    assert.equal(logic.audioSinkCandidates([speaker, stream, microphone])[0], speaker);
});
test('output selection writes only the explicitly selected ready node as a preference', () => {
    const headphones = { id: 1, ready: true };
    const waiting = { id: 2, ready: false };
    const service = { preferredDefaultAudioSink: null };
    assert.equal(logic.requestAudioOutput(service, [headphones, waiting], 2), false);
    assert.equal(service.preferredDefaultAudioSink, null);
    assert.equal(logic.requestAudioOutput(service, [headphones, waiting], 99), false);
    assert.equal(logic.requestAudioOutput(service, [headphones, waiting], 1), true);
    assert.equal(service.preferredDefaultAudioSink, headphones);
});
