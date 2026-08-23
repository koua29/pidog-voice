#!/usr/bin/env bash
#
# Démarrage automatique de l'écoute sur le Raspberry Pi (cron @reboot).
#
#   ./install/pi_autostart.sh            installe
#   ./install/pi_autostart.sh --retirer  désinstalle
#
# cron plutôt que systemd : aucun privilège root requis. La supervision
# (redémarrage après plantage) est déjà assurée par ears_loop.sh.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUP="$RACINE/pi/ears_loop.sh"
MARQUE="# pidog-voice"

# NB : `crontab -l` sort en erreur si aucune crontab n'existe, et `grep -v` sort
# en erreur s'il ne filtre rien. Avec `set -e`, les deux tuent le script : d'où
# les `|| true`.
crontab_actuelle() { crontab -l 2>/dev/null || true; }

if [ "${1:-}" = "--retirer" ]; then
    crontab_actuelle | { grep -v "$MARQUE" || true; } | crontab -
    echo "Entrée cron retirée."
    exit 0
fi

[ -x "$SUP" ] || chmod +x "$SUP"

: "${PIDOG_MAC:?Définissez PIDOG_MAC, ex: export PIDOG_MAC=http://192.168.1.26:8770}"
MARCHE="${PIDOG_MARCHE:-0}"

LIGNE="@reboot PIDOG_MAC='$PIDOG_MAC' PIDOG_MARCHE='$MARCHE' $SUP --boot >> \$HOME/script/superviseur.log 2>&1 $MARQUE"

{ crontab_actuelle | { grep -v "$MARQUE" || true; } ; echo "$LIGNE" ; } | crontab -

echo "== cron installé :"
crontab -l | grep "$MARQUE"
echo
echo "   PIDOG_MAC     = $PIDOG_MAC"
echo "   PIDOG_MARCHE  = $MARCHE  ($([ "$MARCHE" = 1 ] && echo 'déplacements AUTORISÉS' || echo 'déplacements interdits — robot sur une table'))"
echo "   log           = \$HOME/script/superviseur.log"
