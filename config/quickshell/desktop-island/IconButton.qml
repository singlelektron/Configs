import QtQuick
import QtQuick.Controls
import "logic.js" as Logic

Button {
    id: button
    property string symbol: "music"
    property string description: ""
    property color ink: "#eee5ef"
    property bool selected: false
    implicitWidth: 32
    implicitHeight: 32
    padding: 7
    Accessible.name: description
    hoverEnabled: true
    background: Rectangle {
        radius: 12
        color: button.selected || button.down ? "#55364d" : button.hovered ? "#382d3e" : "transparent"
        border.width: button.visualFocus ? 1 : 0
        border.color: "#e6a6c7"
    }
    contentItem: Icon { name: button.symbol; color: button.enabled ? button.ink : "#766c7b" }
    ToolTip.visible: hovered && description.length > 0
    ToolTip.text: Logic.tooltipText(description)
    ToolTip.delay: 700
}
