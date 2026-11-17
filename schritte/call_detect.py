"""
Zusatz: Erkennen, ob man gerade in einem (Teams-)Call ist

Idee: Wer in einem Call ist, benutzt das Mikrofon. Das Betriebssystem
weiss, welches Programm gerade das Mikrofon offen hat – das fragen wir ab.

  Windows: Windows merkt sich in der Registry für jedes Programm, wann es
           das Mikrofon zuletzt benutzt hat (LastUsedTimeStart/Stop).
           Ist "Stop" = 0, benutzt das Programm das Mikrofon GERADE.
           (Das ist dieselbe Info, die das Mikrofon-Symbol in der
           Taskleiste anzeigt.)
  Linux:   Wir fragen PulseAudio/PipeWire mit "pactl list source-outputs",
           welche Programme gerade aufnehmen.
  macOS:   Geht nicht ohne Zusatz-Bibliotheken -> None (unbekannt).

Rückgabe von is_in_call():
  True  = im Call
  False = nicht im Call
  None  = kann man auf diesem System nicht erkennen

Selber testen:  python3 call_detect.py
(zeigt alle 2 Sekunden an, ob ein Call erkannt wird)
"""

import platform
import shutil
import subprocess

SYSTEM = platform.system()   # "Windows", "Linux" oder "Darwin" (= macOS)


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def _windows_mic_users():
    """Liste der Programme, die GERADE das Mikrofon benutzen (Windows)."""
    import winreg  # gibt es nur unter Windows, darum erst hier importieren

    users = []

    def walk(key_path):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            return
        with key:
            # Wert dieses Schlüssels lesen
            try:
                start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
                stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
                if start and stop == 0:           # gestartet, aber nicht beendet
                    users.append(key_path.rsplit("\\", 1)[-1])
            except OSError:
                pass
            # Unterschlüssel durchgehen (z.B. "NonPackaged" für normale Programme)
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                walk(key_path + "\\" + sub)
                i += 1

    walk(MIC_KEY)
    return users


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------
def parse_pactl(text):
    """Liest aus der Ausgabe von 'pactl list source-outputs' die Programmnamen.

    Ein Eintrag sieht ungefähr so aus:
        Source Output #57
                ...
                Properties:
                        application.name = "Chromium"
                        application.process.binary = "chromium"
    """
    users = []
    current = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Source Output #"):
            current = {}
            users.append(current)
        elif current is not None and " = " in line:
            k, v = line.split(" = ", 1)
            current[k] = v.strip().strip('"')
    names = []
    for u in users:
        name = u.get("application.name") or u.get("application.process.binary") or "?"
        # Pegel-Anzeigen (z.B. von der Lautstärke-Einstellung) sind kein Call
        if u.get("application.id") == "org.PulseAudio.pavucontrol":
            continue
        names.append(name)
    return names


def _linux_mic_users():
    if not shutil.which("pactl"):
        return None
    try:
        out = subprocess.run(["pactl", "list", "source-outputs"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_pactl(out)


# ---------------------------------------------------------------------------
# Für alle Systeme
# ---------------------------------------------------------------------------
def mic_users():
    """Welche Programme benutzen gerade das Mikrofon? None = unbekannt."""
    try:
        if SYSTEM == "Windows":
            return _windows_mic_users()
        if SYSTEM == "Linux":
            return _linux_mic_users()
    except Exception:  # Erkennung darf die App nie zum Absturz bringen
        return None
    return None  # macOS und andere


def is_in_call(only_teams=False):
    """True/False/None (siehe oben).

    only_teams=True: nur Teams zählt (unter Windows mit der Teams-App).
    Unter Linux läuft Teams im Browser – dort sieht man nur "Chromium"
    oder "Firefox", darum zählt dort jede Mikrofon-Benutzung.
    """
    users = mic_users()
    if users is None:
        return None
    if only_teams and SYSTEM == "Windows":
        users = [u for u in users if "teams" in u.lower()]
    return len(users) > 0


if __name__ == "__main__":
    import time
    print("System:", SYSTEM)
    print("Starte oder beende einen Call und schau zu. Beenden mit Ctrl+C.\n")
    try:
        while True:
            users = mic_users()
            if users is None:
                print("Auf diesem System kann ich das nicht erkennen.")
                break
            if users:
                print(time.strftime("%H:%M:%S"), " IM CALL  – Mikrofon benutzt von:", ", ".join(users))
            else:
                print(time.strftime("%H:%M:%S"), " kein Call")
            time.sleep(2)
    except KeyboardInterrupt:
        pass
