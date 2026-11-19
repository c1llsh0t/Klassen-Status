#!/usr/bin/env bash
# Klassenzimmer für Omarchy: App + Panel in der Leiste, mit einem einzigen Befehl.
#
#   curl -fsSL https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main/install-omarchy.sh | bash
#
# Ohne Angaben öffnet sich danach das Startfenster (Name, Rolle, Code).
# Mit Angaben wird alles ohne Fenster eingerichtet (praktisch für Claude):
#
#   ... | bash -s -- --name "Lena" --role student --code K7Q-M3X
#   ... | bash -s -- --name "Herr Muster" --role coach --klasse INF3a --code NEU
#
# Macht alles wie install-linux.sh (App, Firewall, App-Menü, Autostart) und dazu:
#   - Panel in der Omarchy-Leiste (Plugin c1llsh0t.klassenzimmer): Schul-Zeichen in
#     Statusfarbe, Klick = Panel mit Teilnehmern und Hilfe, Rechtsklick = Status
#   - Hilfsskript ~/.local/bin/klassenzimmer-leiste (Starten, Klasse wechseln, Beenden)
#   - Fensterregel in ~/.config/hypr/hyprland.lua: Startfenster schwebt unter der Leiste
#
# Nochmal ausführen = aktualisieren. Entfernen: ... | bash -s -- --entfernen

# Alles in einem Block: Bei "curl ... | bash" liest Bash so erst das ganze Skript.
{

set -eu

QUELLE="${KLASSENZIMMER_QUELLE:-https://raw.githubusercontent.com/c1llsh0t/Klassen-Status/main}"
ID="c1llsh0t.klassenzimmer"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
PLUGINS="$CONF/omarchy/plugins"
SHELL_JSON="$CONF/omarchy/shell.json"
HYPR_LUA="$CONF/hypr/hyprland.lua"
HELPER="$HOME/.local/bin/klassenzimmer-leiste"
SETTINGS="$CONF/klassenzimmer/einstellungen.json"

if [ -t 1 ]; then G=$'\033[1;32m' Y=$'\033[1;33m' R=$'\033[1;31m' N=$'\033[0m'; else G="" Y="" R="" N=""; fi
say()  { printf '%s==>%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s!!  %s%s\n' "$Y" "$*" "$N" >&2; }
die()  { printf '%sFehler:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Klassenzimmer für Omarchy installieren oder aktualisieren (App + Panel in der Leiste).

  install-omarchy.sh                              danach Startfenster (Name, Rolle, Code)
  install-omarchy.sh --name NAME --role student --code K7Q-M3X
  install-omarchy.sh --name NAME --role coach --klasse INF3a --code NEU
  install-omarchy.sh --entfernen

Alle weiteren Optionen wie bei install-linux.sh (--ohne-firewall, --nicht-starten).
EOF
}

# Datei aus dem Repo holen: holen <pfad-im-repo> <ziel>
holen() {
  case "$QUELLE" in
    http://*|https://*) curl -fsSL --retry 3 -o "$2" "$QUELLE/$1" || die "Konnte $1 nicht laden. Internet da?" ;;
    *) cp "$QUELLE/$1" "$2" || die "Konnte $1 nicht finden ($QUELLE)." ;;
  esac
}

HAS_NAME=0 REMOVE=0 NOSTART=0
for a in "$@"; do
  case "$a" in
    --name|--name=*) HAS_NAME=1 ;;
    --entfernen) REMOVE=1 ;;
    --nicht-starten) NOSTART=1 ;;
    -h|--help) usage; exit 0 ;;
  esac
done

# --- Grundchecks ---------------------------------------------------------------
[ "$(uname -s)" = Linux ] || die "Das ist der Installer für Omarchy (Linux)."
[ "$(id -u)" != 0 ] || die "Bitte NICHT mit sudo starten, sondern als normaler Benutzer."
if ! command -v omarchy >/dev/null 2>&1 || [ ! -f "$SHELL_JSON" ]; then
  die "Kein Omarchy mit der neuen Leiste gefunden.
       Für Ubuntu, Fedora, Arch usw.: install-linux.sh (siehe README)."
fi
for c in jq hyprctl curl; do command -v "$c" >/dev/null 2>&1 || die "$c fehlt."; done

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
holen install-linux.sh "$TMP/install-linux.sh"

# Fensterregel mit Markierung, damit --entfernen sie wiederfindet
RULE_START="-- >>> klassenzimmer (install-omarchy.sh)"
RULE_END="-- <<< klassenzimmer"

regel_entfernen() {
  [ -f "$HYPR_LUA" ] && grep -qF "$RULE_START" "$HYPR_LUA" || return 0
  cp "$HYPR_LUA" "$HYPR_LUA.bak.$(date +%s)"
  sed -i "/^$(printf '%s' "$RULE_START" | sed 's/[][\.*^$/]/\\&/g')\$/,/^$(printf '%s' "$RULE_END" | sed 's/[][\.*^$/]/\\&/g')\$/d" "$HYPR_LUA"
  hyprctl reload >/dev/null 2>&1 || true
}

andere_panels() {   # IDs von anderen Klassenzimmer-Panels (z.B. selbst gebastelte Kopien)
  local m id
  for m in "$PLUGINS"/*/manifest.json; do
    [ -f "$m" ] || continue
    id=$(jq -r '.id // empty' "$m" 2>/dev/null) || continue
    case "$id" in *.klassenzimmer) [ "$id" != "$ID" ] && echo "$id" ;; esac
  done
  return 0
}

# --- Entfernen -----------------------------------------------------------------
if [ "$REMOVE" = 1 ]; then
  for id in "$ID" $(andere_panels); do
    [ -d "$PLUGINS/$id" ] && { omarchy plugin remove "$id" --yes >/dev/null 2>&1 || rm -rf "$PLUGINS/$id"; }
  done
  rm -f "$HELPER"
  regel_entfernen
  say "Panel, Hilfsskript und Fensterregel entfernt."
  bash "$TMP/install-linux.sh" --entfernen
  exit 0
fi

# --- 1. Panel und Hilfsskript ----------------------------------------------------
say "Panel für die Leiste und Hilfsskript holen"
mkdir -p "$TMP/plugin" "$HOME/.local/bin"
holen omarchy/klassenzimmer-leiste "$TMP/klassenzimmer-leiste"
holen omarchy/plugin/manifest.json "$TMP/plugin/manifest.json"
holen omarchy/plugin/Klassenzimmer.qml "$TMP/plugin/Klassenzimmer.qml"
[ "$(jq -r .id "$TMP/plugin/manifest.json")" = "$ID" ] || die "Das heruntergeladene Panel ist kaputt."
install -m 755 "$TMP/klassenzimmer-leiste" "$HELPER"

# Platz in der Leiste merken (eigener oder von einer alten Kopie), damit er gleich bleibt
platz() {   # gibt "<section> <index>" aus, wenn $1 in der Leiste ist
  jq -r --arg id "$1" '.bar.layout // {} | to_entries[]
      | .key as $s | (.value | map(.id) | index($id)) as $i
      | select($i != null) | "\($s) \($i)"' "$SHELL_JSON" 2>/dev/null | head -1
}
PLATZ=""
for old in $(andere_panels); do
  [ -z "$PLATZ" ] && PLATZ=$(platz "$old")
  say "Alte Kopie des Panels ersetzen: $old (Sicherung bleibt im Plugin-Ordner)"
  omarchy plugin remove "$old" --yes >/dev/null 2>&1 || warn "Konnte $old nicht entfernen."
done
UPDATE=0
[ -f "$PLUGINS/$ID/Klassenzimmer.qml" ] && ! cmp -s "$TMP/plugin/Klassenzimmer.qml" "$PLUGINS/$ID/Klassenzimmer.qml" && UPDATE=1
mkdir -p "$PLUGINS/$ID"
cp "$TMP/plugin/manifest.json" "$TMP/plugin/Klassenzimmer.qml" "$PLUGINS/$ID/"
omarchy plugin validate "$PLUGINS/$ID" >/dev/null 2>&1 || die "Omarchy meldet das Panel als ungültig (omarchy plugin validate $PLUGINS/$ID)."
echo "    $PLUGINS/$ID"

# --- 2. Fensterregel ---------------------------------------------------------------
if [ ! -f "$HYPR_LUA" ]; then
  warn "$HYPR_LUA fehlt: Das Startfenster schwebt evtl. nicht. Sonst funktioniert alles."
elif grep -qE 'title *= *"\^Klassenzimmer"' "$HYPR_LUA"; then
  : # Regel ist schon da
else
  say "Fensterregel für das Startfenster in hyprland.lua eintragen"
  BAK="$HYPR_LUA.bak.$(date +%s)"
  cp "$HYPR_LUA" "$BAK"
  cat >>"$HYPR_LUA" <<EOF

$RULE_START
-- Klassenzimmer: Startfenster schwebt unter der Leiste (das Panel macht der Rest).
o.window({ class = "^Tk\$", title = "^Klassenzimmer" }, {
  float = true,
  move = { "(monitor_w-window_w-10)", 42 },
})
$RULE_END
EOF
  hyprctl reload >/dev/null 2>&1 || true
  sleep 0.5
  ERR=$(hyprctl configerrors 2>/dev/null | grep -v -i -E '^\s*$|no errors' || true)
  if [ -n "$ERR" ]; then
    cp "$BAK" "$HYPR_LUA"
    hyprctl reload >/dev/null 2>&1 || true
    warn "Hyprland mochte die Fensterregel nicht, ich habe sie wieder entfernt. Sonst funktioniert alles."
  fi
fi

# --- 3. App (wie install-linux.sh) ---------------------------------------------------
EINRICHTEN=0
if [ "$HAS_NAME" = 0 ] && [ "$NOSTART" = 0 ] && [ ! -s "$SETTINGS" ]; then
  # Neu und ohne Angaben: Startfenster öffnet am Schluss das Hilfsskript (unter dem Zeichen)
  EINRICHTEN=1
  set -- "$@" --nicht-starten
fi
KLASSENZIMMER_OMARCHY=1 bash "$TMP/install-linux.sh" "$@"

# --- 4. Panel in die Leiste ----------------------------------------------------------
say "Panel in die Leiste setzen"
omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
sleep 1
if jq -e --arg id "$ID" '[.bar.layout[]?[]?.id] | index($id) != null' "$SHELL_JSON" >/dev/null 2>&1; then
  : # ist schon in der Leiste
elif [ -n "$PLATZ" ]; then
  omarchy plugin enable "$ID" --section "${PLATZ% *}" --index "${PLATZ#* }" >/dev/null 2>&1 \
    || omarchy plugin enable "$ID" --section right >/dev/null 2>&1 \
    || warn "Bitte selbst einschalten: omarchy plugin enable $ID --section right"
elif jq -e '[.bar.layout.right[]?.id] | index("omarchy.tray") != null' "$SHELL_JSON" >/dev/null 2>&1; then
  omarchy plugin enable "$ID" --after omarchy.tray >/dev/null 2>&1 \
    || warn "Bitte selbst einschalten: omarchy plugin enable $ID --section right"
else
  omarchy plugin enable "$ID" --section right >/dev/null 2>&1 \
    || warn "Bitte selbst einschalten: omarchy plugin enable $ID --section right"
fi
# Eine geänderte Panel-Datei übernimmt die Leiste erst nach einem Neustart
[ "$UPDATE" = 1 ] && { omarchy restart shell >/dev/null 2>&1 || true; }

if [ "$EINRICHTEN" = 1 ]; then
  sleep 2
  setsid -f "$HELPER" einrichten >/dev/null 2>&1 </dev/null
  say "${G}✔ Installiert.${N} Jetzt im Startfenster Name, Rolle und Code eintragen und 'Los geht's' klicken."
else
  say "${G}✔ Fertig.${N} Klassenzimmer läuft und startet ab jetzt beim Anmelden von selbst."
fi
echo "    Oben rechts in der Leiste: Schul-Zeichen 󰑴 (grün = online, gelb = nicht stören)."
echo "    Klick = Panel mit Teilnehmern und Hilfe, Rechtsklick = Status wechseln."

}
