#!/usr/bin/env bash
# Klassenzimmer: Installation für Linux mit einem einzigen Befehl.
# Für Ubuntu, Debian, Mint, Pop!_OS, Fedora, Arch, Manjaro, openSUSE … auf 64-Bit-Intel/AMD.
#
#   curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-linux.sh | bash
#
# Ohne Angaben geht danach das Startfenster auf (Name, Rolle, Code).
# Mit Angaben wird alles ohne Fenster eingerichtet (praktisch für Claude):
#
#   ... | bash -s -- --name "Lena" --role student --code K7Q-M3X
#   ... | bash -s -- --name "Herr Muster" --role coach --klasse INF3a --code NEU
#
# Was passiert:
#   1. neueste Version herunterladen nach ~/.local/bin/klassenzimmer
#   2. eine laufende Klassenzimmer-App beenden (Update)
#   3. Firewall freigeben: UDP-Ports 50505-50506 (nur wenn ufw oder firewalld aktiv ist)
#   4. Eintrag im App-Menü anlegen
#   5. einrichten (Autostart beim Anmelden) und im Hintergrund starten
#
# Nochmal ausführen = aktualisieren (Name, Rolle und Code bleiben).
# Entfernen: ... | bash -s -- --entfernen

set -eu

REPO="c1llsh0t/Klassen-Status"
URL="https://github.com/$REPO/releases/latest/download/Klassenzimmer-Linux"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/klassenzimmer"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/klassenzimmer"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/klassenzimmer"
MENU_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/klassenzimmer.desktop"
AUTOSTART_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/klassenzimmer.desktop"
CONTROL_PORT="${KLASSENZIMMER_STEUERPORT:-50507}"
CODE_ALPHABET="ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# Alles in einem Block: Bei "curl ... | bash" liest Bash so erst das ganze Skript,
# bevor etwas ausgeführt wird (kein Befehl kann dann Teile davon verschlucken).
{

NAME="" ROLE="" CODE="" KLASSE=""
FIREWALL=1 START=1 REMOVE=0

# --- Ausgabe -------------------------------------------------------------------
if [ -t 1 ]; then B=$'\033[1m' G=$'\033[1;32m' Y=$'\033[1;33m' R=$'\033[1;31m' N=$'\033[0m'; else B="" G="" Y="" R="" N=""; fi
say()  { printf '%s==>%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s!!  %s%s\n' "$Y" "$*" "$N" >&2; }
die()  { printf '%sFehler:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Klassenzimmer für Linux installieren oder aktualisieren.

  install-linux.sh                              danach Startfenster (Name, Rolle, Code)
  install-linux.sh --name NAME --role student --code K7Q-M3X
  install-linux.sh --name NAME --role coach --klasse INF3a --code NEU

Optionen:
  --name NAME         dein Name
  --role ROLLE        student oder coach
  --code CODE         Beitrittscode (6 Zeichen), Coach: NEU = neuen erzeugen
  --klasse KLASSE     Klassenname (nur Coach)
  --ohne-firewall     Firewall nicht anfassen
  --nicht-starten     nur installieren, nicht einrichten und nicht starten
  --entfernen         Klassenzimmer wieder entfernen
  -h, --help          diese Hilfe
EOF
}

# --- Optionen ------------------------------------------------------------------
need() { [ $# -ge 2 ] && [ -n "$2" ] || die "$1 braucht einen Wert (Hilfe: --help)"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --name)    need "$@"; NAME=$2; shift 2 ;;
    --name=*)  NAME=${1#*=}; shift ;;
    --role|--rolle)     need "$@"; ROLE=$2; shift 2 ;;
    --role=*|--rolle=*) ROLE=${1#*=}; shift ;;
    --code)    need "$@"; CODE=$2; shift 2 ;;
    --code=*)  CODE=${1#*=}; shift ;;
    --klasse)  [ $# -ge 2 ] || die "--klasse braucht einen Wert"; KLASSE=$2; shift 2 ;;
    --klasse=*) KLASSE=${1#*=}; shift ;;
    --ohne-firewall) FIREWALL=0; shift ;;
    --nicht-starten) START=0; shift ;;
    --entfernen)     REMOVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unbekannte Option: $1 (Hilfe: --help)" ;;
  esac
done

# --- Hilfsfunktionen -----------------------------------------------------------
# Befehl als root ausführen. Gibt 1 zurück, wenn das nicht geht (kein sudo, kein Passwort).
as_root() {
  if [ "$(id -u)" = 0 ]; then "$@"; return; fi
  command -v sudo >/dev/null 2>&1 || return 1
  if sudo -n true 2>/dev/null; then sudo "$@"; return; fi
  if ( : </dev/tty ) 2>/dev/null; then sudo "$@" </dev/tty; return; fi
  sudo "$@" </dev/null   # ohne Terminal klappt das nur mit einem Passwort-Fenster (askpass)
}

# Läuft eine Klassenzimmer-App? (Sie hält den Steuer-Port auf 127.0.0.1.)
app_running() { (exec 3<>"/dev/tcp/127.0.0.1/$CONTROL_PORT") 2>/dev/null; }

stop_app() {
  local exe=$1
  app_running || return 0
  say "Laufende Klassenzimmer-App beenden"
  "$exe" --beenden >/dev/null 2>&1 || true
  for _ in $(seq 40); do app_running || return 0; sleep 0.1; done
  pkill -x klassenzimmer 2>/dev/null || true
  sleep 0.5
  app_running && warn "Die alte App läuft noch. Bitte von Hand beenden (⏻ in der App)."
  return 0
}

start_bg() {
  if command -v setsid >/dev/null 2>&1; then
    setsid "$@" </dev/null >>"$CACHE_DIR/start.log" 2>&1 &
  else
    nohup "$@" </dev/null >>"$CACHE_DIR/start.log" 2>&1 &
  fi
}

# 'k7q-m3x' -> 'K7QM3X' (leer, wenn ungültig)
clean_code() {
  local c
  c=$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]' | tr -cd 'A-Z0-9')
  [ ${#c} -eq 6 ] || return 0
  case "$c" in *[!$CODE_ALPHABET]*) return 0 ;; esac
  printf '%s' "$c"
}

# --- Grundchecks ---------------------------------------------------------------
[ "$(uname -s)" = Linux ] || die "Dieses Skript ist nur für Linux. Windows und Mac: siehe README."
[ "$(id -u)" != 0 ] || die "Bitte NICHT mit sudo starten, sondern als normaler Benutzer. Nach dem Passwort wird nur für die Firewall gefragt."

# --- Entfernen -----------------------------------------------------------------
if [ "$REMOVE" = 1 ]; then
  [ -x "$BIN" ] && stop_app "$BIN"
  rm -f "$BIN" "$MENU_FILE" "$AUTOSTART_FILE"
  rm -rf "$CACHE_DIR"
  say "Klassenzimmer entfernt (Programm, App-Menü, Autostart)."
  echo "    Deine Einstellungen liegen noch in $CONFIG_DIR (löschen: rm -r \"$CONFIG_DIR\")."
  echo "    Firewall-Regel entfernen (falls gesetzt): sudo ufw delete allow 50505:50506/udp"
  exit 0
fi

case "$(uname -m)" in
  x86_64|amd64) ;;
  *) die "Das fertige Programm gibt es nur für 64-Bit-Intel/AMD (x86_64), dein Rechner ist $(uname -m).
       Alternative mit Python: siehe README, Abschnitt 'Für Entwickler'." ;;
esac

if [ "$START" = 1 ] && [ -n "$NAME$ROLE$CODE$KLASSE" ]; then
  [ -n "$NAME" ] || die "--name fehlt (oder gar keine Angaben machen, dann kommt das Startfenster)."
  case "$ROLE" in
    student|coach) ;;
    "") die "--role fehlt: student oder coach" ;;
    *) die "--role muss student oder coach sein, nicht '$ROLE'" ;;
  esac
  if [ -z "$CODE" ]; then
    [ "$ROLE" = coach ] || die "Als Schüler brauchst du den Beitrittscode vom Coach: --code K7Q-M3X"
    CODE=NEU
  fi
  if [ "$(printf '%s' "$CODE" | tr '[:lower:]' '[:upper:]')" = NEU ]; then
    [ "$ROLE" = coach ] || die "Nur ein Coach kann einen neuen Code erzeugen. Frag deinen Coach nach dem Code."
    CODE=NEU
  else
    C=$(clean_code "$CODE")
    [ -n "$C" ] || die "Der Code '$CODE' stimmt nicht: 6 Zeichen aus A-Z (ohne I, L, O) und 2-9, z.B. K7Q-M3X"
    CODE=$C
  fi
fi

# --- 1. Herunterladen ----------------------------------------------------------
say "Neueste Version herunterladen"
mkdir -p "$BIN_DIR" "$CACHE_DIR"
NEW="$BIN_DIR/.klassenzimmer.neu"
trap 'rm -f "$NEW"' EXIT
if command -v curl >/dev/null 2>&1; then
  curl -fL --retry 3 --progress-bar -o "$NEW" "$URL" || die "Download fehlgeschlagen. Internet da?"
elif command -v wget >/dev/null 2>&1; then
  wget -q --show-progress -O "$NEW" "$URL" || die "Download fehlgeschlagen. Internet da?"
else
  die "Weder curl noch wget gefunden. Installiere eins davon (z.B. sudo apt install curl)."
fi
[ "$(head -c 4 "$NEW" | od -An -c | tr -d ' ')" = '177ELF' ] || die "Die heruntergeladene Datei ist kein Linux-Programm."
chmod 755 "$NEW"
VERSION=$("$NEW" --version 2>&1) || die "Das Programm startet nicht:
$VERSION"
echo "    $VERSION"

# --- 2. alte Version beenden, neue an ihren Platz -------------------------------
stop_app "$NEW"
mv -f "$NEW" "$BIN"      # umbenennen klappt auch, wenn die alte Datei noch benutzt wird
trap - EXIT
echo "    installiert: $BIN"

# --- 3. Firewall ---------------------------------------------------------------
if [ "$FIREWALL" = 1 ]; then
  FW_SHOW="" FW_OK=1
  if command -v ufw >/dev/null 2>&1 && grep -qs '^ENABLED=yes' /etc/ufw/ufw.conf; then
    say "Firewall (ufw) freigeben: UDP 50505-50506 (fragt evtl. nach deinem Passwort)"
    FW_SHOW="sudo ufw allow 50505:50506/udp"
    as_root ufw allow 50505:50506/udp >/dev/null 2>&1 || FW_OK=0
  elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
    say "Firewall (firewalld) freigeben: UDP 50505-50506 (fragt evtl. nach deinem Passwort)"
    FW_SHOW="sudo firewall-cmd --permanent --add-port=50505-50506/udp && sudo firewall-cmd --reload"
    { as_root firewall-cmd --permanent --add-port=50505-50506/udp && as_root firewall-cmd --reload; } >/dev/null 2>&1 || FW_OK=0
  else
    say "Firewall: keine aktive Firewall gefunden, nichts zu tun"
  fi
  if [ "$FW_OK" = 0 ]; then
    warn "Firewall nicht freigegeben (kein Passwort möglich). Bitte selbst im Terminal eingeben:"
    printf '\n    %s%s%s\n\n' "$B" "$FW_SHOW" "$N" >&2
  fi
fi

# --- 4. App-Menü ---------------------------------------------------------------
mkdir -p "$(dirname "$MENU_FILE")"
cat >"$MENU_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Klassenzimmer
GenericName=Klassen-Status
Comment=Sehen, wer in der Klasse online ist, und den Coach um Hilfe fragen
Exec="$BIN"
Icon=applications-education
Terminal=false
Categories=Education;Network;
Keywords=Klasse;Schule;Coach;Hilfe;
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$(dirname "$MENU_FILE")" >/dev/null 2>&1 || true
say "Eintrag im App-Menü: Klassenzimmer"

# --- 5. Einrichten und starten -------------------------------------------------
if [ "$START" = 0 ]; then
  say "${G}Fertig.${N} Starten: Klassenzimmer im App-Menü öffnen."
  exit 0
fi
if [ -z "${DISPLAY:-}" ]; then
  say "${G}Installiert.${N} Kein Bildschirm gefunden (z.B. über SSH): Klassenzimmer am Rechner im App-Menü starten."
  exit 0
fi

: >"$CACHE_DIR/start.log"
SETTINGS="$CONFIG_DIR/einstellungen.json"
MARK="$CACHE_DIR/.vor-dem-start"
touch "$MARK"
DIALOG=0
saved() { [ -n "$(find "$SETTINGS" -newer "$MARK" 2>/dev/null)" ] && [ -f "$AUTOSTART_FILE" ]; }
if [ -n "$NAME" ]; then
  say "Einrichten als $ROLE \"$NAME\" und im Hintergrund starten"
  set -- --name "$NAME" --role "$ROLE" --code "$CODE" --speichern
  [ "$ROLE" = coach ] && [ -n "$KLASSE" ] && set -- "$@" --klasse "$KLASSE"
  start_bg "$BIN" "$@"
  for _ in $(seq 150); do saved && break; sleep 0.1; done
  saved || die "Einrichten hat nicht geklappt:
$(cat "$CACHE_DIR/start.log")"
  C=$(grep -o '"code": *"[A-Z0-9]\{6\}"' "$SETTINGS" | head -1 | grep -o '[A-Z0-9]\{6\}' || true)
  SHOW=${C:+${C:0:3}-${C:3:3}}
elif [ -s "$SETTINGS" ]; then
  say "Mit deinen gespeicherten Einstellungen starten"
  start_bg "$BIN" --autostart
  SHOW=""
else
  say "Startfenster öffnen: Name, Rolle und Code eintragen, dann 'Los geht's'"
  start_bg "$BIN"
  SHOW="" DIALOG=1
fi

for _ in $(seq 50); do app_running && break; sleep 0.1; done
app_running || die "Klassenzimmer startet nicht. Meldung:
$(cat "$CACHE_DIR/start.log")"
rm -f "$MARK"

echo
if [ "$ROLE" = coach ] && [ -n "$SHOW" ]; then
  printf '    %s╔══════════════════════════════╗%s\n' "$B" "$N"
  printf '    %s║   Beitrittscode:  %-9s  ║%s\n' "$B" "$SHOW" "$N"
  printf '    %s╚══════════════════════════════╝%s\n' "$B" "$N"
  echo "    Diesen Code den Schülern sagen."
  echo
fi
if [ "$DIALOG" = 1 ]; then
  say "${G}✔ Installiert.${N} Jetzt im Startfenster Name, Rolle und Code eintragen und 'Los geht's' klicken."
  echo "    Mit dem Häkchen 'Beim Anmelden automatisch starten' startet es danach von selbst."
else
  say "${G}✔ Fertig.${N} Klassenzimmer läuft und startet ab jetzt beim Anmelden von selbst."
fi
echo "    Kleine Leiste am Bildschirmrand: Punkt = Status, Name = grosses Fenster."
echo "    Später wieder öffnen: Klassenzimmer im App-Menü."

}
