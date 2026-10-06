pragma Singleton
import QtQuick
import "logic.js" as Logic
QtObject {
 id: state
 property bool audioAvailable: true
 property int volume: 22
 property bool muted: false
 property string audioMessage: ""
 property int audioOutputId: 101
 property var audioOutputs: [
  { id: 101, ready: true, description: "Test headphones" },
  { id: 102, ready: true, description: "Test digital output" }
 ]
 readonly property string audioDevice: audioOutputs.find(n => n.id === audioOutputId).description
 property QtObject mockService: QtObject { property var preferredDefaultAudioSink: null }
 function setVolume(value) { volume = Math.round(value * 100); }
 function toggleMute() { muted = !muted; }
 function selectAudioOutput(id) {
  if (Logic.requestAudioOutput(mockService, audioOutputs, id)) audioOutputId = mockService.preferredDefaultAudioSink.id;
 }
}
