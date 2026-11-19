# Klassenzimmer-App – Schritt für Schritt erklärt

Eine Peer-to-Peer-App: Alle Rechner im selben WLAN/LAN sehen sich gegenseitig. Es gibt **keinen Server**. Jede laufende App ist gleichwertig.

```
python3 klassenzimmer.py                                        # Startfenster
python3 klassenzimmer.py --name Lena --role student --code K7QM3X
python3 klassenzimmer.py --name "Herr Keller" --role coach --code K7QM3X --klasse INF3a
python3 -m unittest -v test_klassenzimmer                      # automatische Tests
```

Zum Ausprobieren kannst du die App mehrmals auf **einem** Rechner starten, in mehreren Terminals.

---

## Überblick: Wer macht was?

Der ganze Code steht in **einer Datei**, `klassenzimmer.py`, aufgeteilt in 7 Teile:

| Teil in `klassenzimmer.py` | Aufgabe | Schritt unten |
|---|---|---|
| TEIL 1 Protokoll und Beitrittscode | Wie sehen Nachrichten aus? Signieren und Prüfen | 1 |
| TEIL 2 Speicher | Name, Code, feste ID, bekannte Teilnehmer speichern | 5 |
| TEIL 3 Autostart | beim Anmelden starten | 5 |
| TEIL 4 Steuerung und Waybar | „nur einmal starten“, Befehle, Waybar-Modul | 5 |
| TEIL 5 Netzwerk | Senden und Empfangen, Heartbeat, ACK und Wiederholung | 2 + 3 |
| TEIL 6 Oberfläche | grosses Fenster und kleine Leiste | 4 |
| TEIL 7 Start | Kommandozeile, Startfenster, alles verbinden | 5 |

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
{"type": "heartbeat", "id": "3f2a…", "from": "a91c…", "ts": 1763380000, "name": "Lena",
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

### Beitrittscode und Signatur

Jede Nachricht bekommt zusätzlich `ts` (Zeitpunkt) und `mac` (Signatur). Der Ablauf:

1. Der Coach erzeugt mit `new_code()` einen Code wie `K7QM3X`. Dafür nimmt die App `secrets` statt `random`, denn das ist sicherer Zufall.
2. `derive_key(code)` macht daraus mit **PBKDF2** einen Schlüssel. 200 000 Runden machen das absichtlich langsam, damit niemand mitgeschnittene Nachrichten nimmt und den Code durchprobiert.
3. `encode()` hängt `mac = HMAC-SHA256(Schlüssel, Nachricht)` an.
4. `decode()` rechnet die Signatur nach und vergleicht sie mit `hmac.compare_digest` (das ist sicher gegen Zeitmessungs-Tricks). Passt sie nicht, war es eine andere Klasse oder eine Fälschung, und die Nachricht wird weggeworfen.
5. Ist `ts` mehr als 10 Minuten von der eigenen Uhr entfernt, wird die Nachricht auch weggeworfen. So kann niemand eine gestern aufgezeichnete Nachricht nochmal abspielen.

Ebenfalls in dieser Datei: `time.monotonic()` statt `time.time()`. Diese Uhr läuft immer nur vorwärts. Stellt jemand die Systemuhr um, funktionieren unsere Timeouts trotzdem.

---

## Schritt 2: Finden und Status per Broadcast (TEIL 5)

### UDP und Broadcast

Wir benutzen **UDP**. Das ist wie Postkarten verschicken: schnell und ohne Verbindungsaufbau, aber eine Karte kann verloren gehen.

Ein **Broadcast** an `255.255.255.255` geht an **alle** Rechner im lokalen Netz. Damit braucht niemand eine Liste von IP-Adressen. Man ruft einfach in den Raum: „Ich bin Lena!“

### Zusätzlich Multicast (ab Version 2.2)

Viele Schul- und Firmen-WLANs **filtern Broadcasts** zwischen den Geräten, lassen aber **Multicast** durch. Das ist derselbe Weg, auf dem Drucker und Chromecast gefunden werden. Darum tritt die App beim Start der Multicast-Gruppe `239.255.50.55` bei (`IP_ADD_MEMBERSHIP` auf `bsock`) und schickt alles, was sie per Broadcast schickt, zusätzlich an diese Gruppe (Port 50505). Ältere Versionen hören nur Broadcast. In so einem WLAN müssen darum alle mindestens Version 2.2 haben.

Manche WLANs sperren auch **direkte** Verbindungen zwischen Geräten („Client Isolation“). Darum gehen `help`, `done` und `ack` direkt an den Empfänger **und** als Kopie an die Multicast-Gruppe. Die Kopie enthält das Feld `"to"` mit der `peer_id` des Empfängers. Alle anderen ignorieren sie. Kommen beide Kopien an, erkennt der Empfänger die zweite an der gleichen `id` als Duplikat (siehe unten). Ältere Versionen ignorieren das Feld `"to"` einfach.

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
- Ist das länger als **20 Sekunden** her, wird der Punkt **grau** (`_shown_status` in TEIL 6). 20 Sekunden heisst: Vier Heartbeats hintereinander müssen fehlen. Ein paar verlorene Pakete oder ein kurz hängendes WLAN machen also niemanden grau. Ändern kann man das bei `OFFLINE_AFTER` in TEIL 1.
- Beim Beenden schickt die App `bye`. Dann wird man sofort grau und nicht erst nach 20 Sekunden.

**Nur die eigene Klasse:** Nachrichten mit einem anderen Beitrittscode haben eine falsche Signatur und werden schon in `decode()` aussortiert. So können mehrere Klassen im selben WLAN sein, ohne sich zu stören.

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

## Schritt 4: Die Oberfläche (TEIL 6)

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

### Kleine Leiste und Waybar

Die App hat drei Ansichten (`view`):
- **`mini`** (Windows, Mac, Linux): Die Klasse `MiniBar` ist ein kleines `Toplevel`-Fenster ohne Rahmen (`overrideredirect(True)`), das immer im Vordergrund liegt (`-topmost`). Das grosse Fenster wird mit `withdraw()` versteckt und mit `deiconify()` wieder gezeigt.
- **`waybar`** (Omarchy/Hyprland, erkannt an `HYPRLAND_INSTANCE_SIGNATURE`): Statt einer Leiste schreibt `_update_small_views()` den Zustand als fertiges Waybar-JSON in `~/.cache/klassenzimmer/waybar.json`. Die Waybar liest die Datei alle 2 Sekunden mit `cat`. Der farbige Punkt ist Pango-Markup: `<span color='#2e9e44'>●</span>`.
- **`fenster`** (Testmodus): nur das grosse Fenster, wie bisher.

Das Fenster-X ruft `close_window()` auf. Im Testmodus beendet es die App, sonst wird das Fenster nur versteckt.

### Neu zeichnen

`_render_peers()` löscht alle Zeilen und baut sie neu auf. Das ist nicht das Effizienteste, aber einfach zu verstehen und für eine Klasse schnell genug. `_tick()` zeichnet zusätzlich jede Sekunde neu, damit Leute grau werden, auch wenn gerade keine Nachricht kommt.

---

## Schritt 5: Start, Speichern, Autostart und Steuerung (TEIL 2, 3, 4 und 7)

**Zwei Arten zu starten:**
- **Normal** (ohne `--name`): Das Startfenster fragt Name, Rolle und Beitrittscode ab, beim Coach auch den Klassennamen. Alles wird gespeichert, auch eine **feste ID** (`peer_id`), die bei jedem Start gleich bleibt.
- **Testmodus** (`--name … --role …`): Es wird nichts gespeichert, und man kann mehrere Apps auf einem PC starten.

**Klasse speichern (`Store`):** In der Einstellungsdatei steht pro Klasse (`room_id`, aus dem Code abgeleitet) jeder Teilnehmer, den man schon einmal gesehen hat (feste ID, Name, Rolle). Beim Start erscheinen alle sofort **grau** in der Liste und werden grün, sobald sie sich melden. Wer nicht mehr in die Klasse gehört, wird mit dem **✕** neben einem grauen Namen entfernt. Gespeichert wird zuerst in eine `.tmp`-Datei und erst dann umbenannt (`os.replace`). So ist die Datei nie halb geschrieben, auch wenn der PC abstürzt.

**Nur einmal starten und Befehle (`Control`):** Normal gestartet belegt die App den TCP-Port 50507 auf `127.0.0.1`, also nur auf diesem Computer. Ein zweiter Start merkt, dass der Port belegt ist, schickt der laufenden App über diesen Port den Befehl `show` (Fenster zeigen) und beendet sich. Genauso funktionieren `--zeigen`, `--status-umschalten` und `--beenden`, die die Waybar bei einem Klick aufruft. Seit Version 2.1 gibt es dazu Befehle mit Text dahinter: `--hilfe TEXT` (Schüler fragt den Coach), `--erledigt ID` und `--entfernen ID`. Angenommen werden nur diese Befehle (`parse_control`), alles andere wird ignoriert.

**Zustand für Leisten-Panels (`zustand.json`):** Unter Hyprland/Omarchy schreibt die App neben `waybar.json` auch `~/.cache/klassenzimmer/zustand.json` mit allem, was ein Panel braucht: Name, Rolle, Status, Klasse, Code, Teilnehmer mit Status, Warteschlange (Coach) und eigene Anfragen (Schüler). Sie schreibt die Datei nur, wenn sich etwas ändert, und immer ganz (erst `.tmp`, dann umbenennen), damit nie eine halbe Datei gelesen wird.

Ein Detail: Unter Linux und Mac setzt die App `SO_REUSEADDR`. Sonst hält das System den Port nach dem Beenden noch etwa eine Minute fest (`TIME_WAIT`), und ein schneller Neustart würde scheitern. Unter Windows verhindert `SO_EXCLUSIVEADDRUSE`, dass ein anderes Programm den Port „mitbenutzt“.

**Waybar einrichten (`setup_waybar`):** Die Funktion sucht `~/.config/waybar/config.jsonc`, legt eine Sicherung an und fügt mit `insert_waybar_module()` zwei Dinge ein: `"custom/klassenzimmer"` ganz vorne in `modules-right` und die Modul-Einstellungen direkt nach der ersten `{`. Die Datei ist JSONC, also JSON mit Kommentaren. Darum wird nicht `json.load` benutzt, sondern gezielt Text eingefügt. Danach lädt `omarchy-restart-waybar` die Waybar neu.

**Autostart:** Je nach System ein Registry-Eintrag (Windows), eine `.plist` in `~/Library/LaunchAgents` (Mac) oder eine `.desktop`-Datei in `~/.config/autostart` (Linux). Der gespeicherte Befehl enthält `--autostart`. Damit startet die App ohne Startfenster.

**Ablauf in `main()`:**
1. `argparse` liest die Optionen.
2. Normal: Sperre prüfen, Einstellungen laden, eventuell Startfenster zeigen und speichern.
3. Das `me`-dict beschreibt diese App: `peer_id`, Name, Rolle, Klassenname, Status. Aus dem Code wird der Schlüssel (`derive_key`).
4. `Network` wird gestartet, dann die Oberfläche. Beide teilen sich die `events`-Queue.
5. Schliesst man das Fenster, schickt `quit()` zweimal `bye` und schliesst die Sockets.

---

## Schritt 6: Testen

```
python3 -m unittest -v test_klassenzimmer
```

Die Tests starten mehrere „Teilnehmer“ in einem Programm und prüfen:

- alle finden sich, und eine neue App sieht die anderen in unter 1 Sekunde
- ein anderer Beitrittscode ist unsichtbar, gefälschte, unsignierte und alte Nachrichten werden verworfen
- das Waybar-Modul wird richtig eingefügt (und nicht doppelt)
- die Steuerung („läuft schon“, Befehle) funktioniert
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
python3 klassenzimmer.py --name Coach --role coach --code K7QM3X --verlust 0.5
python3 klassenzimmer.py --name Lena --role student --code K7QM3X
```

Der Coach „verliert“ jetzt die Hälfte aller Pakete. Bei Lena siehst du „Versuch 2/5“ oder „Versuch 3/5“ und am Ende trotzdem „✓ angekommen“.

---

## Wenn es nicht klappt

- **Niemand wird gefunden:** Die **Firewall** blockiert oft UDP. Unter Windows erscheint beim ersten Start eine Frage, dort „Zulassen“ wählen (privates Netzwerk). Unter Linux mit `ufw` (z.B. Omarchy) braucht es zwei Ports: 50505 für die Broadcasts und 50506 für direkte Nachrichten (`DIRECT_PORT`). Beide erlaubst du mit `sudo ufw allow 50505:50506/udp`. Ist 50506 schon besetzt, weicht die App auf einen zufälligen Port aus. Im Testmodus nimmt sie immer einen zufälligen Port, damit mehrere Apps auf einem PC laufen können.
- **Schul-WLAN mit „Client Isolation“:** Manche WLANs verbieten, dass Geräte direkt miteinander reden. Dann geht Peer-to-Peer gar nicht. Ausprobieren, sonst mit einem eigenen Router oder Hotspot.
- **Mehrere Netzwerkkarten:** `255.255.255.255` geht manchmal nur über eine Netzwerkkarte raus. Gib dann die Broadcast-Adresse deines Netzes an, z.B. `--broadcast 192.168.1.255`.
- **Mac:** Beim ersten Start fragt macOS, ob Python im lokalen Netzwerk kommunizieren darf. Mit „Erlauben“ bestätigen.

## Sicherheit: Was diese App (bewusst) nicht kann

Die Nachrichten sind **signiert, aber nicht verschlüsselt**:
- Wer den Beitrittscode **nicht** kennt, kann nichts fälschen und nicht mitmachen.
- Wer im selben WLAN mithört, kann trotzdem **mitlesen** (Namen, Fragen).
- Wer den Code **kennt**, also jeder in der Klasse, könnte sich theoretisch als jemand anderes ausgeben.

Für ein Klassenzimmer ist das in Ordnung. Schreib aber keine privaten Dinge in die Hilfeanfrage.

Was die App sonst noch schützt:

- kaputte oder zu grosse Pakete werden ignoriert
- Namen und Texte haben eine Maximallänge
- tkinter zeigt alles als reinen Text an, man kann also keinen Code einschleusen

---

## Übungen zum Weitermachen

1. **Leicht:** Ändere `HEARTBEAT_INTERVAL` auf 2 Sekunden und `OFFLINE_AFTER` auf 5. Was passiert, wenn du eine App mit dem Task-Manager hart beendest (dann kommt kein `bye`)?
2. **Leicht:** Füge einen dritten Status „Pause“ (blau) hinzu. Du musst ihn in TEIL 1 (`STATUSES`) und in TEIL 6 (`COLORS`, `STATUS_TEXT`, `toggle_status`) eintragen.
3. **Mittel:** Der Coach soll sehen, **wie lange** jemand schon wartet („seit 3 min“). Tipp: Speichere beim Empfang `time.monotonic()` und rechne in `_tick` neu.
4. **Mittel:** Ein Schüler soll seine Anfrage **zurückziehen** können. Dafür brauchst du einen neuen Nachrichtentyp `cancel`, der auch zuverlässig mit ACK gesendet wird.
5. **Schwer:** Wenn es zwei Coaches gibt und einer „Erledigt“ klickt, soll die Anfrage auch beim anderen verschwinden. Wie erfahren die Coaches voneinander?
6. **Schwer:** Die Nachrichten sind signiert, aber lesbar. Überlege: Warum gibt es in der Python-Standardbibliothek keine Verschlüsselung wie AES? Welche Bibliothek bräuchte man dafür, und was müsste man in `encode()` und `decode()` ändern?
