# Klassenzimmer-App – Schritt für Schritt erklärt

Eine Peer-to-Peer-App: Alle Rechner im selben WLAN/LAN sehen sich gegenseitig. Es gibt **keinen Server**. Jede laufende App ist gleichwertig.

```
python3 klassenzimmer.py                                        # Startfenster
python3 klassenzimmer.py --name Lena --role student --klasse INF3a
python3 klassenzimmer.py --name "Herr Keller" --role coach --klasse INF3a
python3 -m unittest -v test_klassenzimmer                      # automatische Tests
```

Zum Ausprobieren kannst du die App mehrmals auf **einem** Rechner starten, in mehreren Terminals.

---

## Überblick: Wer macht was?

Der ganze Code steht in **einer Datei**, `klassenzimmer.py`, aufgeteilt in 6 Teile:

| Teil in `klassenzimmer.py` | Aufgabe | Schritt unten |
|---|---|---|
| TEIL 1 Einstellungen und Protokoll | Wie sehen Nachrichten aus? Prüfen von Nachrichten | 1 |
| TEIL 2 Speicher | Name, Klasse, feste ID, bekannte Teilnehmer speichern | 5 |
| TEIL 3 Autostart | beim Anmelden starten | 5 |
| TEIL 4 Netzwerk | Senden und Empfangen, Heartbeat, ACK und Wiederholung | 2 + 3 |
| TEIL 5 Oberfläche | Fenster, Liste, Knöpfe | 4 |
| TEIL 6 Start | Kommandozeile, Startfenster, alles verbinden | 5 |

Dazu kommt `test_klassenzimmer.py` mit den automatischen Tests (Schritt 6).

So hängen die Teile zusammen:

```
          ┌──────────── deine App ──────────────────────────────┐
          │                                                     │
 WLAN ⇄   │  Network (3 Threads)  ──events──▶  Queue  ──▶  App (Hauptthread)
          │        ▲                                            │
          │        └────────── net.send_help() usw. ◀───────────┘
          └─────────────────────────────────────────────────────┘
```

---

## Schritt 1: Das Protokoll (TEIL 1)

Zwei Programme können nur miteinander reden, wenn sie dieselbe „Sprache“ sprechen. Bei uns ist jede Nachricht **JSON**:

```json
{"type": "heartbeat", "id": "3f2a…", "from": "a91c…", "name": "Lena",
 "role": "student", "status": "online", "class": "INF3a", "port": 51234}
```

Jede Nachricht hat immer drei Felder:

- **`type`**: Was für eine Nachricht ist das? (`heartbeat`, `bye`, `help`, `done`, `ack`)
- **`id`**: eine eindeutige Nummer für **diese eine Nachricht**. Wir erzeugen sie mit `uuid.uuid4()`. Daran erkennen wir Duplikate.
- **`from`**: wer sie geschickt hat. Das ist die `peer_id` der App und **nicht** der Name, denn zwei Leute könnten gleich heissen.

Die Nachrichtentypen:

| Typ | Wohin | Wofür |
|---|---|---|
| `heartbeat` | Broadcast an alle | „Ich bin da“, mit Name, Rolle, Status, Klasse und meinem Port |
| `bye` | Broadcast an alle | „Ich gehe“ (beim Beenden) |
| `help` | direkt an den Coach | Hilfeanfrage mit optionalem Text |
| `done` | direkt an den Schüler | „Deine Anfrage ist erledigt“ |
| `ack` | direkt zurück | „Nachricht mit ID xy angekommen“ |

**Warum `decode()` so viel prüft:** Alles, was übers Netzwerk kommt, kann kaputt sein, oder jemand schickt absichtlich Unsinn. `decode()` gibt dann `None` zurück, statt dass die App abstürzt. Merksatz: **Daten von aussen nie blind vertrauen.**

Ebenfalls in dieser Datei: `time.monotonic()` statt `time.time()`. Diese Uhr läuft immer nur vorwärts. Stellt jemand die Systemuhr um, funktionieren unsere Timeouts trotzdem.

---

## Schritt 2: Finden und Status per Broadcast (TEIL 4)

### UDP und Broadcast

Wir benutzen **UDP**. Das ist wie Postkarten verschicken: schnell und ohne Verbindungsaufbau, aber eine Karte kann verloren gehen.

Ein **Broadcast** an `255.255.255.255` geht an **alle** Rechner im lokalen Netz. Damit braucht niemand eine Liste von IP-Adressen. Man ruft einfach in den Raum: „Ich bin Lena!“

### Zwei Sockets

```python
self.bsock.bind(("", 50505))   # hört auf Broadcasts (heartbeat, bye)
self.usock.bind(("", 0))       # Port 0 = Betriebssystem sucht einen freien Port aus
```

- **`bsock`** auf Port 50505: Hier kommen alle Broadcasts an. Mit `SO_REUSEADDR`/`SO_REUSEPORT` dürfen mehrere Apps auf einem PC denselben Port teilen.
- **`usock`** auf einem zufälligen Port: Dorthin schickt man mir **direkte** Nachrichten (help, done, ack). Den Port verrate ich allen im Heartbeat (`"port": 51234`). Würden alle Apps auf einem PC Port 50505 auch für direkte Nachrichten benutzen, wüsste das Betriebssystem nicht, welche App sie bekommen soll.

### Heartbeat und Offline-Erkennung

- Alle **5 Sekunden** schickt jede App einen `heartbeat` per Broadcast (`_timer_loop`).
- Die GUI merkt sich bei jedem Teilnehmer `last_seen`, also wann er sich zuletzt gemeldet hat.
- Ist das länger als **10 Sekunden** her, wird der Punkt **grau** (`_shown_status` in TEIL 5). 10 Sekunden heisst: Zwei Heartbeats hintereinander müssen fehlen. Ein einzelnes verlorenes Paket macht also niemanden grau.
- Beim Beenden schickt die App `bye`. Dann wird man sofort grau und nicht erst nach 10 Sekunden.

**Nur die eigene Klasse:** Jeder Heartbeat enthält den Klassennamen. Gehört er zu einer anderen Klasse, wird er ignoriert. So können mehrere Klassen im selben WLAN sein, ohne sich zu stören. Gross-/Kleinschreibung und Leerzeichen sind dabei egal („INF3a“ = „inf 3A“).

**Trick für schnelles Finden:** Höre ich von einem Teilnehmer, den ich noch nicht kenne, schicke ich ihm **sofort** direkt meinen eigenen Heartbeat. Sonst müsste eine neu gestartete App bis zu 5 Sekunden warten, bis sie die anderen sieht.

### Status wechseln

`set_status()` ändert `me["status"]` und setzt `next_heartbeat = 0`. Dadurch geht sofort ein neuer Heartbeat raus, und alle sehen die neue Farbe in weniger als einer Sekunde.

---

## Schritt 3: Zuverlässig senden mit ACK und Wiederholung

Bei einer Hilfeanfrage darf nichts verloren gehen. UDP garantiert das aber nicht. Darum bauen wir die Zuverlässigkeit selbst:

```
Schüler                                   Coach
   │ ── help (id=42) ─────────────X       (verloren)
   │      … 3 Sekunden kein ACK …
   │ ── help (id=42) Versuch 2 ──────────▶ neu! → in die Warteschlange
   │ ◀──────────────────────── ack(42) ── │
   ✓ angekommen
```

So funktioniert es im Code (`_send_reliable` und `_check_retries`):

1. Nachricht senden und in `self.pending` merken (wann zuletzt gesendet, wie oft).
2. Kommt ein `ack` mit `ack_id == 42`, wird sie aus `pending` gelöscht. Die GUI bekommt das Ereignis `acked`.
3. `_timer_loop` prüft alle 0.2 Sekunden: Ist eine Nachricht seit 3 Sekunden ohne ACK? Dann wird sie nochmal gesendet.
4. Nach **5 Versuchen** gibt die App auf. Die GUI bekommt `failed`.

### Duplikate erkennen

Was passiert, wenn die Anfrage ankommt, aber das **ACK** verloren geht? Dann sendet der Schüler nochmal, und der Coach bekommt dieselbe Anfrage zweimal.

```
Schüler                                   Coach
   │ ── help (id=42) ────────────────────▶ neu → Warteschlange
   │            X────────────── ack(42) ── │  (ACK verloren!)
   │ ── help (id=42) Versuch 2 ──────────▶ schon gesehen! → NICHT nochmal anzeigen,
   │ ◀──────────────────────── ack(42) ── │   aber NOCHMAL ACK senden
   ✓
```

Darum merkt sich jede App alle gesehenen IDs (`self.seen`). Wichtig: Bei einem Duplikat schicken wir **trotzdem** ein ACK. Sonst würde der Schüler bis zum 5. Versuch weitersenden und dann „nicht angekommen“ anzeigen, obwohl die Anfrage längst da ist.

Alte IDs werden nach 2 Minuten vergessen (`_forget_old_ids`), sonst würde die Liste ewig wachsen.

### Threads und Lock

Im Netzwerk-Teil laufen **drei Threads gleichzeitig**: zwei warten auf Pakete (je Socket einer), einer kümmert sich um Heartbeats und Wiederholungen. Weil mehrere Threads auf `pending`, `seen` und `me` zugreifen, schützen wir sie mit `with self.lock:`. So ändert immer nur ein Thread gleichzeitig etwas daran.

**Windows-Falle:** Schickt man unter Windows ein UDP-Paket an jemanden, der nicht mehr da ist, meldet beim nächsten `recvfrom` der Socket „Verbindung zurückgesetzt“. Darum schalten wir das mit `SIO_UDP_CONNRESET` aus, und ein Fehler beim Empfangen beendet den Thread nicht mehr.

`settimeout(0.5)` bei den Sockets sorgt dafür, dass `recvfrom` nicht ewig wartet. So merkt der Thread alle 0.5 Sekunden, ob die App beendet wurde (`self.running`).

---

## Schritt 4: Die Oberfläche (TEIL 5)

### Die goldene Regel

**tkinter darf nur im Hauptthread benutzt werden.** Würde ein Netzwerk-Thread direkt `label.configure(...)` aufrufen, kann das zufällig abstürzen oder einfrieren.

Darum gilt:

- Der Netzwerk-Teil legt nur **Ereignisse** in eine `queue.Queue`, etwa `("peer", {...})`, `("help", {...})` oder `("acked", id, ...)`.
- Die GUI holt sie alle 100 ms ab: `root.after(100, self._poll)`. `after()` heisst: „tkinter, ruf diese Funktion in 100 ms im Hauptthread auf.“
- `_poll` arbeitet alle Ereignisse ab und zeichnet danach neu.

Die Queue ist thread-sicher. Das ist ihr ganzer Zweck.

Die Oberfläche friert nie ein, weil der Hauptthread **nie** auf das Netzwerk wartet. Senden mit UDP geht sofort, und Empfangen machen die anderen Threads.

### Der Zustand

Die GUI speichert alles, was sie anzeigen muss:

- `self.peers`: alle Teilnehmer mit `last_seen`
- `self.queue`: Hilfeanfragen beim Coach. Neue kommen mit `append()` **hinten** dazu, also steht die **älteste vorne**. Pro Schüler gibt es nur **eine** offene Anfrage: Fragt jemand nochmal, wird der Text aktualisiert, aber der Platz bleibt.
- `self.requests`: die eigene Anfrage als Schüler, je Coach ein Status: `sending`, `acked`, `failed` oder `done`

### Hilfe fragen

`ask_for_help()` sucht alle Coaches, die nicht offline sind, und schickt **jedem einzeln** eine Anfrage. Gibt es zwei Coaches, sieht der Schüler auch zwei Bestätigungen.

### Farbige Knöpfe

Auf dem Mac ignoriert tkinter die Farben von `tk.Button`. Weisse Schrift auf einem weissen Knopf wäre unlesbar. Darum gibt es `ColorButton`: ein `tk.Label`, das auf Klicks reagiert und überall gleich aussieht.

### Neu zeichnen

`_render_peers()` löscht alle Zeilen und baut sie neu auf. Das ist nicht das Effizienteste, aber einfach zu verstehen und für eine Klasse schnell genug. `_tick()` zeichnet zusätzlich jede Sekunde neu, damit Leute grau werden, auch wenn gerade keine Nachricht kommt.

---

## Schritt 5: Start, Speichern und Autostart (TEIL 2, 3 und 6)

**Zwei Arten zu starten:**
- **Normal** (ohne `--name`): Das Startfenster fragt Name, Klasse und Rolle ab. Alles wird gespeichert, auch eine **feste ID** (`peer_id`), die bei jedem Start gleich bleibt.
- **Testmodus** (`--name … --role …`): Es wird nichts gespeichert, und man kann mehrere Apps auf einem PC starten.

**Klasse speichern (`Store`):** In der Einstellungsdatei steht pro Klasse jeder Teilnehmer, den man schon einmal gesehen hat (feste ID, Name, Rolle). Beim Start erscheinen alle sofort **grau** in der Liste und werden grün, sobald sie sich melden. Wer nicht mehr in die Klasse gehört, wird mit dem **✕** neben einem grauen Namen entfernt. Gespeichert wird zuerst in eine `.tmp`-Datei und erst dann umbenannt (`os.replace`). So ist die Datei nie halb geschrieben, auch wenn der PC abstürzt.

**Nur einmal starten:** Normal gestartet belegt die App den TCP-Port 50505 auf `127.0.0.1`. Ein zweiter Start (z.B. Autostart plus von Hand) merkt, dass der Port belegt ist, und meldet „Die App läuft schon“.

**Autostart:** Je nach System ein Registry-Eintrag (Windows), eine `.plist` in `~/Library/LaunchAgents` (Mac) oder eine `.desktop`-Datei in `~/.config/autostart` (Linux). Der gespeicherte Befehl enthält `--autostart`. Damit startet die App ohne Startfenster.

**Ablauf in `main()`:**
1. `argparse` liest die Optionen.
2. Normal: Sperre prüfen, Einstellungen laden, eventuell Startfenster zeigen und speichern.
3. Das `me`-dict beschreibt diese App: `peer_id`, Name, Rolle, Klasse, Status.
4. `Network` wird gestartet, dann die Oberfläche. Beide teilen sich die `events`-Queue.
5. Schliesst man das Fenster, schickt `quit()` zweimal `bye` und schliesst die Sockets.

---

## Schritt 6: Testen

```
python3 -m unittest -v test_klassenzimmer
```

Die 19 Tests starten mehrere „Teilnehmer“ in einem Programm und prüfen:

- alle finden sich, und eine neue App sieht die anderen in unter 1 Sekunde
- eine andere Klasse ist unsichtbar
- die Klasse wird gespeichert und am „nächsten Tag“ wieder geladen
- der Autostart lässt sich ein- und ausschalten
- ein Statuswechsel kommt sofort an
- eine Hilfeanfrage kommt an und wird bestätigt
- **2 verlorene Anfragen:** Der 3. Versuch kommt an, und der Coach sieht sie nur 1×
- **2 verlorene ACKs:** Das Duplikat wird erkannt und trotzdem bestätigt
- Nach 5 Versuchen ohne Antwort gibt die App auf
- „erledigt“ und `bye` kommen an
- kaputte Nachrichten werden ignoriert

Der Trick dabei: `DropNetwork` ist eine Unterklasse von `Network`, die absichtlich die ersten N Pakete eines Typs wegwirft. So kann man Paketverlust gezielt nachstellen.

### Selber ausprobieren mit Paketverlust

```
python3 klassenzimmer.py --name Coach --role coach --verlust 0.5
python3 klassenzimmer.py --name Lena --role student
```

Der Coach „verliert“ jetzt die Hälfte aller Pakete. Bei Lena siehst du „Versuch 2/5“ oder „Versuch 3/5“ und am Ende trotzdem „✓ angekommen“.

---

## Wenn es nicht klappt

- **Niemand wird gefunden:** Die **Firewall** blockiert oft UDP. Unter Windows erscheint beim ersten Start eine Frage, dort „Zulassen“ wählen (privates Netzwerk). Unter Linux mit `ufw` (z.B. Omarchy) braucht es zwei Ports: Port 50505 für die Broadcasts und einen festen Port für direkte Nachrichten. Starte die App mit `--port 50506` und erlaube beide Ports: `sudo ufw allow 50505:50506/udp`.
- **Schul-WLAN mit „Client Isolation“:** Manche WLANs verbieten, dass Geräte direkt miteinander reden. Dann geht Peer-to-Peer gar nicht. Ausprobieren, sonst mit einem eigenen Router oder Hotspot.
- **Mehrere Netzwerkkarten:** `255.255.255.255` geht manchmal nur über eine Netzwerkkarte raus. Gib dann die Broadcast-Adresse deines Netzes an, z.B. `--broadcast 192.168.1.255`.
- **Mac:** Beim ersten Start fragt macOS, ob Python im lokalen Netzwerk kommunizieren darf. Mit „Erlauben“ bestätigen.

## Sicherheit: Was diese App (bewusst) nicht kann

Alles läuft **unverschlüsselt** und **ohne Anmeldung**. Jeder im selben Netz kann mitlesen und sich als jemand anderes ausgeben, auch als Coach. Für ein Klassenzimmer ist das meistens in Ordnung. Schreib aber keine privaten Dinge in die Hilfeanfrage.

Was die App trotzdem schützt:

- kaputte oder zu grosse Pakete werden ignoriert
- Namen und Texte haben eine Maximallänge
- tkinter zeigt alles als reinen Text an, man kann also keinen Code einschleusen

---

## Übungen zum Weitermachen

1. **Leicht:** Ändere `HEARTBEAT_INTERVAL` auf 2 Sekunden und `OFFLINE_AFTER` auf 5. Was passiert, wenn du eine App mit dem Task-Manager hart beendest (dann kommt kein `bye`)?
2. **Leicht:** Füge einen dritten Status „Pause“ (blau) hinzu. Du musst ihn in TEIL 1 (`STATUSES`) und in TEIL 5 (`COLORS`, `STATUS_TEXT`, `toggle_status`) eintragen.
3. **Mittel:** Der Coach soll sehen, **wie lange** jemand schon wartet („seit 3 min“). Tipp: Speichere beim Empfang `time.monotonic()` und rechne in `_tick` neu.
4. **Mittel:** Ein Schüler soll seine Anfrage **zurückziehen** können. Dafür brauchst du einen neuen Nachrichtentyp `cancel`, der auch zuverlässig mit ACK gesendet wird.
5. **Schwer:** Wenn es zwei Coaches gibt und einer „Erledigt“ klickt, soll die Anfrage auch beim anderen verschwinden. Wie erfahren die Coaches voneinander?
6. **Schwer:** Verschlüssle die Nachrichten mit einem Klassen-Passwort. Mit der Standardbibliothek geht das mit `hmac` und `hashlib`, aber nur zum *Signieren*, nicht zum Verschlüsseln. Überlege: Was bringt eine Signatur gegen Fälscher?
