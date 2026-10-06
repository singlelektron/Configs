import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "logic.js" as Logic

Rectangle {
    id: card
    width: 330; height: 178; radius: 18
    color: "#211c29"; border.color: "#3c303f"
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 10
        InkLabel { text: "Arch updates"; font.pixelSize: 17; font.weight: Font.DemiBold }
        RowLayout {
            Layout.fillWidth: true
            InkLabel { text: "Official repositories"; color: "#b7a6b9"; Layout.fillWidth: true }
            InkLabel { text: DesktopState.updates.count === null || DesktopState.updates.count === undefined ? "Not checked" : DesktopState.updates.count + " packages" }
        }
        InkLabel {
            Layout.fillWidth: true; font.pixelSize: 11; color: DesktopState.updates.status === "error" ? "#f2beaa" : "#b7a6b9"
            text: DesktopState.checkingUpdates ? "Checking…" : DesktopState.updates.error || DesktopState.updateError || (DesktopState.updates.checked_at ? "Checked " + Qt.formatDateTime(new Date(DesktopState.updates.checked_at * 1000), "MMM d · HH:mm") : "No successful check yet")
            ToolTip.visible: hover.hovered
            ToolTip.text: Logic.tooltipText(text)
            HoverHandler { id: hover }
        }
        Item { Layout.fillHeight: true }
        RowLayout {
            IconButton { symbol: "refresh"; description: "Check for updates"; enabled: !DesktopState.checkingUpdates; onClicked: DesktopState.checkUpdates() }
            InkLabel { text: "Check again"; color: "#e6a6c7"; font.pixelSize: 12 }
            Item { Layout.fillWidth: true }
            InkLabel { text: "Review in terminal"; color: "#e6a6c7"; font.pixelSize: 12 }
            IconButton { symbol: "open"; description: "Review packages in terminal"; onClicked: DesktopState.reviewUpdates() }
        }
    }
}
