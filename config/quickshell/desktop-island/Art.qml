import QtQuick
import Quickshell.Widgets

ClippingRectangle {
    id: art
    property url source: ""
    radius: 8
    color: "#453244"
    Icon { anchors.centerIn: parent; width: parent.width * 0.4; height: width; color: "#e6a6c7" }
    Image {
        anchors.fill: parent
        source: art.source
        asynchronous: true
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: 240
        sourceSize.height: 240
        visible: status === Image.Ready
    }
}
