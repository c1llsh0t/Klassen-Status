"""
Automatische Tests für Protokoll und Netzwerk (ohne Oberfläche).

Starten:  python3 -m unittest -v test_network

Die Tests starten mehrere "Teilnehmer" im selben Programm. Damit sie nicht
ewig dauern, setzen wir die Wartezeit für ACKs auf 0.3 Sekunden.
"""

import queue
import time
import unittest

import protocol as P
from network import Network

P.ACK_TIMEOUT = 0.3


class DropNetwork(Network):
    """Wie Network, aber verwirft absichtlich die ersten N Pakete eines Typs."""

    def __init__(self, *args, drop=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.drop = dict(drop or {})   # z.B. {"help": 2} = die ersten 2 help verwerfen

    def _handle(self, data, addr):
        msg = P.decode(data)
        if msg and self.drop.get(msg["type"], 0) > 0:
            self.drop[msg["type"]] -= 1
            return
        super()._handle(data, addr)


def node(name, role, **kw):
    me = {"peer_id": P.new_id(), "name": name, "role": role, "status": "online"}
    q = queue.Queue()
    n = DropNetwork(me, q, **kw)
    n.start()
    return n, q


def collect(q, seconds):
    """Alle Ereignisse sammeln, die in `seconds` Sekunden ankommen."""
    out, end = [], time.time() + seconds
    while time.time() < end:
        try:
            out.append(q.get(timeout=0.05))
        except queue.Empty:
            pass
    return out


def wait_for(q, kind, seconds=5):
    end = time.time() + seconds
    seen = []
    while time.time() < end:
        try:
            ev = q.get(timeout=0.05)
        except queue.Empty:
            continue
        seen.append(ev)
        if ev[0] == kind:
            return ev, seen
    raise AssertionError("Ereignis %r kam nicht. Gesehen: %r" % (kind, seen))


def find_peer(q, name, seconds=3):
    end = time.time() + seconds
    while time.time() < end:
        ev, _ = wait_for(q, "peer", seconds)
        if ev[1]["name"] == name:
            return ev[1]
    raise AssertionError("Peer %s nicht gefunden" % name)


class ProtocolTest(unittest.TestCase):
    def test_kaputte_nachrichten_werden_ignoriert(self):
        for data in [b"", b"kein json", b"[1,2]", b'{"type":"help"}',
                     b'{"type":"heartbeat","id":"a","from":"b","name":"x","role":"chef","status":"online","port":1}',
                     b"x" * 5000, b"\xff\xfe"]:
            self.assertIsNone(P.decode(data), data[:40])

    def test_gueltige_nachricht(self):
        me = {"peer_id": P.new_id(), "name": "Lena", "role": "student", "status": "online", "port": 1234}
        self.assertEqual(P.decode(P.encode(P.make_heartbeat(me)))["name"], "Lena")

    def test_ids_sind_eindeutig(self):
        self.assertEqual(len({P.new_id() for _ in range(10000)}), 10000)


class NetworkTest(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for n, _ in self.nodes:
            n.stop()
        time.sleep(0.2)

    def make(self, *a, **kw):
        n = node(*a, **kw)
        self.nodes.append(n)
        return n

    def test_alle_finden_sich(self):
        (a, qa), (b, qb), (c, qc) = self.make("Lena", "student"), self.make("Tim", "student"), self.make("Coach", "coach")
        names = {e[1]["name"] for e in collect(qa, 1) if e[0] == "peer"}
        self.assertEqual(names, {"Tim", "Coach"})

    def test_neue_app_sieht_andere_sofort(self):
        (a, qa) = self.make("Lena", "student")
        time.sleep(0.5)  # Lena läuft schon, ihr nächster heartbeat kommt erst in ~4.5 s
        (b, qb) = self.make("Tim", "student")
        t0 = time.time()
        find_peer(qb, "Lena", seconds=2)
        self.assertLess(time.time() - t0, 1.0)

    def test_status_wechsel_kommt_sofort(self):
        (a, qa), (b, qb) = self.make("Lena", "student"), self.make("Tim", "student")
        find_peer(qa, "Tim")
        b.set_status("busy")
        statuses = [e[1]["status"] for e in collect(qa, 1) if e[0] == "peer"]
        self.assertIn("busy", statuses)

    def test_hilfe_mit_bestaetigung(self):
        (s, qs), (c, qc) = self.make("Lena", "student"), self.make("Coach", "coach")
        coach = find_peer(qs, "Coach")
        help_id = s.send_help(coach["ip"], coach["port"], "Aufgabe 3?")
        ev, _ = wait_for(qc, "help")
        self.assertEqual((ev[1]["name"], ev[1]["text"]), ("Lena", "Aufgabe 3?"))
        ev, _ = wait_for(qs, "acked")
        self.assertEqual(ev[1], help_id)

    def test_wiederholung_wenn_paket_verloren(self):
        # Der Coach "verliert" die ersten 2 Anfragen -> 3. Versuch kommt an
        (s, qs), (c, qc) = self.make("Lena", "student"), self.make("Coach", "coach", drop={"help": 2})
        coach = find_peer(qs, "Coach")
        help_id = s.send_help(coach["ip"], coach["port"], "")
        ev, seen = wait_for(qs, "acked", 5)
        tries = [e[2] for e in seen if e[0] == "sending" and e[1] == help_id]
        self.assertEqual(max(tries), 3)
        helps = [e for e in collect(qc, 0.5) if e[0] == "help"]
        self.assertEqual(len(helps), 1)

    def test_duplikat_wird_erkannt_und_trotzdem_bestaetigt(self):
        # Die Schülerin "verliert" die ersten 2 ACKs -> sie schickt die Anfrage
        # 3x. Der Coach erkennt die Duplikate: Er zeigt die Anfrage nur EINMAL
        # an, schickt aber jedes Mal ein ACK – sonst würde Lena nie fertig.
        (s, qs), (c, qc) = self.make("Lena", "student", drop={"ack": 2}), self.make("Coach", "coach")
        coach = find_peer(qs, "Coach")
        help_id = s.send_help(coach["ip"], coach["port"], "Hilfe")
        ev, seen = wait_for(qs, "acked", 5)
        self.assertEqual(max(e[2] for e in seen if e[0] == "sending" and e[1] == help_id), 3)
        helps = [e for e in collect(qc, 0.5) if e[0] == "help"]
        self.assertEqual(len(helps), 1)

    def test_aufgeben_nach_5_versuchen(self):
        (s, qs) = self.make("Lena", "student")
        help_id = s.send_help("127.0.0.1", 9, "niemand da")  # Port 9: hört keiner
        ev, seen = wait_for(qs, "failed", 5)
        self.assertEqual(ev[1], help_id)
        self.assertEqual(max(e[2] for e in seen if e[0] == "sending"), P.MAX_TRIES)

    def test_erledigt_meldung(self):
        (s, qs), (c, qc) = self.make("Lena", "student"), self.make("Coach", "coach")
        coach = find_peer(qs, "Coach")
        help_id = s.send_help(coach["ip"], coach["port"], "")
        ev, _ = wait_for(qc, "help")
        c.send_done(ev[1]["ip"], ev[1]["port"], help_id)
        ev, _ = wait_for(qs, "done")
        self.assertEqual(ev[1], help_id)

    def test_bye_beim_beenden(self):
        (a, qa) = self.make("Lena", "student")
        b, qb = node("Tim", "student")
        tim = find_peer(qa, "Tim")
        b.stop()
        ev, _ = wait_for(qa, "bye")
        self.assertEqual(ev[1], tim["peer_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
