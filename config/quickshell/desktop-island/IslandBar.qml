pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.SystemTray
import "logic.js" as Logic

PanelWindow {
    id: panel
    readonly property string outputName: screen ? screen.name : ""
    readonly property bool musicExpanded: DesktopState.openPanel === "music:" + outputName
    readonly property bool updatesExpanded: DesktopState.openPanel === "updates:" + outputName
    readonly property bool trayExpanded: DesktopState.openPanel === "tray:" + outputName
    readonly property bool ownsFocus: musicExpanded || updatesExpanded || trayExpanded
    readonly property bool wide: width >= 1150
    readonly property var localWorkspaces: DesktopState.workspaces.filter(w => DesktopState.preview || w.output === outputName).sort((a, b) => a.idx - b.idx)
    property bool volumeFeedback: false

    anchors { top: true; left: true; right: true }
    implicitHeight: screen ? screen.height : 1080
    exclusiveZone: 68
    color: "transparent"
    WlrLayershell.namespace: "dotfiles-island"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: ownsFocus ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    mask: DesktopState.openPanel ? null : closedMask

    Region {
        id: closedMask
        Region { item: leftCapsule; radius: 21 }
        Region { item: rightCapsule; radius: 21 }
        Region { item: music; radius: music.radius }
    }

    Connections {
        target: DesktopState
        function onVolumePulseChanged() { panel.volumeFeedback = true; volumeTimer.restart(); }
    }
    Timer { id: volumeTimer; interval: 1200; onTriggered: panel.volumeFeedback = false }
    onOwnsFocusChanged: if (ownsFocus) surface.forceActiveFocus()

    Item {
        id: surface
        anchors.fill: parent
        focus: panel.ownsFocus
        Keys.onEscapePressed: DesktopState.openPanel = ""
        MouseArea {
            anchors.fill: parent
            enabled: Boolean(DesktopState.openPanel)
            acceptedButtons: Qt.AllButtons
            onClicked: DesktopState.openPanel = ""
        }

        Rectangle {
            id: leftCapsule
            x: 18; y: 14; width: workspaceRow.implicitWidth + 18; height: 42; radius: 21
            color: "#211c29"; border.color: "#3c303f"
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
            RowLayout {
                id: workspaceRow
                anchors.centerIn: parent
                spacing: 2
                IconButton { symbol: "controls"; description: "Desktop controls"; onClicked: DesktopState.desktop("menu") }
                Rectangle { implicitWidth: 1; implicitHeight: 14; color: "#574454"; Layout.leftMargin: 5; Layout.rightMargin: 5 }
                Repeater {
                    model: panel.localWorkspaces
                    Button {
                        id: workspaceButton
                        required property var modelData
                        implicitWidth: 25; implicitHeight: 25; padding: 0
                        Accessible.name: "Workspace " + (modelData.name || modelData.idx)
                        enabled: DesktopState.preview || DesktopState.niriConnected
                        background: Rectangle {
                            radius: 13
                            color: workspaceButton.modelData.is_active ? "#56384f" : workspaceButton.hovered ? "#382d3e" : "transparent"
                            border.width: workspaceButton.visualFocus ? 1 : 0; border.color: "#e6a6c7"
                        }
                        contentItem: InkLabel {
                            text: workspaceButton.modelData.idx
                            font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            color: workspaceButton.modelData.is_active ? "#f2c3dc" : "#b7a6b9"
                        }
                        onClicked: DesktopState.focusWorkspace(modelData)
                        ToolTip.visible: hovered; ToolTip.text: Logic.tooltipText(modelData.name || "Workspace " + modelData.idx); ToolTip.delay: 700
                    }
                }
                Rectangle { implicitWidth: 1; implicitHeight: 14; color: "#574454"; Layout.leftMargin: 5; Layout.rightMargin: 5 }
                IconButton { symbol: "search"; description: "Applications"; onClicked: DesktopState.desktop("applications") }
            }
        }

        Rectangle {
            id: rightCapsule
            x: parent.width - width - 18; y: 14; width: statusRow.implicitWidth + 20; height: 42; radius: 21
            color: "#211c29"; border.color: "#3c303f"
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
            RowLayout {
                id: statusRow
                anchors.centerIn: parent; spacing: 3
                Button {
                    id: updatesButton
                    implicitWidth: updateRow.implicitWidth + 12; implicitHeight: 32
                    padding: 6
                    Accessible.name: "Arch updates " + (DesktopState.updates.count === null ? "not checked" : DesktopState.updates.count)
                    background: Rectangle { radius: 12; color: panel.updatesExpanded || updatesButton.hovered ? "#382d3e" : "transparent" }
                    contentItem: RowLayout {
                        id: updateRow; spacing: 5
                        Icon { name: "update"; color: DesktopState.updates.status === "error" ? "#f2beaa" : "#e6a6c7"; Layout.preferredWidth: 16; Layout.preferredHeight: 16 }
                        InkLabel { text: DesktopState.checkingUpdates ? "·" : DesktopState.updates.count === null || DesktopState.updates.count === undefined ? "?" : String(DesktopState.updates.count); visible: DesktopState.profile !== "focus"; font.pixelSize: 11 }
                    }
                    onClicked: DesktopState.openPanel = panel.updatesExpanded ? "" : "updates:" + panel.outputName
                    ToolTip.visible: hovered; ToolTip.text: "Arch updates · " + DesktopState.updates.status; ToolTip.delay: 700
                }
                IconButton { symbol: DesktopState.networkSymbol; description: DesktopState.networkDescription; onClicked: DesktopState.desktop("menu") }
                IconButton {
                    symbol: DesktopState.muted ? "muted" : "volume"
                    description: (DesktopState.muted ? "Muted" : "Volume " + DesktopState.volume + "%") + " · Scroll to adjust, click to mute"
                    onClicked: DesktopState.toggleMute()
                    WheelHandler {
                        target: null
                        onWheel: event => { DesktopState.setVolume(DesktopState.volume / 100 + (event.angleDelta.y > 0 ? 0.05 : -0.05)); event.accepted = true; }
                    }
                }
                IconButton {
                    symbol: "chevron"; description: "System tray"; selected: panel.trayExpanded
                    visible: DesktopState.preview || SystemTray.items.values.length > 0
                    onClicked: DesktopState.openPanel = panel.trayExpanded ? "" : "tray:" + panel.outputName
                }
                RowLayout {
                    visible: DesktopState.hasBattery; spacing: 4
                    Icon { name: "battery"; Layout.preferredWidth: 17; Layout.preferredHeight: 17 }
                    InkLabel { text: DesktopState.hasBattery ? Math.round(DesktopState.battery.percentage * 100) + "%" : ""; font.pixelSize: 11 }
                }
                Rectangle { implicitWidth: 1; implicitHeight: 14; color: "#574454"; Layout.leftMargin: 6; Layout.rightMargin: 7 }
                InkLabel { text: Qt.formatDateTime(DesktopState.now, "ddd d"); visible: panel.wide && DesktopState.profile !== "focus"; color: "#b7a6b9"; font.pixelSize: 11; Layout.rightMargin: 4 }
                InkLabel { text: Qt.formatDateTime(DesktopState.now, DesktopState.profile === "performance" ? "HH:mm:ss" : "HH:mm"); font.pixelSize: 12; font.weight: Font.DemiBold }
            }
        }

        MusicCard {
            id: music
            anchors.horizontalCenter: parent.horizontalCenter
            y: 14
            width: panel.musicExpanded ? Math.min(408, panel.width - 36) : Math.max(150, Math.min(226, panel.width - 2 * Math.max(leftCapsule.width, rightCapsule.width) - 64))
            height: panel.musicExpanded ? 223 : 42
            expanded: panel.musicExpanded
            volumeFeedback: panel.volumeFeedback
            onToggleRequested: DesktopState.openPanel = panel.musicExpanded ? "" : "music:" + panel.outputName
            Behavior on width { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
            Behavior on height { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
        }

        UpdatesCard {
            x: parent.width - width - 18; y: 68
            visible: panel.updatesExpanded
        }

        Rectangle {
            id: trayCard
            x: parent.width - width - 18; y: 68
            width: Math.max(120, trayRow.implicitWidth + 28); height: 62; radius: 18
            visible: panel.trayExpanded
            color: "#211c29"; border.color: "#3c303f"
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
            Row {
                id: trayRow
                anchors.centerIn: parent; spacing: 10
                InkLabel { text: "System tray"; visible: DesktopState.preview; height: 30; color: "#b7a6b9" }
                Repeater {
                    model: DesktopState.preview ? [] : SystemTray.items
                    Item {
                        id: trayIcon
                        required property var modelData
                        width: 30; height: 30
                        Image { id: trayImage; anchors.centerIn: parent; source: trayIcon.modelData.icon; width: 22; height: 22; sourceSize.width: 44; sourceSize.height: 44 }
                        Icon { anchors.centerIn: parent; visible: trayImage.status !== Image.Ready; width: 20; height: 20; name: "controls" }
                        MouseArea {
                            id: trayMouse
                            anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                            onClicked: mouse => {
                                if (mouse.button === Qt.RightButton || trayIcon.modelData.onlyMenu) {
                                    if (trayIcon.modelData.hasMenu) { var point = trayIcon.mapToItem(surface, 0, trayIcon.height); trayIcon.modelData.display(panel, point.x, point.y); }
                                } else if (mouse.button === Qt.MiddleButton) trayIcon.modelData.secondaryActivate();
                                else trayIcon.modelData.activate();
                            }
                            onWheel: wheel => { trayIcon.modelData.scroll(wheel.angleDelta.y, false); wheel.accepted = true; }
                        }
                        ToolTip.visible: trayMouse.containsMouse
                        ToolTip.text: Logic.tooltipText(modelData.tooltipTitle || modelData.title || modelData.id)
                        ToolTip.delay: 700
                    }
                }
            }
        }
    }
}
