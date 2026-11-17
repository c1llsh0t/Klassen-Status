# Installation und Autostart

Die Programme gibt es auf GitHub unter **Releases**. Python braucht man dafür nicht.

> **Wichtig für alle:** Leg das Programm **zuerst an seinen festen Platz** und starte es erst dann. Der Autostart merkt sich, wo das Programm liegt. Verschiebst oder löschst du es danach, startet es beim Anmelden nicht mehr. Dann einfach am neuen Ort starten und das Häkchen nochmal setzen.

---

## 🪟 Windows

**Installieren**
1. `Klassenzimmer-Windows.exe` herunterladen.
2. Einen festen Ordner anlegen, z.B. `Dokumente\Klassenzimmer`, und die Datei dorthin verschieben. Nicht im Ordner *Downloads* lassen.
3. Doppelklick auf die Datei.
4. Erscheint **„Der Computer wurde durch Windows geschützt“**: auf **Weitere Informationen** und dann **Trotzdem ausführen** klicken. Das kommt, weil die App nicht kostenpflichtig signiert ist.
5. Fragt die **Windows-Firewall** nach: Häkchen bei **Private Netzwerke** setzen und auf **Zugriff zulassen** klicken.
   Ist das WLAN in Windows als *öffentliches* Netzwerk eingestellt, blockiert die Firewall die App. Ändern kannst du das unter *Einstellungen → Netzwerk und Internet → WLAN → (dein WLAN) → Netzwerkprofil: Privat*.

**Einrichten**
6. Name, Klasse (z.B. `INF3a`, bei allen gleich) und Rolle eingeben.
7. Häkchen **„Beim Anmelden automatisch starten“** setzen und auf **Los geht's** klicken.

**Autostart prüfen:** Öffne den Task-Manager (Ctrl+Shift+Esc), dann **Autostart-Apps**. Dort steht `klassenzimmer` mit dem Status *Aktiviert*. Über diese Liste kannst du den Autostart auch ausschalten.

---

## 🍎 Mac (mit Apple-Chip: M1, M2, M3, M4 …)

**Installieren**
1. `Klassenzimmer-Mac.zip` herunterladen und doppelklicken. Danach liegt `Klassenzimmer.app` im Ordner *Downloads*.
2. `Klassenzimmer.app` in den Ordner **Programme** ziehen.
3. Die App aus *Programme* öffnen. macOS blockiert sie beim ersten Mal, weil sie nicht bei Apple beglaubigt ist. Klick auf **Fertig** bzw. **OK**.
4. Öffne **Systemeinstellungen → Datenschutz & Sicherheit**, scroll ganz nach unten und klick bei „Klassenzimmer wurde blockiert …“ auf **Dennoch öffnen**. Dann noch einmal **Öffnen** und das Mac-Passwort eingeben.
   (Ab macOS 15 geht der alte Trick „Rechtsklick → Öffnen“ nicht mehr.)
5. Fragt der Mac **„Klassenzimmer möchte Geräte in deinem lokalen Netzwerk finden“**, klick auf **Erlauben**. Ohne diese Erlaubnis sieht die App niemanden.
   Falls du es verpasst hast: *Systemeinstellungen → Datenschutz & Sicherheit → Lokales Netzwerk → Klassenzimmer* einschalten.

Steht da „Klassenzimmer ist beschädigt und kann nicht geöffnet werden“, im Terminal einmal eingeben:
```
xattr -cr /Applications/Klassenzimmer.app
```

**Einrichten**
6. Name, Klasse und Rolle eingeben, Häkchen **„Beim Anmelden automatisch starten“** setzen, auf **Los geht's** klicken.

**Autostart prüfen:** Unter *Systemeinstellungen → Allgemein → Anmeldeobjekte* steht die App unter „Im Hintergrund erlauben“. Dort kannst du sie auch ausschalten. macOS meldet beim ersten Mal eventuell „Hintergrundobjekt hinzugefügt“, das ist normal.

**Alternative**, falls der Autostart nicht klappt: In den *Anmeldeobjekten* oben bei „Beim Anmelden öffnen“ auf **+** klicken und `Klassenzimmer.app` auswählen. Dann zeigt die App beim Start das Startfenster, in dem du nur auf **Los geht's** klicken musst.

---

## 🐧 Linux (Ubuntu, Fedora, Arch, Omarchy …)

**Installieren** (im Terminal, im Ordner, in dem die Datei liegt):
```
mkdir -p ~/.local/bin
mv Klassenzimmer-Linux ~/.local/bin/klassenzimmer
chmod +x ~/.local/bin/klassenzimmer
~/.local/bin/klassenzimmer
```

**Firewall**, falls aktiv (Omarchy und andere mit `ufw`):
```
sudo ufw allow 50505:50506/udp
```
Bei Fedora (firewalld): `sudo firewall-cmd --permanent --add-port=50505-50506/udp && sudo firewall-cmd --reload`

**Einrichten**
1. Name, Klasse und Rolle eingeben, Häkchen **„Beim Anmelden automatisch starten“** setzen, auf **Los geht's** klicken.
2. Die App legt dafür `~/.config/autostart/klassenzimmer.desktop` an. Das funktioniert direkt mit **GNOME, KDE, XFCE, Cinnamon**.

**Omarchy / Hyprland:** Ob `~/.config/autostart` beim Anmelden ausgeführt wird, hängt von der Einrichtung ab. Am einfachsten abmelden, wieder anmelden und schauen, ob die App kommt. Wenn nicht, öffne `~/.config/hypr/autostart.conf` und füge diese Zeile hinzu:
```
exec-once = ~/.local/bin/klassenzimmer --autostart
```
(Gibt es die Datei nicht, kommt die Zeile in `~/.config/hypr/hyprland.conf`.) Nimm dann im Startfenster das Häkchen wieder raus, damit die App nicht doppelt gestartet wird. Doppelt laufen kann sie aber ohnehin nicht, ein zweiter Start meldet „Die App läuft schon“.

**Optional: Eintrag im App-Menü** (damit man sie mit Super-Taste/Launcher findet):
```
cat > ~/.local/share/applications/klassenzimmer.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Klassenzimmer
Exec=$HOME/.local/bin/klassenzimmer
Terminal=false
Categories=Education;
EOF
```

---

## Für alle: Einstellungen ändern oder Autostart ausschalten

- **Name, Klasse oder Rolle ändern:** App schliessen und normal starten, also nicht über den Autostart. Im Startfenster ändern und auf **Los geht's** klicken.
- **Autostart ausschalten:** Genauso, nur das Häkchen entfernen.
- **Alles zurücksetzen:** Den Einstellungsordner löschen:
  - Windows: `%APPDATA%\klassenzimmer` (in die Adresszeile des Explorers eingeben)
  - Mac: `~/Library/Application Support/klassenzimmer`
  - Linux: `~/.config/klassenzimmer`

## Es findet niemanden?

1. Sind alle im **selben WLAN** und haben **dieselbe Klasse** eingetippt? Gross-/Kleinschreibung ist egal.
2. **Firewall** erlaubt? Siehe oben beim jeweiligen System.
3. Manche Schul- und Gäste-WLANs verbieten Verbindungen zwischen Geräten („Client Isolation“). Zum Testen zwei Laptops an denselben Handy-Hotspot hängen. Klappt es dort, liegt es am WLAN.
