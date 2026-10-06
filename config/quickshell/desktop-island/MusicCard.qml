import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "logic.js" as Logic

Rectangle {
    id: card
    property bool expanded: false
    property bool volumeFeedback: false
    signal toggleRequested()
    color: "#211c29"
    radius: expanded ? 22 : 21
    clip: true
    border.color: "#3c303f"
    border.width: 1
    Behavior on radius { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
    // Absorb unused space within the card instead of dismissing it as an outside click.
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

    Button {
        id: summary
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 42
        padding: 0
        Accessible.name: card.expanded ? "Collapse music player" : "Expand music player"
        onClicked: card.toggleRequested()
        background: Rectangle { color: summary.hovered ? "#2c2434" : "transparent"; radius: 21 }
        contentItem: Item {
            RowLayout {
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                spacing: 9
                visible: !card.volumeFeedback
                Art { source: DesktopState.art; Layout.preferredWidth: 26; Layout.preferredHeight: 26; Layout.alignment: Qt.AlignVCenter; radius: 7 }
                ColumnLayout {
                    spacing: 0
                    Layout.fillWidth: true
                    InkLabel { text: DesktopState.title; font.pixelSize: 12; font.weight: Font.Medium; Layout.fillWidth: true }
                    InkLabel { text: DesktopState.artist || (DesktopState.hasPlayer ? "Paused" : "Open NetEase Cloud Music"); color: "#b7a6b9"; font.pixelSize: 10; Layout.fillWidth: true }
                }
                Icon { name: DesktopState.playing ? "music" : "pause"; color: "#e6a6c7"; Layout.preferredWidth: 16; Layout.preferredHeight: 16 }
            }
            RowLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                spacing: 12
                visible: card.volumeFeedback
                Icon { name: DesktopState.muted ? "muted" : "volume" }
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: 4; radius: 2; color: "#594557"
                    Rectangle { width: parent.width * Math.min(1, DesktopState.volume / 100); height: 4; radius: 2; color: "#e6a6c7" }
                }
                InkLabel { text: DesktopState.muted ? "Muted" : DesktopState.volume + "%"; font.pixelSize: 12 }
            }
        }
    }

    Item {
        id: detail
        anchors { top: summary.bottom; topMargin: 12; left: parent.left; leftMargin: 18; right: parent.right; rightMargin: 18 }
        height: 145
        opacity: card.expanded ? 1 : 0
        enabled: card.expanded
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
        RowLayout {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 112
            spacing: 18
            Art { source: DesktopState.art; Layout.preferredWidth: 104; Layout.preferredHeight: 104; radius: 12 }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                InkLabel { text: DesktopState.title; font.pixelSize: 16; font.weight: Font.DemiBold; Layout.fillWidth: true }
                InkLabel { text: DesktopState.artist || (DesktopState.hasPlayer ? DesktopState.playerName : "Your music, one click away"); color: "#b7a6b9"; font.pixelSize: 12; Layout.fillWidth: true }
                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 12
                    IconButton { symbol: "previous"; description: "Previous track"; enabled: Boolean(DesktopState.player && DesktopState.player.canGoPrevious); onClicked: DesktopState.previous() }
                    IconButton {
                        symbol: DesktopState.playing ? "pause" : "play"; description: DesktopState.playing ? "Pause" : "Play"
                        selected: true; implicitWidth: 38; implicitHeight: 38; ink: "#f6cce2"
                        enabled: !DesktopState.hasPlayer || DesktopState.preview || Boolean(DesktopState.player && DesktopState.player.canTogglePlaying)
                        onClicked: DesktopState.togglePlayback()
                    }
                    IconButton { symbol: "next"; description: "Next track"; enabled: Boolean(DesktopState.player && DesktopState.player.canGoNext); onClicked: DesktopState.next() }
                }
                Slider {
                    id: progress
                    Layout.fillWidth: true
                    implicitHeight: 12
                    from: 0; to: Math.max(1, DesktopState.duration)
                    enabled: DesktopState.seekable
                    Accessible.name: "Track position"
                    value: DesktopState.position
                    onMoved: DesktopState.seek(value)
                    background: Rectangle {
                        x: progress.leftPadding; y: progress.topPadding + progress.availableHeight / 2 - height / 2
                        width: progress.availableWidth; height: 3; radius: 2; color: "#594557"
                        Rectangle { width: progress.visualPosition * parent.width; height: parent.height; radius: 2; color: "#e6a6c7" }
                    }
                    handle: Rectangle {
                        x: progress.leftPadding + progress.visualPosition * (progress.availableWidth - width)
                        y: progress.topPadding + progress.availableHeight / 2 - height / 2
                        width: 8; height: 8; radius: 4; color: "#f5d5e5"; visible: progress.enabled && (progress.hovered || progress.pressed)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    InkLabel { text: Logic.clockTime(DesktopState.position); color: "#b7a6b9"; font.pixelSize: 10 }
                    Item { Layout.fillWidth: true }
                    InkLabel { text: DesktopState.duration > 0 ? Logic.clockTime(DesktopState.duration) : "–:––"; color: "#b7a6b9"; font.pixelSize: 10 }
                }
            }
        }
        RowLayout {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            spacing: 7
            Rectangle { implicitWidth: 4; implicitHeight: 4; radius: 2; color: "#e6a6c7" }
            InkLabel { text: DesktopState.playerName || "NetEase Cloud Music"; font.pixelSize: 10; color: "#b7a6b9"; Layout.fillWidth: true }
            InkLabel { text: "Open player"; font.pixelSize: 11; color: "#e6a6c7" }
            IconButton { symbol: "open"; description: "Open NetEase Cloud Music"; implicitWidth: 26; implicitHeight: 26; padding: 5; onClicked: DesktopState.desktop("music") }
        }
    }
}
