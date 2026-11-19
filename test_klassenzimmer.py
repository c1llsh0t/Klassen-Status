"""
Automatische Tests für klassenzimmer.py

Starten:  python3 -m unittest -v test_klassenzimmer

Die Tests starten mehrere "Teilnehmer" im selben Programm (ohne Fenster).
Damit sie schnell sind, warten wir nur 0.3 s auf ACKs statt 3 s.
"""

import os
import plistlib
import queue
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import klassenzimmer as K

K.ACK_TIMEOUT = 0.3
KEY = K.derive_key("K7QM3X")


# ---------------------------------------------------------------------------
# Hilfsmittel
# ---------------------------------------------------------------------------
class DropNetwork(K.Network):
    """Wie Network, verwirft aber absichtlich die ersten N Nachrichten eines Typs.
    Eine Nachricht kann doppelt ankommen (direkt + Multicast-Kopie), darum wird die
    Kopie, die gleich danach kommt, auch verworfen. Eine Wiederholung (gleiche ID,
    aber erst nach ACK_TIMEOUT) zählt als neuer Versuch."""

    def __init__(self, *a, drop=None, **kw):
        super().__init__(*a, **kw)
        self.drop = dict(drop or {})
        self.dropped = {}                 # msg_id -> Zeitpunkt des Verwerfens

    def _handle(self, data, addr):
        msg = K.decode(data, self.key)
        if msg and time.time() - self.dropped.get(msg["id"], 0) < K.ACK_TIMEOUT / 2:
            return                                    # Kopie desselben Versuchs
        if msg and self.drop.get(msg["type"], 0) > 0:
            self.drop[msg["type"]] -= 1
            self.dropped[msg["id"]] = time.time()
            return
        super()._handle(data, addr)


def collect(q, seconds):
    out, end = [], time.time() + seconds
    while time.time() < end:
        try:
            out.append(q.get(timeout=0.05))
        except queue.Empty:
            pass
    return out


def wait_for(q, kind, seconds=5, match=lambda ev: True):
    end, seen = time.time() + seconds, []
    while time.time() < end:
        try:
            ev = q.get(timeout=0.05)
        except queue.Empty:
            continue
        seen.append(ev)
        if ev[0] == kind and match(ev):
            return ev, seen
    raise AssertionError("Ereignis %r kam nicht. Gesehen: %r" % (kind, seen))


def find_peer(q, name, seconds=3):
    ev, _ = wait_for(q, "peer", seconds, match=lambda ev: ev[1]["name"] == name)
    return ev[1]


# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------
class ProtocolTest(unittest.TestCase):
    def me(self):
        return {"peer_id": K.new_id(), "name": "Lena", "role": "student",
                "status": "online", "klasse": "", "port": 1234}

    def test_gueltige_nachrichten(self):
        me = self.me()
        for msg in (K.make_heartbeat(me), K.make_bye(me), K.make_help(me, "Hallo"),
                    K.make_help(me, ""), K.make_done(me, K.new_id()), K.make_ack(me, K.new_id())):
            got = K.decode(K.encode(msg, KEY), KEY)
            got.pop("mac")
            self.assertEqual(got, msg)

    def test_kaputte_nachrichten_werden_ignoriert(self):
        hb = K.make_heartbeat(self.me())
        bad = [b"", b"kein json", b"[1,2]", b"null", b'{"type":"help"}', b"x" * 5000, b"\xff\xfe"]
        for change in ({"role": "chef"}, {"status": "weg"}, {"port": "80"}, {"port": True},
                       {"port": 0}, {"name": ""}, {"name": "x" * 31}, {"class": "x" * 21},
                       {"id": ""}, {"from": 5}, {"type": "hack"}, {"ts": "jetzt"}):
            bad.append(K.encode({**hb, **change}, KEY))   # richtig signiert, aber Unsinn
        for data in bad:
            self.assertIsNone(K.decode(data, KEY), data[:60])

    def test_falscher_code_und_faelschung(self):
        hb = K.make_heartbeat(self.me())
        self.assertIsNone(K.decode(K.encode(hb, K.derive_key("ABCDEF")), KEY))  # anderer Code
        import json
        forged = json.loads(K.encode(hb, KEY))
        forged["role"] = "coach"                                              # verändert
        self.assertIsNone(K.decode(json.dumps(forged).encode(), KEY))
        unsigned = json.dumps(hb).encode()                                    # ohne Signatur
        self.assertIsNone(K.decode(unsigned, KEY))

    def test_alte_nachricht_wird_ignoriert(self):
        hb = {**K.make_heartbeat(self.me()), "ts": int(time.time()) - K.TS_WINDOW - 5}
        self.assertIsNone(K.decode(K.encode(hb, KEY), KEY))

    def test_code_eingabe(self):
        c = K.new_code()
        self.assertEqual(len(c), 6)
        self.assertEqual(K.clean_code(K.format_code(c).lower()), c)
        self.assertEqual(K.clean_code(" k7q m3x "), "K7QM3X")
        for bad in ("", "K7QM3", "K7QM3XX", "K0QM3X", "KIQM3X", "K7QM3!"):
            self.assertIsNone(K.clean_code(bad), bad)

    def test_ids_sind_eindeutig(self):
        self.assertEqual(len({K.new_id() for _ in range(10000)}), 10000)



# ---------------------------------------------------------------------------
# Netzwerk
# ---------------------------------------------------------------------------
class NetworkTest(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for n, _ in self.nodes:
            n.stop()
        time.sleep(0.2)

    def make(self, name, role, code="K7QM3X", **kw):
        me = {"peer_id": K.new_id(), "name": name, "role": role, "status": "online", "klasse": ""}
        q = queue.Queue()
        n = DropNetwork(me, q, KEY if code == "K7QM3X" else K.derive_key(code), **kw)
        n.start()
        self.nodes.append((n, q))
        return n, q

    def test_alle_finden_sich(self):
        (a, qa), _, _ = self.make("Lena", "student"), self.make("Tim", "student"), self.make("Coach", "coach")
        names = {e[1]["name"] for e in collect(qa, 1) if e[0] == "peer"}
        self.assertEqual(names, {"Tim", "Coach"})

    def test_anderer_code_ist_unsichtbar(self):
        (a, qa), _ = self.make("Lena", "student"), self.make("Fremd", "student", "ABCDEF")
        _, _ = self.make("Tim", "student")
        names = {e[1]["name"] for e in collect(qa, 1) if e[0] == "peer"}
        self.assertEqual(names, {"Tim"})

    def test_neue_app_sieht_andere_sofort(self):
        self.make("Lena", "student")
        time.sleep(0.5)
        _, qb = self.make("Tim", "student")
        t0 = time.time()
        find_peer(qb, "Lena", seconds=2)
        self.assertLess(time.time() - t0, 1.0)

    def test_status_wechsel_kommt_sofort(self):
        (a, qa), (b, qb) = self.make("Lena", "student"), self.make("Tim", "student")
        find_peer(qa, "Tim")
        b.set_status("busy")
        wait_for(qa, "peer", 1.0, match=lambda ev: ev[1]["status"] == "busy")

    def test_hilfe_mit_bestaetigung(self):
        (s, qs), (c, qc) = self.make("Lena", "student"), self.make("Coach", "coach")
        coach = find_peer(qs, "Coach")
        help_id = s.send_help(coach["ip"], coach["port"], "Aufgabe 3?")
        ev, _ = wait_for(qc, "help")
        self.assertEqual((ev[1]["name"], ev[1]["text"]), ("Lena", "Aufgabe 3?"))
        ev, _ = wait_for(qs, "acked")
        self.assertEqual(ev[1], help_id)

    def test_wiederholung_wenn_anfrage_verloren(self):
        (s, qs), (c, qc) = self.make("Lena", "student"), self.make("Coach", "coach", drop={"help": 2})
        coach = find_peer(qs, "Coach")
        help_id = s.send_help(coach["ip"], coach["port"], "")
        _, seen = wait_for(qs, "acked", 5)
        self.assertEqual(max(e[2] for e in seen if e[0] == "sending" and e[1] == help_id), 3)
        self.assertEqual(len([e for e in collect(qc, 0.5) if e[0] == "help"]), 1)

    def test_duplikat_wird_erkannt_und_trotzdem_bestaetigt(self):
        (s, qs), (c, qc) = self.make("Lena", "student", drop={"ack": 2}), self.make("Coach", "coach")
        coach = find_peer(qs, "Coach")
        help_id = s.send_help(coach["ip"], coach["port"], "Hilfe")
        _, seen = wait_for(qs, "acked", 5)
        self.assertEqual(max(e[2] for e in seen if e[0] == "sending" and e[1] == help_id), 3)
        self.assertEqual(len([e for e in collect(qc, 0.5) if e[0] == "help"]), 1)

    def test_aufgeben_nach_5_versuchen(self):
        s, qs = self.make("Lena", "student")
        help_id = s.send_help("127.0.0.1", 9, "niemand da")
        ev, seen = wait_for(qs, "failed", 5)
        self.assertEqual(ev[1], help_id)
        self.assertEqual(max(e[2] for e in seen if e[0] == "sending"), K.MAX_TRIES)
        # Danach funktioniert das Empfangen weiterhin (wichtig unter Windows)
        _, qt = self.make("Tim", "student")
        find_peer(qs, "Tim")

    def test_erledigt_meldung(self):
        (s, qs), (c, qc) = self.make("Lena", "student"), self.make("Coach", "coach")
        coach = find_peer(qs, "Coach")
        help_id = s.send_help(coach["ip"], coach["port"], "")
        ev, _ = wait_for(qc, "help")
        c.send_done(ev[1]["ip"], ev[1]["port"], help_id)
        ev, _ = wait_for(qs, "done")
        self.assertEqual(ev[1], help_id)

    def test_fester_port_und_ausweichen(self):
        a, qa = self.make("Lena", "student", port=K.DIRECT_PORT, port_fallback=True)
        self.assertEqual(a.me["port"], K.DIRECT_PORT)
        b, qb = self.make("Tim", "student", port=K.DIRECT_PORT, port_fallback=True)
        self.assertNotEqual(b.me["port"], K.DIRECT_PORT)    # besetzt -> anderer Port
        find_peer(qa, "Tim")

    def test_multicast_wenn_direkt_gesperrt(self):
        # Schul-WLAN sperrt direkte Verbindungen: Die Kopie per Multicast kommt
        # trotzdem an, aber nur beim richtigen Empfänger.
        s, qs = self.make("Lena", "student")
        c, qc = self.make("Coach", "coach")
        _, qt = self.make("Tim", "student")
        if not (s.mcast and c.mcast):
            self.skipTest("kein Multicast auf diesem Rechner")
        find_peer(qs, "Coach")
        help_id = s.send_help("127.0.0.1", 9, "Aufgabe 3?", to=c.me["peer_id"])  # direkt: niemand da
        ev, _ = wait_for(qc, "help")
        self.assertEqual(ev[1]["help_id"], help_id)
        ev, _ = wait_for(qs, "acked")
        self.assertEqual(ev[1], help_id)
        self.assertFalse([e for e in collect(qt, 1) if e[0] in ("help", "acked")])

    def test_empfaenger_feld(self):
        me = {"peer_id": "a1", "name": "Lena", "role": "student", "status": "online", "klasse": ""}
        self.assertNotIn("to", K.make_help(me, "x"))
        msg = K.decode(K.encode(K.make_help(me, "x", "c9"), KEY), KEY)
        self.assertEqual(msg["to"], "c9")          # signiert und gültig
        self.assertEqual(K.make_ack(me, "m1", "b2")["to"], "b2")

    def test_bye_beim_beenden(self):
        a, qa = self.make("Lena", "student")
        me = {"peer_id": K.new_id(), "name": "Tim", "role": "student", "status": "online", "klasse": ""}
        b = K.Network(me, queue.Queue(), KEY)
        b.start()
        find_peer(qa, "Tim")
        b.stop()
        ev, _ = wait_for(qa, "bye")
        self.assertEqual(ev[1], me["peer_id"])


# ---------------------------------------------------------------------------
# Internet-Weg (TEIL 5b)
# ---------------------------------------------------------------------------
class IsolatedNetwork(DropNetwork):
    """WLAN mit Client-Isolation: Über das WLAN kommt nichts an, nur übers Internet."""

    def _send(self, msg, addr):
        if addr[0] == K.RELAY_IP:
            super()._send(msg, addr)


class FakeHub:
    """Ein Vermittler im Speicher: verteilt Pakete an alle, die das Thema abonniert
    haben (auch an den Absender, wie ein echter MQTT-Vermittler)."""

    def __init__(self):
        self.subs = []                      # (thema, callback)
        self.log = []                       # (thema, payload)
        self.q = queue.Queue()
        threading.Thread(target=self._deliver, daemon=True).start()

    def _deliver(self):
        while True:
            topic, payload = self.q.get()
            for t, cb in list(self.subs):
                if t == topic:
                    cb(topic, payload)


class FakeRelay:
    def __init__(self, hub):
        self.hub, self.connected = hub, False

    def start(self, topics, on_message, on_state=None, log=print):
        self.hub.subs += [(t, on_message) for t in topics]
        self.connected = True
        if on_state:
            on_state(True)

    def publish(self, topic, payload):
        self.hub.log.append((topic, payload))
        self.hub.q.put((topic, payload))
        return True

    def stop(self):
        self.connected = False


class MiniBroker:
    """Winziger MQTT-über-WebSocket-Vermittler auf 127.0.0.1 (ohne TLS), damit der
    echte Relay-Code getestet wird, ohne ins Internet zu gehen."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen()
        self.port = self.srv.getsockname()[1]
        self.clients = {}                   # socket -> abonnierte Themen
        self.lock = threading.Lock()
        self.connects = 0
        self.disconnects = 0
        threading.Thread(target=self._accept, daemon=True).start()

    def url(self):
        return "ws://test:geheim@127.0.0.1:%d/mqtt" % self.port

    def close(self):
        self.srv.close()
        with self.lock:
            for c in list(self.clients):
                c.close()

    def kick_all(self):
        with self.lock:
            for c in list(self.clients):
                c.close()

    @staticmethod
    def _frame(data):
        n = len(data)
        head = bytes([0x82, n]) if n < 126 else bytes([0x82, 126]) + struct.pack("!H", n)
        return head + data

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(c,), daemon=True).start()

    def _client(self, c):
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                head += c.recv(1024)
            rbuf = head.split(b"\r\n\r\n", 1)[1]
            c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      b"Connection: Upgrade\r\nSec-WebSocket-Protocol: mqtt\r\n\r\n")
            mbuf = b""
            while True:
                frame = K.ws_parse(rbuf)
                if not frame:
                    chunk = c.recv(4096)
                    if not chunk:
                        return
                    rbuf += chunk
                    continue
                _, data, rbuf = frame
                mbuf += data
                while True:
                    pkt = K.mqtt_parse(mbuf)
                    if not pkt:
                        break
                    first, body, mbuf = pkt
                    self._packet(c, first >> 4, first, body)
        except OSError:
            pass
        finally:
            with self.lock:
                self.clients.pop(c, None)
            c.close()

    def _packet(self, c, kind, first, body):
        if kind == 1:                                          # CONNECT
            n = struct.unpack("!H", body[:2])[0]
            assert body[2:2 + n] == b"MQTT"
            self.connects += 1
            c.sendall(self._frame(K.mqtt_packet(0x20, b"\x00\x00")))
        elif kind == 8:                                        # SUBSCRIBE
            i, topics = 2, []
            while i < len(body):
                n = struct.unpack("!H", body[i:i + 2])[0]
                topics.append(body[i + 2:i + 2 + n].decode())
                i += 3 + n
            with self.lock:
                self.clients[c] = topics
            c.sendall(self._frame(K.mqtt_packet(0x90, body[:2] + b"\x00" * len(topics))))
        elif kind == 3:                                        # PUBLISH -> weiterreichen
            n = struct.unpack("!H", body[:2])[0]
            topic = body[2:2 + n].decode()
            with self.lock:
                targets = [s for s, t in self.clients.items() if topic in t]
            for s in targets:
                try:
                    s.sendall(self._frame(K.mqtt_packet(0x30, body)))
                except OSError:
                    pass
        elif kind == 12:                                       # PINGREQ
            c.sendall(self._frame(K.mqtt_packet(0xD0, b"")))
        elif kind == 14:                                       # DISCONNECT
            self.disconnects += 1


class InternetTest(unittest.TestCase):
    def setUp(self):
        self.nodes = []
        self.hub = FakeHub()

    def tearDown(self):
        for n, _ in self.nodes:
            n.stop()
        time.sleep(0.2)

    def make(self, name, role, code="K7QM3X", relay=None, **kw):
        me = {"peer_id": K.new_id(), "name": name, "role": role, "status": "online", "klasse": ""}
        q = queue.Queue()
        n = IsolatedNetwork(me, q, KEY if code == "K7QM3X" else K.derive_key(code),
                            multicast=False, relay=relay or FakeRelay(self.hub), **kw)
        n.start()
        self.nodes.append((n, q))
        return n, q

    def me(self):
        return {"peer_id": K.new_id(), "name": "Lena", "role": "student", "status": "online",
                "klasse": "", "port": 1234}

    # ---- Bausteine -------------------------------------------------------------
    def test_verschluesselung(self):
        data = K.encode(K.make_help(self.me(), "Aufgabe 3 geht nicht"), KEY)
        a, b = K.seal(data, KEY), K.seal(data, KEY)
        self.assertNotEqual(a, b)                          # jedes Mal anders (nonce)
        self.assertNotIn(b"Lena", a)
        self.assertNotIn(b"Aufgabe", a)
        self.assertEqual(K.unseal(a, KEY), data)
        other = K.derive_key("ABCDEF")
        self.assertIsNone(K.decode(K.unseal(a, other), other))   # anderer Code: Datensalat
        bad = bytearray(a)
        bad[-5] ^= 1                                       # ein Bit verändert
        self.assertIsNone(K.decode(K.unseal(bytes(bad), KEY), KEY))
        for junk in (b"", b"KZ1", b"hallo", b"KZ1" + b"x" * 16, b"KZ1" + b"x" * 5000, "KZ1x"):
            self.assertIsNone(K.unseal(junk, KEY))

    def test_themen(self):
        alle, mein = K.relay_topics(KEY, "a1")
        self.assertEqual((alle, mein), K.relay_topics(KEY, "a1"))
        self.assertEqual(alle, K.relay_topics(KEY, "b2")[0])          # alle: gleich
        self.assertNotEqual(mein, K.relay_topics(KEY, "b2")[1])       # meins: pro Person
        self.assertNotEqual(alle, K.relay_topics(K.derive_key("ABCDEF"), "a1")[0])
        self.assertNotIn("K7QM3X", alle + mein)

    def test_mqtt_und_websocket_rahmen(self):
        for n in (0, 1, 127, 128, 16383, 16384, 70000):
            body = os.urandom(n)
            pkt = K.mqtt_packet(0x30, body) + b"rest"
            self.assertEqual(K.mqtt_parse(pkt), (0x30, body, b"rest"))
            self.assertIsNone(K.mqtt_parse(pkt[:len(pkt) - 5]))      # noch nicht ganz da
            frame = K.ws_frame(body) + b"rest"
            self.assertEqual(K.ws_parse(frame), (0x2, body, b"rest"))
            self.assertIsNone(K.ws_parse(frame[:len(frame) - 5]))
        self.assertIsNone(K.mqtt_parse(b""))
        with self.assertRaises(ValueError):
            K.mqtt_parse(b"\x30\xff\xff\xff\xff\x01")
        with self.assertRaises(ValueError):
            K.Relay("https://beispiel.ch/")

    # ---- Netzwerk nur übers Internet ---------------------------------------------
    def test_finden_und_hilfe_nur_uebers_internet(self):
        s, qs = self.make("Lena", "student")
        c, qc = self.make("Coach", "coach")
        _, qt = self.make("Tim", "student")
        coach = find_peer(qs, "Coach")
        self.assertEqual(coach["ip"], K.RELAY_IP)
        help_id = s.send_help(coach["ip"], coach["port"], "Aufgabe 3?", to=coach["peer_id"])
        ev, _ = wait_for(qc, "help")
        self.assertEqual((ev[1]["help_id"], ev[1]["text"]), (help_id, "Aufgabe 3?"))
        wait_for(qs, "acked", match=lambda ev: ev[1] == help_id)
        c.send_done(ev[1]["ip"], ev[1]["port"], help_id, to=ev[1]["peer_id"])
        wait_for(qs, "done", match=lambda ev: ev[1] == help_id)
        self.assertFalse([e for e in collect(qt, 0.5) if e[0] in ("help", "acked", "done")])
        # Direkte Nachrichten gehen nur ins Thema des Empfängers
        topic_coach = K.relay_topics(KEY, c.me["peer_id"])[1]
        self.assertIn(topic_coach, {t for t, _ in self.hub.log})

    def test_neuer_sieht_andere_sofort(self):
        self.make("Lena", "student")
        time.sleep(0.5)                       # Lenas nächster Internet-Heartbeat erst in 15 s
        _, qb = self.make("Tim", "student")
        t0 = time.time()
        find_peer(qb, "Lena", seconds=2)
        self.assertLess(time.time() - t0, 1.0)

    def test_anderer_code_ist_unsichtbar(self):
        (a, qa), _ = self.make("Lena", "student"), self.make("Fremd", "student", "ABCDEF")
        _, _ = self.make("Tim", "student")
        a.relay.publish(a.topic_all, b"KZ1" + os.urandom(80))         # Datensalat stört nicht
        names = {e[1]["name"] for e in collect(qa, 1) if e[0] == "peer"}
        self.assertEqual(names, {"Tim"})

    def test_heartbeat_seltener_und_status_sofort(self):
        with mock.patch.object(K, "HEARTBEAT_INTERVAL", 0.1), mock.patch.object(K, "RELAY_HEARTBEAT", 0.6):
            a, qa = self.make("Lena", "student")
            time.sleep(1.0)
            self.assertLessEqual(len(self.hub.log), 3)                  # nicht alle 0.1 s
            _, qb = self.make("Tim", "student")
            find_peer(qb, "Lena")
            a.set_status("busy")
            wait_for(qb, "peer", 0.5, match=lambda ev: ev[1]["status"] == "busy")

    def test_bye_uebers_internet(self):
        a, qa = self.make("Lena", "student")
        b, _ = self.make("Tim", "student")
        find_peer(qa, "Tim")
        b.stop()
        ev, _ = wait_for(qa, "bye")
        self.assertEqual(ev[1], b.me["peer_id"])

    # ---- Echter Relay-Code gegen einen Mini-Vermittler -----------------------------
    def test_echter_relay_mit_mini_vermittler(self):
        broker = MiniBroker()
        self.addCleanup(broker.close)
        s, qs = self.make("Lena", "student", relay=K.Relay(broker.url(), keepalive=2))
        c, qc = self.make("Coach", "coach", relay=K.Relay(broker.url(), keepalive=2))
        wait_for(qs, "internet", match=lambda ev: ev[1] is True)
        coach = find_peer(qs, "Coach", seconds=5)
        help_id = s.send_help(coach["ip"], coach["port"], "x" * 300, to=coach["peer_id"])  # > 125 Bytes
        wait_for(qc, "help", match=lambda ev: ev[1]["help_id"] == help_id)
        wait_for(qs, "acked", match=lambda ev: ev[1] == help_id)
        time.sleep(2.5)                                    # Pings halten die Verbindung
        self.assertEqual(broker.connects, 2)
        # Verbindung bricht ab -> neu verbinden, dann geht es weiter
        broker.kick_all()
        wait_for(qs, "internet", 3, match=lambda ev: ev[1] is False)
        wait_for(qs, "internet", 5, match=lambda ev: ev[1] is True)
        help2 = s.send_help(coach["ip"], coach["port"], "nochmal", to=coach["peer_id"])
        wait_for(qs, "acked", 5, match=lambda ev: ev[1] == help2)
        # Beenden: "bye" kommt noch an, dann DISCONNECT
        c.stop()
        wait_for(qs, "bye", 3)
        end = time.time() + 1
        while broker.disconnects < 1 and time.time() < end:
            time.sleep(0.02)                               # kommt direkt nach dem "bye"
        self.assertGreaterEqual(broker.disconnects, 1)

    @unittest.skipUnless(os.environ.get("KZ_LIVE"), "nur mit KZ_LIVE=1 (braucht Internet)")
    def test_live_oeffentlicher_vermittler(self):
        s, qs = self.make("Lena", "student", code="LIVE23", relay=K.Relay())
        c, qc = self.make("Coach", "coach", code="LIVE23", relay=K.Relay())
        coach = find_peer(qs, "Coach", seconds=15)
        help_id = s.send_help(coach["ip"], coach["port"], "live", to=coach["peer_id"])
        wait_for(qs, "acked", 10, match=lambda ev: ev[1] == help_id)


# ---------------------------------------------------------------------------
# Speicher und Autostart (in einem Test-Ordner, ändert nichts Echtes)
# ---------------------------------------------------------------------------
class StoreAndAutostartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.dict(os.environ, {"HOME": self.tmp.name, "APPDATA": self.tmp.name,
                                         "XDG_CONFIG_HOME": self.tmp.name + "/.config"}),
            mock.patch.object(Path, "home", return_value=Path(self.tmp.name)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_klasse_wird_gespeichert(self):
        s = K.Store()
        s.set_profile("Lena", "student", "K7QM3X")
        pid = s.get("peer_id")
        room = K.room_id(KEY)
        s.remember(room, "a" * 32, "Tim", "student")
        s.remember("anderer", "b" * 32, "Fremd", "student")
        # "Nächster Morgen": neu laden
        s2 = K.Store()
        self.assertEqual(s2.get("peer_id"), pid)            # feste ID
        self.assertEqual(s2.get("code"), "K7QM3X")
        self.assertEqual(list(s2.known(room).values()), [{"name": "Tim", "role": "student"}])
        s2.forget(room, "a" * 32)
        self.assertEqual(K.Store().known(room), {})

    def test_kaputte_datei(self):
        K.config_dir().mkdir(parents=True)
        (K.config_dir() / "einstellungen.json").write_text("{kaputt", encoding="utf-8")
        self.assertEqual(K.Store().known("x"), {})

    @unittest.skipIf(K.SYSTEM == "Windows", "Linux-Test")
    def test_linux_autostart_an_und_aus(self):
        with mock.patch.object(K, "SYSTEM", "Linux"):
            self.assertFalse(K.autostart_enabled())
            self.assertIsNone(K.set_autostart(True))
            self.assertTrue(K.autostart_enabled())
            self.assertIn("--autostart", K._linux_file().read_text(encoding="utf-8"))
            K.set_autostart(False)
            self.assertFalse(K.autostart_enabled())

    def test_mac_plist(self):
        data = plistlib.loads(K.mac_plist(["/Applications/Klassenzimmer.app/x", "--autostart"]))
        self.assertTrue(data["RunAtLoad"])

    def test_pfad_mit_leerzeichen(self):
        line = K.linux_desktop(["/home/lena/Meine Apps/Klassenzimmer", "--autostart"])
        self.assertIn('Exec="/home/lena/Meine Apps/Klassenzimmer" --autostart', line)


# ---------------------------------------------------------------------------
# Steuerung und Waybar
# ---------------------------------------------------------------------------
OMARCHY_LIKE = '''// Waybar
{
  "reload_style_on_change": true,
  "layer": "top",
  "modules-left": ["custom/omarchy", "hyprland/workspaces"],
  "modules-right": [
    "group/tray-expander",
    "bluetooth",
    "battery"
  ],
  /* Kommentar mit { Klammer */
  "battery": {"format": "{capacity}%"}
}
'''


def strip_jsonc(text):
    import re
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


class WaybarAndControlTest(unittest.TestCase):
    def test_waybar_modul_einfuegen(self):
        import json
        cmd = ["/home/lena/.local/bin/klassenzimmer"]
        new = K.insert_waybar_module(OMARCHY_LIKE, cmd)
        data = json.loads(strip_jsonc(new))                  # bleibt gültig
        self.assertEqual(data["modules-right"][0], "custom/klassenzimmer")
        mod = data["custom/klassenzimmer"]
        self.assertEqual(mod["return-type"], "json")
        self.assertTrue(mod["on-click"].endswith("--zeigen"))
        self.assertEqual(data["battery"], {"format": "{capacity}%"})   # Rest unverändert
        self.assertEqual(K.insert_waybar_module(new, cmd), new)        # nicht doppelt

    def test_waybar_mehrere_leisten(self):
        with self.assertRaises(ValueError):
            K.insert_waybar_module('[{"modules-right": []}]', ["x"])

    def test_steuerung(self):
        c = K.Control()
        if not c.acquire():
            self.skipTest("Steuer-Port belegt (läuft die App gerade?)")
        try:
            self.assertFalse(K.Control().acquire())          # zweiter Start: besetzt
            q = queue.Queue()
            c.start(q)
            self.assertTrue(K.send_control("toggle"))
            self.assertEqual(q.get(timeout=2), ("control", "toggle"))
            self.assertFalse(K.send_control("rm -rf"))       # unbekannt -> ignoriert
        finally:
            c.close()
        # Kurz danach wieder starten muss gehen (kein "Port belegt" nach dem Beenden)
        time.sleep(0.6)
        c2 = K.Control()
        self.assertTrue(c2.acquire())
        c2.close()


    def test_steuerbefehle_mit_text(self):
        P = K.parse_control
        self.assertEqual(P("toggle\n"), ("toggle", None))
        self.assertEqual(P("hilfe Aufgabe 3 geht nicht"), ("hilfe", "Aufgabe 3 geht nicht"))
        self.assertEqual(P("hilfe"), ("hilfe", ""))             # Hilfe ohne Text
        self.assertEqual(P("erledigt abc123"), ("erledigt", "abc123"))
        self.assertIsNone(P("toggle jetzt"))                    # alte Befehle ohne Text
        self.assertIsNone(P("rm -rf /"))
        c = K.Control()
        if not c.acquire():
            self.skipTest("Steuer-Port belegt (läuft die App gerade?)")
        try:
            q = queue.Queue()
            c.start(q)
            self.assertTrue(K.send_control("hilfe", "Aufgabe 3 \n  mit Umlaut ä"))
            self.assertEqual(q.get(timeout=2), ("control", "hilfe", "Aufgabe 3 mit Umlaut ä"))
            self.assertTrue(K.send_control("hilfe", "x" * 5000))  # zu lang -> abgeschnitten
            name, kind, text = q.get(timeout=2)
            self.assertEqual(kind, "hilfe")
            self.assertLess(len(text.encode("utf-8")), K.MAX_CONTROL)
        finally:
            c.close()

    def test_zustand_datei(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CACHE_HOME": d}):
            self.assertEqual(K.state_file(), Path(d) / "klassenzimmer" / "zustand.json")
            K.write_state({"name": "Lena", "peers": []})
            import json
            self.assertEqual(json.loads(K.state_file().read_text(encoding="utf-8"))["name"], "Lena")
            self.assertFalse(K.state_file().with_suffix(".tmp").exists())

if __name__ == "__main__":
    unittest.main(verbosity=2)
