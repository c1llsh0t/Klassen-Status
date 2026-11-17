#!/usr/bin/env python3
"""
Klassenzimmer – eine Peer-to-Peer-App fürs Klassenzimmer
=========================================================

Alle Rechner im selben WLAN/LAN sehen sich gegenseitig. Es gibt KEINEN
Server: Jede laufende App ist gleichwertig und redet direkt mit den anderen.

Funktionen
  - Teilnehmerliste mit farbigem Punkt: grün = online, gelb = nicht stören,
    grau = offline (20 Sekunden nichts gehört)
  - eigenen Status per Klick zwischen grün und gelb wechseln
  - Schüler: "Coach um Hilfe fragen" (mit optionalem Text) + Bestätigung
  - Coach: Warteschlange der Hilfeanfragen (älteste zuerst), "Erledigt"
  - Klasse wird gespeichert: Am nächsten Tag stehen alle schon (grau) in der Liste
  - nur die eigene Klasse ist sichtbar (mehrere Klassen im selben WLAN möglich)
  - Autostart beim Anmelden

Starten
    python3 klassenzimmer.py                         (Startfenster)
    python3 klassenzimmer.py --name Lena --role student --klasse INF3a
    python3 klassenzimmer.py --name "Herr Keller" --role coach --klasse INF3a

Nur Python-Standardbibliothek: socket, threading, json, tkinter, …

Aufbau dieser Datei (in dieser Reihenfolge lesen!):
  TEIL 1  Einstellungen und Protokoll   – wie sehen Nachrichten aus?
  TEIL 2  Speicher                      – Name, Klasse, bekannte Teilnehmer
  TEIL 3  Autostart                     – beim Anmelden starten
  TEIL 4  Netzwerk                      – Broadcast, Heartbeat, ACK, Wiederholung
  TEIL 5  Oberfläche                    – tkinter
  TEIL 6  Start                         – Kommandozeile, Startfenster, main()
"""

import argparse
import json
import os
import platform
import plistlib
import queue
import random
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    if __name__ == "__main__":
        print("tkinter fehlt. Installieren mit:\n"
              "  Ubuntu/Debian:  sudo apt install python3-tk\n"
              "  Arch/Omarchy:   sudo pacman -S tk\n"
              "  Fedora:         sudo dnf install python3-tkinter")
        sys.exit(1)
    raise

APP_VERSION = "1.1"


# ===========================================================================
# TEIL 1: Einstellungen und Protokoll
# ===========================================================================
# Jede Nachricht ist ein JSON-Objekt mit mindestens:
#   type – Art der Nachricht (heartbeat, bye, help, done, ack)
#   id   – eindeutige ID DIESER Nachricht -> Duplikate erkennen
#   from – ID der App, die sie geschickt hat
# Details und Beispiele: siehe PROTOKOLL.md

DISCOVERY_PORT = 50505        # hier hören alle auf Broadcasts (UDP)
HEARTBEAT_INTERVAL = 5.0      # alle 5 s "Ich bin da"
OFFLINE_AFTER = 20.0          # 20 s nichts gehört -> grau (= 4 verpasste Heartbeats)
ACK_TIMEOUT = 3.0             # 3 s auf Bestätigung warten, dann nochmal
MAX_TRIES = 5                 # höchstens 5 Versuche
MAX_PACKET = 4096             # grössere Pakete werden ignoriert

ROLES = ("student", "coach")
STATUSES = ("online", "busy")  # online = grün, busy = gelb ("nicht stören")
MAX_NAME = 30
MAX_CLASS = 20
MAX_TEXT = 300


def new_id():
    """Zufällige, eindeutige ID (uuid4 = 122 Zufallsbits)."""
    return uuid.uuid4().hex


def now():
    """Zeit in Sekunden für Timeouts. monotonic() springt nie zurück,
    auch nicht, wenn jemand die Uhr verstellt."""
    return time.monotonic()


def clean_text(text, max_len):
    """Leerzeichen aufräumen und Länge begrenzen."""
    return " ".join(str(text).split())[:max_len]


def class_key(klasse):
    """Klassenname zum Vergleichen: 'INF 3a' == 'inf 3A'."""
    return clean_text(klasse, MAX_CLASS).casefold()


def make_heartbeat(me):
    return {"type": "heartbeat", "id": new_id(), "from": me["peer_id"],
            "name": me["name"], "role": me["role"], "status": me["status"],
            "class": me["klasse"], "port": me["port"]}


def make_bye(me):
    return {"type": "bye", "id": new_id(), "from": me["peer_id"]}


def make_help(me, text):
    return {"type": "help", "id": new_id(), "from": me["peer_id"],
            "name": me["name"], "text": text[:MAX_TEXT]}


def make_done(me, help_id):
    return {"type": "done", "id": new_id(), "from": me["peer_id"], "help_id": help_id}


def make_ack(me, msg_id):
    return {"type": "ack", "id": new_id(), "from": me["peer_id"], "ack_id": msg_id}


def encode(msg):
    """dict -> Bytes fürs Netzwerk."""
    return json.dumps(msg, ensure_ascii=False).encode("utf-8")


def _is_id(v):
    return isinstance(v, str) and 1 <= len(v) <= 64


def _is_text(v, max_len, allow_empty=False):
    return isinstance(v, str) and (allow_empty or v.strip()) and len(v) <= max_len


def decode(data):
    """Bytes -> dict, oder None wenn die Nachricht kaputt/ungültig ist.

    Alles aus dem Netzwerk kann falsch oder absichtlich böse sein.
    Darum prüfen wir jedes Feld. Lieber wegwerfen als abstürzen.
    """
    if len(data) > MAX_PACKET:
        return None
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict) or not (_is_id(msg.get("id")) and _is_id(msg.get("from"))):
        return None

    t = msg.get("type")
    if t == "heartbeat":
        port = msg.get("port")
        ok = (_is_text(msg.get("name"), MAX_NAME)
              and _is_text(msg.get("class"), MAX_CLASS)
              and msg.get("role") in ROLES
              and msg.get("status") in STATUSES
              and isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535)
    elif t == "bye":
        ok = True
    elif t == "help":
        ok = _is_text(msg.get("name"), MAX_NAME) and _is_text(msg.get("text"), MAX_TEXT, allow_empty=True)
    elif t == "done":
        ok = _is_id(msg.get("help_id"))
    elif t == "ack":
        ok = _is_id(msg.get("ack_id"))
    else:
        ok = False
    return msg if ok else None


# ===========================================================================
# TEIL 2: Speicher – damit man nicht jeden Morgen alles neu machen muss
# ===========================================================================
# Gespeichert wird in einer JSON-Datei:
#   Windows: %APPDATA%\klassenzimmer\einstellungen.json
#   macOS:   ~/Library/Application Support/klassenzimmer/einstellungen.json
#   Linux:   ~/.config/klassenzimmer/einstellungen.json
#
# Inhalt:
#   name, role, klasse – vom Startfenster
#   peer_id            – meine feste ID (bleibt gleich, auch nach Neustart)
#   klassen            – pro Klasse alle Teilnehmer, die man schon gesehen hat

SYSTEM = platform.system()   # "Windows", "Darwin" (= macOS) oder "Linux"
APP_ID = "klassenzimmer"


def config_dir():
    if SYSTEM == "Windows":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif SYSTEM == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_ID


class Store:
    """Liest und schreibt die Einstellungsdatei."""

    def __init__(self, path=None):
        self.path = Path(path) if path else config_dir() / "einstellungen.json"
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.data = {}   # noch keine Datei oder kaputt -> leer anfangen
        if not isinstance(self.data.get("klassen"), dict):
            self.data["klassen"] = {}

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)  # erst fertig schreiben, dann ersetzen
        except OSError as e:
            print("Einstellungen konnten nicht gespeichert werden:", e)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set_profile(self, name, role, klasse):
        self.data.update(name=name, role=role, klasse=klasse)
        if not _is_id(self.data.get("peer_id")):
            self.data["peer_id"] = new_id()
        self.save()

    def known(self, klasse):
        """{peer_id: {"name", "role"}} aller bekannten Teilnehmer der Klasse."""
        k = self.data["klassen"].get(class_key(klasse), {})
        return {pid: p for pid, p in k.items()
                if _is_id(pid) and isinstance(p, dict) and p.get("role") in ROLES
                and _is_text(p.get("name"), MAX_NAME)}

    def remember(self, klasse, peer_id, name, role):
        k = self.data["klassen"].setdefault(class_key(klasse), {})
        if k.get(peer_id) != {"name": name, "role": role}:
            k[peer_id] = {"name": name, "role": role}
            self.save()

    def forget(self, klasse, peer_id):
        k = self.data["klassen"].get(class_key(klasse), {})
        if k.pop(peer_id, None) is not None:
            self.save()


# ===========================================================================
# TEIL 3: Autostart beim Anmelden
# ===========================================================================
#   Windows: Registry-Eintrag unter HKCU\...\CurrentVersion\Run
#   macOS:   .plist-Datei in ~/Library/LaunchAgents
#   Linux:   .desktop-Datei in ~/.config/autostart

MAC_LABEL = "ch.klassenzimmer.app"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def start_command():
    """Befehl, der die App mit --autostart startet.
    Fertiges Programm (PyInstaller): sys.frozen ist gesetzt."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        if SYSTEM == "Darwin" and ".app/Contents/MacOS/" in exe:
            app = exe.split(".app/Contents/MacOS/")[0] + ".app"
            return ["/usr/bin/open", "-a", app, "--args", "--autostart"]
        return [exe, "--autostart"]
    python = sys.executable
    if SYSTEM == "Windows" and python.lower().endswith("python.exe"):
        w = python[:-len("python.exe")] + "pythonw.exe"   # ohne schwarzes Fenster
        if os.path.exists(w):
            python = w
    return [python, str(Path(__file__).resolve()), "--autostart"]


def _mac_file():
    return Path.home() / "Library" / "LaunchAgents" / (MAC_LABEL + ".plist")


def _linux_file():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / (APP_ID + ".desktop")


def mac_plist(cmd):
    return plistlib.dumps({"Label": MAC_LABEL, "ProgramArguments": cmd, "RunAtLoad": True})


def linux_desktop(cmd):
    def q(a):
        return '"%s"' % a.replace('"', '\\"') if (" " in a or '"' in a) else a
    return ("[Desktop Entry]\nType=Application\nName=Klassenzimmer\n"
            "Comment=Peer-to-Peer-App fürs Klassenzimmer\n"
            "Exec=%s\nX-GNOME-Autostart-enabled=true\n" % " ".join(q(a) for a in cmd))


def autostart_enabled():
    try:
        if SYSTEM == "Windows":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_ID)
            return True
        return (_mac_file() if SYSTEM == "Darwin" else _linux_file()).exists()
    except OSError:
        return False


def set_autostart(enabled):
    """Autostart ein/aus. Gibt eine Fehlermeldung oder None zurück."""
    try:
        if SYSTEM == "Windows":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    cmd = " ".join('"%s"' % a if " " in a else a for a in start_command())
                    winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, APP_ID)
                    except FileNotFoundError:
                        pass
            return None
        path = _mac_file() if SYSTEM == "Darwin" else _linux_file()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            if SYSTEM == "Darwin":
                path.write_bytes(mac_plist(start_command()))
            else:
                path.write_text(linux_desktop(start_command()), encoding="utf-8")
        elif path.exists():
            path.unlink()
        return None
    except OSError as e:
        return "Autostart konnte nicht geändert werden: %s" % e


# ===========================================================================
# TEIL 4: Netzwerk
# ===========================================================================
# Die Oberfläche weiss nichts von Sockets. Das Netzwerk legt "Ereignisse"
# in eine queue.Queue, und die Oberfläche holt sie im Hauptthread ab:
#
#     Netzwerk-Threads --(events.put)--> Queue --(events.get)--> Oberfläche
#
# Zwei UDP-Sockets:
#   bsock – Port 50505, empfängt Broadcasts (heartbeat, bye) von allen
#   usock – eigener Port, empfängt direkte Nachrichten (help, done, ack)
#           und verschickt alles. Den Port verraten wir im heartbeat.
#
# Ereignisse an die Oberfläche:
#   ("peer", info)      jemand hat sich gemeldet
#   ("bye", peer_id)    jemand hat die App beendet
#   ("help", info)      Hilfeanfrage angekommen (Coach)
#   ("done", help_id)   meine Anfrage wurde erledigt (Schüler)
#   ("sending", id, n)  Nachricht wird gesendet, Versuch n
#   ("acked", id, von)  Nachricht wurde bestätigt
#   ("failed", id)      nach 5 Versuchen keine Bestätigung
#   ("log", text)       Info für die Konsole

class Network:
    def __init__(self, me, events, broadcast_addr="255.255.255.255", loss=0.0, port=0):
        self.me = me                      # dict: peer_id, name, role, status, klasse
        self.events = events
        self.broadcast_addr = broadcast_addr
        self.loss = loss                  # zum Üben: Anteil verlorener Pakete
        self.unicast_port = port          # 0 = Betriebssystem wählt
        self.lock = threading.Lock()      # schützt me, pending, seen, known
        self.running = False
        self.pending = {}                 # msg_id -> {msg, addr, tries, next}
        self.seen = {}                    # msg_id -> Zeit (Duplikate)
        self.known = set()                # (peer_id, port) schon gesehen
        self.next_heartbeat = 0.0

    # ---- Starten / Stoppen ------------------------------------------------
    def start(self):
        self.bsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.bsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):          # nicht unter Windows
            try:
                self.bsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        self.bsock.bind(("", DISCOVERY_PORT))
        self.bsock.settimeout(0.5)       # damit die Threads "running" prüfen können

        self.usock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.usock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.usock.bind(("", self.unicast_port))
        except OSError:
            self.bsock.close()
            self.usock.close()
            raise
        self.usock.settimeout(0.5)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            # Nur Windows: Sonst bricht recvfrom mit "Verbindung zurückgesetzt" ab,
            # wenn wir vorher an jemanden gesendet haben, der nicht mehr da ist.
            try:
                self.usock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except (OSError, ValueError):
                pass
        self.me["port"] = self.usock.getsockname()[1]

        self.running = True
        for target, args in ((self._receive_loop, (self.bsock,)),
                             (self._receive_loop, (self.usock,)),
                             (self._timer_loop, ())):
            threading.Thread(target=target, args=args, daemon=True).start()

    def stop(self):
        if not self.running:
            return
        bye = make_bye(self.me)
        for _ in range(2):               # UDP kann verloren gehen -> 2x
            self._broadcast(bye)
        self.running = False
        self.bsock.close()
        self.usock.close()

    # ---- Für die Oberfläche ----------------------------------------------
    def set_status(self, status):
        with self.lock:
            self.me["status"] = status
            self.next_heartbeat = 0.0    # sofort melden

    def send_help(self, ip, port, text):
        msg = make_help(self.me, text)
        self._send_reliable(msg, (ip, port))
        return msg["id"]

    def send_done(self, ip, port, help_id):
        self._send_reliable(make_done(self.me, help_id), (ip, port))

    # ---- Zuverlässig senden: ACK + Wiederholung ---------------------------
    # 1. senden und in pending merken
    # 2. ACK kommt -> aus pending löschen -> "acked"
    # 3. 3 s kein ACK -> nochmal (höchstens 5 Versuche)
    # 4. nach 5 Versuchen -> "failed"
    def _send_reliable(self, msg, addr):
        with self.lock:
            self.pending[msg["id"]] = {"msg": msg, "addr": addr, "tries": 1,
                                       "next": now() + ACK_TIMEOUT}
        self._send(msg, addr)
        self.events.put(("sending", msg["id"], 1))

    def _check_retries(self):
        t = now()
        resend, failed = [], []
        with self.lock:
            for msg_id, p in list(self.pending.items()):
                if t < p["next"]:
                    continue
                if p["tries"] >= MAX_TRIES:
                    del self.pending[msg_id]
                    failed.append(msg_id)
                else:
                    p["tries"] += 1
                    p["next"] = t + ACK_TIMEOUT
                    resend.append((p["msg"], p["addr"], p["tries"]))
        for msg, addr, tries in resend:          # senden ausserhalb des Locks
            self._send(msg, addr)
            self.events.put(("sending", msg["id"], tries))
        for msg_id in failed:
            self.events.put(("failed", msg_id))

    # ---- Threads ------------------------------------------------------------
    def _timer_loop(self):
        """Heartbeats, Wiederholungen und Aufräumen."""
        while self.running:
            hb = None
            with self.lock:
                if now() >= self.next_heartbeat:
                    self.next_heartbeat = now() + HEARTBEAT_INTERVAL
                    hb = make_heartbeat(self.me)
            if hb:
                self._broadcast(hb)
            self._check_retries()
            self._forget_old_ids()
            time.sleep(0.2)

    def _receive_loop(self, sock):
        while self.running:
            try:
                data, addr = sock.recvfrom(MAX_PACKET + 1)
            except socket.timeout:
                continue
            except OSError:
                if not self.running:
                    break          # Socket wurde beim Beenden geschlossen
                time.sleep(0.2)    # z.B. Windows meldet "Port nicht erreichbar"
                continue
            try:
                self._handle(data, addr)
            except Exception as e:   # ein Paket darf nie alles stoppen
                self.events.put(("log", "Fehler bei Paket von %s: %s" % (addr[0], e)))

    # ---- Empfangen ------------------------------------------------------------
    def _handle(self, data, addr):
        if self.loss and random.random() < self.loss:
            return                                   # Paketverlust simulieren
        msg = decode(data)
        if msg is None or msg["from"] == self.me["peer_id"]:
            return                                   # kaputt oder von mir selbst
        t, ip = msg["type"], addr[0]

        if t == "heartbeat" and class_key(msg["class"]) != class_key(self.me["klasse"]):
            return                                   # andere Klasse -> ignorieren

        # Duplikate: schon gesehen? Bei help/done trotzdem ACK senden,
        # weil wahrscheinlich unser erstes ACK verloren ging.
        with self.lock:
            duplicate = msg["id"] in self.seen
            self.seen[msg["id"]] = now()
        if duplicate:
            if t in ("help", "done"):
                self._send(make_ack(self.me, msg["id"]), addr)
            return

        if t == "heartbeat":
            # Neu (oder neu gestartet = neuer Port)? Sofort direkt antworten,
            # damit er uns nicht erst in bis zu 5 s sieht.
            key = (msg["from"], msg["port"])
            with self.lock:
                is_new = key not in self.known
                self.known.add(key)
                hb = make_heartbeat(self.me) if is_new else None
            if hb:
                self._send(hb, (ip, msg["port"]))
            self.events.put(("peer", {
                "peer_id": msg["from"], "name": clean_text(msg["name"], MAX_NAME),
                "role": msg["role"], "status": msg["status"], "ip": ip, "port": msg["port"]}))
        elif t == "bye":
            with self.lock:
                self.known = {k for k in self.known if k[0] != msg["from"]}
            self.events.put(("bye", msg["from"]))
        elif t == "help":
            self._send(make_ack(self.me, msg["id"]), addr)
            self.events.put(("help", {
                "help_id": msg["id"], "peer_id": msg["from"],
                "name": clean_text(msg["name"], MAX_NAME), "text": clean_text(msg["text"], MAX_TEXT),
                "ip": ip, "port": addr[1]}))
        elif t == "done":
            self._send(make_ack(self.me, msg["id"]), addr)
            self.events.put(("done", msg["help_id"]))
        elif t == "ack":
            with self.lock:
                found = self.pending.pop(msg["ack_id"], None)
            if found:
                self.events.put(("acked", msg["ack_id"], msg["from"]))

    # ---- Hilfsfunktionen ------------------------------------------------------
    def _send(self, msg, addr):
        try:
            self.usock.sendto(encode(msg), addr)
        except OSError as e:
            if self.running:
                self.events.put(("log", "Senden an %s fehlgeschlagen: %s" % (addr[0], e)))

    def _broadcast(self, msg):
        self._send(msg, (self.broadcast_addr, DISCOVERY_PORT))

    def _forget_old_ids(self):
        limit = now() - 120          # nach 2 Minuten vergessen
        with self.lock:
            for msg_id, t in list(self.seen.items()):
                if t < limit:
                    del self.seen[msg_id]


# ===========================================================================
# TEIL 5: Oberfläche (tkinter)
# ===========================================================================
# Goldene Regel: Nur der Hauptthread darf tkinter-Widgets anfassen.
# _poll() holt alle 100 ms die Ereignisse aus der Queue,
# _tick() zeichnet jede Sekunde neu (damit "offline" erscheint).

COLORS = {"online": "#2e9e44", "busy": "#e0b000", "offline": "#9a9a9a"}
STATUS_TEXT = {"online": "Online", "busy": "Nicht stören", "offline": "Offline"}
ROLE_TEXT = {"student": "Schüler/in", "coach": "Coach"}
BG = "white"


class ColorButton(tk.Label):
    """Ein farbiger Knopf, der auf allen Systemen gleich aussieht.
    (Echte tk.Button-Farben werden auf dem Mac ignoriert – weisse Schrift
    auf weissem Knopf wäre dort unlesbar. Darum ein Label, das Klicks annimmt.)"""

    def __init__(self, parent, text, command, bg, fg="white", hover=None, **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg, cursor="hand2",
                         padx=kw.pop("padx", 10), pady=kw.pop("pady", 5), **kw)
        self.command, self.normal_bg, self.hover_bg = command, bg, hover or bg
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self.configure(bg=self.hover_bg))
        self.bind("<Leave>", lambda e: self.configure(bg=self.normal_bg))

    def set_colors(self, bg, fg, hover=None):
        self.normal_bg, self.hover_bg = bg, hover or bg
        self.configure(bg=bg, fg=fg)


def dot(parent, color, size=14):
    c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bg=parent["bg"])
    c.create_oval(2, 2, size - 2, size - 2, fill=color, outline="")
    return c


class App:
    def __init__(self, root, me, net, events, store=None):
        self.root, self.me, self.net, self.events = root, me, net, events
        self.store = store             # None = nichts speichern (z.B. beim Testen)

        self.peers = {}                # peer_id -> {name, role, status, ip, port, last_seen}
        self.queue = []                # Coach: offene Anfragen, älteste zuerst
        self.requests = {}             # Schüler: help_id -> {coach, state, tries}

        # Gespeicherte Klasse laden: alle Bekannten erscheinen sofort (grau)
        if store:
            for pid, p in store.known(me["klasse"]).items():
                if pid != me["peer_id"]:
                    self.peers[pid] = {"peer_id": pid, "name": p["name"], "role": p["role"],
                                       "status": "online", "ip": None, "port": None, "last_seen": None}

        root.title("Klassenzimmer – %s" % me["name"])
        root.geometry("430x580")
        root.minsize(360, 440)
        root.configure(bg=BG)
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(100, self._poll)
        root.after(1000, self._tick)

    # ---- Aufbau -------------------------------------------------------------
    def _build(self):
        top = tk.Frame(self.root, bg=BG, padx=12, pady=10)
        top.pack(fill="x")
        info = tk.Frame(top, bg=BG)
        info.pack(side="left")
        tk.Label(info, text="%s (%s)" % (self.me["name"], ROLE_TEXT[self.me["role"]]),
                 font=("TkDefaultFont", 12, "bold"), bg=BG).pack(anchor="w")
        tk.Label(info, text="Klasse: " + self.me["klasse"], fg="#777", bg=BG).pack(anchor="w")
        self.status_btn = ColorButton(top, "", self.toggle_status, bg="#eee")
        self.status_btn.pack(side="right")
        self._update_status_button()

        ttk.Separator(self.root).pack(fill="x")
        tk.Label(self.root, text="Teilnehmer", bg=BG, anchor="w",
                 font=("TkDefaultFont", 10, "bold"), padx=12, pady=6).pack(fill="x")

        # Liste mit Scrollbalken (für grosse Klassen)
        holder = tk.Frame(self.root, bg=BG)
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.peer_frame = tk.Frame(self.canvas, bg=BG, padx=12)
        self.peer_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        win = self.canvas.create_window((0, 0), window=self.peer_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        ttk.Separator(self.root).pack(fill="x")
        bottom = tk.Frame(self.root, bg=BG, padx=12, pady=10)
        bottom.pack(fill="x")
        if self.me["role"] == "student":
            self._build_student(bottom)
        else:
            self._build_coach(bottom)
        self._render_peers()

    def _build_student(self, parent):
        tk.Label(parent, text="Frage (optional):", bg=BG, anchor="w").pack(fill="x")
        self.help_text = tk.Entry(parent)
        self.help_text.pack(fill="x", pady=(2, 6))
        self.help_text.bind("<Return>", lambda e: self.ask_for_help())
        ColorButton(parent, "Coach um Hilfe fragen", self.ask_for_help, bg="#ff9f1a",
                    hover="#e88a00", font=("TkDefaultFont", 11, "bold"), pady=7).pack(fill="x")
        self.request_frame = tk.Frame(parent, bg=BG, pady=6)
        self.request_frame.pack(fill="x")

    def _build_coach(self, parent):
        tk.Label(parent, text="Hilfeanfragen (älteste zuerst)", bg=BG, anchor="w",
                 font=("TkDefaultFont", 10, "bold")).pack(fill="x")
        self.queue_frame = tk.Frame(parent, bg=BG, pady=4)
        self.queue_frame.pack(fill="x")
        self._render_queue()

    # ---- Aktionen -------------------------------------------------------------
    def toggle_status(self):
        new = "busy" if self.me["status"] == "online" else "online"
        self.net.set_status(new)
        self._update_status_button()

    def ask_for_help(self):
        coaches = [p for p in self.peers.values()
                   if p["role"] == "coach" and self._shown_status(p) != "offline" and p["ip"]]
        if not coaches:
            self._show_request_info("Kein Coach online.")
            return
        text = self.help_text.get().strip()[:MAX_TEXT]
        self.requests.clear()          # nur die neueste Anfrage anzeigen
        for c in coaches:              # jedem Coach einzeln, jeder bestätigt selbst
            help_id = self.net.send_help(c["ip"], c["port"], text)
            self.requests[help_id] = {"coach": c["name"], "state": "sending", "tries": 1}
        self.help_text.delete(0, "end")
        self._render_requests()

    def mark_done(self, help_id):
        for item in self.queue:
            if item["help_id"] == help_id:
                self.queue.remove(item)
                self.net.send_done(item["ip"], item["port"], help_id)
                break
        self._render_queue()

    def remove_peer(self, peer_id):
        """Jemanden aus der gespeicherten Klassenliste entfernen."""
        p = self.peers.get(peer_id)
        if p and messagebox.askyesno("Entfernen", "%s aus der Klassenliste entfernen?" % p["name"],
                                     parent=self.root):
            del self.peers[peer_id]
            if self.store:
                self.store.forget(self.me["klasse"], peer_id)
            self._render_peers()

    def quit(self):
        self.net.stop()
        self.root.destroy()

    # ---- Ereignisse verarbeiten (Hauptthread!) -----------------------------
    def _poll(self):
        changed = set()
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "peer":
                    info = ev[1]
                    info["last_seen"] = time.monotonic()
                    self.peers[info["peer_id"]] = info
                    if self.store:
                        self.store.remember(self.me["klasse"], info["peer_id"], info["name"], info["role"])
                    changed.add("peers")
                elif kind == "bye":
                    if ev[1] in self.peers:
                        self.peers[ev[1]]["last_seen"] = None   # sofort offline
                        changed.add("peers")
                elif kind == "help":
                    self._add_to_queue(ev[1])
                    changed.add("queue")
                elif kind in ("sending", "acked", "failed"):
                    r = self.requests.get(ev[1])
                    if r and r["state"] not in ("acked", "done"):
                        r["state"] = kind
                        if kind == "sending":
                            r["tries"] = ev[2]
                        changed.add("requests")
                elif kind == "done":
                    r = self.requests.get(ev[1])
                    if r:
                        r["state"] = "done"
                        changed.add("requests")
                elif kind == "log":
                    print(ev[1])
        except queue.Empty:
            pass
        if "peers" in changed:
            self._render_peers()
        if "queue" in changed:
            self._render_queue()
        if "requests" in changed:
            self._render_requests()
        self.root.after(100, self._poll)

    def _add_to_queue(self, item):
        # Pro Schüler nur EINE offene Anfrage: Fragt jemand nochmal, wird die
        # bestehende aktualisiert (neuer Text), behält aber ihren Platz.
        for q in self.queue:
            if q["peer_id"] == item["peer_id"]:
                q.update(help_id=item["help_id"], text=item["text"] or q["text"],
                         ip=item["ip"], port=item["port"])
                return
        item["time"] = time.strftime("%H:%M")
        self.queue.append(item)       # hinten anhängen = älteste vorne
        self.root.bell()

    def _tick(self):
        self._render_peers()
        self.root.after(1000, self._tick)

    def _shown_status(self, peer):
        if peer["last_seen"] is None or time.monotonic() - peer["last_seen"] > OFFLINE_AFTER:
            return "offline"
        return peer["status"]

    # ---- Anzeige ----------------------------------------------------------------
    def _update_status_button(self):
        s = self.me["status"]
        self.status_btn.configure(text="● " + STATUS_TEXT[s])
        self.status_btn.set_colors("#eeeeee", COLORS[s], hover="#e0e0e0")

    def _render_peers(self):
        for w in self.peer_frame.winfo_children():
            w.destroy()
        if not self.peers:
            tk.Label(self.peer_frame, text="Noch niemand gefunden …", fg="#777", bg=BG).pack(anchor="w")
            return
        # Coaches zuerst, dann wer da ist, dann nach Name
        def order(p):
            return (p["role"] != "coach", self._shown_status(p) == "offline", p["name"].lower())
        for p in sorted(self.peers.values(), key=order):
            status = self._shown_status(p)
            row = tk.Frame(self.peer_frame, bg=BG)
            row.pack(fill="x", pady=2)
            dot(row, COLORS[status]).pack(side="left", padx=(0, 8))
            label = p["name"] + ("  (Coach)" if p["role"] == "coach" else "")
            tk.Label(row, text=label, bg=BG, fg="#999" if status == "offline" else "black").pack(side="left")
            if status == "offline":
                x = tk.Label(row, text="✕", bg=BG, fg="#bbb", cursor="hand2")
                x.bind("<Button-1>", lambda e, pid=p["peer_id"]: self.remove_peer(pid))
                x.pack(side="right", padx=(6, 0))
            tk.Label(row, text=STATUS_TEXT[status], bg=BG, fg="#777").pack(side="right")

    def _render_queue(self):
        for w in self.queue_frame.winfo_children():
            w.destroy()
        if not self.queue:
            tk.Label(self.queue_frame, text="Keine offenen Anfragen.", fg="#777", bg=BG).pack(anchor="w")
            return
        for i, item in enumerate(self.queue, start=1):
            row = tk.Frame(self.queue_frame, bg="#fff4e0", padx=6, pady=4)
            row.pack(fill="x", pady=2)
            text = "%d. %s  %s" % (i, item["time"], item["name"])
            if item["text"]:
                text += ": " + item["text"]
            tk.Label(row, text=text, bg=row["bg"], anchor="w", justify="left",
                     wraplength=280).pack(side="left", fill="x", expand=True)
            ColorButton(row, "Erledigt", lambda h=item["help_id"]: self.mark_done(h),
                        bg="#2e9e44", hover="#24803a").pack(side="right")

    def _show_request_info(self, text):
        for w in self.request_frame.winfo_children():
            w.destroy()
        tk.Label(self.request_frame, text=text, bg=BG, fg="#b00").pack(anchor="w")

    def _render_requests(self):
        for w in self.request_frame.winfo_children():
            w.destroy()
        texts = {
            "sending": ("#777", "wird gesendet … (Versuch {tries}/%d)" % MAX_TRIES),
            "acked": ("#2e9e44", "✓ angekommen"),
            "failed": ("#b00", "✗ nicht angekommen – bitte nochmal versuchen"),
            "done": ("#2e9e44", "✓ erledigt"),
        }
        for r in self.requests.values():
            color, t = texts[r["state"]]
            tk.Label(self.request_frame, text="%s: %s" % (r["coach"], t.format(tries=r["tries"])),
                     bg=BG, fg=color, anchor="w").pack(fill="x")


# ===========================================================================
# TEIL 6: Start
# ===========================================================================

def ask_profile(name, role, klasse):
    """Startfenster: Name, Rolle, Klasse, Autostart.
    Gibt (name, role, klasse, autostart) oder None zurück."""
    result = {}
    win = tk.Tk()
    win.title("Klassenzimmer – Start")
    win.resizable(False, False)
    f = tk.Frame(win, padx=20, pady=16)
    f.pack()

    tk.Label(f, text="Dein Name:").grid(row=0, column=0, columnspan=2, sticky="w")
    name_var = tk.StringVar(value=name or "")
    e = tk.Entry(f, textvariable=name_var, width=26)
    e.grid(row=1, column=0, columnspan=2, pady=(2, 8), sticky="we")
    e.focus()

    tk.Label(f, text="Klasse (z.B. INF3a):").grid(row=2, column=0, columnspan=2, sticky="w")
    class_var = tk.StringVar(value=klasse or "")
    tk.Entry(f, textvariable=class_var, width=26).grid(row=3, column=0, columnspan=2,
                                                       pady=(2, 8), sticky="we")

    tk.Label(f, text="Rolle:").grid(row=4, column=0, sticky="w")
    role_var = tk.StringVar(value=role or "student")
    tk.Radiobutton(f, text="Schüler/in", variable=role_var, value="student").grid(row=5, column=0, sticky="w")
    tk.Radiobutton(f, text="Coach", variable=role_var, value="coach").grid(row=5, column=1, sticky="w")

    auto_var = tk.BooleanVar(value=autostart_enabled())
    tk.Checkbutton(f, text="Beim Anmelden automatisch starten",
                   variable=auto_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))
    error = tk.Label(f, text="", fg="#b00")
    error.grid(row=7, column=0, columnspan=2, sticky="w")

    def ok(_event=None):
        n, k = clean_text(name_var.get(), MAX_NAME), clean_text(class_var.get(), MAX_CLASS)
        if not n or not k:
            error.configure(text="Bitte Name und Klasse eingeben.")
            return
        result.update(name=n, role=role_var.get(), klasse=k, auto=auto_var.get())
        win.destroy()

    tk.Button(f, text="Los geht's", command=ok).grid(row=8, column=0, columnspan=2,
                                                      pady=(6, 0), sticky="we")
    win.bind("<Return>", ok)
    win.mainloop()
    if not result:
        return None
    return result["name"], result["role"], result["klasse"], result["auto"]


def single_instance_lock():
    """Verhindert, dass die App zweimal läuft (z.B. Autostart + von Hand).
    Trick: Nur ein Programm kann denselben TCP-Port belegen."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", DISCOVERY_PORT))
        s.listen(1)
        return s                 # offen lassen, solange die App läuft
    except OSError:
        s.close()
        return None


def main():
    parser = argparse.ArgumentParser(description="Peer-to-Peer-App fürs Klassenzimmer")
    parser.add_argument("--name", help="dein Name")
    parser.add_argument("--role", choices=ROLES, help="student oder coach")
    parser.add_argument("--klasse", help="Name der Klasse, z.B. INF3a")
    parser.add_argument("--autostart", action="store_true",
                        help="gespeicherte Einstellungen benutzen, nicht nachfragen")
    parser.add_argument("--port", type=int, default=0,
                        help="fester Port für direkte Nachrichten (z.B. 50506)")
    parser.add_argument("--broadcast", default="255.255.255.255",
                        help="Broadcast-Adresse, z.B. 192.168.1.255")
    parser.add_argument("--verlust", type=float, default=0.0,
                        help="zum Üben: Anteil verlorener Pakete, z.B. 0.3")
    parser.add_argument("--version", action="version", version="Klassenzimmer " + APP_VERSION)
    args = parser.parse_args()

    # Testmodus: Name+Rolle auf der Kommandozeile -> nichts speichern,
    # mehrere Instanzen auf einem PC erlaubt.
    test_mode = bool(args.name and args.role)

    if test_mode:
        store = None
        me = {"peer_id": new_id(), "name": clean_text(args.name, MAX_NAME),
              "role": args.role, "klasse": clean_text(args.klasse or "Standard", MAX_CLASS)}
        if not me["name"]:
            parser.error("--name darf nicht leer sein")
    else:
        lock = single_instance_lock()
        if lock is None:
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo("Klassenzimmer", "Die App läuft schon.")
            return
        store = Store()
        name = clean_text(store.get("name", ""), MAX_NAME)
        role = store.get("role") if store.get("role") in ROLES else None
        klasse = clean_text(store.get("klasse", ""), MAX_CLASS)
        if not (args.autostart and name and role and klasse):
            answer = ask_profile(name, role, klasse)
            if answer is None:
                return                        # Startfenster geschlossen
            name, role, klasse, auto = answer
            store.set_profile(name, role, klasse)
            problem = set_autostart(auto)
            if problem:
                print(problem)
        if not _is_id(store.get("peer_id")):        # z.B. Datei von Hand geändert
            store.set_profile(name, role, klasse)
        me = {"peer_id": store.get("peer_id"), "name": name, "role": role, "klasse": klasse}
        main.lock = lock                      # Referenz behalten

    me["status"] = "online"
    events = queue.Queue()
    net = Network(me, events, broadcast_addr=args.broadcast, loss=args.verlust, port=args.port)
    try:
        net.start()
    except OSError as e:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("Klassenzimmer", "Netzwerk konnte nicht gestartet werden:\n%s" % e)
        return

    root = tk.Tk()
    App(root, me, net, events, store)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        net.stop()


if __name__ == "__main__":
    main()
