import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "logic.js" as Logic

Rectangle {
    id: card
    width: 320; height: 216 + Math.min(3, DesktopState.audioOutputs.length) * 36; radius: 18
    color: "#211c29"; border.color: "#3c303f"
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 8
        RowLayout {
            Layout.fillWidth: true
            InkLabel { text: "Sound output"; font.pixelSize: 17; font.weight: Font.DemiBold; Layout.fillWidth: true }
            InkLabel {
                text: DesktopState.audioAvailable ? DesktopState.volume + "%" : "—"
                font.family: "JetBrains Mono NL"; font.pixelSize: 14
                Layout.preferredWidth: 48; horizontalAlignment: Text.AlignRight
            }
        }
        InkLabel {
            Layout.fillWidth: true; text: DesktopState.audioDevice; color: "#b7a6b9"; font.pixelSize: 11
            ToolTip.visible: deviceHover.hovered; ToolTip.text: Logic.tooltipText(text)
            HoverHandler { id: deviceHover }
        }
        Slider {
            id: volumeSlider
            objectName: "volumeSlider"
            Layout.fillWidth: true; implicitHeight: 30
            from: 0; to: 100; stepSize: 1
            enabled: DesktopState.audioAvailable
            Accessible.name: "Output volume"
            value: DesktopState.volume
            onMoved: DesktopState.setVolume(value / 100)
            WheelHandler {
                target: null
                onWheel: event => {
                    DesktopState.setVolume(Logic.volumeStep(DesktopState.volume / 100, event.angleDelta.y, event.pixelDelta.y));
                    event.accepted = true;
                }
            }
            background: Rectangle {
                x: volumeSlider.leftPadding; y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                width: volumeSlider.availableWidth; height: 5; radius: 3; color: "#594557"
                Rectangle { width: volumeSlider.visualPosition * parent.width; height: parent.height; radius: 3; color: volumeSlider.enabled ? "#e6a6c7" : "#766c7b" }
            }
            handle: Rectangle {
                x: volumeSlider.leftPadding + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                width: 14; height: 14; radius: 7; color: volumeSlider.enabled ? "#f5d5e5" : "#766c7b"
                border.width: volumeSlider.visualFocus ? 2 : 0; border.color: "#e6a6c7"
            }
        }
        RowLayout {
            Layout.fillWidth: true
            IconButton {
                objectName: "muteButton"
                symbol: DesktopState.muted ? "muted" : "volume"
                description: DesktopState.muted ? "Unmute output" : "Mute output"
                enabled: DesktopState.audioAvailable; selected: DesktopState.muted
                onClicked: DesktopState.toggleMute()
            }
            InkLabel {
                Layout.fillWidth: true; font.pixelSize: 11
                text: DesktopState.audioMessage || (DesktopState.muted ? "Muted · click to unmute" : "Scroll or drag to adjust")
                color: DesktopState.audioMessage ? "#f2beaa" : "#b7a6b9"
                ToolTip.visible: messageHover.hovered; ToolTip.text: Logic.tooltipText(text)
                HoverHandler { id: messageHover }
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#49384a" }
        InkLabel { text: "Default output"; color: "#b7a6b9"; font.pixelSize: 11 }
        ListView {
            id: outputList
            objectName: "audioOutputs"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(3, count) * 36
            clip: true; spacing: 4
            model: DesktopState.audioOutputs
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: Button {
                id: outputButton
                required property var modelData
                width: ListView.view.width; height: 32; padding: 7
                Accessible.name: "Use output " + (modelData.description || modelData.nickname || modelData.name)
                onClicked: DesktopState.selectAudioOutput(modelData.id)
                background: Rectangle {
                    radius: 10
                    color: outputButton.modelData.id === DesktopState.audioOutputId ? "#493248" : outputButton.hovered ? "#382d3e" : "transparent"
                    border.width: outputButton.visualFocus ? 1 : 0; border.color: "#e6a6c7"
                }
                contentItem: RowLayout {
                    spacing: 8
                    Rectangle {
                        implicitWidth: 6; implicitHeight: 6; radius: 3
                        color: outputButton.modelData.id === DesktopState.audioOutputId ? "#f2c3dc" : "#766c7b"
                    }
                    InkLabel {
                        Layout.fillWidth: true; font.pixelSize: 11
                        text: outputButton.modelData.description || outputButton.modelData.nickname || outputButton.modelData.name
                    }
                }
                ToolTip.visible: hovered
                ToolTip.text: Logic.tooltipText(modelData.description || modelData.nickname || modelData.name)
                ToolTip.delay: 500
            }
        }
        InkLabel {
            Layout.fillWidth: true; font.pixelSize: 10; color: "#b7a6b9"
            text: DesktopState.audioOutputs.length ? "Apps can keep a separate output choice." : "No output devices available"
        }
    }
}
