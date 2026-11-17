# Klassenzimmer

Eine Peer-to-Peer-App fürs Klassenzimmer: Alle Rechner im selben WLAN/LAN sehen sich gegenseitig, **ohne Server**. Schüler fragen den Coach per Knopfdruck um Hilfe, und der Coach sieht alle Anfragen in einer Warteschlange.

- 🟢 online · 🟡 nicht stören · ⚪ offline (20 Sekunden nichts gehört)
- die Klasse wird gespeichert, sodass am nächsten Tag alle schon in der Liste stehen
- mehrere Klassen im selben WLAN stören sich nicht
- Autostart beim Anmelden
- nur Python 3 mit der Standardbibliothek, alles in **einer Datei**: `klassenzimmer.py`

## Herunterladen

Fertige Programme für Windows, Mac und Linux gibt es unter **[Releases](../../releases/latest)**. Python muss dafür nicht installiert sein.

## Starten (aus dem Code)

```
python3 klassenzimmer.py
```

Das Startfenster fragt nach Name, Klasse und Rolle und bietet den Autostart an. Alles wird gespeichert.

Testmodus (speichert nichts, mehrere Apps auf einem PC möglich):

```
python3 klassenzimmer.py --name Lena --role student --klasse INF3a
python3 klassenzimmer.py --name "Herr Keller" --role coach --klasse INF3a
```

| Option | Wofür |
|---|---|
| `--klasse INF3a` | Klassenname (im Testmodus, sonst „Standard“) |
| `--autostart` | gespeicherte Einstellungen benutzen, nicht nachfragen |
| `--port 50506` | fester Port für direkte Nachrichten (für Firewalls) |
| `--broadcast 192.168.1.255` | eigene Broadcast-Adresse, wenn 255.255.255.255 nicht geht |
| `--verlust 0.3` | zum Üben: 30 % der Pakete gehen absichtlich verloren |

Fehlt unter Linux `tkinter`: `sudo apt install python3-tk` bzw. auf Arch/Omarchy `sudo pacman -S tk`.

## Tests

```
python3 -m unittest -v test_klassenzimmer
```

## Dateien

| Datei | Inhalt |
|---|---|
| `klassenzimmer.py` | die ganze App (6 Teile, mit Kommentaren) |
| `test_klassenzimmer.py` | 19 automatische Tests |
| `ERKLAERUNG.md` | **alle Funktionen und wie alles funktioniert, zum Weitererklären** |
| `ANLEITUNG.md` | ausführliche technische Erklärung, Fehlersuche, Übungen |
| `PROTOKOLL.md` | alle Nachrichten mit Beispiel-JSON |
| `schritte/` | Lernversion: Konsolenprogramm aus Schritt 2 |

Neue Version veröffentlichen: auf GitHub **Actions → Programme bauen → Run workflow**.
