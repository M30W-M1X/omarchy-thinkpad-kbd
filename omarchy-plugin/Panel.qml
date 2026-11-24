import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

Panel {
  id: root
  moduleName: "thinkpad.kbd"
  ipcTarget: "thinkpad.kbd"
  manageIpc: false

  Commons.Translations {
    id: strings
    directory: Qt.resolvedUrl("i18n")
  }

  property bool daemonRunning: false
  property bool adaptiveEnabled: true
  property string mode: "adaptive"
  property string activityState: "idle"
  property bool activityActive: false
  property int level: 0
  property int restingLevel: 0

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color accent: Commons.Color.accent
  readonly property color urgent: bar ? bar.urgent : Commons.Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color barIconColor: daemonRunning && adaptiveEnabled ? barForeground : Qt.darker(barForeground, 1.55)

  readonly property var previewEffects: [
    { id: "think", state: "thinking", key: "effect.think" },
    { id: "run", state: "tool_command", key: "effect.run" },
    { id: "edit", state: "tool_edit", key: "effect.edit" },
    { id: "read", state: "tool_read", key: "effect.read" },
    { id: "agent", state: "tool_agent", key: "effect.agent" },
    { id: "error", state: "error", key: "effect.error" },
    { id: "attention", state: "attention", key: "effect.attention" },
    { id: "done", state: "complete", key: "effect.done" }
  ]

  function stateLabel() {
    if (!daemonRunning) return strings.t("state.stopped")
    if (!adaptiveEnabled && !activityActive) return strings.t("state.paused")
    return strings.t("state." + activityState)
  }

  function applyStatusJson(raw) {
    var trimmed = String(raw || "").trim()
    if (trimmed === "") return
    try {
      var data = JSON.parse(trimmed)
      if (typeof data !== "object" || data === null) return
      daemonRunning = data.running === true
      adaptiveEnabled = data.enabled === true
      if (typeof data.mode === "string") mode = data.mode
      if (typeof data.state === "string") activityState = data.state
      activityActive = data.active === true
      if (typeof data.level === "number") level = Math.max(0, Math.min(2, Math.round(data.level)))
      if (typeof data.resting_level === "number") restingLevel = Math.max(0, Math.min(2, Math.round(data.resting_level)))
    } catch (e) {
      daemonRunning = false
    }
  }

  function refresh() {
    if (!statusProc.running) statusProc.running = true
  }

  function runCli(args) {
    if (actionProc.running) return
    actionProc.command = ["omarchy-thinkpad-kbd"].concat(args).concat(["--json"])
    actionProc.running = true
  }

  function toggleAdaptive() {
    runCli(["toggle"])
  }

  function setMode(nextMode) {
    runCli(["mode", nextMode])
  }

  function setLevel(nextLevel) {
    runCli(["level", String(nextLevel)])
  }

  function previewEffect(effectId) {
    runCli(["preview", effectId])
  }

  Component.onCompleted: refresh()

  onOpenedChanged: if (opened) refresh()

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: statusProc
    command: ["omarchy-thinkpad-kbd", "status", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyStatusJson(text)
    }
  }

  Process {
    id: actionProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyStatusJson(text)
    }
  }

  Timer {
    interval: root.opened || root.activityActive ? 450 : 1400
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  ShellIpc {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function toggleAdaptive(): string { root.toggleAdaptive(); return "ok" }
    function status(): string { return root.activityState }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    iconComponent: Component {
      Item {
        KbdIcon {
          x: (parent.width - width) / 2
          y: (parent.height - height) / 2
          iconSize: button.iconSize
          color: root.barIconColor
          accentColor: root.activityState === "error" ? root.urgent : root.accent
          active: root.activityActive
          enabled: root.daemonRunning && root.adaptiveEnabled
          level: root.level
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) root.toggleAdaptive()
      else if (buttonCode === Qt.MiddleButton) root.refresh()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: panel.loadedContent
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(panel.loadedContentHeight)

    content: PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      implicitHeight: column.implicitHeight
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(12)

        PanelHero {
          id: hero
          width: parent.width
          title: strings.t("title")
          meta: root.stateLabel()
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconOpacity: root.daemonRunning ? 1.0 : 0.45

          iconComponent: Component {
            KbdIcon {
              iconSize: Style.font.display
              color: root.foreground
              accentColor: root.activityState === "error" ? root.urgent : root.accent
              active: root.activityActive
              enabled: root.daemonRunning && root.adaptiveEnabled
              level: root.level
            }
          }

          trailingControl: Component {
            ToggleSwitch {
              id: adaptiveSwitch
              checked: root.daemonRunning && root.adaptiveEnabled
              foreground: hero.foreground
              onToggled: root.toggleAdaptive()

              PanelToolTip {
                visible: adaptiveSwitch.containsMouse
                text: root.adaptiveEnabled ? strings.t("toggle.disable") : strings.t("toggle.enable")
                fontFamily: hero.fontFamily
              }
            }
          }
        }

        Text {
          visible: !root.daemonRunning
          width: parent.width
          text: strings.t("status.daemonStopped")
          textFormat: Text.PlainText
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        PanelSeparator {
          foreground: root.foreground
        }

        // Backlight resting level selector (0 / 1 / 2)
        Column {
          width: parent.width
          spacing: Style.space(8)

          PanelSectionHeader {
            text: strings.t("section.level")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Row {
            id: levelRow
            width: parent.width
            spacing: Style.space(6)
            readonly property real cellWidth: (width - spacing * 2) / 3

            Repeater {
              model: [
                { val: 0, key: "level.off" },
                { val: 1, key: "level.dim" },
                { val: 2, key: "level.bright" }
              ]
              Button {
                required property var modelData
                width: levelRow.cellWidth
                text: strings.t(modelData.key)
                fontSize: Style.font.bodySmall
                foreground: root.foreground
                fontFamily: root.fontFamily
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY
                bordered: true
                active: root.restingLevel === modelData.val
                onClicked: root.setLevel(modelData.val)
              }
            }
          }
        }

        PanelSeparator {
          foreground: root.foreground
        }

        // Mode selector (Adaptive / Static / Off)
        Column {
          width: parent.width
          spacing: Style.space(8)

          PanelSectionHeader {
            text: strings.t("section.mode")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Row {
            id: modeRow
            width: parent.width
            spacing: Style.space(6)
            readonly property real cellWidth: (width - spacing * 2) / 3

            Repeater {
              model: [
                { id: "adaptive", key: "mode.adaptive" },
                { id: "static", key: "mode.static" },
                { id: "off", key: "mode.off" }
              ]
              Button {
                required property var modelData
                width: modeRow.cellWidth
                text: strings.t(modelData.key)
                fontSize: Style.font.bodySmall
                foreground: root.foreground
                fontFamily: root.fontFamily
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY
                bordered: true
                active: root.mode === modelData.id
                onClicked: root.setMode(modelData.id)
              }
            }
          }
        }

        PanelSeparator {
          foreground: root.foreground
        }

        // Effect previews
        Column {
          width: parent.width
          spacing: Style.space(8)

          PanelSectionHeader {
            text: strings.t("section.preview")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Grid {
            id: previewGrid
            width: parent.width
            columns: 4
            spacing: Style.space(6)
            readonly property real cellWidth: (width - spacing * (columns - 1)) / columns

            Repeater {
              model: root.previewEffects
              Button {
                required property var modelData
                width: previewGrid.cellWidth
                text: strings.t(modelData.key)
                fontSize: Style.font.bodySmall
                foreground: root.foreground
                fontFamily: root.fontFamily
                horizontalPadding: Style.space(6)
                verticalPadding: Style.spacing.controlPaddingY
                bordered: true
                active: root.activityActive && root.activityState === modelData.state
                onClicked: root.previewEffect(modelData.id)
              }
            }
          }
        }
      }
    }
  }
}
