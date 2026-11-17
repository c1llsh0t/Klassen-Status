# Klassenzimmer

Eine Peer-to-Peer-App fürs Klassenzimmer: Alle Rechner im selben WLAN/LAN sehen sich gegenseitig, **ohne Server**. Schüler fragen den Coach per Knopfdruck um Hilfe, und der Coach sieht alle Anfragen in einer Warteschlange.

- 🟢 online · 🟡 nicht stören · ⚪ offline (20 Sekunden nichts gehört)
- die Klasse wird gespeichert, sodass am nächsten Tag alle schon in der Liste stehen
- mehrere Klassen im selben WLAN stören sich nicht
- Autostart beim Anmelden, danach muss man nichts mehr tun

**Download:** unter **[Releases](../../releases/latest)** die Datei für dein System holen. Python braucht man dafür nicht.

---

## 🤖 Zu faul? Lass Claude installieren

Kopiere diesen Text in **Claude** (Claude Code oder die Claude-App mit Zugriff auf deinen Computer). Claude erledigt den Rest und fragt dich nur nach Name, Klasse und Rolle.

```text
Installiere mir die App "Klassenzimmer" auf diesem Computer und richte den Autostart ein.

1. Finde heraus, welches Betriebssystem ich habe (Windows, macOS oder Linux).
2. Lade von https://github.com/c1llsh0t/Klassen-Status/releases/latest die passende Datei:
   - Windows: Klassenzimmer-Windows.exe
   - macOS:   Klassenzimmer-Mac.zip
   - Linux:   Klassenzimmer-Linux
3. Lege sie an einen festen Platz (dort bleibt sie, weil der Autostart sich den Pfad merkt):
   - Windows: %LOCALAPPDATA%\Programs\Klassenzimmer\Klassenzimmer.exe
   - macOS:   entpacken mit "ditto -x -k" nach /Applications/Klassenzimmer.app,
              danach "xattr -dr com.apple.quarantine /Applications/Klassenzimmer.app"
   - Linux:   ~/.local/bin/klassenzimmer und "chmod +x" darauf
4. Firewall (frag mich vorher, bevor du etwas mit Admin-Rechten/sudo machst):
   - Linux: wenn ufw aktiv ist: sudo ufw allow 50505:50506/udp
            wenn firewalld aktiv ist: Ports 50505-50506/udp dauerhaft freigeben
   - Windows: wenn möglich eine eingehende Regel für die exe im Profil "Privat" anlegen,
              sonst sag mir, dass ich beim ersten Start "Zulassen" klicken muss.
   - macOS: nichts, aber sag mir, dass ich "Lokales Netzwerk -> Erlauben" klicken muss.
5. Frag mich nach meinem Namen, meiner Klasse (z.B. INF3a) und ob ich student oder coach bin.
6. Starte die App einmal so (das speichert alles und schaltet den Autostart ein):
   <Pfad zur App> --name "<Name>" --klasse "<Klasse>" --role <student|coach> --speichern
   Auf macOS stattdessen: /Applications/Klassenzimmer.app/Contents/MacOS/Klassenzimmer ...
7. Prüfe, ob der Autostart-Eintrag existiert:
   - Windows: Registry HKCU\Software\Microsoft\Windows\CurrentVersion\Run, Wert "klassenzimmer"
   - macOS:   ~/Library/LaunchAgents/ch.klassenzimmer.app.plist
   - Linux:   ~/.config/autostart/klassenzimmer.desktop
     Bei Hyprland (z.B. Omarchy) zusätzlich in ~/.config/hypr/autostart.conf die Zeile
     "exec-once = ~/.local/bin/klassenzimmer --autostart" eintragen, falls noch nicht vorhanden.
8. Sag mir am Schluss kurz, was du gemacht hast und was ich noch selbst anklicken muss
   (z.B. Windows-SmartScreen "Trotzdem ausführen" oder macOS "Dennoch öffnen").
```

---

## 🪟 Installation: Windows

1. `Klassenzimmer-Windows.exe` herunterladen und in einen **festen Ordner** verschieben, z.B. `Dokumente\Klassenzimmer`. Nicht im Ordner *Downloads* lassen, denn der Autostart merkt sich den Ort.
2. Doppelklicken. Bei **„Der Computer wurde durch Windows geschützt“**: **Weitere Informationen → Trotzdem ausführen**.
3. Bei der Frage der Firewall: Häkchen bei **Private Netzwerke** und dann **Zugriff zulassen**.
   Das WLAN muss in Windows als *privat* eingestellt sein: *Einstellungen → Netzwerk und Internet → WLAN → (dein WLAN) → Netzwerkprofil: Privat*.
4. Name, Klasse und Rolle eingeben, ✅ **„Beim Anmelden automatisch starten“** setzen, **Los geht's**.

Autostart prüfen oder ausschalten: Task-Manager (Ctrl+Shift+Esc) → **Autostart-Apps** → `klassenzimmer`.

## 🍎 Installation: Mac (Apple-Chip M1–M4)

1. `Klassenzimmer-Mac.zip` doppelklicken und `Klassenzimmer.app` in den Ordner **Programme** ziehen.
2. Die App öffnen. Beim ersten Mal wird sie blockiert, das ist normal. Mit **Fertig** schliessen.
3. **Systemeinstellungen → Datenschutz & Sicherheit**, ganz nach unten scrollen und **Dennoch öffnen** klicken, dann mit dem Passwort bestätigen. Ab macOS 15 geht „Rechtsklick → Öffnen“ nicht mehr.
4. Bei „… möchte Geräte in deinem lokalen Netzwerk finden“: **Erlauben**. Ohne diese Erlaubnis sieht die App niemanden. Nachträglich geht das unter *Datenschutz & Sicherheit → Lokales Netzwerk*.
5. Name, Klasse und Rolle eingeben, ✅ **„Beim Anmelden automatisch starten“** setzen, **Los geht's**.

Steht da „ist beschädigt“, im Terminal eingeben: `xattr -cr /Applications/Klassenzimmer.app`
Autostart prüfen oder ausschalten: *Systemeinstellungen → Allgemein → Anmeldeobjekte*.

## 🐧 Installation: Linux (Ubuntu, Fedora, Arch, Omarchy …)

```bash
mkdir -p ~/.local/bin
mv Klassenzimmer-Linux ~/.local/bin/klassenzimmer
chmod +x ~/.local/bin/klassenzimmer
sudo ufw allow 50505:50506/udp      # nur wenn ufw aktiv ist (z.B. Omarchy)
~/.local/bin/klassenzimmer
```

Danach Name, Klasse und Rolle eingeben, ✅ **„Beim Anmelden automatisch starten“** setzen, **Los geht's**.

- **GNOME, KDE, XFCE, Cinnamon:** Der Autostart funktioniert damit direkt.
- **Omarchy/Hyprland:** Zum Testen ab- und wieder anmelden. Startet die App nicht von selbst, diese Zeile in `~/.config/hypr/autostart.conf` eintragen:
  ```
  exec-once = ~/.local/bin/klassenzimmer --autostart
  ```
- **Fedora (firewalld)** statt ufw: `sudo firewall-cmd --permanent --add-port=50505-50506/udp && sudo firewall-cmd --reload`

---

## Benutzen

- **Status wechseln:** oben rechts klicken (🟢 ↔ 🟡). Den Heartbeat schickt die App automatisch im Hintergrund, du musst nichts tun.
- **Schüler:** „Coach um Hilfe fragen“, optional mit Text. Darunter siehst du *✓ angekommen* und später *✓ erledigt*.
- **Coach:** Die Anfragen stehen in einer Warteschlange, die älteste zuerst, und werden mit „Erledigt“ abgehakt.
- **Grauer Name mit ✕:** Die Person aus der gespeicherten Klassenliste entfernen.
- **Name, Klasse oder Autostart ändern:** App schliessen, normal starten und im Startfenster ändern.

## Es findet niemanden?

1. Sind alle im **selben WLAN** mit **derselben Klasse**? Gross-/Kleinschreibung ist egal.
2. Ist die **Firewall** freigegeben? Siehe oben beim jeweiligen System.
3. Manche Schul- und Gäste-WLANs verbieten Verbindungen zwischen Geräten („Client Isolation“). Zum Testen zwei Laptops an denselben Handy-Hotspot hängen.

---

## Für Entwickler

Der ganze Code steckt in **einer Datei**, `klassenzimmer.py`, mit 6 kommentierten Teilen. Er benutzt nur die Python-Standardbibliothek.

```bash
python3 klassenzimmer.py                                             # normal (Startfenster)
python3 klassenzimmer.py --name Lena --role student --klasse INF3a   # Testmodus, speichert nichts
python3 -m unittest -v test_klassenzimmer                            # 20 Tests
```

| Option | Wofür |
|---|---|
| `--speichern` | mit `--name/--role/--klasse`: speichern, Autostart an, starten (ohne Startfenster) |
| `--kein-autostart` | mit `--speichern`: Autostart nicht einschalten |
| `--autostart` | gespeicherte Einstellungen benutzen, nicht nachfragen |
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

Neue Version veröffentlichen: **Actions → Programme bauen → Run workflow**.
