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
