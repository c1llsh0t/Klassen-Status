# Klassenzimmer-App (Peer-to-Peer, Python)

Alle Rechner im selben WLAN/LAN sehen sich gegenseitig, **ohne Server**. Schüler können den Coach um Hilfe fragen, und der Coach sieht die Anfragen in einer Warteschlange.

- grün = online, gelb = nicht stören, grau = offline (10 Sekunden ohne Meldung)
- nur Python 3 mit der Standardbibliothek (socket, threading, json, tkinter)

## Herunterladen

Fertige Programme für Windows, Mac und Linux gibt es unter **[Releases](../../releases/latest)**. Python muss dafür nicht installiert sein.

## Autostart

Im Startfenster das Häkchen **„Beim Anmelden automatisch starten“** setzen. Name und Rolle werden gespeichert, und die App startet beim nächsten Anmelden von selbst, ohne nachzufragen. Zum Ausschalten die App normal starten und das Häkchen entfernen.

## Starten (aus dem Code)

```
python3 main.py                                   # fragt Name und Rolle ab
python3 main.py --name Lena --role student
python3 main.py --name "Herr Keller" --role coach
```

Optionen:

| Option | Wofür |
|---|---|
| `--port 50506` | fester Port für direkte Nachrichten (für Firewalls) |
| `--broadcast 192.168.1.255` | eigene Broadcast-Adresse, wenn 255.255.255.255 nicht geht |
| `--autostart` | gespeicherten Namen und Rolle benutzen, nicht nachfragen |
| `--verlust 0.3` | zum Üben: 30 % der Pakete gehen absichtlich verloren |

Unter Linux muss eventuell `tkinter` nachinstalliert werden, z.B. `sudo apt install python3-tk` oder auf Arch/Omarchy `sudo pacman -S tk`.

## Tests

```
python3 -m unittest -v test_network test_autostart
```

## Dateien

| Datei | Inhalt |
|---|---|
| `PROTOKOLL.md` | Schritt 1: alle Nachrichten mit Beispiel-JSON |
| `protocol.py` | Nachrichten bauen und prüfen |
| `network.py` | UDP-Broadcast, Heartbeat, ACK und Wiederholung, Duplikate |
| `gui.py` | tkinter-Oberfläche |
| `main.py` | Startpunkt |
| `autostart.py` | Autostart und gespeicherte Einstellungen |
| `test_network.py` | automatische Tests |
| `ANLEITUNG.md` | ausführliche Erklärung, Fehlersuche und Übungen |
