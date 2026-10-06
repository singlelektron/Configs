import QtQuick

Canvas {
    id: icon
    property string name: "music"
    property color color: "#eee5ef"
    implicitWidth: 18
    implicitHeight: 18
    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        var c = getContext("2d"); c.reset();
        c.scale(width / 24, height / 24);
        c.strokeStyle = color; c.fillStyle = color;
        c.lineWidth = 1.6; c.lineCap = "round"; c.lineJoin = "round";
        function line(points) {
            c.beginPath(); c.moveTo(points[0], points[1]);
            for (var i = 2; i < points.length; i += 2) c.lineTo(points[i], points[i + 1]);
            c.stroke();
        }
        function circle(x, y, r) { c.beginPath(); c.arc(x, y, r, 0, 2 * Math.PI); c.stroke(); }
        switch (name) {
        case "controls":
            line([3,6,21,6]); line([3,18,21,18]); line([8,3,8,9]); line([16,15,16,21]); break;
        case "search": circle(10,10,6); line([15,15,21,21]); break;
        case "play": line([8,5,19,12,8,19,8,5]); break;
        case "pause": line([8,5,8,19]); line([16,5,16,19]); break;
        case "next": line([5,5,15,12,5,19,5,5]); line([19,5,19,19]); break;
        case "previous": line([19,5,9,12,19,19,19,5]); line([5,5,5,19]); break;
        case "open": line([7,5,3,5,3,21,19,21,19,17]); line([12,3,21,3,21,12]); line([10,14,21,3]); break;
        case "close": line([6,6,18,18]); line([6,18,18,6]); break;
        case "volume":
        case "muted":
            line([3,9,7,9,12,5,12,19,7,15,3,15,3,9]);
            if (name === "muted") { line([17,9,22,15]); line([22,9,17,15]); }
            else { c.beginPath(); c.arc(12,12,6,-0.8,0.8); c.stroke(); c.beginPath(); c.arc(12,12,10,-0.8,0.8); c.stroke(); } break;
        case "wifi":
            c.beginPath(); c.arc(12,20,17,-2.25,-0.89); c.stroke();
            c.beginPath(); c.arc(12,20,11,-2.25,-0.89); c.stroke();
            c.beginPath(); c.arc(12,20,5,-2.25,-0.89); c.stroke(); circle(12,20,0.6); break;
        case "wired": line([5,3,19,3,19,14,5,14,5,3]); line([12,14,12,21]); line([6,21,18,21]); break;
        case "offline": circle(12,12,9); line([5,19,19,5]); break;
        case "battery": line([2,6,19,6,19,18,2,18,2,6]); line([22,10,22,14]); break;
        case "chevron": line([5,14,12,7,19,14]); break;
        case "update": line([12,3,12,15]); line([7,10,12,15,17,10]); line([4,17,4,21,20,21,20,17]); break;
        case "refresh": c.beginPath(); c.arc(12,12,8,0.4,5.4); c.stroke(); line([17,3,17,8,22,8]); break;
        default: line([10,17,10,5,20,3,20,15]); circle(6.5,18,3.5); circle(16.5,16,3.5); break;
        }
    }
}
