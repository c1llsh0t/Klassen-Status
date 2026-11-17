"""
SCHRITT 1: Das Protokoll – wie sehen unsere Nachrichten aus?

Bevor zwei Programme miteinander reden können, müssen sie sich auf eine
"Sprache" einigen. Das nennt man Protokoll. Bei uns ist jede Nachricht
ein JSON-Objekt, zum Beispiel:

    {"type": "heartbeat", "id": "3f2a...", "from": "a91c...",
     "name": "Lena", "role": "student", "status": "online", "port": 51234}

Diese Datei enthält:
  - die Einstellungen (Port, Zeiten), damit man sie an einem Ort ändern kann
  - Funktionen, um Nachrichten zu bauen (make_...)
  - eine Funktion, um empfangene Bytes sicher in eine Nachricht umzuwandeln
"""

import json
import time
import uuid

# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------
DISCOVERY_PORT = 50505        # Auf diesem Port hören alle auf Broadcasts
HEARTBEAT_INTERVAL = 5.0      # Sekunden zwischen zwei "Ich bin da"-Meldungen
OFFLINE_AFTER = 10.0          # So lange ohne Meldung -> grau (offline)
ACK_TIMEOUT = 3.0             # So lange auf eine Bestätigung warten
MAX_TRIES = 5                 # So oft höchstens senden
MAX_PACKET = 4096             # Grössere Pakete ignorieren wir

ROLES = ("student", "coach")
STATUSES = ("online", "busy")  # online = grün, busy = gelb ("nicht stören")
MAX_NAME = 30
MAX_TEXT = 300


def new_id():
    """Eine zufällige, eindeutige ID, z.B. '9b1deb4d3b7d4bad9bdd2b0d7b3dcb6d'.

    uuid4 erzeugt 122 zufällige Bits – dass zwei IDs gleich sind,
    ist praktisch unmöglich. Damit erkennen wir doppelte Nachrichten.
    """
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Nachrichten bauen
# ---------------------------------------------------------------------------
# Jede Nachricht hat mindestens:
#   type  – was für eine Nachricht ist es?
#   id    – eindeutige Nummer DIESER Nachricht
#   from  – wer hat sie geschickt? (die ID der App-Instanz, nicht der Name!)

def make_heartbeat(me):
    """'Ich bin da' – wird alle 5 Sekunden an alle geschickt (Broadcast)."""
    return {
        "type": "heartbeat",
        "id": new_id(),
        "from": me["peer_id"],
        "name": me["name"],
        "role": me["role"],
        "status": me["status"],
        "port": me["port"],   # dorthin schickt man mir direkte Nachrichten
    }


def make_bye(me):
    """'Ich gehe' – beim Beenden an alle (Broadcast)."""
    return {"type": "bye", "id": new_id(), "from": me["peer_id"]}


def make_help(me, text):
    """Hilfeanfrage eines Schülers – direkt an den Coach (Unicast)."""
    return {
        "type": "help",
        "id": new_id(),
        "from": me["peer_id"],
        "name": me["name"],
        "text": text[:MAX_TEXT],
    }


def make_done(me, help_id):
    """Coach meldet dem Schüler: deine Anfrage ist erledigt (Unicast)."""
    return {"type": "done", "id": new_id(), "from": me["peer_id"], "help_id": help_id}


def make_ack(me, msg_id):
    """Bestätigung: 'Ich habe die Nachricht mit dieser ID bekommen.'"""
    return {"type": "ack", "id": new_id(), "from": me["peer_id"], "ack_id": msg_id}


# ---------------------------------------------------------------------------
# Senden und Empfangen: Umwandeln zwischen Python-dict und Bytes
# ---------------------------------------------------------------------------

def encode(msg):
    """dict -> Bytes, die man über das Netzwerk schicken kann."""
    return json.dumps(msg, ensure_ascii=False).encode("utf-8")


def _is_id(value):
    return isinstance(value, str) and 1 <= len(value) <= 64


def decode(data):
    """Bytes -> dict. Gibt None zurück, wenn die Nachricht kaputt ist.

    WICHTIG: Alles, was aus dem Netzwerk kommt, kann falsch oder
    absichtlich böse sein. Darum prüfen wir jedes Feld, bevor wir es
    benutzen. Lieber eine Nachricht wegwerfen als abstürzen.
    """
    if len(data) > MAX_PACKET:
        return None
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(msg, dict):
        return None
    if not (_is_id(msg.get("id")) and _is_id(msg.get("from"))):
        return None

    t = msg.get("type")
    if t == "heartbeat":
        name = msg.get("name")
        port = msg.get("port")
        ok = (
            isinstance(name, str) and 1 <= len(name.strip()) <= MAX_NAME
            and msg.get("role") in ROLES
            and msg.get("status") in STATUSES
            and isinstance(port, int) and 1 <= port <= 65535
        )
        return msg if ok else None
    if t == "bye":
        return msg
    if t == "help":
        ok = (
            isinstance(msg.get("name"), str) and 1 <= len(msg["name"]) <= MAX_NAME
            and isinstance(msg.get("text"), str) and len(msg["text"]) <= MAX_TEXT
        )
        return msg if ok else None
    if t == "done":
        return msg if _is_id(msg.get("help_id")) else None
    if t == "ack":
        return msg if _is_id(msg.get("ack_id")) else None
    return None  # unbekannter Typ


def clean_name(name):
    """Name aufräumen: Leerzeichen am Rand weg, Länge begrenzen."""
    name = " ".join(str(name).split())
    return name[:MAX_NAME]


def now():
    """Aktuelle Zeit in Sekunden. monotonic() springt nie zurück
    (auch nicht, wenn jemand die Uhr verstellt) – ideal für Timeouts."""
    return time.monotonic()
