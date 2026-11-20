# Klassenzimmer

Eine Peer-to-Peer-App fürs Klassenzimmer: Alle Rechner im selben WLAN/LAN sehen sich gegenseitig, **ohne eigenen Server**. Trennt das WLAN die Geräte voneinander (wie viele Schul-WLANs), geht es ab Version 2.3 automatisch verschlüsselt übers Internet. Schüler fragen den Coach per Knopfdruck um Hilfe, und der Coach sieht alle Anfragen in einer Warteschlange.

- 🔑 **Beitrittscode:** Der Coach erzeugt einen Code (z.B. `K7Q-M3X`), die Schüler geben ihn ein. Nur wer den Code kennt, gehört zur Klasse.
- 🟢 online · 🟡 nicht stören · ⚪ offline (20 Sekunden nichts gehört)
- **klein statt gross:** unter Windows, Mac und Linux eine kleine Leiste am Bildschirmrand, unter **Omarchy** ein Panel oben in der Leiste (wie WLAN und Bluetooth)
- die Klasse wird gespeichert, sodass am nächsten Tag alle schon in der Liste stehen
- Autostart beim Anmelden, danach muss man nichts mehr tun

**Download:** unter **[Releases](../../releases/latest)** die Datei für dein System holen. Python braucht man dafür nicht.

**Omarchy mit einem Befehl**: App plus Panel in der Leiste (wie WLAN und Bluetooth), im Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-omarchy.sh | bash
```

**Linux mit einem Befehl** (Ubuntu, Debian, Mint, Fedora, Arch …), im Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-linux.sh | bash
```

**Windows / Mac:** Datei aus den **[Releases](../../releases/latest)** laden und starten (Details unten).

**Aktualisieren:** denselben Befehl nochmal ausführen bzw. die neue Datei laden.

### 📣 Zum Weitergeben an die Klasse

Diesen Text kann der Coach in den Klassenchat kopieren (`<CODE>` durch den eigenen Beitrittscode ersetzen):

```text
Klassenzimmer installieren 🏫

Omarchy (App + Panel oben in der Leiste), im Terminal eingeben:
curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-omarchy.sh | bash

Anderes Linux (Ubuntu, Fedora, Arch …), im Terminal eingeben:
curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-linux.sh | bash

Windows / Mac: Datei herunterladen und starten:
https://github.com/c1llsh0t/Klassen-Status/releases/latest

Im Startfenster eintragen:
  Name: dein Name
  Rolle: Schüler/in
  Code: <CODE>
Dann "Los geht's". Danach startet es jeden Tag von selbst.
Wenn du Hilfe brauchst: Klassenzimmer öffnen und "Coach um Hilfe fragen".
```

---

## 🤖 Zu faul? Lass Claude alles installieren

Kopiere den passenden Text in **Claude** (Claude Code oder die Claude-App mit Zugriff auf deinen Computer). Claude fragt dich einmal nach Name, Rolle und Code und erledigt dann **alles** selbst. Funktioniert auch zum **Aktualisieren**.

### 🟢 Omarchy (App + Panel in der Leiste)

```text
Installiere die App "Klassenzimmer" auf diesem Omarchy-Computer. Mach alles selbst.
Frag mich nur EINMAL ganz am Anfang (alles in einer einzigen Frage):
  - meinen Namen
  - ob ich "student" oder "coach" bin
  - student: den Beitrittscode vom Coach (6 Zeichen, z.B. K7Q-M3X)
  - coach: den Klassennamen (z.B. INF3a) und meinen Code, falls ich schon einen habe
    (sonst NEU, dann erzeugt die App einen)

Dann führe diesen einen Befehl aus (Platzhalter ersetzen, --klasse nur beim Coach):

  curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-omarchy.sh | bash -s -- \
    --name "<Name>" --role <student|coach> --code <Code|NEU> --klasse "<Klasse>"

Das Skript lädt die App herunter, beendet eine alte Version, gibt die Firewall frei,
legt Autostart und App-Menü an, setzt das Klassenzimmer-Panel in die Leiste und
startet die App. Am Ende steht "✔ Fertig".
  - Steht da "Firewall nicht freigegeben": zeig mir den sudo-Befehl, den das Skript
    ausgibt, zum Kopieren (ich tippe ihn selbst in ein Terminal). Sonst nichts tun.
  - Bei einer Fehlermeldung: lesen, Ursache beheben, den Befehl nochmal ausführen.
  - Die Leiste (shell.json) und hyprland.lua NICHT von Hand ändern, das macht das Skript.

Zum Schluss kurz sagen, dass alles fertig ist: oben rechts in der Leiste ist das
Schul-Zeichen, Klick öffnet das Panel. Beim Coach den Beitrittscode gross anzeigen
(steht im Kasten in der Ausgabe).
```

### 🐧 Linux (Ubuntu, Fedora, Arch …, benutzt den Installer)

```text
Installiere die App "Klassenzimmer" auf diesem Linux-Computer. Mach alles selbst.
Frag mich nur EINMAL ganz am Anfang (alles in einer einzigen Frage):
  - meinen Namen
  - ob ich "student" oder "coach" bin
  - student: den Beitrittscode vom Coach (6 Zeichen, z.B. K7Q-M3X)
  - coach: den Klassennamen (z.B. INF3a) und meinen Code, falls ich schon einen habe
    (sonst NEU, dann erzeugt die App einen)

Dann führe diesen einen Befehl aus (Platzhalter ersetzen, --klasse nur beim Coach):

  curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-linux.sh | bash -s -- \
    --name "<Name>" --role <student|coach> --code <Code|NEU> --klasse "<Klasse>"

Das Skript lädt die App herunter, beendet eine alte Version, gibt die Firewall frei,
legt Autostart und App-Menü an und startet die App. Am Ende steht "✔ Fertig".
  - Steht da "Firewall nicht freigegeben": zeig mir den sudo-Befehl, den das Skript
    ausgibt, zum Kopieren (ich tippe ihn selbst in ein Terminal). Sonst nichts tun.
  - Bei einer Fehlermeldung: lesen, Ursache beheben, den Befehl nochmal ausführen.

Ist das hier Omarchy (Befehl "omarchy" vorhanden), stattdessen install-omarchy.sh mit
denselben Angaben nehmen, dann kommt Klassenzimmer zusätzlich als Panel in die Leiste.

Zum Schluss nur kurz sagen, dass alles fertig ist. Beim Coach den Beitrittscode gross
anzeigen (steht im Kasten in der Ausgabe).
```

### 🪟🍎 Windows, Mac (und Linux ohne Installer)

```text
Installiere die App "Klassenzimmer" komplett auf diesem Computer. Mach alles selbst,
ohne mich bei jedem Schritt zu fragen. Frag mich nur EINMAL ganz am Anfang:
  - meinen Namen
  - ob ich "student" oder "coach" bin
  - student: den Beitrittscode vom Coach (6 Zeichen, z.B. K7Q-M3X)
  - coach: den Klassennamen (z.B. INF3a) und ob ich schon einen Code habe
    (wenn nicht: --code NEU verwenden, die App erzeugt dann einen)

Dann:

1. Betriebssystem herausfinden (Windows, macOS oder Linux).

2. Falls Klassenzimmer schon läuft (Update): mit "<App> --beenden" beenden.

3. Herunterladen und an den festen Platz legen (Ordner anlegen, alte Version überschreiben):
   - Windows:
       https://github.com/c1llsh0t/Klassen-Status/releases/latest/download/Klassenzimmer-Windows.exe
       -> %LOCALAPPDATA%\Programs\Klassenzimmer\Klassenzimmer.exe
       danach in PowerShell: Unblock-File auf die exe (sonst blockiert SmartScreen)
   - macOS:
       https://github.com/c1llsh0t/Klassen-Status/releases/latest/download/Klassenzimmer-Mac.zip
       -> mit "ditto -x -k" entpacken nach /Applications/Klassenzimmer.app (alte vorher löschen)
       danach: xattr -dr com.apple.quarantine /Applications/Klassenzimmer.app
   - Linux:
       https://github.com/c1llsh0t/Klassen-Status/releases/latest/download/Klassenzimmer-Linux
       -> ~/.local/bin/klassenzimmer, danach chmod +x

4. Firewall freigeben (UDP-Ports 50505 und 50506):
   - Windows: eingehende Firewall-Regel "Klassenzimmer" für die exe, Protokoll UDP,
     Ports 50505-50506, alle Profile (netsh advfirewall firewall add rule ...).
     Braucht Admin-Rechte: per Start-Process -Verb RunAs ausführen, dann muss ich
     nur bei der Windows-Abfrage auf "Ja" klicken.
   - Linux: wenn ufw aktiv ist: sudo ufw allow 50505:50506/udp
            wenn firewalld aktiv ist: Ports 50505-50506/udp dauerhaft freigeben und neu laden
            (Falls sudo ein Passwort braucht, das du nicht eingeben kannst: gib mir genau
             den einen Befehl zum Kopieren und mach danach weiter.)
   - macOS: nichts zu tun.

5. Einrichten und starten. Das speichert alles, schaltet den Autostart ein und richtet
   unter Omarchy/Hyprland automatisch den Punkt in der Waybar ein. Die App im Hintergrund
   starten, damit sie weiterläuft, wenn du fertig bist:
     <App> --name "<Name>" --role <student|coach> --code <Code> --speichern
   Coach zusätzlich: --klasse "<Klasse>"   (und --code NEU, falls noch kein Code)
   <App> ist:
   - Windows: "%LOCALAPPDATA%\Programs\Klassenzimmer\Klassenzimmer.exe"
   - macOS:   /Applications/Klassenzimmer.app/Contents/MacOS/Klassenzimmer
   - Linux:   ~/.local/bin/klassenzimmer   (mit nohup oder setsid starten)

6. Prüfen:
   - läuft der Prozess?
   - gibt es den Autostart-Eintrag?
       Windows: Registry HKCU\Software\Microsoft\Windows\CurrentVersion\Run, Wert "klassenzimmer"
       macOS:   ~/Library/LaunchAgents/ch.klassenzimmer.app.plist
       Linux:   ~/.config/autostart/klassenzimmer.desktop
   - Linux mit Hyprland (z.B. Omarchy):
       steht "custom/klassenzimmer" in ~/.config/waybar/config.jsonc? Sonst
       "<App> --waybar-einrichten" ausführen.
       Fehlt in ~/.config/hypr/autostart.conf die Zeile
       "exec-once = ~/.local/bin/klassenzimmer --autostart", sie anhängen.
   Wenn etwas nicht klappt, selbst beheben und nochmal prüfen.

7. Zum Schluss nur kurz sagen, dass alles fertig ist. Beim Coach: den Beitrittscode gross
   anzeigen (steht in der Ausgabe von Schritt 5). Auf macOS zusätzlich: "Wenn gefragt wird,
   ob Klassenzimmer Geräte im lokalen Netzwerk finden darf: Erlauben klicken."
```

---

## 🪟 Installation: Windows

1. `Klassenzimmer-Windows.exe` herunterladen und in einen **festen Ordner** verschieben, z.B. `Dokumente\Klassenzimmer`. Nicht im Ordner *Downloads* lassen, denn der Autostart merkt sich den Ort.
2. Doppelklicken. Bei **„Der Computer wurde durch Windows geschützt“**: **Weitere Informationen → Trotzdem ausführen**.
3. Bei der Frage der Firewall: Häkchen bei **Private Netzwerke** und dann **Zugriff zulassen**.
   Das WLAN muss in Windows als *privat* eingestellt sein: *Einstellungen → Netzwerk und Internet → WLAN → (dein WLAN) → Netzwerkprofil: Privat*.
4. Im Startfenster Name, Rolle und Code eingeben, ✅ **„Beim Anmelden automatisch starten“** setzen, **Los geht's**.

Autostart prüfen oder ausschalten: Task-Manager (Ctrl+Shift+Esc) → **Autostart-Apps** → `klassenzimmer`.

## 🍎 Installation: Mac (Apple-Chip M1–M4)

1. `Klassenzimmer-Mac.zip` doppelklicken und `Klassenzimmer.app` in den Ordner **Programme** ziehen.
2. Die App öffnen. Beim ersten Mal wird sie blockiert, das ist normal. Mit **Fertig** schliessen.
3. **Systemeinstellungen → Datenschutz & Sicherheit**, ganz nach unten scrollen und **Dennoch öffnen** klicken, dann mit dem Passwort bestätigen. Ab macOS 15 geht „Rechtsklick → Öffnen“ nicht mehr.
4. Bei „… möchte Geräte in deinem lokalen Netzwerk finden“: **Erlauben**. Ohne diese Erlaubnis sieht die App niemanden. Nachträglich geht das unter *Datenschutz & Sicherheit → Lokales Netzwerk*.
5. Im Startfenster Name, Rolle und Code eingeben, ✅ **„Beim Anmelden automatisch starten“** setzen, **Los geht's**.

Steht da „ist beschädigt“, im Terminal eingeben: `xattr -cr /Applications/Klassenzimmer.app`
Autostart prüfen oder ausschalten: *Systemeinstellungen → Allgemein → Anmeldeobjekte*.

## 🟢 Installation: Omarchy

Im Terminal (als normaler Benutzer, nicht mit sudo):

```bash
curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-omarchy.sh | bash
```

Das Skript ([install-omarchy.sh](install-omarchy.sh)) macht alles, was der Linux-Installer macht (App, Firewall, App-Menü, Autostart), und dazu:

- **Panel in der Leiste** (Plugin `c1llsh0t.klassenzimmer`): Das Schul-Zeichen 󰑴 zeigt deinen Status (grün = online, gelb = nicht stören, orange = offene Fragen beim Coach). **Klick** öffnet das Panel wie bei WLAN oder Bluetooth, **Klick daneben oder Esc** schliesst es, **Rechtsklick** wechselt den Status.
- Im Panel: Name, Klasse und Code, alle Teilnehmer mit Status, beim Schüler **„Coach um Hilfe fragen“** mit Textfeld, beim Coach die **Hilfeanfragen** mit „Erledigt“. Unten: Code kopieren, **Klasse wechseln**, Beenden.
- Hilfsskript `~/.local/bin/klassenzimmer-leiste` (Starten, Klasse wechseln, Beenden) und eine Fensterregel in `~/.config/hypr/hyprland.lua`, damit das Startfenster unter der Leiste schwebt (vorher wird eine Sicherung `hyprland.lua.bak.*` angelegt).

Ohne Angaben öffnet sich am Schluss das Startfenster direkt unter dem Zeichen. Danach braucht man das grosse Fenster nicht mehr, alles geht über das Panel.

- Ohne Startfenster einrichten: `... | bash -s -- --name "Lena" --role student --code K7Q-M3X` (Coach: `--role coach --klasse INF3a --code NEU`)
- Wieder entfernen (App, Panel, Hilfsskript, Fensterregel): `... | bash -s -- --entfernen`
- Braucht die neue Omarchy-Leiste (`~/.config/omarchy/shell.json`). Ältere Omarchy-Versionen mit Waybar: Linux-Installer nehmen (unten).

## 🐧 Installation: Linux

**Am einfachsten**, im Terminal (als normaler Benutzer, nicht mit sudo):

```bash
curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-linux.sh | bash
```

Das Skript ([install-linux.sh](install-linux.sh)) lädt die neueste Version nach `~/.local/bin/klassenzimmer`, beendet eine alte Version, gibt die Firewall frei (ufw oder firewalld, fragt dafür nach deinem Passwort), legt einen Eintrag im **App-Menü** an und öffnet das Startfenster. Nochmal ausführen = aktualisieren.

- Ohne Startfenster einrichten: `... | bash -s -- --name "Lena" --role student --code K7Q-M3X` (Coach: `--role coach --klasse INF3a --code NEU`)
- Wieder entfernen: `... | bash -s -- --entfernen`
- Nur für 64-Bit-Intel/AMD. Auf anderen Rechnern (z.B. Raspberry Pi) siehe *Für Entwickler*.

**Von Hand** geht es so:

```bash
mkdir -p ~/.local/bin
mv Klassenzimmer-Linux ~/.local/bin/klassenzimmer
chmod +x ~/.local/bin/klassenzimmer
sudo ufw allow 50505:50506/udp      # nur wenn ufw aktiv ist (z.B. Omarchy)
~/.local/bin/klassenzimmer
```

Im Startfenster Name, Rolle und Code eingeben, ✅ **„Beim Anmelden automatisch starten“** setzen, **Los geht's**.

- **Hyprland mit Waybar** (auch ältere Omarchy-Versionen): Die App richtet den **Punkt in der Waybar** automatisch ein (eine Sicherung der alten Einstellung bleibt als `config.jsonc.vor-klassenzimmer` liegen). Von Hand geht das mit `~/.local/bin/klassenzimmer --waybar-einrichten`. Startet die App nach dem Anmelden nicht von selbst, diese Zeile in `~/.config/hypr/autostart.conf` eintragen:
  ```
  exec-once = ~/.local/bin/klassenzimmer --autostart
  ```
- **GNOME, KDE, XFCE …:** Statt der Waybar gibt es die kleine Leiste. Der Autostart funktioniert direkt.
- **Fedora (firewalld)** statt ufw: `sudo firewall-cmd --permanent --add-port=50505-50506/udp && sudo firewall-cmd --reload`

---

## Benutzen

**Coach:** Beim ersten Start **Coach** wählen. Die App zeigt einen **Beitrittscode** (z.B. `K7Q-M3X`), den du an die Tafel schreibst. Er steht später auch oben im Fenster, ein Klick darauf kopiert ihn. Mit **„Neuen Code“** gibt es einen neuen, dann müssen ihn aber alle neu eingeben.

**Schüler:** Beim ersten Start **Schüler/in** wählen und den Code vom Coach eingeben.

**Die kleine Leiste** (Windows, Mac, Linux), immer im Vordergrund:

| Schüler | Coach |
|---|---|
| `⋮ ● Lena  ✋  ⤢` | `⋮ ● Herr Keller  🔔 2  ⤢` |

- **●** klicken: Status wechseln (🟢 ↔ 🟡)
- **✋** klicken: Coach um Hilfe fragen. Danach zeigt sie `…` (wird gesendet), `✓` (angekommen) oder `✗` (nicht angekommen).
- **🔔 2**: zwei offene Fragen, ein Klick öffnet die Warteschlange
- **⤢** oder Name: grosses Fenster öffnen (Frage mit Text, Teilnehmerliste)
- **⋮** ziehen: Leiste verschieben
- **Rechtsklick**: Menü mit **Beenden**

**Omarchy/Waybar:** Oben rechts in der Waybar steht ein farbiger **●**. Beim Coach kommt **🔔2** dazu, wenn Fragen offen sind, beim Schüler **✋✓**, wenn die Anfrage angekommen ist.
- **Klick:** grosses Fenster öffnen oder schliessen
- **Rechtsklick:** Status wechseln
- **Maus darüber:** Details

Das Fenster-X versteckt das Fenster nur, die App läuft klein weiter. **Beenden** geht mit ⏻ oben im Fenster oder mit dem Rechtsklick-Menü der Leiste.

**Name, Code oder Autostart ändern:** App beenden, normal neu starten und im Startfenster ändern.

## Es findet niemanden?

1. Haben alle **denselben Code** eingegeben? Gross-/Kleinschreibung und Bindestrich sind egal.
2. Sind alle im **selben WLAN**?
3. Ist die **Firewall** freigegeben? Siehe oben beim jeweiligen System.
4. Stimmt die **Uhrzeit** am Computer ungefähr? Mehr als 10 Minuten falsch geht nicht, das ist ein Schutz gegen aufgezeichnete Nachrichten.
5. Haben alle **mindestens Version 2.3**? Viele Schul-WLANs trennen die Geräte ganz voneinander („Client-Isolation“, z. B. BbcBYOD): kein Broadcast, kein Multicast, nicht einmal ein Ping. Ab 2.3 geht die App dann automatisch übers Internet (siehe unten). Aktualisieren: Installer nochmal ausführen bzw. neue Datei aus den Releases holen.
6. Kommt die App ins Internet? Wenn niemand gefunden wird, steht im Fenster „Internet-Weg: keine Verbindung“. Dann blockt etwas die Verbindung zu `public.cloud.shiftr.io` (Port 443).

### Übers Internet (ab Version 2.3)

Die App sucht zuerst im WLAN. Zusätzlich verbindet sie sich mit einem kostenlosen, öffentlichen Vermittler (MQTT über WebSocket bei `public.cloud.shiftr.io`, Port 443 wie normale Webseiten). Über ihn findet sich die Klasse auch dann, wenn das WLAN die Geräte voneinander trennt.

- **Verschlüsselt:** Alles ist mit dem Beitrittscode verschlüsselt und signiert. Der Vermittler sieht weder Namen noch Hilfetexte noch den Code, nur Datensalat.
- **Ausschalten:** mit `--ohne-internet` starten oder `KLASSENZIMMER_INTERNET=aus` setzen. Dann geht es nur im WLAN.
- **Anderer Vermittler:** `KLASSENZIMMER_INTERNET=wss://benutzer:passwort@host/pfad` (jeder MQTT-Server mit WebSocket). Alle in der Klasse müssen denselben benutzen.

### Erweiterungen (ab Version 2.3)

Liegt im Einstellungs-Ordner (neben `einstellungen.json`) eine Datei `erweiterung.py`, lädt die App sie beim Start. Eine Erweiterung kann eigene Knöpfe und Textzeilen ins Fenster, ins Menü der kleinen Leiste und ins Omarchy-Panel bringen und eigene Nachrichten an die anderen schicken. Wie das geht, steht in `klassenzimmer.py` bei **TEIL 8**. Achtung: Eine Erweiterung ist Python-Code und darf alles, was die App darf. Nur Dateien aus einer Quelle benutzen, der man vertraut.

**Aus- und einblenden:** Die Zusatzknöpfe lassen sich mit dem Knopf **🙈 Ausblenden** oder mit **Strg + Umschalt + P** verstecken (im Omarchy-Panel die Taste **P**). Zum Zeigen dasselbe nochmal. Das bleibt auch nach einem Neustart so gespeichert.

**Fertiges Programm prüfen:** `klassenzimmer --selbsttest` startet ohne Fenster und meldet, ob der Internet-Weg und eine Erweiterung funktionieren.

---

## Für Entwickler

Der ganze Code steckt in **einer Datei**, `klassenzimmer.py`, mit 7 kommentierten Teilen. Er benutzt nur die Python-Standardbibliothek.

```bash
python3 klassenzimmer.py                                         # normal (Startfenster)
python3 klassenzimmer.py --name Lena --role student --code K7QM3X  # Testmodus, speichert nichts
python3 -m unittest -v test_klassenzimmer                        # automatische Tests
```

| Option | Wofür |
|---|---|
| `--code K7QM3X` | Beitrittscode. Coach: `--code NEU` erzeugt einen neuen |
| `--klasse INF3a` | Klassenname (nur Coach) |
| `--speichern` | mit `--name/--role/--code`: speichern, Autostart an, klein starten |
| `--kein-autostart` | mit `--speichern`: Autostart nicht einschalten |
| `--autostart` | gespeicherte Einstellungen benutzen, klein starten |
| `--zeigen` / `--status-umschalten` / `--beenden` | Befehl an die laufende App |
| `--hilfe [TEXT]` / `--erledigt ID` / `--entfernen ID` | Hilfe anfragen, Anfrage erledigen, jemanden aus der Liste nehmen (für Leisten-Panels) |
| `--waybar-einrichten` | Omarchy/Hyprland: Punkt in die Waybar eintragen |
| `--ansicht mini\|waybar\|fenster` | Ansicht erzwingen (Standard: automatisch) |
| `--port 50510` | anderer Port für direkte Nachrichten (Standard: 50506) |
| `--broadcast 192.168.1.255` | eigene Broadcast-Adresse, wenn 255.255.255.255 nicht geht |
| `--verlust 0.3` | zum Üben: 30 % der Pakete gehen absichtlich verloren |

Fehlt unter Linux `tkinter` (nur beim Starten aus dem Code): `sudo apt install python3-tk` bzw. `sudo pacman -S tk`.

| Datei | Inhalt |
|---|---|
| `klassenzimmer.py` | die ganze App |
| `test_klassenzimmer.py` | automatische Tests |
| `ERKLAERUNG.md` | alle Funktionen und wie alles funktioniert, zum Weitererklären |
| `ANLEITUNG.md` | technische Erklärung Schritt für Schritt, Übungen |
| `PROTOKOLL.md` | alle Nachrichten mit Beispiel-JSON |
| `schritte/` | Lernversion: Konsolenprogramm |

Neue Version: Sobald `klassenzimmer.py` auf GitHub geändert wird, entsteht automatisch ein neues Release.
