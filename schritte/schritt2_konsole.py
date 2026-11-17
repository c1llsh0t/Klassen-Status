"""
SCHRITT 2: Konsolenversion – Heartbeat senden und empfangen

Was dieses Programm macht:
  - Alle 5 Sekunden ruft es per UDP-Broadcast "Ich bin da" ins Netz (heartbeat)
  - Gleichzeitig hört es auf Port 50505, wer sonst noch da ist
  - Wenn sich die Liste ändert, wird sie neu ausgegeben

Starten (in zwei Terminals oder auf zwei Rechnern):
    python3 schritt2_konsole.py --name Lena --role student
    python3 schritt2_konsole.py --name "Herr Keller" --role coach

Beenden mit Ctrl+C.
"""

import argparse
import json
import socket
import threading
import time
import uuid

# --- Einstellungen ---------------------------------------------------------
DISCOVERY_PORT = 50505          # hier hören alle auf Broadcasts
BROADCAST_ADDR = "255.255.255.255"
HEARTBEAT_INTERVAL = 5.0        # Sekunden


# --- Nachrichten -----------------------------------------------------------
def make_heartbeat(me):
    """Baut eine heartbeat-Nachricht (siehe PROTOKOLL.md)."""
    return {
        "type": "heartbeat",
        "id": uuid.uuid4().hex,     # jede Nachricht bekommt eine neue ID
        "from": me["peer_id"],      # wer bin ich? (neu bei jedem Start)
        "name": me["name"],
        "role": me["role"],
        "status": me["status"],
        "port": me["port"],
    }


def decode(data):
    """Bytes -> dict. Gibt None zurück, wenn etwas nicht stimmt."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(msg, dict) or msg.get("type") != "heartbeat":
        return None
    # Nur annehmen, wenn alle Felder da sind und den richtigen Typ haben
    if not (isinstance(msg.get("from"), str)
            and isinstance(msg.get("name"), str) and 0 < len(msg["name"]) <= 30
            and msg.get("role") in ("student", "coach")
            and msg.get("status") in ("online", "busy")):
        return None
    return msg


# --- Sockets ---------------------------------------------------------------
def make_listen_socket():
    """Socket, der auf Port 50505 alle Broadcasts empfängt."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Erlaubt mehreren Programmen auf demselben PC, Port 50505 zu benutzen
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):          # gibt es nicht unter Windows
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    s.bind(("", DISCOVERY_PORT))                  # "" = auf allen Netzwerkkarten
    return s


def make_send_socket():
    """Socket zum Senden. Bekommt einen freien Port vom Betriebssystem.
    (Diesen Port brauchen wir ab Schritt 4 für direkte Nachrichten.)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Broadcast erlauben
    s.bind(("", 0))                                           # 0 = irgendein freier Port
    return s


# --- Threads ---------------------------------------------------------------
def heartbeat_loop(sock, me):
    """Thread 1: alle 5 Sekunden einen heartbeat an alle schicken."""
    while True:
        data = json.dumps(make_heartbeat(me)).encode("utf-8")
        try:
            sock.sendto(data, (BROADCAST_ADDR, DISCOVERY_PORT))
        except OSError as e:
            print("Senden fehlgeschlagen:", e)
        time.sleep(HEARTBEAT_INTERVAL)


def receive_loop(sock, me, peers, lock):
    """Thread 2: auf Pakete warten und die Teilnehmerliste aktualisieren."""
    while True:
        data, addr = sock.recvfrom(4096)   # wartet, bis ein Paket kommt
        msg = decode(data)
        if msg is None:
            continue                       # kaputt -> ignorieren
        if msg["from"] == me["peer_id"]:
            continue                       # das war mein eigener Broadcast
        with lock:                         # peers wird von 2 Threads benutzt
            peers[msg["from"]] = {
                "name": msg["name"],
                "role": msg["role"],
                "status": msg["status"],
                "ip": addr[0],
                "last_seen": time.monotonic(),
            }


# --- Ausgabe ---------------------------------------------------------------
def print_peers(peers):
    print()
    print("=== Teilnehmer (%s) ===" % time.strftime("%H:%M:%S"))
    if not peers:
        print("  (noch niemand gefunden)")
    for p in sorted(peers.values(), key=lambda p: p["name"].lower()):
        print("  %-20s %-8s %-7s %s" % (p["name"], p["role"], p["status"], p["ip"]))


# --- Hauptprogramm ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=["student", "coach"], required=True)
    args = parser.parse_args()

    listen_sock = make_listen_socket()
    send_sock = make_send_socket()

    me = {
        "peer_id": uuid.uuid4().hex,
        "name": args.name.strip()[:30],
        "role": args.role,
        "status": "online",
        "port": send_sock.getsockname()[1],
    }
    print("Ich bin %s (%s), mein Port: %d" % (me["name"], me["role"], me["port"]))

    peers = {}                 # peer_id -> Infos
    lock = threading.Lock()

    # daemon=True: Die Threads enden automatisch, wenn das Hauptprogramm endet
    threading.Thread(target=heartbeat_loop, args=(send_sock, me), daemon=True).start()
    threading.Thread(target=receive_loop, args=(listen_sock, me, peers, lock), daemon=True).start()

    # Hauptthread: jede Sekunde schauen, ob sich die Liste geändert hat
    last_shown = None
    try:
        while True:
            with lock:
                # Nur Name/Rolle/Status vergleichen (last_seen ändert sich ja ständig)
                now_shown = sorted((p["name"], p["role"], p["status"]) for p in peers.values())
                snapshot = dict(peers)
            if now_shown != last_shown:
                print_peers(snapshot)
                last_shown = now_shown
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nTschüss!")


if __name__ == "__main__":
    main()
