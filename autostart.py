"""
Autostart: Die App startet automatisch, wenn man sich am Computer anmeldet.

Jedes Betriebssystem macht das anders:
  Windows: ein Eintrag in der Registry unter
           HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
  macOS:   eine kleine .plist-Datei in ~/Library/LaunchAgents
  Linux:   eine .desktop-Datei in ~/.config/autostart

Ausserdem speichern wir Name und Rolle in einer Einstellungsdatei,
damit die App beim Autostart nicht nachfragen muss.
"""

import json
import os
import platform
import plistlib
import sys
from pathlib import Path

SYSTEM = platform.system()
APP_ID = "klassenzimmer"
MAC_LABEL = "ch.klassenzimmer.app"


# ---------------------------------------------------------------------------
# Einstellungen (Name, Rolle) speichern und laden
# ---------------------------------------------------------------------------
def config_dir():
    if SYSTEM == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif SYSTEM == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_ID


def load_settings():
    try:
        with open(config_dir() / "einstellungen.json", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "einstellungen.json", "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Wie wird die App gestartet?
# ---------------------------------------------------------------------------
def start_command():
    """Befehl (als Liste), der die App startet – mit --autostart.

    Als fertiges Programm (mit PyInstaller gebaut) ist sys.frozen gesetzt,
    dann ist sys.executable die App selbst. Sonst starten wir main.py mit
    dem aktuellen Python.
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        if SYSTEM == "Darwin" and ".app/Contents/MacOS/" in exe:
            # Mac: lieber das ganze .app-Paket öffnen
            app = exe.split(".app/Contents/MacOS/")[0] + ".app"
            return ["/usr/bin/open", "-a", app, "--args", "--autostart"]
        return [exe, "--autostart"]
    main_py = str(Path(__file__).resolve().parent / "main.py")
    python = sys.executable
    if SYSTEM == "Windows" and python.lower().endswith("python.exe"):
        # pythonw.exe startet ohne schwarzes Konsolenfenster
        candidate = python[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(candidate):
            python = candidate
    return [python, main_py, "--autostart"]


def _quote_windows(args):
    return " ".join('"%s"' % a if " " in a else a for a in args)


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _win_set(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _quote_windows(start_command()))
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass


def _win_get():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_ID)
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------
def _mac_file():
    return Path.home() / "Library" / "LaunchAgents" / (MAC_LABEL + ".plist")


def mac_plist(cmd):
    """Inhalt der LaunchAgent-Datei. RunAtLoad = beim Anmelden starten."""
    return plistlib.dumps({"Label": MAC_LABEL, "ProgramArguments": cmd, "RunAtLoad": True})


# ---------------------------------------------------------------------------
# Linux (funktioniert mit GNOME, KDE, XFCE … und Omarchy/Hyprland über uwsm)
# ---------------------------------------------------------------------------
def _linux_file():
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / (APP_ID + ".desktop")


def linux_desktop(cmd):
    def q(a):  # Argumente mit Leerzeichen in Anführungszeichen
        return '"%s"' % a.replace('"', '\\"') if (" " in a or '"' in a) else a
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Klassenzimmer\n"
        "Comment=Peer-to-Peer-App fürs Klassenzimmer\n"
        "Exec=%s\n"
        "X-GNOME-Autostart-enabled=true\n" % " ".join(q(a) for a in cmd)
    )


# ---------------------------------------------------------------------------
# Für alle Systeme
# ---------------------------------------------------------------------------
def is_enabled():
    try:
        if SYSTEM == "Windows":
            return _win_get()
        if SYSTEM == "Darwin":
            return _mac_file().exists()
        return _linux_file().exists()
    except Exception:
        return False


def set_enabled(enabled):
    """Autostart ein- oder ausschalten. Gibt eine Fehlermeldung oder None zurück."""
    try:
        if SYSTEM == "Windows":
            _win_set(enabled)
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
    except Exception as e:  # z.B. keine Schreibrechte
        return "Autostart konnte nicht geändert werden: %s" % e
