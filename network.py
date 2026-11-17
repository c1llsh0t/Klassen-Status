"""
SCHRITT 2 und 3: Der Netzwerk-Teil

Hier passiert alles, was mit dem Netzwerk zu tun hat. Die Oberfläche
(gui.py) weiss nichts von Sockets – sie bekommt nur "Ereignisse"
(Events) über eine Warteschlange (queue.Queue).

Warum so? tkinter ist NICHT thread-sicher: Nur der Hauptthread darf die
Oberfläche verändern. Die Netzwerk-Threads legen darum nur Zettel in die
Queue, und die Oberfläche holt sie regelmässig ab (siehe gui.py, _poll).

    Netzwerk-Threads  --(events.put)-->  Queue  --(events.get)-->  GUI

Wir benutzen ZWEI UDP-Sockets:

  1. bsock  ("Broadcast-Socket") auf Port 50505
     Hier kommen die Broadcasts an: heartbeat und bye von allen.

  2. usock  ("Unicast-Socket") auf einem freien Port, den das
     Betriebssystem aussucht. Dorthin schickt man mir direkte Nachrichten
     (help, done, ack). Den Port verrate ich allen im heartbeat.
     Vorteil: Man kann mehrere Instanzen auf DEMSELBEN Rechner testen,
     weil jede ihren eigenen Unicast-Port hat.
"""

import random
import socket
import threading
import time

import protocol as P


class Network:
    def __init__(self, me, events, broadcast_addr="255.255.255.255", loss=0.0, port=0):
        """
        me             – dict mit peer_id, name, role, status (gehört uns)
        events         – queue.Queue, in die wir Ereignisse für die GUI legen
        broadcast_addr – wohin Broadcasts gehen (255.255.255.255 = alle im LAN)
        port           – fester Port für direkte Nachrichten (0 = zufällig).
                         Praktisch, wenn eine Firewall nur bestimmte Ports erlaubt.
        loss           – zum Üben: Anteil Pakete, die wir absichtlich
                         "verlieren" (0.3 = 30 %). Damit sieht man die
                         Wiederholungen (Retries) in Aktion.
        """
        self.me = me
        self.events = events
        self.broadcast_addr = broadcast_addr
        self.loss = loss
        self.unicast_port = port

        self.lock = threading.Lock()   # schützt me["status"], pending, seen
        self.running = False
        self.pending = {}   # msg_id -> {"msg", "addr", "tries", "next"}
        self.seen = {}      # msg_id -> Zeitpunkt  (für Duplikat-Erkennung)
        self.known = set()  # peer_ids, die wir schon kennen
        self.next_heartbeat = 0.0

    # ------------------------------------------------------------------
    # Starten und Stoppen
    # ------------------------------------------------------------------
    def start(self):
        # --- Broadcast-Socket ---
        self.bsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # REUSEADDR/REUSEPORT: mehrere Programme dürfen Port 50505 teilen
        # (z.B. zwei Instanzen auf einem PC zum Testen).
        self.bsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):  # gibt es nicht unter Windows
            try:
                self.bsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        self.bsock.bind(("", P.DISCOVERY_PORT))
        self.bsock.settimeout(0.5)  # damit der Thread regelmässig "running" prüft

        # --- Unicast-Socket (sendet auch die Broadcasts) ---
        self.usock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.usock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.usock.bind(("", self.unicast_port))  # 0 = "Betriebssystem, such dir einen aus"
        self.usock.settimeout(0.5)
        self.me["port"] = self.usock.getsockname()[1]

        self.running = True
        # daemon=True: Threads werden beim Programmende automatisch beendet
        for target, args in (
            (self._receive_loop, (self.bsock,)),
            (self._receive_loop, (self.usock,)),
            (self._timer_loop, ()),
        ):
            threading.Thread(target=target, args=args, daemon=True).start()

    def stop(self):
        """Beim Beenden: 'bye' an alle, dann Sockets schliessen."""
        if not self.running:
            return
        bye = P.make_bye(self.me)
        for _ in range(2):  # UDP kann verloren gehen -> sicherheitshalber 2x
            self._broadcast(bye)
        self.running = False
        self.bsock.close()
        self.usock.close()

    # ------------------------------------------------------------------
    # Öffentliche Funktionen für die GUI
    # ------------------------------------------------------------------
    def set_status(self, status):
        with self.lock:
            self.me["status"] = status
            self.next_heartbeat = 0.0  # sofort einen heartbeat schicken

    def send_help(self, coach_ip, coach_port, text):
        """Hilfeanfrage zuverlässig an einen Coach schicken. Gibt die ID zurück."""
        msg = P.make_help(self.me, text)
        self._send_reliable(msg, (coach_ip, coach_port))
        return msg["id"]

    def send_done(self, student_ip, student_port, help_id):
        msg = P.make_done(self.me, help_id)
        self._send_reliable(msg, (student_ip, student_port))

    # ------------------------------------------------------------------
    # SCHRITT 3: Zuverlässig senden mit ACK und Wiederholung
    # ------------------------------------------------------------------
    # UDP garantiert nicht, dass ein Paket ankommt. Darum:
    #   1. Nachricht senden und in "pending" merken
    #   2. Kommt ein ACK mit derselben ID -> aus "pending" löschen, fertig
    #   3. Kein ACK nach 3 s -> nochmal senden (höchstens 5 Versuche)
    #   4. Nach 5 Versuchen ohne ACK -> aufgeben und der GUI melden
    def _send_reliable(self, msg, addr):
        with self.lock:
            self.pending[msg["id"]] = {
                "msg": msg, "addr": addr, "tries": 1, "next": P.now() + P.ACK_TIMEOUT,
            }
        self._send(msg, addr)
        self.events.put(("sending", msg["id"], 1))

    def _check_retries(self):
        t = P.now()
        resend, failed = [], []
        with self.lock:
            for msg_id, p in list(self.pending.items()):
                if t < p["next"]:
                    continue
                if p["tries"] >= P.MAX_TRIES:
                    del self.pending[msg_id]
                    failed.append(msg_id)
                else:
                    p["tries"] += 1
                    p["next"] = t + P.ACK_TIMEOUT
                    resend.append((p["msg"], p["addr"], p["tries"]))
        # Senden ausserhalb des Locks (Netzwerk kann langsam sein)
        for msg, addr, tries in resend:
            self._send(msg, addr)
            self.events.put(("sending", msg["id"], tries))
        for msg_id in failed:
            self.events.put(("failed", msg_id))

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------
    def _timer_loop(self):
        """Läuft im Hintergrund: heartbeats und Wiederholungen."""
        while self.running:
            with self.lock:
                due = P.now() >= self.next_heartbeat
                if due:
                    self.next_heartbeat = P.now() + P.HEARTBEAT_INTERVAL
                    hb = P.make_heartbeat(self.me)
            if due:
                self._broadcast(hb)
            self._check_retries()
            self._forget_old_ids()
            time.sleep(0.2)  # kurz schlafen

    def _receive_loop(self, sock):
        """Wartet auf Pakete und verarbeitet sie. Ein Thread pro Socket."""
        while self.running:
            try:
                data, addr = sock.recvfrom(P.MAX_PACKET + 1)
            except socket.timeout:
                continue
            except OSError:
                break  # Socket wurde geschlossen
            try:
                self._handle(data, addr)
            except Exception as e:  # ein kaputtes Paket darf nie alles stoppen
                self.events.put(("log", "Fehler bei Paket von %s: %s" % (addr[0], e)))

    # ------------------------------------------------------------------
    # Empfangene Nachrichten verarbeiten
    # ------------------------------------------------------------------
    def _handle(self, data, addr):
        if self.loss and random.random() < self.loss:
            return  # Paketverlust simulieren (nur zum Üben)

        msg = P.decode(data)
        if msg is None or msg["from"] == self.me["peer_id"]:
            return  # kaputt, oder unser eigener Broadcast

        t = msg["type"]
        ip = addr[0]

        # --- Duplikate erkennen ---
        with self.lock:
            duplicate = msg["id"] in self.seen
            self.seen[msg["id"]] = P.now()
        if duplicate:
            # Ganz wichtig: Bei help/done trotzdem nochmal ACK senden!
            # Wahrscheinlich ist nämlich unser erstes ACK verloren gegangen,
            # und der Absender wartet immer noch darauf.
            if t in ("help", "done"):
                self._send(P.make_ack(self.me, msg["id"]), addr)
            return

        if t == "heartbeat":
            # Neuer Teilnehmer? Dann antworten wir ihm sofort direkt mit
            # unserem eigenen heartbeat. Sonst müsste er bis zu 5 Sekunden
            # warten, bis er uns sieht.
            if msg["from"] not in self.known:
                self.known.add(msg["from"])
                with self.lock:
                    hb = P.make_heartbeat(self.me)
                self._send(hb, (ip, msg["port"]))
            self.events.put(("peer", {
                "peer_id": msg["from"], "name": P.clean_name(msg["name"]),
                "role": msg["role"], "status": msg["status"],
                "ip": ip, "port": msg["port"],
            }))
        elif t == "bye":
            self.known.discard(msg["from"])
            self.events.put(("bye", msg["from"]))
        elif t == "help":
            # Antwort an die Absender-Adresse (IP + Port des Unicast-Sockets)
            self._send(P.make_ack(self.me, msg["id"]), addr)
            self.events.put(("help", {
                "help_id": msg["id"], "peer_id": msg["from"],
                "name": P.clean_name(msg["name"]), "text": msg["text"],
                "ip": ip, "port": addr[1],
            }))
        elif t == "done":
            self._send(P.make_ack(self.me, msg["id"]), addr)
            self.events.put(("done", msg["help_id"]))
        elif t == "ack":
            with self.lock:
                found = self.pending.pop(msg["ack_id"], None)
            if found:
                self.events.put(("acked", msg["ack_id"], msg["from"]))

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------
    def _send(self, msg, addr):
        try:
            self.usock.sendto(P.encode(msg), addr)
        except OSError as e:
            self.events.put(("log", "Senden an %s fehlgeschlagen: %s" % (addr[0], e)))

    def _broadcast(self, msg):
        self._send(msg, (self.broadcast_addr, P.DISCOVERY_PORT))

    def _forget_old_ids(self):
        """Gesehene IDs nach 2 Minuten vergessen, sonst wächst die Liste ewig."""
        limit = P.now() - 120
        with self.lock:
            for msg_id, t in list(self.seen.items()):
                if t < limit:
                    del self.seen[msg_id]
