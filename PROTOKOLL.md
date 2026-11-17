# Schritt 1: Das Nachrichtenprotokoll

Jede Nachricht ist ein JSON-Objekt und wird als UTF-8 über UDP verschickt. Drei Felder hat **jede** Nachricht:

| Feld | Bedeutung |
|---|---|
| `type` | was für eine Nachricht es ist |
| `id` | eine eindeutige ID **dieser** Nachricht (`uuid4`), damit man Duplikate erkennt |
| `from` | die feste ID der App, die sie geschickt hat. Sie wird beim ersten Start erzeugt und gespeichert. Wir nehmen nicht den Namen, weil zwei Leute gleich heissen können. |
| `ts` | Zeitpunkt in Sekunden (Unix-Zeit). Nachrichten, die mehr als 10 Minuten alt sind, werden ignoriert. |
| `mac` | Signatur mit dem **Beitrittscode** (HMAC-SHA256). Nur wer den Code kennt, kann gültige Nachrichten schicken. |

## Nachrichtentypen

### 1. `heartbeat`: „Ich bin da“
Geht alle 5 Sekunden per **Broadcast** an alle, auf Port 50505.
```json
{"type": "heartbeat", "id": "b3f1c2…", "from": "a91c7e…", "ts": 1763380000,
 "name": "Lena", "role": "student", "status": "online", "class": "",
 "port": 50506, "mac": "9f2c…"}
```
- `role`: `student` oder `coach`
- `status`: `online` (grün) oder `busy` (gelb, nicht stören). „Offline“ (grau) wird nie verschickt. Das erkennt jeder selbst, wenn 20 Sekunden lang kein Heartbeat kommt.
- `class`: der Klassenname, den der Coach eingegeben hat (bei Schülern leer). Er dient nur zur Anzeige. Wer zur Klasse gehört, entscheidet der Beitrittscode (siehe unten).
- `port`: der Port, an den man mir **direkt** schreibt. Jede App hört dafür auf einem zweiten, eigenen Port. Der Vorteil: Man kann mehrere Apps auf einem Rechner testen, ohne dass sie sich die direkten Nachrichten wegnehmen.

### 2. `bye`: „Ich gehe“
Geht beim Beenden per Broadcast an alle, dann wird man sofort grau.
```json
{"type": "bye", "id": "c42d…", "from": "a91c7e…"}
```

### 3. `help`: Hilfeanfrage
Geht direkt (**Unicast**) an `IP:port` des Coaches. `text` darf leer sein.
```json
{"type": "help", "id": "d9e0…", "from": "a91c7e…",
 "name": "Lena", "text": "Wie geht Aufgabe 3b?"}
```

### 4. `ack`: Bestätigung
Geht direkt an den Absender zurück. In `ack_id` steht die ID der Nachricht, die angekommen ist.
```json
{"type": "ack", "id": "e5f6…", "from": "7f3b90…", "ack_id": "d9e0…"}
```

### 5. `done`: Anfrage erledigt (Extra)
Der Coach hat „Erledigt“ geklickt. Geht direkt an den Schüler, auch mit ACK.
```json
{"type": "done", "id": "f7a8…", "from": "7f3b90…", "help_id": "d9e0…"}
```

## Beitrittscode und Signatur

Der Coach erzeugt einen Code aus 6 Zeichen, z.B. `K7Q-M3X`. Daraus macht jede App mit **PBKDF2** (200 000 Runden) einen geheimen Schlüssel. Mit diesem Schlüssel wird jede Nachricht signiert (`mac` = HMAC-SHA256 über alle anderen Felder, sortiert).

- Wer den Code nicht kennt, kann **keine gültigen Nachrichten** schicken, und seine werden ignoriert.
- Mehrere Klassen im selben WLAN (verschiedene Codes) sehen sich gegenseitig nicht.
- Eine veränderte Nachricht (z.B. `"role": "coach"` statt `"student"`) passt nicht mehr zur Signatur und wird verworfen.
- Mit `ts` und den gespeicherten IDs kann niemand alte, mitgeschnittene Nachrichten erneut abspielen.
- **Aber:** Die Nachrichten sind **nicht verschlüsselt**. Wer im WLAN mithört, kann Namen und Fragen lesen.

## Regeln

- Nachrichten, die kein gültiges JSON sind, grösser als 4 KB sind, eine falsche Signatur haben, zu alt sind oder bei denen Felder fehlen, werden einfach ignoriert. Kein Absturz.
- Nachrichten mit meinem eigenen `from` ignoriere ich, denn meinen eigenen Broadcast höre ich auch.
- `help` und `done` werden so lange wiederholt, bis ein `ack` kommt: alle 3 Sekunden, höchstens 5 Mal.
- Kommt eine `id` doppelt an, zeige ich sie nicht nochmal an, schicke aber **trotzdem ein ACK**. Wahrscheinlich ist nämlich mein erstes ACK verloren gegangen.

## Zum Ausprobieren

```python
import json, uuid, time
msg = {"type": "bye", "id": uuid.uuid4().hex, "from": uuid.uuid4().hex, "ts": int(time.time())}
daten = json.dumps(msg).encode("utf-8")   # so geht es übers Netzwerk
print(daten)
print(json.loads(daten.decode("utf-8")))  # und so wird es wieder ein dict
```
