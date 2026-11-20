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
  TEIL 5b Internet-Weg                 – falls das WLAN die Geräte voneinander trennt
  TEIL 6  Oberfläche                   – grosses Fenster und kleine Leiste
  TEIL 7  Start                        – Kommandozeile, Startfenster, main()
  TEIL 8  Erweiterungen                – eigene Knöpfe aus erweiterung.py
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import platform
import plistlib
import queue
import random
import re
import struct
import secrets
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

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

APP_VERSION = "2.5"


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
# Zusätzlich zum Broadcast: Viele Schul-WLANs filtern Broadcasts zwischen Geräten,
# lassen Multicast (wie bei Druckern und Chromecast) aber durch.
MULTICAST_GROUP = "239.255.50.55"
# Und wenn das WLAN die Geräte ganz voneinander trennt (Client-Isolation, z.B. im
# Schul-WLAN BbcBYOD), geht gar nichts direkt, auch kein Multicast. Dann zusätzlich
# übers Internet: über einen öffentlichen MQTT-Vermittler, per WebSocket auf Port 443
# wie eine normale Webseite. Alles ist mit dem Beitrittscode verschlüsselt und
# signiert, der Vermittler sieht nur Datensalat (siehe TEIL 5b).
RELAY_URL = "wss://public:public@public.cloud.shiftr.io/"
RELAY_IP = "internet"         # "Adresse" von jemandem, den wir nur übers Internet hören
RELAY_HEARTBEAT = 15.0        # übers Internet seltener "Ich bin da" (schont den Vermittler)
OFFLINE_AFTER_INTERNET = 50.0 # ... und darum später grau
RAW_MAGIC = b"KZX"            # rohe Pakete von Erweiterungen (TEIL 8), nicht signiert
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


def _to(to):
    """Empfänger (peer_id) für direkte Nachrichten. Die Multicast-Kopie geht an
    alle, so erkennt jeder, ob sie für ihn ist. Ältere Versionen ignorieren das Feld."""
    return {"to": to} if to else {}


def make_help(me, text, to=None):
    return {**_base("help", me), "name": me["name"], "text": text[:MAX_TEXT], **_to(to)}


def make_done(me, help_id, to=None):
    return {**_base("done", me), "help_id": help_id, **_to(to)}


def make_ack(me, msg_id, to=None):
    return {**_base("ack", me), "ack_id": msg_id, **_to(to)}


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


# Fürs Internet zusätzlich verschlüsseln: Die Signatur (mac) schützt nur vor
# Fälschungen, Name und Hilfetext wären sonst lesbar. Verfahren: HMAC-SHA256 als
# Schlüsselstrom (Zähler-Modus), jedes Paket mit eigener Zufallszahl (nonce).
# Ob nichts verändert wurde, prüft danach decode() über die Signatur.
SEAL_MAGIC = b"KZ1"
SEAL_NONCE = 16


def _sub_key(key, purpose):
    return hmac.new(key, purpose, hashlib.sha256).digest()


def _keystream(key, nonce, n):
    k = _sub_key(key, b"internet-verschluesselung")
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hmac.new(k, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:n])


def _xor(data, stream):
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def seal(data, key):
    """Signierte Bytes -> verschlüsselte Bytes fürs Internet."""
    nonce = os.urandom(SEAL_NONCE)
    return SEAL_MAGIC + nonce + _xor(data, _keystream(key, nonce, len(data)))


def unseal(blob, key):
    """Gegenstück zu seal(). None, wenn es kein Paket von uns ist."""
    head = len(SEAL_MAGIC) + SEAL_NONCE
    if not isinstance(blob, bytes) or not blob.startswith(SEAL_MAGIC) or not head < len(blob) <= head + MAX_PACKET:
        return None
    nonce, body = blob[len(SEAL_MAGIC):head], blob[head:]
    return _xor(body, _keystream(key, nonce, len(body)))


RAW_TOPIC = re.compile(r"[a-z0-9_-]{1,40}")


def raw_relay_topic(topic, reverse=False):
    """Thema einer Erweiterung <-> MQTT-Thema. reverse: MQTT-Thema -> Thema (oder None)."""
    prefix = "klassenzimmer-x/"
    if reverse:
        return topic[len(prefix):] if topic.startswith(prefix) else None
    return prefix + topic


def relay_topics(key, peer_id):
    """MQTT-Themen: eins für alle in der Klasse, eins nur für mich.
    Aus dem Schlüssel berechnet, damit sie den Code nicht verraten."""
    root = "klassenzimmer/" + _sub_key(key, b"internet-thema").hex()[:24]
    return root + "/alle", root + "/" + hmac.new(key, peer_id.encode(), hashlib.sha256).hexdigest()[:16]


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

COMMANDS = ("show", "toggle", "status", "quit", "erweiterung-umschalten")
# Befehle mit Text dahinter, z.B. "hilfe Aufgabe 3" (für Leisten-Panels wie Omarchy)
ARG_COMMANDS = ("hilfe", "erledigt", "entfernen", "erweiterung")
MAX_CONTROL = 1024                 # Bytes pro Steuerbefehl


def parse_control(line):
    """'hilfe Aufgabe 3' -> ('hilfe', 'Aufgabe 3'). Unbekanntes -> None."""
    name, _, arg = line.strip().partition(" ")
    if name in COMMANDS and not arg:
        return name, None
    if name in ARG_COMMANDS:
        return name, arg.strip()
    return None


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
                        data = b""
                        while b"\n" not in data and len(data) < MAX_CONTROL:
                            chunk = conn.recv(MAX_CONTROL)
                            if not chunk:
                                break
                            data += chunk
                        parsed = parse_control(data[:MAX_CONTROL].decode("utf-8", "ignore"))
                        if parsed:
                            name, arg = parsed
                            events.put(("control", name) if arg is None else ("control", name, arg))
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


def send_control(cmd, arg=None):
    """Der laufenden App einen Befehl schicken. True = hat geklappt."""
    line = cmd if arg is None else "%s %s" % (cmd, " ".join(str(arg).split()))
    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=2) as s:
            s.sendall(line.encode("utf-8")[:MAX_CONTROL - 1] + b"\n")
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


def state_file():
    """Ganzer Zustand als JSON (Teilnehmer, Anfragen …) für Leisten-Panels,
    z.B. das Omarchy-Panel. Liegt neben waybar.json."""
    return waybar_file().with_name("zustand.json")


def write_state(state):
    path = state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)                  # nie halb geschrieben lesen
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
#   ("internet", bool)  Internet-Weg verbunden / getrennt (TEIL 5b)
#   ("log", text)       Info für die Konsole
#
# Mit relay (TEIL 5b) geht zusätzlich alles übers Internet. Wen wir nur dort
# hören, hat die "Adresse" (RELAY_IP, 0). Doppelt ankommende Nachrichten
# (WLAN und Internet) fallen bei der Duplikat-Erkennung (seen) weg.

class Network:
    def __init__(self, me, events, key, broadcast_addr="255.255.255.255", loss=0.0, port=0,
                 port_fallback=False, multicast=True, relay=None):
        self.me = me                      # dict: peer_id, name, role, status, klasse
        self.events = events
        self.key = key                    # aus dem Beitrittscode (derive_key)
        self.broadcast_addr = broadcast_addr
        self.loss = loss                  # zum Üben: Anteil verlorener Pakete
        self.unicast_port = port          # 0 = Betriebssystem wählt
        self.port_fallback = port_fallback  # Port besetzt -> irgendeinen freien nehmen
        self.multicast = multicast        # zusätzlich per Multicast senden und hören
        self.mcast = False                # Multicast klappt hier wirklich (nach start)
        self.relay = relay                # Internet-Weg (TEIL 5b) oder None
        self.topic_all = self.topic_me = None
        self.raw_listeners = {}           # Erweiterungen: Thema -> fn(daten)
        self.next_relay_heartbeat = 0.0
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
        self.mcast = False
        if self.multicast:
            # Gruppe beitreten: Dann kommen auch Multicast-Pakete an Port 50505 an
            try:
                mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP), socket.inet_aton("0.0.0.0"))
                self.bsock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                self.mcast = True
            except OSError as e:
                self.events.put(("log", "Multicast geht hier nicht (%s), nur Broadcast" % e))

        self.usock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.usock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.usock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)   # nur lokales Netz
        except OSError:
            pass
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
        if self.relay:
            self.topic_all, self.topic_me = relay_topics(self.key, self.me["peer_id"])
            self.relay.start([self.topic_all, self.topic_me], self._from_relay, self._relay_state,
                             lambda text: self.events.put(("log", text)))
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
        if self.relay:
            self.relay.stop()            # schickt vorher noch das "bye"

    # ---- Für die Oberfläche ----------------------------------------------
    def set_status(self, status):
        with self.lock:
            self.me["status"] = status
            self.next_heartbeat = 0.0    # sofort melden
            self.next_relay_heartbeat = 0.0

    def send_help(self, ip, port, text, to=None):
        msg = make_help(self.me, text, to)
        self._send_reliable(msg, (ip, port))
        return msg["id"]

    def send_done(self, ip, port, help_id, to=None):
        self._send_reliable(make_done(self.me, help_id, to), (ip, port))

    # ---- Zuverlässig senden: ACK + Wiederholung ---------------------------
    # 1. senden und in pending merken
    # 2. ACK kommt -> aus pending löschen -> "acked"
    # 3. 3 s kein ACK -> nochmal (höchstens 5 Versuche)
    # 4. nach 5 Versuchen -> "failed"
    def _send_reliable(self, msg, addr):
        with self.lock:
            self.pending[msg["id"]] = {"msg": msg, "addr": addr, "tries": 1,
                                       "next": now() + ACK_TIMEOUT}
        self._send_direct(msg, addr)
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
            self._send_direct(msg, addr)         # gleiche Nachricht, gleiche ID
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
        if data.startswith(RAW_MAGIC):
            self._handle_raw(data)                   # Paket einer Erweiterung
            return
        msg = decode(data, self.key)
        if msg is None or msg["from"] == self.me["peer_id"]:
            return               # ungültig, andere Klasse (anderer Code) oder von mir
        if msg.get("to") is not None and msg["to"] != self.me["peer_id"]:
            return               # Multicast-Kopie einer direkten Nachricht an jemand anderen
        t, ip = msg["type"], addr[0]

        # Duplikate: schon gesehen? Bei help/done trotzdem ACK senden,
        # weil wahrscheinlich unser erstes ACK verloren ging.
        with self.lock:
            duplicate = msg["id"] in self.seen
            self.seen[msg["id"]] = now()
        if duplicate:
            if t in ("help", "done"):
                self._send_direct(make_ack(self.me, msg["id"], msg["from"]), addr)
            return

        if t == "heartbeat":
            # Neu (oder neu gestartet = neuer Port)? Sofort direkt antworten,
            # damit er uns nicht erst in bis zu 5 s sieht.
            key = (msg["from"], msg["port"])
            with self.lock:
                is_new = key not in self.known
                self.known.add(key)
                hb = make_heartbeat(self.me) if is_new else None
            if hb and ip == RELAY_IP:
                hb["to"] = msg["from"]        # übers Internet nur an den Neuen
                self._publish(hb)
            elif hb:
                self._send(hb, (ip, msg["port"]))
                if self.mcast:
                    self._send(hb, (MULTICAST_GROUP, DISCOVERY_PORT))
            self.events.put(("peer", {
                "peer_id": msg["from"], "name": clean_text(msg["name"], MAX_NAME),
                "role": msg["role"], "status": msg["status"],
                "klasse": clean_text(msg["class"], MAX_CLASS), "ip": ip, "port": msg["port"]}))
        elif t == "bye":
            with self.lock:
                self.known = {k for k in self.known if k[0] != msg["from"]}
            self.events.put(("bye", msg["from"]))
        elif t == "help":
            self._send_direct(make_ack(self.me, msg["id"], msg["from"]), addr)
            self.events.put(("help", {
                "help_id": msg["id"], "peer_id": msg["from"],
                "name": clean_text(msg["name"], MAX_NAME), "text": clean_text(msg["text"], MAX_TEXT),
                "ip": ip, "port": addr[1]}))
        elif t == "done":
            self._send_direct(make_ack(self.me, msg["id"], msg["from"]), addr)
            self.events.put(("done", msg["help_id"]))
        elif t == "ack":
            with self.lock:
                found = self.pending.pop(msg["ack_id"], None)
            if found:
                self.events.put(("acked", msg["ack_id"], msg["from"]))

    # ---- Hilfsfunktionen ------------------------------------------------------
    def _send(self, msg, addr):
        if addr[0] == RELAY_IP:
            self._publish(msg)
            return
        try:
            self.usock.sendto(encode(msg, self.key), addr)
        except OSError as e:
            if self.running:
                self.events.put(("log", "Senden an %s fehlgeschlagen: %s" % (addr[0], e)))

    def _send_direct(self, msg, addr):
        """Direkt an eine Adresse und (mit Empfänger) als Kopie per Multicast,
        falls das WLAN direkte Verbindungen zwischen Geräten sperrt."""
        self._send(msg, addr)
        if msg.get("to") and addr[0] != RELAY_IP:
            if self.mcast:
                self._send(msg, (MULTICAST_GROUP, DISCOVERY_PORT))
            self._publish(msg)                   # und übers Internet

    def _broadcast(self, msg):
        self._send(msg, (self.broadcast_addr, DISCOVERY_PORT))
        if self.mcast:
            self._send(msg, (MULTICAST_GROUP, DISCOVERY_PORT))
        if self.relay:
            if msg["type"] == "heartbeat":
                with self.lock:
                    due = now() >= self.next_relay_heartbeat
                    if due:
                        self.next_relay_heartbeat = now() + RELAY_HEARTBEAT
                if not due:
                    return
            self._publish(msg)

    # ---- Internet-Weg (TEIL 5b) ------------------------------------------------
    def _publish(self, msg):
        """Verschlüsselt übers Internet: direkte Nachrichten ins Thema des
        Empfängers, alles andere ins Thema der ganzen Klasse."""
        if not self.relay or not self.running:
            return
        topic = (relay_topics(self.key, msg["to"])[1] if msg.get("to") else self.topic_all)
        self.relay.publish(topic, seal(encode(msg, self.key), self.key))

    def _from_relay(self, topic, payload):
        fn = self.raw_listeners.get(raw_relay_topic(topic, reverse=True))
        if fn:
            fn(payload)
            return
        data = unseal(payload, self.key)
        if data is not None and self.running:
            self._handle(data, (RELAY_IP, 0))

    def _relay_state(self, connected):
        if connected:
            with self.lock:                      # gleich melden, wer wir sind
                self.next_heartbeat = self.next_relay_heartbeat = 0.0
        self.events.put(("internet", connected))

    # ---- Rohe Pakete für Erweiterungen (TEIL 8) -----------------------------------
    # Format im WLAN: "KZX" + Länge des Themas (1 Byte) + Thema + Daten.
    # Übers Internet: Daten im MQTT-Thema raw_relay_topic(thema).
    # Die App prüft hier nichts: Verschlüsseln und Signieren macht die Erweiterung.
    def listen_raw(self, topic, fn):
        """fn(daten) für jedes Paket mit diesem Thema (läuft im Netzwerk-Thread)."""
        if not RAW_TOPIC.fullmatch(topic):
            raise ValueError("Thema: 1-40 Zeichen a-z, 0-9, - oder _")
        self.raw_listeners[topic] = fn
        if self.relay:
            self.relay.add_topic(raw_relay_topic(topic))

    def send_raw(self, topic, data):
        """An alle: Broadcast, Multicast und Internet."""
        if not RAW_TOPIC.fullmatch(topic) or len(data) > MAX_PACKET:
            raise ValueError("Thema ungültig oder Paket zu gross")
        packet = RAW_MAGIC + bytes([len(topic)]) + topic.encode() + data
        for addr in [(self.broadcast_addr, DISCOVERY_PORT)] + \
                    ([(MULTICAST_GROUP, DISCOVERY_PORT)] if self.mcast else []):
            try:
                self.usock.sendto(packet, addr)
            except OSError as e:
                if self.running:
                    self.events.put(("log", "Senden an %s fehlgeschlagen: %s" % (addr[0], e)))
        if self.relay and self.running:
            self.relay.publish(raw_relay_topic(topic), data)

    def _handle_raw(self, data):
        n = data[len(RAW_MAGIC)] if len(data) > len(RAW_MAGIC) else 0
        start = len(RAW_MAGIC) + 1
        topic = data[start:start + n].decode("ascii", "replace")
        fn = self.raw_listeners.get(topic)
        if fn and len(data) > start + n:
            fn(data[start + n:])

    def _forget_old_ids(self):
        limit = now() - SEEN_KEEP
        with self.lock:
            for msg_id, t in list(self.seen.items()):
                if t < limit:
                    del self.seen[msg_id]


# ===========================================================================
# TEIL 5b: Internet-Weg – falls das WLAN die Geräte voneinander trennt
# ===========================================================================
# Manche WLANs (Schulen, Firmen, Hotels) lassen Geräte nicht miteinander reden
# ("Client-Isolation"): kein Broadcast, kein Multicast, nicht einmal ein Ping.
# Ins Internet kommt aber jeder. Darum verbindet sich die App zusätzlich mit
# einem öffentlichen MQTT-Vermittler (Publish/Subscribe):
#
#     App A --publish("…/alle", Paket)--> Vermittler --> alle, die "…/alle" abonniert haben
#
# - Verbindung: WebSocket über TLS auf Port 443 (wie https), das lassen auch
#   strenge Firewalls durch. MQTT 3.1.1 ist einfach genug für die
#   Standardbibliothek: CONNECT, SUBSCRIBE, PUBLISH, PINGREQ.
# - Datenschutz: Jedes Paket ist mit dem Beitrittscode verschlüsselt (seal) und
#   signiert (encode). Die Themen sind aus dem Code berechnet (relay_topics).
#   Der Vermittler sieht nur, dass jemand Datensalat schickt.
# - Ein einziger Thread macht alles mit dem Socket (lesen, senden, Ping).
#   Andere Threads legen ihre Pakete nur in eine Warteschlange.
# - Bricht die Verbindung ab: neu verbinden, Wartezeit 1, 2, 4 … höchstens 60 s.

CA_FILES = ("/etc/ssl/certs/ca-certificates.crt",   # Debian, Ubuntu, Arch
            "/etc/pki/tls/certs/ca-bundle.crt",     # Fedora
            "/etc/ssl/ca-bundle.pem",               # openSUSE
            "/etc/ssl/cert.pem")                    # macOS, Alpine


def tls_context():
    """TLS mit Zertifikatsprüfung. Eine mit PyInstaller gebaute App sucht die
    Zertifikate oft am Ort des Build-Rechners, darum die üblichen Orte dazu."""
    ctx = ssl.create_default_context()
    for path in CA_FILES:
        if os.path.isfile(path):
            try:
                ctx.load_verify_locations(path)
                break
            except (OSError, ssl.SSLError):
                pass
    return ctx


def mqtt_string(text):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return struct.pack("!H", len(data)) + data


def mqtt_packet(first, body):
    """Feste Kopfzeile: Typ-Byte + Länge (7 Bit pro Byte, oberstes Bit = "es geht weiter")."""
    n, length = len(body), b""
    while True:
        n, digit = divmod(n, 128)
        length += bytes([digit | (0x80 if n else 0)])
        if not n:
            return bytes([first]) + length + body


def mqtt_parse(buf):
    """Ein ganzes MQTT-Paket vorne aus buf: (typ_byte, inhalt, rest) oder None."""
    n, mult, i = 0, 1, 1
    while True:
        if i >= len(buf):
            return None
        digit = buf[i]
        n += (digit & 0x7F) * mult
        mult *= 128
        i += 1
        if not digit & 0x80:
            break
        if i > 4:
            raise ValueError("MQTT-Länge kaputt")
    if len(buf) < i + n:
        return None
    return buf[0], buf[i:i + n], buf[i + n:]


def ws_frame(data, opcode=0x2):
    """WebSocket-Frame vom Client: immer maskiert (so will es RFC 6455)."""
    n = len(data)
    if n < 126:
        head = bytes([0x80 | opcode, 0x80 | n])
    elif n < 65536:
        head = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack("!H", n)
    else:
        head = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack("!Q", n)
    mask = os.urandom(4)
    return head + mask + _xor(data, (mask * (n // 4 + 1))[:n])


def ws_parse(buf):
    """Ein ganzes WebSocket-Frame vorne aus buf: (opcode, daten, rest) oder None."""
    if len(buf) < 2:
        return None
    op, n, i = buf[0] & 0x0F, buf[1] & 0x7F, 2
    if n == 126:
        if len(buf) < 4:
            return None
        n, i = struct.unpack("!H", buf[2:4])[0], 4
    elif n == 127:
        if len(buf) < 10:
            return None
        n, i = struct.unpack("!Q", buf[2:10])[0], 10
    if n > 1 << 20:
        raise ValueError("WebSocket-Frame zu gross")
    mask = None
    if buf[1] & 0x80:
        mask, i = buf[i:i + 4], i + 4
    if len(buf) < i + n:
        return None
    data = buf[i:i + n]
    if mask:
        data = _xor(data, (mask * (n // 4 + 1))[:n])
    return op, data, buf[i + n:]


class Relay:
    """MQTT über WebSocket. url z.B. wss://benutzer:passwort@host/pfad
    (ws:// ohne Verschlüsselung nur für Tests und eigene Vermittler im LAN)"""

    def __init__(self, url=RELAY_URL, keepalive=30):
        u = urlsplit(url)
        if u.scheme not in ("wss", "ws") or not u.hostname:
            raise ValueError("Internet-Adresse muss mit wss:// anfangen: %r" % url)
        self.tls = u.scheme == "wss"
        self.host, self.port = u.hostname, u.port or (443 if self.tls else 80)
        self.path = (u.path or "/") + ("?" + u.query if u.query else "")
        self.user = unquote(u.username) if u.username else None
        self.password = unquote(u.password) if u.password else None
        self.keepalive = keepalive
        self.outbox = queue.Queue(maxsize=500)
        self.running = False
        self.connected = False
        self.thread = None
        self.topics = []
        self.resubscribe = False          # neue Themen dazugekommen -> nochmal SUBSCRIBE
        self.packet_id = 0

    # ---- für Network -----------------------------------------------------------
    def start(self, topics, on_message, on_state=None, log=print):
        self.topics, self.on_message = list(topics) + self.topics, on_message
        self.on_state, self.log = on_state or (lambda connected: None), log
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def add_topic(self, topic):
        """Später noch ein Thema abonnieren (z.B. für eine Erweiterung)."""
        if topic not in self.topics:
            self.topics.append(topic)
            self.resubscribe = True

    def publish(self, topic, payload):
        """Nur in die Warteschlange (der Relay-Thread schickt es).
        Ohne Verbindung wird verworfen, Heartbeats und Wiederholungen kommen ja nach."""
        if not self.connected:
            return False
        try:
            self.outbox.put_nowait(mqtt_packet(0x30, mqtt_string(topic) + payload))
            return True
        except queue.Full:
            return False

    def stop(self, wait=1.5):
        """Warteschlange noch leeren (z.B. das "bye"), dann trennen."""
        self.running = False
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(wait)

    # ---- Relay-Thread ----------------------------------------------------------
    def _loop(self):
        wait = 1
        while self.running:
            sock = None
            try:
                sock = self._connect()
                wait = 1
                self._session(sock)
            except Exception as e:       # auch kaputte Pakete: neu verbinden
                if self.running:
                    self.log("Internet: %s" % (str(e) or type(e).__name__))
            finally:
                if self.connected:
                    self.connected = False
                    self.on_state(False)
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
            end = time.monotonic() + wait
            while self.running and time.monotonic() < end:
                time.sleep(0.2)
            wait = min(wait * 2, 60)

    def _connect(self):
        raw = socket.create_connection((self.host, self.port), timeout=10)
        try:
            sock = tls_context().wrap_socket(raw, server_hostname=self.host) if self.tls else raw
        except OSError:
            raw.close()
            raise
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
                      "Sec-WebSocket-Protocol: mqtt\r\n\r\n" % (self.path, self.host, key)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk or len(head) > 16384:
                sock.close()
                raise OSError("keine WebSocket-Antwort")
            head += chunk
        head, self.rbuf = head.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n")[0].decode("latin-1")
        if status.split(" ")[1:2] != ["101"]:
            sock.close()
            raise OSError("WebSocket abgelehnt: %s" % status)
        self.mbuf = b""
        flags = 0x02 | (0x80 if self.user else 0) | (0x40 if self.password else 0)   # 0x02 = clean session
        body = (mqtt_string("MQTT") + bytes([4, flags]) + struct.pack("!H", self.keepalive)
                + mqtt_string("kz-" + os.urandom(8).hex()))
        for extra in (self.user, self.password):
            if extra:
                body += mqtt_string(extra)
        sock.sendall(ws_frame(mqtt_packet(0x10, body)))                  # CONNECT
        return sock

    def _session(self, sock):
        sock.settimeout(0.1)
        last_rx = last_ping = time.monotonic()
        self.got_connack = False
        while True:
            if self.got_connack and self.resubscribe:
                self._subscribe(sock)
            # 1. Senden, was in der Warteschlange liegt
            while True:
                try:
                    packet = self.outbox.get_nowait()
                except queue.Empty:
                    break
                sock.sendall(ws_frame(packet))
            if not self.running:
                sock.sendall(ws_frame(mqtt_packet(0xE0, b"")))           # DISCONNECT
                return
            # 2. Lebenszeichen, damit der Vermittler (und jedes NAT) die Verbindung offen hält
            t = time.monotonic()
            if t - last_ping > self.keepalive / 2:
                sock.sendall(ws_frame(mqtt_packet(0xC0, b"")))           # PINGREQ
                last_ping = t
            if t - last_rx > self.keepalive * 1.5:
                raise OSError("keine Antwort vom Vermittler")
            # 3. Empfangen
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise OSError("Verbindung beendet")
            last_rx = time.monotonic()
            self.rbuf += chunk
            while True:
                frame = ws_parse(self.rbuf)
                if not frame:
                    break
                op, data, self.rbuf = frame
                if op == 0x8:
                    raise OSError("Vermittler hat die Verbindung geschlossen")
                if op == 0x9:
                    sock.sendall(ws_frame(data, opcode=0xA))             # Ping -> Pong
                elif op in (0x0, 0x1, 0x2):
                    self.mbuf += data
            while True:
                packet = mqtt_parse(self.mbuf)
                if not packet:
                    break
                first, body, self.mbuf = packet
                self._on_packet(sock, first, body)

    def _subscribe(self, sock):
        self.resubscribe = False
        self.packet_id = self.packet_id % 65535 + 1
        filters = b"".join(mqtt_string(t) + b"\x00" for t in list(self.topics))  # QoS 0
        sock.sendall(ws_frame(mqtt_packet(0x82, struct.pack("!H", self.packet_id) + filters)))

    def _on_packet(self, sock, first, body):
        kind = first >> 4
        if kind == 2:                                                     # CONNACK
            if len(body) < 2 or body[1] != 0:
                raise OSError("Vermittler lehnt Anmeldung ab (Code %s)" % (body[1:2].hex() or "?"))
            self.got_connack = True
            self._subscribe(sock)
        elif kind == 9:                                                   # SUBACK
            if not self.connected:
                self.connected = True
                self.log("Internet verbunden (%s)" % self.host)
                self.on_state(True)
        elif kind == 3 and self.connected:                                # PUBLISH
            qos = (first >> 1) & 3
            n = struct.unpack("!H", body[:2])[0]
            topic = body[2:2 + n].decode("utf-8", "replace")
            payload = body[2 + n + (2 if qos else 0):]
            try:
                self.on_message(topic, payload)
            except Exception as e:      # ein Paket darf nie alles stoppen
                self.log("Fehler bei Internet-Paket: %s" % e)


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

        def fill_menu():                         # bei jedem Öffnen neu (Erweiterung, TEIL 8)
            menu.delete(0, "end")
            menu.add_command(label="Fenster öffnen", command=app.show_window)
            menu.add_command(label="Status wechseln", command=app.toggle_status)
            if app.ext_visible():
                menu.add_separator()
                for button_id, text, fn in app.ext_buttons:
                    menu.add_command(label=text, command=lambda f=fn: app.ext_call(f))
            menu.add_separator()
            menu.add_command(label="Beenden", command=app.quit)
        menu.configure(postcommand=fill_menu)
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
        self.last_state = None
        self.request_info = ""         # z.B. "Kein Coach online."
        # Internet-Weg: None = aus, sonst True/False = verbunden/getrennt
        self.internet = None if net.relay is None else False
        self.extension = None          # Name der geladenen Erweiterung (TEIL 8)
        self.ext_buttons = []          # [(id, text, fn)]
        self.ext_info = []
        # Erweiterung ausgeblendet? (Knopf 🙈, Strg+Umschalt+P, --erweiterung-umschalten)
        self.ext_hidden = bool(store.get("erweiterung_versteckt")) if store else False

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
        root.bind_all("<Control-P>", lambda e: self.ext_toggle_hidden())     # Strg+Umschalt+P

        self.mini = MiniBar(self) if view == "mini" else None
        if start_hidden and view != "fenster":
            self.hide_window()

        root.after(100, self._poll)
        root.after(1000, self._tick)
        self._update_small_views()

    # ---- Aufbau -------------------------------------------------------------
    def _build(self):
        top = self.top_frame = tk.Frame(self.root, bg=BG, padx=12, pady=10)
        top.pack(fill="x")
        info = tk.Frame(top, bg=BG)
        info.pack(side="left")
        name_label = tk.Label(info, text="%s (%s)" % (self.me["name"], ROLE_TEXT[self.me["role"]]),
                              font=("TkDefaultFont", 12, "bold"), bg=BG)
        name_label.pack(anchor="w")
        # Geheim: 3x schnell auf den Namen -> Erweiterung aus-/einblenden (wie im Panel)
        name_label.bind("<Triple-Button-1>", lambda e: self.ext_toggle_hidden())
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

        # Knöpfe einer Erweiterung (TEIL 8), erst sichtbar, wenn es welche gibt
        self.ext_frame = tk.Frame(self.root, bg=BG, padx=12, pady=6)

        ttk.Separator(self.root).pack(fill="x")
        bottom = tk.Frame(self.root, bg=BG, padx=12, pady=10)
        bottom.pack(fill="x")
        if self.me["role"] == "student":
            self._build_student(bottom)
        else:
            self._build_coach(bottom)
        self._render_peers()

    # ---- Erweiterung (TEIL 8) ---------------------------------------------------
    def ext_add_button(self, button_id, text, fn):
        self.ext_buttons = [b for b in self.ext_buttons if b[0] != button_id] + [(button_id, text, fn)]
        self._render_ext()

    def ext_set_info(self, lines):
        if lines != self.ext_info:
            self.ext_info = lines
            self._render_ext()

    def ext_call(self, fn, *args):
        try:
            fn(*args)
        except Exception as e:                   # Fehler der Erweiterung: App läuft weiter
            print("Fehler in der Erweiterung: %s: %s" % (type(e).__name__, e))

    def ext_click(self, button_id):
        for b in self.ext_buttons:
            if b[0] == button_id:
                self.ext_call(b[2])

    def ext_visible(self):
        return bool(self.ext_buttons or self.ext_info) and not self.ext_hidden

    def ext_toggle_hidden(self):
        """Erweiterung schnell aus- und wieder einblenden. Gespeichert, damit sie
        auch nach einem Neustart versteckt bleibt. Meldungen kommen weiterhin."""
        self.ext_hidden = not self.ext_hidden
        if self.store:
            self.store.set("erweiterung_versteckt", self.ext_hidden)
        self._render_ext()
        self._update_small_views()

    def _render_ext(self):
        for w in self.ext_frame.winfo_children():
            w.destroy()
        if not self.ext_visible():
            self.ext_frame.pack_forget()
            return
        if not self.ext_frame.winfo_ismapped():
            self.ext_frame.pack(fill="x", after=self.top_frame)   # gleich unter dem Kopf
        for line in self.ext_info:
            tk.Label(self.ext_frame, text=line, bg=BG, fg="#b45309", anchor="w", justify="left",
                     wraplength=380).pack(fill="x")
        row = tk.Frame(self.ext_frame, bg=BG)
        row.pack(fill="x", pady=(4, 0))
        # Verstecken geht geheim: 3x auf den Namen klicken oder Strg+Umschalt+P
        # (kein sichtbarer Knopf, damit der Coach nichts bemerkt).
        buttons = [(text, lambda f=fn: self.ext_call(f)) for _, text, fn in self.ext_buttons]
        for i, (text, fn) in enumerate(buttons):
            ColorButton(row, text, fn, bg="#eeeeee", hover="#e0e0e0",
                        padx=8, pady=3).grid(row=i // 3, column=i % 3, sticky="we", padx=2, pady=2)
        for c in range(3):
            row.grid_columnconfigure(c, weight=1)
        self._update_small_views()

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

    def ask_for_help(self, text=None, show=True):
        if self.me["role"] != "student":
            return
        coaches = [p for p in self.peers.values()
                   if p["role"] == "coach" and self._shown_status(p) != "offline" and p["ip"]]
        if not coaches:
            self._show_request_info("Kein Coach online.")
            if text is not None and show:   # von der kleinen Leiste: Fenster zeigen
                self.show_window()
            self._update_small_views()
            return
        self.request_info = ""
        if text is None:
            text = self.help_text.get().strip()
            self.help_text.delete(0, "end")
        text = text[:MAX_TEXT]
        self.requests.clear()          # nur die neueste Anfrage anzeigen
        for c in coaches:              # jedem Coach einzeln, jeder bestätigt selbst
            help_id = self.net.send_help(c["ip"], c["port"], text, c.get("peer_id"))
            self.requests[help_id] = {"coach": c["name"], "state": "sending", "tries": 1}
        self._render_requests()
        self._update_small_views()

    def mark_done(self, help_id):
        for item in self.queue:
            if item["help_id"] == help_id:
                self.queue.remove(item)
                self.net.send_done(item["ip"], item["port"], help_id, item.get("peer_id"))
                break
        self._render_queue()
        self._update_small_views()

    def remove_peer(self, peer_id, ask=True):
        """Jemanden aus der gespeicherten Klassenliste entfernen."""
        p = self.peers.get(peer_id)
        if p and (not ask or messagebox.askyesno("Entfernen", "%s aus der Klassenliste entfernen?" % p["name"],
                                                 parent=self.root)):
            del self.peers[peer_id]
            if self.store:
                self.store.forget(self.room, peer_id)
            self._render_peers()
            self._update_small_views()

    def copy_code(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(format_code(self.code))
        self.class_label.configure(text="Code kopiert ✓")
        self.root.after(1500, self._update_class_label)

    def quit(self):
        if self.view == "waybar":
            write_waybar("<span color='%s'>●</span>" % COLORS["offline"], "offline",
                         "Klassenzimmer läuft nicht")
            try:
                state_file().unlink()
            except OSError:
                pass
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
                    arg = ev[2] if len(ev) > 2 else ""
                    if ev[1] == "hilfe":
                        self.ask_for_help(arg, show=False)
                    elif ev[1] == "erledigt":
                        self.mark_done(arg)
                    elif ev[1] == "entfernen":
                        self.remove_peer(arg, ask=False)
                    elif ev[1] == "erweiterung":
                        self.ext_click(arg)
                    else:
                        {"show": self.show_window, "toggle": self.toggle_window,
                         "status": self.toggle_status, "quit": self.quit,
                         "erweiterung-umschalten": self.ext_toggle_hidden}[ev[1]]()
                    if ev[1] == "quit":
                        return
                elif kind == "internet":
                    self.internet = ev[1]
                    changed.add("peers")
                elif kind == "ext":
                    self.ext_call(ev[1], ev[2])
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
        # Übers Internet melden sich alle seltener (RELAY_HEARTBEAT), also später grau
        limit = OFFLINE_AFTER_INTERNET if peer.get("ip") == RELAY_IP else OFFLINE_AFTER
        if peer["last_seen"] is None or time.monotonic() - peer["last_seen"] > limit:
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
        if self.view == "waybar":
            full = self._full_state()
            if full != self.last_state:
                self.last_state = full
                write_state(full)

    def _peer_order(self, p):
        # Coaches zuerst, dann wer da ist, dann nach Name
        return (p["role"] != "coach", self._shown_status(p) == "offline", p["name"].lower())

    def _full_state(self):
        """Alles, was ein Leisten-Panel zum Anzeigen braucht (siehe state_file)."""
        return {
            "version": APP_VERSION,
            "name": self.me["name"],
            "role": self.me["role"],
            "status": self.me["status"],
            "klasse": self._class_name(),
            "code": format_code(self.code),
            "peers": [{"id": p["peer_id"], "name": p["name"], "role": p["role"],
                       "status": self._shown_status(p)}
                      for p in sorted(self.peers.values(), key=self._peer_order)],
            "searching_long": not self.peers and time.monotonic() - self.started > 15,
            "queue": [{"id": q["help_id"], "name": q["name"], "text": q["text"], "time": q["time"]}
                      for q in self.queue],
            "requests": [{"coach": r["coach"], "state": r["state"], "tries": r["tries"]}
                         for r in self.requests.values()],
            "max_tries": MAX_TRIES,
            "info": self.request_info,
            "internet": self.internet,
            **({"extra": {"title": self.extension,
                          "buttons": [{"id": b[0], "text": b[1]} for b in self.ext_buttons],
                          "info": self.ext_info}} if self.ext_visible() else {}),
        }

    def _render_peers(self):
        for w in self.peer_frame.winfo_children():
            w.destroy()
        if not self.peers:
            hint = "Noch niemand gefunden …"
            if time.monotonic() - self.started > 15:
                hint += "\nStimmt der Code? Haben alle Version %s?" % APP_VERSION
                if self.internet is False:
                    hint += "\nInternet-Weg: keine Verbindung (nur WLAN)"
            tk.Label(self.peer_frame, text=hint, fg="#777", bg=BG, justify="left").pack(anchor="w")
            return
        for p in sorted(self.peers.values(), key=self._peer_order):
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
        self.request_info = text
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
# TEIL 8: Erweiterungen
# ===========================================================================
# Wer mehr Knöpfe will, legt eine Datei erweiterung.py in den Einstellungs-Ordner
# (neben einstellungen.json, siehe TEIL 2). Gibt es sie, lädt die App sie beim
# Start und ruft setup(api) auf. Ohne Datei passiert nichts. Eine kaputte
# Erweiterung stoppt die App nicht, sie wird nur nicht geladen.
#
# Was eine Erweiterung mit api machen kann:
#   api.me, api.key, api.lib     wer bin ich, Schlüssel der Klasse, dieses Modul
#   api.button(id, text, fn)     Knopf im Fenster, im Menü der kleinen Leiste und
#                                im Leisten-Panel (klassenzimmer --erweiterung ID)
#   api.info(zeilen)             Textzeilen dazu (z.B. ein Countdown)
#   api.notify(titel, text, dringend=False)   Meldung auf dem Bildschirm
#   api.listen(thema, fn)        rohe Pakete empfangen, fn(daten) im Hauptthread
#   api.send(thema, daten)       rohe Pakete an alle (WLAN und Internet)
#   api.every(sekunden, fn)      regelmässig etwas tun (im Hauptthread)
# Die App liest die Pakete nicht: Verschlüsseln und Signieren macht die
# Erweiterung selbst (z.B. mit api.lib.seal und einem eigenen Schlüssel).
#
# Achtung: Eine Erweiterung ist Python-Code und darf alles, was die App darf.
# Nur Dateien aus einer Quelle benutzen, der man vertraut.

EXTENSION_FILE = "erweiterung.py"
EXTENSION_ENV = "KLASSENZIMMER_ERWEITERUNG"      # anderer Pfad (z.B. zum Testen)


def extension_path():
    """Wo liegt die Erweiterung? Zuerst KLASSENZIMMER_ERWEITERUNG, dann der
    Einstellungs-Ordner, dann eine ins Programm eingebaute (PyInstaller --add-data)."""
    p = os.environ.get(EXTENSION_ENV)
    if p:
        return Path(p)
    own = config_dir() / EXTENSION_FILE
    bundled = Path(getattr(sys, "_MEIPASS", "")) / EXTENSION_FILE if getattr(sys, "frozen", False) else None
    if not own.is_file() and bundled and bundled.is_file():
        return bundled
    return own


def notify(title, text, urgent=False, root=None):
    """Meldung auf dem Bildschirm: Linux notify-send, Mac Mitteilung,
    sonst (Windows) ein kleines Fenster, das immer im Vordergrund ist."""
    try:
        if SYSTEM == "Linux" and shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "Klassenzimmer", "-u", "critical" if urgent else "normal",
                              title, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if SYSTEM == "Darwin":
            script = "display notification %s with title %s" % (json.dumps(text), json.dumps(title))
            subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    except OSError:
        pass
    if root is None:
        return
    w = tk.Toplevel(root, bg=ORANGE if urgent else "#333", padx=14, pady=10)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    tk.Label(w, text=title, bg=w["bg"], fg="white", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
    tk.Label(w, text=text, bg=w["bg"], fg="white", justify="left", wraplength=320).pack(anchor="w")
    w.update_idletasks()
    w.geometry("+%d+%d" % (w.winfo_screenwidth() - w.winfo_reqwidth() - 30, 80))
    w.bind("<Button-1>", lambda e: w.destroy())
    w.after(12000, w.destroy)


class ExtensionAPI:
    def __init__(self, app, net):
        self._app, self._net = app, net
        self.me, self.key = app.me, net.key
        self.lib = sys.modules[__name__]

    def button(self, button_id, text, fn):
        self._app.ext_add_button(clean_text(button_id, 30), clean_text(text, 40), fn)

    def info(self, lines):
        self._app.ext_set_info([clean_text(line, 120) for line in lines][:6])

    def notify(self, title, text, urgent=False):
        notify(clean_text(title, 80), clean_text(text, 300), urgent, self._app.root)
        if urgent:
            self._app.root.bell()

    def listen(self, topic, fn):
        # Netzwerk-Thread -> Queue -> Hauptthread (tkinter-Regel, siehe TEIL 6)
        self._net.listen_raw(topic, lambda data: self._app.events.put(("ext", fn, data)))

    def send(self, topic, data):
        self._net.send_raw(topic, data)

    def every(self, seconds, fn):
        def run():
            self._app.ext_call(fn)
            self._app.root.after(int(seconds * 1000), run)
        self._app.root.after(int(seconds * 1000), run)


def load_extension(app, net, path=None):
    """erweiterung.py laden und setup(api) aufrufen. Gibt den Namen zurück oder None."""
    path = Path(path) if path else extension_path()
    if not path.is_file():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("klassenzimmer_erweiterung", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.setup(ExtensionAPI(app, net))
    except Exception as e:                       # kaputte Erweiterung: App läuft weiter
        print("Erweiterung %s nicht geladen: %s: %s" % (path, type(e).__name__, e))
        return None
    name = getattr(module, "NAME", path.stem)
    print("Erweiterung geladen: %s" % name)
    return name


def self_test(report_file=""):
    """Ohne Fenster prüfen, ob das fertige Programm funktioniert (für GitHub
    Actions nach dem Bauen und zur Fehlersuche): Zertifikate, Internet-Weg
    hin und zurück, Erweiterung. Exit-Code 0 = alles gut. Unter Windows hat das
    Programm keine Konsole, darum geht der Bericht auch in eine Datei."""
    lines, ok = ["Klassenzimmer %s auf %s" % (APP_VERSION, SYSTEM)], True
    url = os.environ.get("KLASSENZIMMER_INTERNET", RELAY_URL).strip()
    try:
        relay = Relay(url)
        topic = relay_topics(derive_key(new_code()), new_id())[0]
        marker = os.urandom(16)
        connected, echoed, errors = threading.Event(), threading.Event(), []
        relay.start([topic], lambda t, p: echoed.set() if p == marker else None,
                    lambda c: connected.set() if c else None, log=errors.append)
        t0 = time.monotonic()
        if connected.wait(30):
            relay.publish(topic, marker)
            if echoed.wait(10):
                lines.append("Internet-Weg: ok (%s, %d ms)" % (relay.host, (time.monotonic() - t0) * 1000))
            else:
                ok = False
                lines.append("Internet-Weg: verbunden, aber nichts zurückbekommen")
        else:
            ok = False
            lines.append("Internet-Weg: FEHLER %s" % ("; ".join(errors[-3:]) or "keine Verbindung"))
        relay.stop()
    except ValueError as e:
        ok = False
        lines.append("Internet-Weg: %s" % e)
    path = extension_path()
    if path.is_file():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("klassenzimmer_erweiterung", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not callable(getattr(module, "setup", None)):
                raise ValueError("setup(api) fehlt")
            lines.append("Erweiterung: %s ok (%s)" % (getattr(module, "NAME", path.stem), path))
        except Exception as e:
            ok = False
            lines.append("Erweiterung: FEHLER %s: %s" % (type(e).__name__, e))
    else:
        lines.append("Erweiterung: keine")
    lines.append("Ergebnis: %s" % ("OK" if ok else "FEHLER"))
    text = "\n".join(lines)
    try:
        print(text)                    # unter Windows (--windowed) gibt es keine Konsole
    except (OSError, ValueError, AttributeError):
        pass
    if report_file:
        Path(report_file).write_text(text + "\n", encoding="utf-8")
    return 0 if ok else 1


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
    parser.add_argument("--hilfe", nargs="?", const="", metavar="TEXT",
                        help="Schüler: der laufenden App sagen, den Coach um Hilfe zu fragen")
    parser.add_argument("--erledigt", metavar="ID", help="Coach: Hilfeanfrage als erledigt markieren")
    parser.add_argument("--entfernen", metavar="ID", help="jemanden aus der Klassenliste entfernen")
    parser.add_argument("--erweiterung", metavar="ID", help="Knopf einer Erweiterung drücken (TEIL 8)")
    parser.add_argument("--erweiterung-umschalten", action="store_true",
                        help="Knöpfe der Erweiterung aus- bzw. wieder einblenden")
    parser.add_argument("--selbsttest", nargs="?", const="", metavar="DATEI",
                        help="ohne Fenster prüfen, ob Internet-Weg und Erweiterung gehen (Bericht in DATEI)")
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
    parser.add_argument("--ohne-internet", action="store_true",
                        help="nur im WLAN suchen, nicht übers Internet (TEIL 5b)")
    parser.add_argument("--version", action="version", version="Klassenzimmer " + APP_VERSION)
    args = parser.parse_args()

    if args.waybar_einrichten:
        print(setup_waybar())
        return
    if args.code and args.code.strip().upper() == "NEU":
        args.code = new_code()
        print("Neuer Beitrittscode: %s" % format_code(args.code))

    if args.selbsttest is not None:
        sys.exit(self_test(args.selbsttest))
    command = "toggle" if args.zeigen else "status" if args.status_umschalten else \
              "quit" if args.beenden else "erweiterung-umschalten" if args.erweiterung_umschalten else None
    command_arg = None
    for name, value in (("hilfe", args.hilfe), ("erledigt", args.erledigt),
                        ("entfernen", args.entfernen), ("erweiterung", args.erweiterung)):
        if value is not None:
            command, command_arg = name, value

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
            if send_control(command or "show", command_arg):
                return
            if command:
                print("Klassenzimmer läuft nicht.")
                return
            # Ein fremdes Programm benutzt den Port -> ohne Steuerung weitermachen
            print("Port %d ist von einem anderen Programm belegt – "
                  "'nur einmal starten' und Waybar-Klicks funktionieren nicht." % CONTROL_PORT)
            control = None
        elif command in ("status", "quit", "erweiterung-umschalten") + ARG_COMMANDS:
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
    # Internet-Weg: an, ausser --ohne-internet oder KLASSENZIMMER_INTERNET=aus.
    # Mit KLASSENZIMMER_INTERNET=wss://… geht es über einen anderen Vermittler.
    relay_url = os.environ.get("KLASSENZIMMER_INTERNET", RELAY_URL).strip()
    relay = None
    if not args.ohne_internet and relay_url.lower() not in ("", "aus", "0", "nein", "off"):
        try:
            relay = Relay(relay_url)
        except ValueError as e:
            print(e)
    net = Network(me, events, key, broadcast_addr=args.broadcast, loss=args.verlust,
                  port=port, port_fallback=not args.port, relay=relay)
    try:
        net.start()
    except OSError as e:
        show_message("Klassenzimmer", "Netzwerk konnte nicht gestartet werden:\n%s" % e, error=True)
        return

    view = args.ansicht or ("fenster" if test_mode else "waybar" if is_hyprland() else "mini")
    root = tk.Tk()
    app = App(root, me, net, events, room_id(key), code, store, view=view,
              start_hidden=args.autostart or args.speichern, control=control)
    # Erweiterung: normal aus dem Einstellungs-Ordner, im Testmodus nur mit KLASSENZIMMER_ERWEITERUNG
    if store or os.environ.get(EXTENSION_ENV):
        app.extension = load_extension(app, net)
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
