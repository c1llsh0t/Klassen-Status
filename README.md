# Klassenzimmer-App (Peer-to-Peer, Python)

Alle Rechner im selben WLAN/LAN sehen sich gegenseitig, **ohne Server**. Schüler können den Coach um Hilfe fragen, und der Coach sieht die Anfragen in einer Warteschlange.

- grün = online, gelb = nicht stören, grau = offline (10 Sekunden ohne Meldung)
- nur Python 3 mit der Standardbibliothek (socket, threading, json, tkinter)

## Starten

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
| `--verlust 0.3` | zum Üben: 30 % der Pakete gehen absichtlich verloren |

Unter Linux muss eventuell `tkinter` nachinstalliert werden, z.B. `sudo apt install python3-tk` oder auf Arch/Omarchy `sudo pacman -S tk`.

## Tests

```
python3 -m unittest -v test_network
```

## Dateien

| Datei | Inhalt |
|---|---|
| `PROTOKOLL.md` | Schritt 1: alle Nachrichten mit Beispiel-JSON |
| `protocol.py` | Nachrichten bauen und prüfen |
| `network.py` | UDP-Broadcast, Heartbeat, ACK und Wiederholung, Duplikate |
| `gui.py` | tkinter-Oberfläche |
| `main.py` | Startpunkt |
| `test_network.py` | automatische Tests |
| `ANLEITUNG.md` | ausführliche Erklärung, Fehlersuche und Übungen |
