import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Klassenzimmer als echtes Leisten-Panel (wie Netzwerk, Bluetooth, Claude-Tab).
// Leiste: Schul-Zeichen in Statusfarbe (grün online, gelb nicht stören,
// grau läuft nicht), Coach mit offenen Fragen: orange + Zahl.
// Klick = Panel auf/zu (Klick daneben oder Esc schliesst), Rechtsklick = Status.
//
// Daten: ~/.cache/klassenzimmer/zustand.json (schreibt die App ab Version 2.1).
// Befehle: klassenzimmer --status-umschalten | --hilfe TEXT | --erledigt ID |
//          --entfernen ID | --erweiterung ID; Klasse wechseln / Starten / Beenden über
//          ~/.local/bin/klassenzimmer-leiste.
// Erweiterung (ab 2.3): Hat die App eine erweiterung.py geladen, stehen ihre
// Knöpfe und Zeilen in st.extra und erscheinen hier unter dem Kopf.
Panel {
  id: root
  moduleName: "c1llsh0t.klassenzimmer"
  ipcTarget: "c1llsh0t.klassenzimmer"
  manageIpc: false

  readonly property string home: Quickshell.env("HOME") || ""
  readonly property string app: home + "/.local/bin/klassenzimmer"
  readonly property string helper: home + "/.local/bin/klassenzimmer-leiste"
  readonly property string stateFile: (Quickshell.env("XDG_CACHE_HOME") || (home + "/.cache")) + "/klassenzimmer/zustand.json"
  readonly property string controlPort: Quickshell.env("KLASSENZIMMER_STEUERPORT") || "50507"

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color urgent: bar ? bar.urgent : Commons.Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color helpColor: "#f76b15"
  readonly property var statusColors: ({ online: "#2e9e44", busy: "#e0b000", offline: "#9a9a9a" })
  readonly property var statusNames: ({ online: "Online", busy: "Nicht stören", offline: "Offline" })

  property bool running: false
  property var st: null
  property bool quitArmed: false
  property bool changeArmed: false
  property string removeArmed: ""
  property string copied: ""

  readonly property bool live: running && st !== null
  readonly property bool isCoach: live && st.role === "coach"
  readonly property var peers: live && st.peers ? st.peers : []
  readonly property var queue: live && st.queue ? st.queue : []
  readonly property var requests: live && st.requests ? st.requests : []
  readonly property var extra: live && st.extra ? st.extra : null
  readonly property int onlineCount: {
    var n = 0
    for (var i = 0; i < peers.length; i++) if (peers[i].status !== "offline") n++
    return n
  }
  readonly property string reqState: {
    var order = ["acked", "sending", "failed", "done"]
    for (var o = 0; o < order.length; o++)
      for (var i = 0; i < requests.length; i++) if (requests[i].state === order[o]) return order[o]
    return ""
  }
  readonly property color myColor: live ? (statusColors[st.status] || dim) : dim
  readonly property color barIconColor: {
    if (!live) return Qt.darker(barForeground, 1.8)
    if (isCoach && queue.length > 0) return helpColor
    return statusColors[st.status] || barForeground
  }
  readonly property string hoverText: {
    if (!running) return "Klassenzimmer läuft nicht"
    if (!st) return "Klassenzimmer"
    var t = "Klassenzimmer · " + statusNames[st.status] + " · " + onlineCount + " andere online"
    if (isCoach && queue.length > 0) t += " · " + queue.length + " offene Frage(n)"
    return t
  }

  function run(args) { Quickshell.execDetached([root.app].concat(args)); soon.restart() }
  function leiste(arg) { Quickshell.execDetached([root.helper, arg]); soon.restart() }
  function toggleStatus() { if (live) run(["--status-umschalten"]) }
  function askHelp() {
    if (!live || isCoach) return
    run(["--hilfe", questionField.text.trim()])
    questionField.text = ""
  }
  function copyCode() {
    if (!live) return
    Quickshell.execDetached(["wl-copy", st.code])
    copied = "Code kopiert ✓"
    copiedTimer.restart()
  }
  function refresh() {
    if (!probe.running) probe.running = true
    stateView.reload()
  }
  function requestLine(r) {
    if (r.state === "sending") return r.coach + ": wird gesendet … (Versuch " + r.tries + "/" + (st.max_tries || 5) + ")"
    if (r.state === "acked") return r.coach + ": ✓ angekommen"
    if (r.state === "failed") return r.coach + ": ✗ nicht angekommen, bitte nochmal versuchen"
    if (r.state === "done") return r.coach + ": ✓ erledigt"
    return r.coach
  }
  function requestColor(r) {
    if (r.state === "acked" || r.state === "done") return statusColors.online
    if (r.state === "failed") return urgent
    return dim
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: {
    quitArmed = false; changeArmed = false; removeArmed = ""
    if (opened) {
      refresh()
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    }
  }

  // Läuft die App? (Sie hält den Steuer-Port auf 127.0.0.1.)
  Process {
    id: probe
    command: ["bash", "-c", "(exec 3<>/dev/tcp/127.0.0.1/" + root.controlPort + ") 2>/dev/null && echo RUN || echo OFF"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.running = String(text || "").trim() === "RUN"
    }
  }

  FileView {
    id: stateView
    path: root.stateFile
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        var parsed = JSON.parse(String(text() || ""))
        root.st = parsed && typeof parsed === "object" ? parsed : null
      } catch (e) { root.st = null }
    }
    onLoadFailed: root.st = null
  }

  Timer { interval: root.opened ? 1000 : 3000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refresh() }
  Timer { id: soon; interval: 400; onTriggered: root.refresh() }
  Timer { id: copiedTimer; interval: 1500; onTriggered: root.copied = "" }
  Timer { id: armTimer; interval: 4000; onTriggered: { root.quitArmed = false; root.changeArmed = false; root.removeArmed = "" } }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function status(): string { return root.hoverText }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰑴"
    foreground: root.barIconColor
    tooltipText: root.opened ? "" : root.hoverText
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) root.toggleStatus()
      else root.toggle()
    }

    // Coach: Anzahl offener Fragen als kleines Abzeichen
    Rectangle {
      visible: root.isCoach && root.queue.length > 0
      width: Math.max(height, badgeText.implicitWidth + Style.space(6))
      height: Style.space(13)
      radius: height / 2
      color: root.helpColor
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.rightMargin: Style.space(1)
      anchors.topMargin: Style.space(2)
      Text {
        id: badgeText
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: String(root.queue.length)
        color: "white"
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }

    // Schüler: Zeichen pulsiert, solange die Hilfe unterwegs ist
    SequentialAnimation on opacity {
      running: root.reqState === "sending"
      loops: Animation.Infinite
      onRunningChanged: if (!running) button.opacity = 1
      NumberAnimation { to: 0.35; duration: 600; easing.type: Easing.InOutSine }
      NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutSine }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: questionField.activeFocus
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "s" || t === "S") root.toggleStatus()
        else if ((t === "h" || t === "H") && root.live && !root.isCoach) questionField.forceActiveFocus()
        // Taste P: Extras aus-/einblenden (geht auch, wenn sie gerade versteckt sind)
        else if ((t === "p" || t === "P") && root.live) root.run(["--erweiterung-umschalten"])
      }

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: flick.width
          spacing: Style.space(12)

          component Line: Text {
            textFormat: Text.PlainText
            width: column.width
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          // ---- Kopf: Name, Rolle, Klasse, Code + Status-Knopf ----
          PanelHero {
            id: hero
            width: parent.width
            title: root.live ? root.st.name : "Klassenzimmer"
            meta: {
              if (!root.running) return "läuft nicht"
              if (!root.st) return "startet …"
              return (root.isCoach ? "Coach" : "Schüler/in") + (root.st.klasse ? " · " + root.st.klasse : "")
            }
            detail: root.live ? (root.copied !== "" ? root.copied : "Code " + root.st.code) : ""
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconComponent: Component {
              Text {
                textFormat: Text.PlainText
                text: "󰑴"
                color: root.live ? root.myColor : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
              }
            }
            // Geheim: 3x schnell auf den Namen -> Extras aus-/einblenden (nur Plus).
            // Keine Beschriftung, damit der Coach es nicht bemerkt. Lässt den
            // Status-Knopf rechts frei.
            MouseArea {
              anchors.left: hero.left
              anchors.top: hero.top
              anchors.bottom: hero.bottom
              anchors.right: hero.right
              anchors.rightMargin: Style.space(72)
              acceptedButtons: Qt.LeftButton
              property int klicks: 0
              Timer { id: nameKlick; interval: 600; onTriggered: parent.klicks = 0 }
              onClicked: {
                klicks += 1
                nameKlick.restart()
                if (klicks >= 3) { klicks = 0; if (root.live) root.run(["--erweiterung-umschalten"]) }
              }
            }
            trailingControl: Component {
              Button {
                visible: root.live
                iconText: "●"
                text: root.live ? root.statusNames[root.st.status] : ""
                foreground: root.myColor
                tooltipText: "Status wechseln (Rechtsklick aufs Zeichen geht auch)"
                onClicked: root.toggleStatus()
              }
            }
          }

          // ---- Erweiterung (erweiterung.py): Zeilen + Knöpfe ----
          Column {
            visible: root.extra !== null
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader {
              text: root.extra && root.extra.title ? String(root.extra.title).toUpperCase() : "EXTRAS"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }
            Repeater {
              model: root.extra && root.extra.info ? root.extra.info : []
              Line { text: modelData; color: root.helpColor }
            }
            Flow {
              width: parent.width
              spacing: Style.space(6)
              Repeater {
                model: root.extra && root.extra.buttons ? root.extra.buttons : []
                Button {
                  text: modelData.text
                  foreground: root.foreground
                  bordered: true
                  onClicked: root.run(["--erweiterung", modelData.id])
                }
              }
            }
          }

          PanelSeparator { visible: root.extra !== null; foreground: root.foreground }

          // ---- Läuft nicht ----
          Column {
            visible: !root.live
            width: parent.width
            spacing: Style.space(8)
            Line {
              color: root.dim
              text: root.running ? "Die App startet gerade oder ist noch nicht eingerichtet."
                                 : "Klassenzimmer ist nicht gestartet."
            }
            Button {
              visible: !root.running
              iconText: "󰐊"
              text: "Starten"
              foreground: root.foreground
              onClicked: root.leiste("start")
            }
          }

          // ---- Teilnehmer ----
          Column {
            visible: root.live
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader {
              text: "TEILNEHMER · " + root.onlineCount + " ONLINE"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Line {
              visible: root.peers.length === 0
              color: root.dim
              text: "Noch niemand gefunden …" + (root.live && root.st.searching_long
                    ? "\nStimmt der Code? Haben alle Version " + root.st.version + "?"
                      + (root.st.internet === false ? "\nInternet-Weg: keine Verbindung (nur WLAN)" : "")
                    : "")
            }

            Repeater {
              model: root.peers
              Item {
                width: column.width
                height: Math.max(nameText.implicitHeight, Style.space(20))
                readonly property bool off: modelData.status === "offline"

                Rectangle {
                  id: peerDot
                  width: Style.space(9); height: width; radius: width / 2
                  anchors.left: parent.left
                  anchors.verticalCenter: parent.verticalCenter
                  color: root.statusColors[modelData.status] || root.dim
                }
                Text {
                  id: nameText
                  textFormat: Text.PlainText
                  anchors.left: peerDot.right
                  anchors.leftMargin: Style.space(8)
                  anchors.right: peerRight.left
                  anchors.rightMargin: Style.space(6)
                  anchors.verticalCenter: parent.verticalCenter
                  elide: Text.ElideRight
                  text: modelData.name + (modelData.role === "coach" ? "  · Coach" : "")
                  color: parent.off ? root.dim : root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: modelData.role === "coach"
                }
                Row {
                  id: peerRight
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(6)
                  Text {
                    anchors.verticalCenter: parent.verticalCenter
                    textFormat: Text.PlainText
                    text: root.statusNames[modelData.status] || ""
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                  PanelActionButton {
                    visible: modelData.status === "offline" && root.isCoach   // nur der Coach darf entfernen
                    anchors.verticalCenter: parent.verticalCenter
                    iconText: root.removeArmed === modelData.id ? "󰗠" : "󰅖"
                    foreground: root.removeArmed === modelData.id ? root.urgent : root.dim
                    tooltipText: root.removeArmed === modelData.id ? "Nochmal klicken: entfernen" : "Aus der Klassenliste entfernen"
                    onClicked: {
                      if (root.removeArmed !== modelData.id) { root.removeArmed = modelData.id; armTimer.restart(); return }
                      root.removeArmed = ""
                      root.run(["--entfernen", modelData.id])
                    }
                  }
                }
              }
            }
          }

          PanelSeparator { visible: root.live; foreground: root.foreground }

          // ---- Schüler: Coach um Hilfe fragen ----
          Column {
            visible: root.live && !root.isCoach
            width: parent.width
            spacing: Style.space(8)

            PanelSectionHeader {
              text: "COACH UM HILFE FRAGEN"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }
            TextField {
              id: questionField
              width: parent.width
              placeholderText: "Frage (optional), Enter = senden"
              foreground: root.foreground
              maximumLength: 300
              onAccepted: root.askHelp()
              Keys.onEscapePressed: { if (text !== "") text = ""; else keyCatcher.forceActiveFocus() }
            }
            Button {
              width: parent.width
              iconText: "✋"
              text: "Coach um Hilfe fragen"
              foreground: root.helpColor
              bordered: true
              onClicked: root.askHelp()
            }
            Repeater {
              model: root.requests
              Line { text: root.requestLine(modelData); color: root.requestColor(modelData) }
            }
            Line {
              visible: root.live && !!root.st.info
              text: root.live ? (root.st.info || "") : ""
              color: root.urgent
            }
          }

          // ---- Coach: Warteschlange ----
          Column {
            visible: root.isCoach
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader {
              text: "HILFEANFRAGEN · ÄLTESTE ZUERST"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }
            Line {
              visible: root.queue.length === 0
              color: root.dim
              text: "Keine offenen Anfragen."
            }
            Repeater {
              model: root.queue
              Item {
                width: column.width
                height: Math.max(qText.implicitHeight, doneBtn.implicitHeight)
                Text {
                  id: qText
                  textFormat: Text.PlainText
                  anchors.left: parent.left
                  anchors.right: doneBtn.left
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  wrapMode: Text.WordWrap
                  text: (index + 1) + ". " + modelData.time + "  " + modelData.name + (modelData.text ? ": " + modelData.text : "")
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                }
                Button {
                  id: doneBtn
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: "󰄬"
                  text: "Erledigt"
                  foreground: root.statusColors.online
                  onClicked: root.run(["--erledigt", modelData.id])
                }
              }
            }
          }

          PanelSeparator { visible: root.live; foreground: root.foreground }

          // ---- Unten: Code kopieren, Klasse wechseln, Beenden ----
          Flow {
            visible: root.running
            width: parent.width
            spacing: Style.space(6)
            Button {
              visible: root.live
              iconText: "󰆏"
              text: "Code kopieren"
              foreground: root.foreground
              onClicked: root.copyCode()
            }
            Button {
              iconText: "󰑴"
              text: root.changeArmed ? "Wirklich? Neuer Code …" : "Klasse wechseln"
              active: root.changeArmed
              foreground: root.foreground
              onClicked: {
                if (!root.changeArmed) { root.changeArmed = true; armTimer.restart(); return }
                root.changeArmed = false
                root.close()
                root.leiste("neu")
              }
            }
            Button {
              iconText: "󰅖"
              text: root.quitArmed ? "Wirklich beenden?" : "Beenden"
              active: root.quitArmed
              foreground: root.foreground
              onClicked: {
                if (!root.quitArmed) { root.quitArmed = true; armTimer.restart(); return }
                root.quitArmed = false
                root.leiste("beenden")
              }
            }
          }
        }
      }
    }
  }
}
