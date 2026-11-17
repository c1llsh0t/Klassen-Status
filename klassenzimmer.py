#!/usr/bin/env python3
"""
Klassenzimmer – eine Peer-to-Peer-App fürs Klassenzimmer
=========================================================

Alle Rechner im selben WLAN/LAN sehen sich gegenseitig. Es gibt KEINEN
Server: Jede laufende App ist gleichwertig und redet direkt mit den anderen.

Funktionen
  - Beitrittscode: Der Coach erzeugt einen Code, die Schüler geben ihn ein.
    Nur wer den Code kennt, ist in der Klasse (Nachrichten sind signiert).
  - Teilnehmerliste mit farbigem Punkt: grün = online, gelb = nicht stören,
    grau = offline (20 Sekunden nichts gehört)
  - eigenen Status per Klick zwischen grün und gelb wechseln
  - Schüler: "Coach um Hilfe fragen" (mit optionalem Text) + Bestätigung
  - Coach: Warteschlange der Hilfeanfragen (älteste zuerst), "Erledigt"
  - Klasse wird gespeichert: Am nächsten Tag stehen alle schon (grau) in der Liste
  - klein statt gross: Windows/Mac/Linux eine kleine Leiste, Omarchy/Hyprland
    ein Punkt oben in der Waybar
  - Autostart beim Anmelden

Starten
    python3 klassenzimmer.py                                        (Startfenster)
    python3 klassenzimmer.py --name Lena --role student --code K7QM3X   (Testmodus)

Nur Python-Standardbibliothek: socket, threading, json, hmac, tkinter, …

Aufbau dieser Datei (in dieser Reihenfolge lesen!):
  TEIL 1  Protokoll und Beitrittscode  – wie sehen Nachrichten aus?
  TEIL 2  Speicher                     – Name, Code, bekannte Teilnehmer
  TEIL 3  Autostart                    – beim Anmelden starten
  TEIL 4  Steuerung und Waybar         – "nur einmal starten", Waybar-Modul
  TEIL 5  Netzwerk                     – Broadcast, Heartbeat, ACK, Wiederholung
  TEIL 6  Oberfläche                   – grosses Fenster und kleine Leiste
  TEIL 7  Start                        – Kommandozeile, Startfenster, main()
"""

import argparse
import hashlib
import hmac
import json
import os
import platform
import plistlib
import queue
import random
import re
import secrets
import shlex
import shutil
import socket
import subprocess
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

APP_VERSION = "2.0"


# ===========================================================================
# TEIL 1: Protokoll und Beitrittscode
# ===========================================================================
# Jede Nachricht ist ein JSON-Objekt mit mindestens:
#   type – Art der Nachricht (heartbeat, bye, help, done, ack)
#   id   – eindeutige ID DIESER Nachricht -> Duplikate erkennen
#   from – feste ID der App, die sie geschickt hat
#   ts   – Zeitpunkt (Unix-Zeit) -> alte, aufgezeichnete Nachrichten erkennen
#   mac  – Signatur mit dem Beitrittscode -> nur die eigene Klasse zählt
# Details und Beispiele: siehe PROTOKOLL.md

DISCOVERY_PORT = 50505        # hier hören alle auf Broadcasts (UDP)
DIRECT_PORT = 50506           # hier kommen direkte Nachrichten an (help, done, ack).
                              # Fest, damit man in der Firewall nur 50505-50506 öffnen muss.
CONTROL_PORT = int(os.environ.get("KLASSENZIMMER_STEUERPORT", 50507))
                              # TCP auf 127.0.0.1: "läuft schon?" + Befehle (siehe TEIL 4)
HEARTBEAT_INTERVAL = 5.0      # alle 5 s "Ich bin da"
OFFLINE_AFTER = 20.0          # 20 s nichts gehört -> grau (= 4 verpasste Heartbeats)
ACK_TIMEOUT = 3.0             # 3 s auf Bestätigung warten, dann nochmal
MAX_TRIES = 5                 # höchstens 5 Versuche
MAX_PACKET = 4096             # grössere Pakete werden ignoriert
TS_WINDOW = 600               # Nachrichten, die mehr als 10 min alt sind, ignorieren
SEEN_KEEP = 900               # gesehene IDs 15 min merken (länger als TS_WINDOW!)

ROLES = ("student", "coach")
STATUSES = ("online", "busy")  # online = grün, busy = gelb ("nicht stören")
MAX_NAME = 30
MAX_CLASS = 20
MAX_TEXT = 300

# Beitrittscode: 6 Zeichen ohne Verwechslungsgefahr (kein 0/O, 1/I/L)
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 6


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


def new_code():
    """Neuer Beitrittscode, z.B. 'K7QM3X'. secrets = sicherer Zufall."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def clean_code(text):
    """'k7q-m3x' -> 'K7QM3X'. Gibt None zurück, wenn es kein gültiger Code ist."""
    c = "".join(ch for ch in str(text).upper() if ch.isalnum())
    if len(c) == CODE_LEN and all(ch in CODE_ALPHABET for ch in c):
        return c
    return None


def format_code(code):
    """'K7QM3X' -> 'K7Q-M3X' (leichter vorzulesen)."""
    return code[:3] + "-" + code[3:]


def derive_key(code):
    """Aus dem Code einen geheimen Schlüssel machen.
    PBKDF2 rechnet absichtlich langsam (200 000 Runden). Wer Nachrichten
    mitschneidet, kann so den Code nicht in vernünftiger Zeit erraten."""
    return hashlib.pbkdf2_hmac("sha256", code.encode(), b"klassenzimmer-v2", 200_000)


def room_id(key):
    """Kurzer Name für die Klasse im Speicher (verrät den Code nicht)."""
    return hmac.new(key, b"room", hashlib.sha256).hexdigest()[:16]


def _base(type_, me):
    return {"type": type_, "id": new_id(), "from": me["peer_id"], "ts": int(time.time())}


def make_heartbeat(me):
    return {**_base("heartbeat", me), "name": me["name"], "role": me["role"],
            "status": me["status"], "class": me.get("klasse", ""), "port": me["port"]}


def make_bye(me):
    return _base("bye", me)


def make_help(me, text):
    return {**_base("help", me), "name": me["name"], "text": text[:MAX_TEXT]}


def make_done(me, help_id):
    return {**_base("done", me), "help_id": help_id}


def make_ack(me, msg_id):
    return {**_base("ack", me), "ack_id": msg_id}


def _signature(msg, key):
    """HMAC über die Nachricht (ohne das Feld 'mac').
    sort_keys sorgt dafür, dass Sender und Empfänger genau dieselben Bytes
    signieren, egal in welcher Reihenfolge die Felder stehen."""
    body = {k: v for k, v in msg.items() if k != "mac"}
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(key, data.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def encode(msg, key):
    """dict -> signierte Bytes fürs Netzwerk."""
    return json.dumps({**msg, "mac": _signature(msg, key)}, ensure_ascii=False).encode("utf-8")


def _is_id(v):
    return isinstance(v, str) and 1 <= len(v) <= 64


def _is_text(v, max_len, allow_empty=False):
    return isinstance(v, str) and (allow_empty or v.strip()) and len(v) <= max_len


def decode(data, key):
    """Bytes -> dict, oder None wenn die Nachricht ungültig ist.

    Alles aus dem Netzwerk kann falsch oder absichtlich böse sein. Geprüft wird:
      1. gültiges JSON, nicht zu gross
      2. Signatur passt -> Absender kennt den Beitrittscode
      3. nicht zu alt   -> keine aufgezeichneten Nachrichten von gestern
      4. alle Felder haben den richtigen Typ
    """
    if len(data) > MAX_PACKET:
        return None
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict) or not isinstance(msg.get("mac"), str):
        return None
    if not hmac.compare_digest(msg["mac"], _signature(msg, key)):
        return None                       # falscher Code oder verändert
    ts = msg.get("ts")
    if not isinstance(ts, int) or isinstance(ts, bool) or abs(time.time() - ts) > TS_WINDOW:
        return None
    if not (_is_id(msg.get("id")) and _is_id(msg.get("from"))):
        return None

    t = msg.get("type")
    if t == "heartbeat":
        port = msg.get("port")
        ok = (_is_text(msg.get("name"), MAX_NAME)
              and _is_text(msg.get("class"), MAX_CLASS, allow_empty=True)
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
#   name, role, code, klasse – vom Startfenster
#   peer_id                  – meine feste ID (bleibt gleich, auch nach Neustart)
#   klassen                  – pro Klasse alle Teilnehmer, die man schon gesehen hat
#   mini_pos                 – wo die kleine Leiste auf dem Bildschirm steht

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

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def set_profile(self, name, role, code, klasse=""):
        self.data.update(name=name, role=role, code=code, klasse=klasse)
        if not _is_id(self.data.get("peer_id")):
            self.data["peer_id"] = new_id()
        self.save()

    def known(self, room):
        """{peer_id: {"name", "role"}} aller bekannten Teilnehmer der Klasse."""
        k = self.data["klassen"].get(room, {})
        return {pid: p for pid, p in k.items()
                if _is_id(pid) and isinstance(p, dict) and p.get("role") in ROLES
                and _is_text(p.get("name"), MAX_NAME)}

    def remember(self, room, peer_id, name, role):
        k = self.data["klassen"].setdefault(room, {})
        if k.get(peer_id) != {"name": name, "role": role}:
            k[peer_id] = {"name": name, "role": role}
            self.save()

    def forget(self, room, peer_id):
        k = self.data["klassen"].get(room, {})
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


def base_command():
    """Befehl, der diese App startet (ohne Optionen).
    Fertiges Programm (PyInstaller): sys.frozen ist gesetzt."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    python = sys.executable
    if SYSTEM == "Windows" and python.lower().endswith("python.exe"):
        w = python[:-len("python.exe")] + "pythonw.exe"   # ohne schwarzes Fenster
        if os.path.exists(w):
            python = w
    return [python, str(Path(__file__).resolve())]


def start_command():
    """Befehl für den Autostart (mit --autostart)."""
    cmd = base_command()
    if SYSTEM == "Darwin" and ".app/Contents/MacOS/" in cmd[0]:
        app = cmd[0].split(".app/Contents/MacOS/")[0] + ".app"
        return ["/usr/bin/open", "-a", app, "--args", "--autostart"]
    return cmd + ["--autostart"]


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
# TEIL 4: Steuerung ("läuft schon?") und Waybar
# ===========================================================================
# Die laufende App belegt den TCP-Port 50507 auf 127.0.0.1 (nur dieser PC).
#  - Startet man sie ein zweites Mal, ist der Port besetzt -> das zweite
#    Programm schickt der laufenden App "show" (Fenster zeigen) und endet.
#  - So funktionieren auch Befehle wie "klassenzimmer --zeigen", die die
#    Waybar beim Klick aufruft.

COMMANDS = ("show", "toggle", "status", "quit")


class Control:
    def __init__(self):
        self.sock = None
        self.running = False

    def acquire(self):
        """Port belegen. False = die App läuft schon."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if SYSTEM == "Windows":
            # Windows: niemand anders darf den Port "mitbenutzen"
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            # Linux/Mac: Nach dem Beenden hält das System den Port sonst noch
            # ~1 Minute fest (TIME_WAIT) und ein schneller Neustart scheitert.
            # Zwei laufende Apps verhindert das trotzdem.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", CONTROL_PORT))
            s.listen(5)
            s.settimeout(0.5)
        except OSError:
            s.close()
            return False
        self.sock = s
        return True

    def start(self, events):
        """Befehle annehmen und als ("control", befehl) in die Queue legen."""
        self.running = True

        def loop():
            while self.running:
                try:
                    conn, _ = self.sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with conn:
                    try:
                        conn.settimeout(1)
                        cmd = conn.recv(32).decode("ascii", "ignore").strip()
                        if cmd in COMMANDS:
                            events.put(("control", cmd))
                            conn.sendall(b"ok\n")
                    except OSError:
                        pass
        threading.Thread(target=loop, daemon=True).start()

    def close(self):
        self.running = False
        if self.sock:
            try:
                # weckt den wartenden accept()-Thread sofort auf, damit der
                # Port wirklich frei wird (sonst erst nach bis zu 0.5 s)
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
            self.sock = None


def send_control(cmd):
    """Der laufenden App einen Befehl schicken. True = hat geklappt."""
    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=2) as s:
            s.sendall(cmd.encode("ascii") + b"\n")
            return s.recv(8).startswith(b"ok")
    except OSError:
        return False


def is_hyprland():
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


# --- Waybar (Omarchy/Hyprland) ----------------------------------------------
# Die App schreibt ihren Zustand als fertiges Waybar-JSON in eine Datei.
# Die Waybar liest sie alle 2 Sekunden mit "cat" – das kostet fast nichts.

def waybar_file():
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / APP_ID / "waybar.json"


def write_waybar(text, css_class, tooltip):
    if SYSTEM != "Linux":
        return
    try:
        f = waybar_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"text": text, "class": css_class, "tooltip": tooltip},
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass


def waybar_module(cmd):
    """Die Waybar-Einstellungen für unser Modul (als JSONC-Text)."""
    sh = " ".join(shlex.quote(a) for a in cmd)
    entry = {
        "exec": "cat " + shlex.quote(str(waybar_file())) + " 2>/dev/null",
        "return-type": "json",
        "interval": 2,
        "on-click": sh + " --zeigen",
        "on-click-right": sh + " --status-umschalten",
        "tooltip": True,
    }
    return '"custom/klassenzimmer": ' + json.dumps(entry, indent=4, ensure_ascii=False)


def _skip_comments(text, i):
    """Index des nächsten Zeichens, das kein Leerzeichen/Kommentar ist."""
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = len(text) if j < 0 else j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            i = len(text) if j < 0 else j + 2
        else:
            break
    return i


def insert_waybar_module(config_text, cmd):
    """Fügt unser Modul in eine Waybar-config.jsonc ein (ganz links rechts).
    Gibt den neuen Text zurück. Ist es schon drin, bleibt alles gleich."""
    if '"custom/klassenzimmer"' in config_text:
        return config_text
    start = _skip_comments(config_text, 0)
    if start >= len(config_text) or config_text[start] != "{":
        raise ValueError("Unbekanntes Format (mehrere Leisten?) – bitte von Hand eintragen.")
    m = re.search(r'"modules-right"\s*:\s*\[', config_text)
    if not m:
        raise ValueError('Kein "modules-right" gefunden – bitte von Hand eintragen.')
    text = config_text[:m.end()] + '"custom/klassenzimmer", ' + config_text[m.end():]
    # Definition direkt nach der ersten "{" einfügen (bleibt gültiges JSON)
    return text[:start + 1] + "\n  " + waybar_module(cmd).replace("\n", "\n  ") + "," + text[start + 1:]


def setup_waybar():
    """Waybar einrichten (Omarchy). Gibt eine Meldung für den Benutzer zurück."""
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "waybar"
    config = next((p for p in (base / "config.jsonc", base / "config") if p.exists()), None)
    if config is None:
        return "Keine Waybar-Einstellungen gefunden (%s/config.jsonc)." % base
    old = config.read_text(encoding="utf-8")
    try:
        new = insert_waybar_module(old, base_command())
    except ValueError as e:
        return "%s\n\nSo sieht der Eintrag aus:\n%s" % (e, waybar_module(base_command()))
    if new == old:
        return "Die Waybar ist schon eingerichtet."
    backup = config.with_name(config.name + ".vor-klassenzimmer")
    if not backup.exists():
        backup.write_text(old, encoding="utf-8")
    config.write_text(new, encoding="utf-8")
    # Waybar neu laden
    if shutil.which("omarchy-restart-waybar"):
        subprocess.Popen(["omarchy-restart-waybar"])
    elif shutil.which("pkill"):
        subprocess.run(["pkill", "-SIGUSR2", "waybar"])
    return "Waybar eingerichtet (Sicherung: %s)." % backup.name


# ===========================================================================
# TEIL 5: Netzwerk
# ===========================================================================
# Die Oberfläche weiss nichts von Sockets. Das Netzwerk legt "Ereignisse"
# in eine queue.Queue, und die Oberfläche holt sie im Hauptthread ab:
#
#     Netzwerk-Threads --(events.put)--> Queue --(events.get)--> Oberfläche
#
# Zwei UDP-Sockets:
#   bsock – Port 50505, empfängt Broadcasts (heartbeat, bye) von allen
#   usock – Port 50506, empfängt direkte Nachrichten (help, done, ack)
#           und verschickt alles. Den Port verraten wir im heartbeat.
#
# Ereignisse an die Oberfläche:
#   ("peer", info)      jemand aus der Klasse hat sich gemeldet
#   ("bye", peer_id)    jemand hat die App beendet
#   ("help", info)      Hilfeanfrage angekommen (Coach)
#   ("done", help_id)   meine Anfrage wurde erledigt (Schüler)
#   ("sending", id, n)  Nachricht wird gesendet, Versuch n
#   ("acked", id, von)  Nachricht wurde bestätigt
#   ("failed", id)      nach 5 Versuchen keine Bestätigung
#   ("log", text)       Info für die Konsole

class Network:
    def __init__(self, me, events, key, broadcast_addr="255.255.255.255", loss=0.0, port=0,
                 port_fallback=False):
        self.me = me                      # dict: peer_id, name, role, status, klasse
        self.events = events
        self.key = key                    # aus dem Beitrittscode (derive_key)
        self.broadcast_addr = broadcast_addr
        self.loss = loss                  # zum Üben: Anteil verlorener Pakete
        self.unicast_port = port          # 0 = Betriebssystem wählt
        self.port_fallback = port_fallback  # Port besetzt -> irgendeinen freien nehmen
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
            try:
                self.usock.bind(("", self.unicast_port))
            except OSError:
                if not (self.port_fallback and self.unicast_port):
                    raise
                self.usock.bind(("", 0))       # Port besetzt -> freien Port nehmen
                self.events.put(("log", "Port %d besetzt, benutze %d"
                                 % (self.unicast_port, self.usock.getsockname()[1])))
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
            self._send(msg, addr)                # gleiche Nachricht, gleiche ID
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
        msg = decode(data, self.key)
        if msg is None or msg["from"] == self.me["peer_id"]:
            return               # ungültig, andere Klasse (anderer Code) oder von mir
        t, ip = msg["type"], addr[0]

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
                "role": msg["role"], "status": msg["status"],
                "klasse": clean_text(msg["class"], MAX_CLASS), "ip": ip, "port": msg["port"]}))
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
            self.usock.sendto(encode(msg, self.key), addr)
        except OSError as e:
            if self.running:
                self.events.put(("log", "Senden an %s fehlgeschlagen: %s" % (addr[0], e)))

    def _broadcast(self, msg):
        self._send(msg, (self.broadcast_addr, DISCOVERY_PORT))

    def _forget_old_ids(self):
        limit = now() - SEEN_KEEP
        with self.lock:
            for msg_id, t in list(self.seen.items()):
                if t < limit:
                    del self.seen[msg_id]


# ===========================================================================
# TEIL 6: Oberfläche (tkinter)
# ===========================================================================
# Goldene Regel: Nur der Hauptthread darf tkinter-Widgets anfassen.
# _poll() holt alle 100 ms die Ereignisse aus der Queue,
# _tick() zeichnet jede Sekunde neu (damit "offline" erscheint).
#
# Drei Ansichten:
#   "mini"    – kleine Leiste immer im Vordergrund (Windows, Mac, Linux)
#               das grosse Fenster öffnet sich nur bei Bedarf
#   "waybar"  – Omarchy/Hyprland: Punkt oben in der Waybar, Klick = Fenster
#   "fenster" – nur das grosse Fenster (Testmodus)

COLORS = {"online": "#2e9e44", "busy": "#e0b000", "offline": "#9a9a9a"}
STATUS_TEXT = {"online": "Online", "busy": "Nicht stören", "offline": "Offline"}
ROLE_TEXT = {"student": "Schüler/in", "coach": "Coach"}
BG = "white"
ORANGE, ORANGE_DARK = "#ff9f1a", "#e88a00"


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


class MiniBar:
    """Die kleine Leiste: [⋮ ● Lena  ✋  ⤢]  bzw. beim Coach [⋮ ● Coach  🔔 2  ⤢]

    - ziehen am ⋮ verschiebt sie (Position wird gespeichert)
    - Klick auf den Punkt: Status wechseln
    - ✋: Coach um Hilfe fragen (ohne Text)
    - 🔔 / ⤢ / Name: grosses Fenster öffnen
    - Rechtsklick: Menü mit "Beenden"
    """

    def __init__(self, app):
        self.app = app
        w = self.win = tk.Toplevel(app.root, bg="#cfcfcf")
        w.overrideredirect(True)                 # ohne Rahmen und Titelleiste
        w.attributes("-topmost", True)           # immer im Vordergrund
        inner = tk.Frame(w, bg=BG, padx=4, pady=3)
        inner.pack(padx=1, pady=1)

        grip = tk.Label(inner, text="⋮", bg=BG, fg="#999", cursor="fleur", padx=2)
        grip.pack(side="left")
        grip.bind("<ButtonPress-1>", self._drag_start)
        grip.bind("<B1-Motion>", self._drag_move)
        grip.bind("<ButtonRelease-1>", self._drag_end)

        self.dot = tk.Canvas(inner, width=16, height=16, highlightthickness=0, bg=BG, cursor="hand2")
        self.dot_item = self.dot.create_oval(2, 2, 14, 14, outline="")
        self.dot.pack(side="left", padx=(2, 4))
        self.dot.bind("<Button-1>", lambda e: app.toggle_status())

        name = tk.Label(inner, text=app.me["name"][:14], bg=BG, cursor="hand2")
        name.pack(side="left", padx=(0, 6))
        name.bind("<Button-1>", lambda e: app.show_window())

        if app.me["role"] == "student":
            self.action = ColorButton(inner, "✋", lambda: app.ask_for_help(""), bg=ORANGE,
                                      hover=ORANGE_DARK, padx=8, pady=1)
        else:
            self.action = ColorButton(inner, "🔔 0", app.show_window, bg="#eeeeee", fg="#777",
                                      padx=8, pady=1)
        self.action.pack(side="left")
        ColorButton(inner, "⤢", app.show_window, bg=BG, fg="#555", hover="#eeeeee",
                    padx=6, pady=1).pack(side="left", padx=(4, 0))

        menu = tk.Menu(w, tearoff=0)
        menu.add_command(label="Fenster öffnen", command=app.show_window)
        menu.add_command(label="Status wechseln", command=app.toggle_status)
        menu.add_separator()
        menu.add_command(label="Beenden", command=app.quit)
        for widget in (w, inner, grip, self.dot, name, self.action):
            widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
            widget.bind("<Button-2>", lambda e: menu.tk_popup(e.x_root, e.y_root))  # Mac

        w.update_idletasks()
        pos = app.store.get("mini_pos") if app.store else None
        if isinstance(pos, list) and len(pos) == 2 and all(isinstance(v, int) for v in pos):
            x, y = pos
        else:                                    # Standard: oben rechts
            x, y = w.winfo_screenwidth() - w.winfo_reqwidth() - 30, 40
        x = max(0, min(x, w.winfo_screenwidth() - 60))
        y = max(0, min(y, w.winfo_screenheight() - 30))
        w.geometry("+%d+%d" % (x, y))

    def update(self, status, open_requests, my_request_state):
        self.dot.itemconfigure(self.dot_item, fill=COLORS[status])
        if self.app.me["role"] == "coach":
            if open_requests:
                self.action.configure(text="🔔 %d" % open_requests)
                self.action.set_colors(ORANGE, "white", ORANGE_DARK)
            else:
                self.action.configure(text="🔔 0")
                self.action.set_colors("#eeeeee", "#777")
        else:
            symbol = {"sending": "…", "acked": "✓", "failed": "✗"}.get(my_request_state, "✋")
            self.action.configure(text=symbol)

    def _drag_start(self, e):
        self._off = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag_move(self, e):
        self.win.geometry("+%d+%d" % (e.x_root - self._off[0], e.y_root - self._off[1]))

    def _drag_end(self, e):
        if self.app.store:
            self.app.store.set("mini_pos", [self.win.winfo_x(), self.win.winfo_y()])


class App:
    def __init__(self, root, me, net, events, room, code, store=None, view="fenster",
                 start_hidden=False, control=None):
        self.root, self.me, self.net, self.events = root, me, net, events
        self.room, self.code = room, code
        self.store = store             # None = nichts speichern (z.B. beim Testen)
        self.view = view
        self.control = control
        self.started = time.monotonic()
        self.visible = True
        self.last_waybar = None

        self.peers = {}                # peer_id -> {name, role, status, ip, port, last_seen}
        self.queue = []                # Coach: offene Anfragen, älteste zuerst
        self.requests = {}             # Schüler: help_id -> {coach, state, tries}

        # Gespeicherte Klasse laden: alle Bekannten erscheinen sofort (grau)
        if store:
            for pid, p in store.known(room).items():
                if pid != me["peer_id"]:
                    self.peers[pid] = {"peer_id": pid, "name": p["name"], "role": p["role"],
                                       "status": "online", "ip": None, "port": None,
                                       "last_seen": None, "klasse": ""}

        root.title("Klassenzimmer – %s" % me["name"])
        root.geometry("430x600")
        root.minsize(360, 440)
        root.configure(bg=BG)
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close_window)

        self.mini = MiniBar(self) if view == "mini" else None
        if start_hidden and view != "fenster":
            self.hide_window()

        root.after(100, self._poll)
        root.after(1000, self._tick)
        self._update_small_views()

    # ---- Aufbau -------------------------------------------------------------
    def _build(self):
        top = tk.Frame(self.root, bg=BG, padx=12, pady=10)
        top.pack(fill="x")
        info = tk.Frame(top, bg=BG)
        info.pack(side="left")
        tk.Label(info, text="%s (%s)" % (self.me["name"], ROLE_TEXT[self.me["role"]]),
                 font=("TkDefaultFont", 12, "bold"), bg=BG).pack(anchor="w")
        self.class_label = tk.Label(info, text="", fg="#777", bg=BG, cursor="hand2")
        self.class_label.pack(anchor="w")
        self.class_label.bind("<Button-1>", lambda e: self.copy_code())
        self._update_class_label()

        right = tk.Frame(top, bg=BG)
        right.pack(side="right")
        self.status_btn = ColorButton(right, "", self.toggle_status, bg="#eee")
        self.status_btn.pack(side="left")
        if self.view != "fenster":
            ColorButton(right, "⏻", self.quit, bg=BG, fg="#999", hover="#eee",
                        padx=6).pack(side="left", padx=(6, 0))
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
        ColorButton(parent, "Coach um Hilfe fragen", self.ask_for_help, bg=ORANGE,
                    hover=ORANGE_DARK, font=("TkDefaultFont", 11, "bold"), pady=7).pack(fill="x")
        self.request_frame = tk.Frame(parent, bg=BG, pady=6)
        self.request_frame.pack(fill="x")

    def _build_coach(self, parent):
        tk.Label(parent, text="Hilfeanfragen (älteste zuerst)", bg=BG, anchor="w",
                 font=("TkDefaultFont", 10, "bold")).pack(fill="x")
        self.queue_frame = tk.Frame(parent, bg=BG, pady=4)
        self.queue_frame.pack(fill="x")
        self._render_queue()

    # ---- Fenster zeigen / verstecken ------------------------------------------
    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        self.visible = True

    def hide_window(self):
        self.root.withdraw()
        self.visible = False

    def toggle_window(self):
        if self.visible:
            self.hide_window()
        else:
            self.show_window()

    def close_window(self):
        """Fenster-X: Im Testmodus beenden, sonst nur verstecken
        (die App läuft klein weiter – Beenden mit ⏻ oder Rechtsklick)."""
        if self.view == "fenster":
            self.quit()
        else:
            self.hide_window()

    # ---- Aktionen -------------------------------------------------------------
    def toggle_status(self):
        new = "busy" if self.me["status"] == "online" else "online"
        self.net.set_status(new)
        self._update_status_button()
        self._update_small_views()

    def ask_for_help(self, text=None):
        coaches = [p for p in self.peers.values()
                   if p["role"] == "coach" and self._shown_status(p) != "offline" and p["ip"]]
        if not coaches:
            self._show_request_info("Kein Coach online.")
            if text is not None:          # von der kleinen Leiste: Fenster zeigen
                self.show_window()
            return
        if text is None:
            text = self.help_text.get().strip()
            self.help_text.delete(0, "end")
        text = text[:MAX_TEXT]
        self.requests.clear()          # nur die neueste Anfrage anzeigen
        for c in coaches:              # jedem Coach einzeln, jeder bestätigt selbst
            help_id = self.net.send_help(c["ip"], c["port"], text)
            self.requests[help_id] = {"coach": c["name"], "state": "sending", "tries": 1}
        self._render_requests()
        self._update_small_views()

    def mark_done(self, help_id):
        for item in self.queue:
            if item["help_id"] == help_id:
                self.queue.remove(item)
                self.net.send_done(item["ip"], item["port"], help_id)
                break
        self._render_queue()
        self._update_small_views()

    def remove_peer(self, peer_id):
        """Jemanden aus der gespeicherten Klassenliste entfernen."""
        p = self.peers.get(peer_id)
        if p and messagebox.askyesno("Entfernen", "%s aus der Klassenliste entfernen?" % p["name"],
                                     parent=self.root):
            del self.peers[peer_id]
            if self.store:
                self.store.forget(self.room, peer_id)
            self._render_peers()

    def copy_code(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(format_code(self.code))
        self.class_label.configure(text="Code kopiert ✓")
        self.root.after(1500, self._update_class_label)

    def quit(self):
        if self.view == "waybar":
            write_waybar("<span color='%s'>●</span>" % COLORS["offline"], "offline",
                         "Klassenzimmer läuft nicht")
        self.net.stop()
        if self.control:
            self.control.close()
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
                        self.store.remember(self.room, info["peer_id"], info["name"], info["role"])
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
                elif kind == "control":
                    {"show": self.show_window, "toggle": self.toggle_window,
                     "status": self.toggle_status, "quit": self.quit}[ev[1]]()
                    if ev[1] == "quit":
                        return
                elif kind == "log":
                    print(ev[1])
        except queue.Empty:
            pass
        if "peers" in changed:
            self._render_peers()
            self._update_class_label()
        if "queue" in changed:
            self._render_queue()
        if "requests" in changed:
            self._render_requests()
        if changed:
            self._update_small_views()
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
        self._update_small_views()
        self.root.after(1000, self._tick)

    def _shown_status(self, peer):
        if peer["last_seen"] is None or time.monotonic() - peer["last_seen"] > OFFLINE_AFTER:
            return "offline"
        return peer["status"]

    # ---- Anzeige ----------------------------------------------------------------
    def _class_name(self):
        """Klassenname: eigener (Coach) oder der vom Coach gemeldete (Schüler)."""
        if self.me.get("klasse"):
            return self.me["klasse"]
        for p in self.peers.values():
            if p["role"] == "coach" and p.get("klasse"):
                return p["klasse"]
        return ""

    def _update_class_label(self):
        name = self._class_name()
        text = ("Klasse %s · " % name if name else "") + "Code: " + format_code(self.code)
        self.class_label.configure(text=text)

    def _update_status_button(self):
        s = self.me["status"]
        self.status_btn.configure(text="● " + STATUS_TEXT[s])
        self.status_btn.set_colors("#eeeeee", COLORS[s], hover="#e0e0e0")

    def _my_request_state(self):
        states = [r["state"] for r in self.requests.values()]
        for s in ("acked", "sending", "failed"):   # das Beste zuerst
            if s in states:
                return s
        return None

    def _update_small_views(self):
        """Kleine Leiste und Waybar auf den neuesten Stand bringen."""
        status = self.me["status"]
        req = self._my_request_state()
        if self.mini:
            self.mini.update(status, len(self.queue), req)
        # Waybar-Text: farbiger Punkt + Glocke (Coach) bzw. Hand (Schüler)
        text = "<span color='%s'>●</span>" % COLORS[status]
        tip = ["Klassenzimmer: %s" % STATUS_TEXT[status]]
        css = status
        if self.me["role"] == "coach" and self.queue:
            text += " 🔔%d" % len(self.queue)
            tip.append("%d offene Frage(n): %s" % (len(self.queue), ", ".join(q["name"] for q in self.queue)))
            css = "help"
        elif self.me["role"] == "student" and req:
            text += {"sending": " ✋…", "acked": " ✋✓", "failed": " ✋✗"}[req]
            tip.append({"sending": "Hilfe wird gesendet", "acked": "Hilfe angekommen",
                        "failed": "Hilfe nicht angekommen"}[req])
        online = sum(1 for p in self.peers.values() if self._shown_status(p) != "offline")
        tip.append("%d andere online · Klick: Fenster · Rechtsklick: Status" % online)
        state = (text, css, "\n".join(tip))
        if self.view == "waybar" and state != self.last_waybar:
            self.last_waybar = state
            write_waybar(*state)

    def _render_peers(self):
        for w in self.peer_frame.winfo_children():
            w.destroy()
        if not self.peers:
            hint = "Noch niemand gefunden …"
            if time.monotonic() - self.started > 15:
                hint += "\nStimmt der Code? Sind alle im selben WLAN?"
            tk.Label(self.peer_frame, text=hint, fg="#777", bg=BG, justify="left").pack(anchor="w")
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
        if self.me["role"] != "student":
            return
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
# TEIL 7: Start
# ===========================================================================

def ask_profile(name, role, code, klasse):
    """Startfenster: Name, Rolle, Beitrittscode, (Coach: Klassenname), Autostart.
    Gibt (name, role, code, klasse, autostart) oder None zurück."""
    result = {}
    win = tk.Tk()
    win.title("Klassenzimmer – Start")
    win.resizable(False, False)
    f = tk.Frame(win, padx=20, pady=16)
    f.pack()

    tk.Label(f, text="Dein Name:").grid(row=0, column=0, columnspan=2, sticky="w")
    name_var = tk.StringVar(value=name or "")
    e = tk.Entry(f, textvariable=name_var, width=28)
    e.grid(row=1, column=0, columnspan=2, pady=(2, 8), sticky="we")
    e.focus()

    tk.Label(f, text="Rolle:").grid(row=2, column=0, sticky="w")
    role_var = tk.StringVar(value=role or "student")
    tk.Radiobutton(f, text="Schüler/in", variable=role_var, value="student").grid(row=3, column=0, sticky="w")
    tk.Radiobutton(f, text="Coach", variable=role_var, value="coach").grid(row=3, column=1, sticky="w")

    code_label = tk.Label(f, text="")
    code_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
    code_row = tk.Frame(f)
    code_row.grid(row=5, column=0, columnspan=2, sticky="we", pady=(2, 0))
    code_var = tk.StringVar(value=format_code(code) if code else "")
    tk.Entry(code_row, textvariable=code_var, width=12, font=("TkFixedFont", 13)).pack(side="left")
    new_btn = tk.Button(code_row, text="Neuen Code", command=lambda: code_var.set(format_code(new_code())))

    class_label = tk.Label(f, text="Klasse (Name, z.B. INF3a):")
    class_var = tk.StringVar(value=klasse or "")
    class_entry = tk.Entry(f, textvariable=class_var, width=28)

    def role_changed(*_):
        if role_var.get() == "coach":
            code_label.configure(text="Beitrittscode (gib ihn deiner Klasse):")
            new_btn.pack(side="left", padx=(8, 0))
            if not clean_code(code_var.get()):
                code_var.set(format_code(new_code()))
            class_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
            class_entry.grid(row=7, column=0, columnspan=2, sticky="we", pady=(2, 0))
        else:
            code_label.configure(text="Beitrittscode (vom Coach):")
            new_btn.pack_forget()
            class_label.grid_remove()
            class_entry.grid_remove()
    role_var.trace_add("write", role_changed)
    role_changed()

    auto_var = tk.BooleanVar(value=autostart_enabled() if name else True)
    tk.Checkbutton(f, text="Beim Anmelden automatisch starten",
                   variable=auto_var).grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 0))
    error = tk.Label(f, text="", fg="#b00")
    error.grid(row=9, column=0, columnspan=2, sticky="w")

    def ok(_event=None):
        n = clean_text(name_var.get(), MAX_NAME)
        c = clean_code(code_var.get())
        if not n:
            error.configure(text="Bitte deinen Namen eingeben.")
            return
        if not c:
            error.configure(text="Der Code hat 6 Zeichen, z.B. K7Q-M3X.")
            return
        k = clean_text(class_var.get(), MAX_CLASS) if role_var.get() == "coach" else ""
        result.update(name=n, role=role_var.get(), code=c, klasse=k, auto=auto_var.get())
        win.destroy()

    tk.Button(f, text="Los geht's", command=ok).grid(row=10, column=0, columnspan=2,
                                                      pady=(6, 0), sticky="we")
    win.bind("<Return>", ok)
    win.mainloop()
    if not result:
        return None
    return result["name"], result["role"], result["code"], result["klasse"], result["auto"]


def show_message(title, text, error=False):
    r = tk.Tk()
    r.withdraw()
    (messagebox.showerror if error else messagebox.showinfo)(title, text)
    r.destroy()


def main():
    parser = argparse.ArgumentParser(description="Peer-to-Peer-App fürs Klassenzimmer")
    parser.add_argument("--name", help="dein Name")
    parser.add_argument("--role", choices=ROLES, help="student oder coach")
    parser.add_argument("--code", help="Beitrittscode vom Coach (6 Zeichen), Coach: NEU = neuen erzeugen")
    parser.add_argument("--klasse", default="", help="Klassenname (nur Coach, z.B. INF3a)")
    parser.add_argument("--speichern", action="store_true",
                        help="mit --name/--role/--code: dauerhaft speichern und Autostart einschalten")
    parser.add_argument("--kein-autostart", action="store_true",
                        help="mit --speichern: Autostart NICHT einschalten")
    parser.add_argument("--autostart", action="store_true",
                        help="gespeicherte Einstellungen benutzen, klein starten")
    parser.add_argument("--zeigen", action="store_true", help="Fenster der laufenden App zeigen/verstecken")
    parser.add_argument("--status-umschalten", action="store_true", help="Status der laufenden App wechseln")
    parser.add_argument("--beenden", action="store_true", help="laufende App beenden")
    parser.add_argument("--waybar-einrichten", action="store_true",
                        help="Omarchy/Hyprland: Punkt in der Waybar einrichten")
    parser.add_argument("--ansicht", choices=("mini", "waybar", "fenster"),
                        help="kleine Leiste, Waybar oder nur Fenster (Standard: automatisch)")
    parser.add_argument("--port", type=int, default=0,
                        help="Port für direkte Nachrichten (Standard: 50506, im Testmodus zufällig)")
    parser.add_argument("--broadcast", default="255.255.255.255",
                        help="Broadcast-Adresse, z.B. 192.168.1.255")
    parser.add_argument("--verlust", type=float, default=0.0,
                        help="zum Üben: Anteil verlorener Pakete, z.B. 0.3")
    parser.add_argument("--version", action="version", version="Klassenzimmer " + APP_VERSION)
    args = parser.parse_args()

    if args.waybar_einrichten:
        print(setup_waybar())
        return
    if args.code and args.code.strip().upper() == "NEU":
        args.code = new_code()
        print("Neuer Beitrittscode: %s" % format_code(args.code))

    command = "toggle" if args.zeigen else "status" if args.status_umschalten else \
              "quit" if args.beenden else None

    # Testmodus: Name+Rolle auf der Kommandozeile -> nichts speichern,
    # mehrere Instanzen auf einem PC erlaubt.
    test_mode = bool(args.name and args.role) and not args.speichern and command is None
    if args.speichern and not (args.name and args.role and clean_code(args.code or "")):
        parser.error("--speichern braucht --name, --role und --code")
    if args.code and not clean_code(args.code):
        parser.error("Der Code hat 6 Zeichen aus A-Z (ohne I, L, O) und 2-9, z.B. K7QM3X")

    control = None
    if test_mode:
        store = None
        code = clean_code(args.code or "") or "TEST23"
        name = clean_text(args.name, MAX_NAME)
        if not name:
            parser.error("--name darf nicht leer sein")
        me = {"peer_id": new_id(), "name": name, "role": args.role,
              "klasse": clean_text(args.klasse, MAX_CLASS) if args.role == "coach" else ""}
    else:
        control = Control()
        if not control.acquire():
            # Port besetzt: Läuft die App schon? Dann ihr den Befehl schicken.
            if send_control(command or "show"):
                return
            if command:
                print("Klassenzimmer läuft nicht.")
                return
            # Ein fremdes Programm benutzt den Port -> ohne Steuerung weitermachen
            print("Port %d ist von einem anderen Programm belegt – "
                  "'nur einmal starten' und Waybar-Klicks funktionieren nicht." % CONTROL_PORT)
            control = None
        elif command in ("status", "quit"):
            control.close()                     # läuft nicht -> nichts zu tun
            print("Klassenzimmer läuft nicht.")
            return
        store = Store()
        if args.speichern:
            # Einrichten ohne Startfenster (z.B. für Installations-Skripte)
            store.set_profile(clean_text(args.name, MAX_NAME), args.role, clean_code(args.code),
                              clean_text(args.klasse, MAX_CLASS) if args.role == "coach" else "")
            problem = set_autostart(not args.kein_autostart)
            print(problem or "Gespeichert. Autostart: %s" % ("aus" if args.kein_autostart else "an"))
            if is_hyprland():
                print(setup_waybar())
        name = clean_text(store.get("name", ""), MAX_NAME)
        role = store.get("role") if store.get("role") in ROLES else None
        code = clean_code(store.get("code") or "")
        klasse = clean_text(store.get("klasse", ""), MAX_CLASS)
        if not (args.autostart and name and role and code) and not args.speichern:
            answer = ask_profile(name, role, code, klasse)
            if answer is None:
                if control:
                    control.close()
                return                        # Startfenster geschlossen
            name, role, code, klasse, auto = answer
            store.set_profile(name, role, code, klasse)
            problem = set_autostart(auto)
            if problem:
                print(problem)
            if auto and is_hyprland():
                print(setup_waybar())
        if not _is_id(store.get("peer_id")):        # z.B. Datei von Hand geändert
            store.set_profile(name, role, code, klasse)
        me = {"peer_id": store.get("peer_id"), "name": name, "role": role, "klasse": klasse}

    me["status"] = "online"
    key = derive_key(code)
    events = queue.Queue()
    # Normal: fester Port 50506 (gut für Firewalls). Testmodus: zufälliger Port,
    # damit mehrere Apps auf einem PC laufen können.
    port = args.port or (0 if test_mode else DIRECT_PORT)
    net = Network(me, events, key, broadcast_addr=args.broadcast, loss=args.verlust,
                  port=port, port_fallback=not args.port)
    try:
        net.start()
    except OSError as e:
        show_message("Klassenzimmer", "Netzwerk konnte nicht gestartet werden:\n%s" % e, error=True)
        return

    view = args.ansicht or ("fenster" if test_mode else "waybar" if is_hyprland() else "mini")
    root = tk.Tk()
    App(root, me, net, events, room_id(key), code, store, view=view,
        start_hidden=args.autostart or args.speichern, control=control)
    if control:
        control.start(events)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        net.stop()
        if control:
            control.close()


if __name__ == "__main__":
    main()
