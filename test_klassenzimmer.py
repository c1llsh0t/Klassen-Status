"""
Automatische Tests für klassenzimmer.py

Starten:  python3 -m unittest -v test_klassenzimmer

Die Tests starten mehrere "Teilnehmer" im selben Programm (ohne Fenster).
Damit sie schnell sind, warten wir nur 0.3 s auf ACKs statt 3 s.
"""

import os
import plistlib
import queue
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import klassenzimmer as K

K.ACK_TIMEOUT = 0.3


# ---------------------------------------------------------------------------
# Hilfsmittel
# ---------------------------------------------------------------------------
class DropNetwork(K.Network):
    """Wie Network, verwirft aber absichtlich die ersten N Pakete eines Typs."""

    def __init__(self, *a, drop=None, **kw):
        super().__init__(*a, **kw)
        self.drop = dict(drop or {})

    def _handle(self, data, addr):
        msg = K.decode(data)
        if msg and self.drop.get(msg["type"], 0) > 0:
            self.drop[msg["type"]] -= 1
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
                "status": "online", "klasse": "INF3a", "port": 1234}

    def test_gueltige_nachrichten(self):
        me = self.me()
        for msg in (K.make_heartbeat(me), K.make_bye(me), K.make_help(me, "Hallo"),
                    K.make_help(me, ""), K.make_done(me, K.new_id()), K.make_ack(me, K.new_id())):
            self.assertEqual(K.decode(K.encode(msg)), msg)

    def test_kaputte_nachrichten_werden_ignoriert(self):
        hb = K.make_heartbeat(self.me())
        bad = [b"", b"kein json", b"[1,2]", b"null", b'{"type":"help"}', b"x" * 5000, b"\xff\xfe"]
        for change in ({"role": "chef"}, {"status": "weg"}, {"port": "80"}, {"port": True},
                       {"port": 0}, {"name": ""}, {"name": "x" * 31}, {"class": ""},
                       {"id": ""}, {"from": 5}, {"type": "hack"}):
            bad.append(K.encode({**hb, **change}))
        for data in bad:
            self.assertIsNone(K.decode(data), data[:60])

    def test_ids_sind_eindeutig(self):
        self.assertEqual(len({K.new_id() for _ in range(10000)}), 10000)

    def test_klassenname_vergleich(self):
        self.assertEqual(K.class_key("  INF  3a "), K.class_key("inf 3A"))


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

    def make(self, name, role, klasse="INF3a", **kw):
        me = {"peer_id": K.new_id(), "name": name, "role": role, "status": "online", "klasse": klasse}
        q = queue.Queue()
        n = DropNetwork(me, q, **kw)
        n.start()
        self.nodes.append((n, q))
        return n, q

    def test_alle_finden_sich(self):
        (a, qa), _, _ = self.make("Lena", "student"), self.make("Tim", "student"), self.make("Coach", "coach")
        names = {e[1]["name"] for e in collect(qa, 1) if e[0] == "peer"}
        self.assertEqual(names, {"Tim", "Coach"})

    def test_andere_klasse_ist_unsichtbar(self):
        (a, qa), _ = self.make("Lena", "student", "INF3a"), self.make("Fremd", "student", "INF3b")
        _, _ = self.make("Tim", "student", "inf3A")   # gleiche Klasse, andere Schreibweise
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

    def test_bye_beim_beenden(self):
        a, qa = self.make("Lena", "student")
        me = {"peer_id": K.new_id(), "name": "Tim", "role": "student", "status": "online", "klasse": "INF3a"}
        b = K.Network(me, queue.Queue())
        b.start()
        find_peer(qa, "Tim")
        b.stop()
        ev, _ = wait_for(qa, "bye")
        self.assertEqual(ev[1], me["peer_id"])


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
        s.set_profile("Lena", "student", "INF3a")
        pid = s.get("peer_id")
        s.remember("INF3a", "a" * 32, "Tim", "student")
        s.remember("INF3b", "b" * 32, "Fremd", "student")
        # "Nächster Morgen": neu laden
        s2 = K.Store()
        self.assertEqual(s2.get("peer_id"), pid)            # feste ID
        self.assertEqual(s2.get("klasse"), "INF3a")
        self.assertEqual(list(s2.known("inf3a").values()), [{"name": "Tim", "role": "student"}])
        s2.forget("INF3a", "a" * 32)
        self.assertEqual(K.Store().known("INF3a"), {})

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
