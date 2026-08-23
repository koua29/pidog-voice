#!/usr/bin/env bash
#
# Démarrage automatique du serveur STT sur le Mac (LaunchAgent, session utilisateur).
#
#   ./install/mac_autostart.sh            installe et démarre
#   ./install/mac_autostart.sh --retirer  désinstalle
#
# Crée un venv dédié : le service ne doit dépendre d'aucun autre projet.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.koua29.pidog-voice.stt"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
VENV="$RACINE/.venv"
LOG="$HOME/Library/Logs/pidog-voice"

if [ "${1:-}" = "--retirer" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "LaunchAgent retiré."
    exit 0
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "== création du venv dédié ($VENV)"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q faster-whisper
fi
echo "== faster-whisper : $("$VENV/bin/python" -c 'import faster_whisper; print(faster_whisper.__version__)')"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>              <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV/bin/python</string>
        <string>$RACINE/mac/stt_server.py</string>
    </array>
    <key>WorkingDirectory</key>   <string>$RACINE</string>
    <key>RunAtLoad</key>          <true/>
    <key>KeepAlive</key>          <true/>
    <key>ProcessType</key>        <string>Interactive</string>
    <key>StandardOutPath</key>    <string>$LOG/stt.log</string>
    <key>StandardErrorPath</key>  <string>$LOG/stt.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key> <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "== LaunchAgent installé : $PLIST"
echo "   log : $LOG/stt.log"
echo "   Ollama doit tourner de son côté (app menu-bar ou 'ollama serve')."
