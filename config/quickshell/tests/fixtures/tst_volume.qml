import QtQuick
import QtTest
import "../components" as Island
Item {
 width: 380; height: 380
 Island.VolumeCard { id: card; anchors.centerIn: parent }
 TestCase {
  name: "VolumeCardPointer"
  when: windowShown
  function test_1_drag_volume() {
   var slider = findChild(card, "volumeSlider");
   verify(slider !== null);
   mousePress(slider, slider.width * 0.22, slider.height / 2);
   mouseMove(slider, slider.width * 0.72, slider.height / 2, 100);
   mouseRelease(slider, slider.width * 0.72, slider.height / 2);
   verify(Island.DesktopState.volume > 65 && Island.DesktopState.volume < 80, "Actual pointer drag updates bound volume: " + Island.DesktopState.volume);
  }
  function test_2_click_device() {
   var list = findChild(card, "audioOutputs");
   verify(list !== null);compare(list.count, 2);
   compare(Island.DesktopState.audioOutputId, 101);
   mouseClick(list, list.width / 2, 50);
   tryCompare(Island.DesktopState, "audioOutputId", 102);
   compare(Island.DesktopState.mockService.preferredDefaultAudioSink.id, 102);
  }
  function test_3_click_mute() {
   mouseClick(findChild(card, "muteButton"));
   compare(Island.DesktopState.muted, true);
  }
 }
}
