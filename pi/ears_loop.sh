#!/usr/bin/env bash
# Superviseur des oreilles du PiDog : relance l'ecoute si elle s'arrete.
# Usage : nohup ~/script/ears_loop.sh > ~/script/superviseur.log 2>&1 &
export PATH=$PATH:/usr/sbin
cd "$HOME/script" || exit 1

while true; do
    echo "[sup] $(date '+%H:%M:%S') demarrage de l'ecoute"
    # marqueur : sans lui on confond les lignes d'un run avec celles du precedent
    echo "===== run $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$HOME/script/ears.log"
    python3 -u pidog_ears.py >> "$HOME/script/ears.log" 2>&1
    code=$?
    if [ $code -eq 0 ]; then
        echo "[sup] $(date '+%H:%M:%S') arret propre (code 0) — fin du superviseur"
        break
    fi
    echo "[sup] $(date '+%H:%M:%S') ecoute morte (code $code) — relance dans 5 s"
    sleep 5
done
