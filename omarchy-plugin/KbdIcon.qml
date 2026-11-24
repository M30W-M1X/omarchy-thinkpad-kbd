import QtQuick
import qs.Commons

Item {
  id: root

  property real iconSize: 16
  property color color: Color.foreground
  property color accentColor: Color.accent
  property bool active: false
  property bool enabled: true
  property int level: 0

  implicitWidth: Math.round(iconSize * 1.15)
  implicitHeight: Math.round(iconSize)
  width: implicitWidth
  height: implicitHeight

  readonly property real stroke: Math.max(1.2, iconSize * 0.095)
  readonly property real bodyWidth: Math.round(iconSize * 1.05)
  readonly property real bodyHeight: Math.round(iconSize * 0.62)

  // Subtle top glow rays when backlight level > 0 or animating
  Row {
    id: rays
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: kbdBody.top
    anchors.bottomMargin: Math.max(1, Math.round(root.iconSize * 0.08))
    spacing: Math.max(2, Math.round(root.iconSize * 0.16))
    opacity: root.active ? 1.0 : (root.level === 2 ? 0.95 : (root.level === 1 ? 0.5 : 0.15))

    Behavior on opacity { NumberAnimation { duration: Style.duration(160); easing.type: Easing.OutCubic } }

    Repeater {
      model: 3
      Rectangle {
        required property int index
        width: Math.max(1.4, root.stroke)
        height: index === 1 ? Math.max(3, Math.round(root.iconSize * 0.20)) : Math.max(2, Math.round(root.iconSize * 0.14))
        radius: width / 2
        color: root.active ? root.accentColor : root.color
        anchors.bottom: parent.bottom
      }
    }
  }

  // Minimal geometric keyboard chassis
  Rectangle {
    id: kbdBody
    width: root.bodyWidth
    height: root.bodyHeight
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: Math.max(1, Math.round(root.iconSize * 0.06))
    radius: Math.max(1.5, Math.round(root.iconSize * 0.12))
    color: "transparent"
    border.width: root.stroke
    border.color: root.color
    opacity: root.enabled ? 1.0 : 0.5

    // Keycaps row
    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.top: parent.top
      anchors.topMargin: Math.max(2, Math.round(parent.height * 0.24))
      spacing: Math.max(1.5, Math.round(parent.width * 0.10))

      Repeater {
        model: 3
        Rectangle {
          width: Math.max(2, Math.round(kbdBody.width * 0.14))
          height: Math.max(1.5, Math.round(kbdBody.height * 0.16))
          radius: 0.8
          color: root.color
        }
      }
    }

    // Spacebar
    Rectangle {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Math.max(2, Math.round(parent.height * 0.20))
      width: Math.max(4, Math.round(parent.width * 0.48))
      height: Math.max(1.5, Math.round(parent.height * 0.15))
      radius: 0.8
      color: root.active ? root.accentColor : root.color
    }
  }

  // Pulsing live activity dot when AGY is working
  Rectangle {
    id: liveDot
    visible: root.active
    width: Math.max(4, Math.round(root.iconSize * 0.26))
    height: width
    radius: width / 2
    color: root.accentColor
    anchors.right: parent.right
    anchors.top: parent.top

    SequentialAnimation on opacity {
      running: root.active && !Style.reduceMotion
      loops: Animation.Infinite
      NumberAnimation { from: 1.0; to: 0.25; duration: Style.duration(260); easing.type: Easing.OutCubic }
      NumberAnimation { from: 0.25; to: 1.0; duration: Style.duration(260); easing.type: Easing.OutCubic }
    }
  }
}
