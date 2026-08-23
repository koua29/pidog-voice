#!/usr/bin/env python3
"""
Executeur de commandes PiDog, pilote par commandes.json.

Une commande est une SEQUENCE d'etapes declaratives. Verbes disponibles :

  {"action": "sit", "speed": 70, "attendre": true}   do_action() de la lib pidog
  {"preset": "hand_shake", "args": {...}}            pidog.preset_actions
  {"son": "single_bark_1"}                           joue un son de ~/pidog/sounds
  {"led": {"mode":"breath","color":"cyan","bps":1}}  bandeau RGB
  {"tete": [yaw, roll, pitch], "speed": 80}          mouvement de tete
  {"pattes": [8 angles], "speed": 50}                pose des pattes
  {"pattes_stop": true}                              coupe les servos des pattes
  {"pause": 0.5}                                     attente en secondes
  {"dire": "texte"}                                  synthese vocale
  {"repeter": 3, "etapes": [...]}                    boucle
  {"builtin": "distance"}                            comportement code en Python
                                                     (demo|patrouille|stop|distance|volume)

SECURITE : une commande marquee "deplace": true est REFUSEE par defaut (le robot
est le plus souvent sur une table). L'autoriser avec PIDOG_MARCHE=1.
"""
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config  # noqa: E402

from pidog import preset_actions as pa  # noqa: E402

MARCHE_AUTORISEE = os.environ.get("PIDOG_MARCHE", "0") == "1"
PAS_VOLUME = 20
VOL_MIN, VOL_MAX = 20, 200


def volume_actuel():
    try:
        out = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                             capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"(\d+)%", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def regler_volume(pourcent):
    """⚠️ Au-dela de 100 %, PipeWire sur-amplifie et le petit haut-parleur greside."""
    pourcent = max(VOL_MIN, min(VOL_MAX, int(pourcent)))
    subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pourcent}%"],
                   capture_output=True, timeout=5)
    subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
                   capture_output=True, timeout=5)
    return pourcent


class Executeur:
    def __init__(self, dog, cfg=None, autoriser_marche=MARCHE_AUTORISEE, parler=None):
        self.dog = dog
        self.cfg = cfg or Config()
        self.autoriser_marche = autoriser_marche
        self.parler = parler or (lambda t: None)
        self._annuler = threading.Event()
        self._thread = None

    @property
    def occupe(self):
        return self._thread is not None and self._thread.is_alive()

    # -- interpreteur d'etapes ----------------------------------------------
    def _etape(self, e):
        if self._annuler.is_set():
            return
        d = self.dog

        if "pause" in e:
            fin = time.time() + float(e["pause"])
            while time.time() < fin and not self._annuler.is_set():
                time.sleep(0.05)
            return
        if "action" in e:
            d.do_action(e["action"], speed=e.get("speed", 70))
            if e.get("attendre", True):
                d.wait_all_done()
            return
        if "preset" in e:
            getattr(pa, e["preset"])(d, **e.get("args", {}))
            d.wait_all_done()
            return
        if "son" in e:
            d.speak(e["son"])
            return
        if "led" in e:
            d.rgb_strip.set_mode(**e["led"])
            return
        if "tete" in e:
            d.head_move([e["tete"]], speed=e.get("speed", 80))
            if e.get("attendre", True):
                d.wait_all_done()
            return
        if "pattes" in e:
            d.legs_move([e["pattes"]], speed=e.get("speed", 50))
            if e.get("attendre", True):
                d.wait_all_done()
            return
        if e.get("pattes_stop"):
            d.legs_stop()
            return
        if "dire" in e:
            self.parler(e["dire"])
            return
        if "repeter" in e:
            for _ in range(int(e["repeter"])):
                if self._annuler.is_set():
                    return
                for sous in e.get("etapes", []):
                    self._etape(sous)
            return
        if "builtin" in e:
            self._builtin(e)
            return
        print(f"[action] etape ignoree (verbe inconnu) : {e}")

    # -- comportements qui demandent du vrai code ---------------------------
    def _builtin(self, e):
        nom = e["builtin"]
        if nom == "stop":
            self.stop()
        elif nom == "volume":
            self._volume(int(e.get("sens", 1)))
        elif nom == "distance":
            self._distance()
        elif nom == "demo":
            self._demo()
        elif nom == "patrouille":
            self._patrouille()
        else:
            print(f"[action] builtin inconnu : {nom}")

    def _distance(self):
        d = round(self.dog.read_distance())
        self.dog.head_move([[0, 0, -10]], speed=80)
        self.dog.wait_all_done()
        self.parler(f"J'ai un obstacle a {d} centimetres." if 0 < d < 200
                    else "Je ne vois rien devant moi.")

    def _volume(self, sens):
        actuel = volume_actuel()
        if actuel is None:
            self.parler("Je n'arrive pas a regler mon volume.")
            return
        nouveau = regler_volume(actuel + sens * PAS_VOLUME)
        print(f"[volume] {actuel}% -> {nouveau}%")
        for _ in range(2):                      # accuse reception AU NOUVEAU volume
            pa.bark_action(self.dog, speak='single_bark_1')
            time.sleep(0.25)
        if nouveau == actuel:
            self.parler("Je suis deja au maximum." if sens > 0 else "Je suis deja au minimum.")

    def _demo(self):
        """Enchaine toutes les commandes non-deplacantes, sauf les meta-commandes."""
        exclues = {"demo", "patrouille", "stop", "inconnu", "distance",
                   "son_plus", "son_moins"}
        for nom in self.cfg.noms():
            if nom in exclues or self.cfg.deplace(nom) or self._annuler.is_set():
                continue
            print(f"   >> {nom}")
            for e in self.cfg.sequence(nom):
                self._etape(e)
            time.sleep(0.4)

    def _patrouille(self):
        d = self.dog
        d.do_action('stand', speed=70)
        d.wait_all_done()
        for _ in range(20):
            if self._annuler.is_set():
                return
            dist = d.read_distance()
            if 0 < dist < 25:
                d.rgb_strip.set_mode('bark', color='red', bps=2)
                d.speak('single_bark_1')
                d.do_action('turn_left', step_count=3, speed=88)
            else:
                d.rgb_strip.set_mode('breath', color='green', bps=1)
                d.do_action('forward', step_count=3, speed=90)
            d.wait_all_done()

    # -- pilotage ------------------------------------------------------------
    def stop(self):
        self._annuler.set()
        self.dog.legs_stop()
        self.dog.head_stop()
        self.dog.tail_stop()
        if self._thread:
            self._thread.join(timeout=3)
        self._annuler.clear()
        return "J'arrete."

    def executer(self, action, bloquant=False):
        """Lance une commande. Retourne la phrase a prononcer (ou None)."""
        if action in (None, "inconnu"):
            return "Je n'ai pas compris."
        if action not in self.cfg.commandes:
            return "Je ne sais pas faire ca."
        if action == "stop":
            return self.stop()

        if self.cfg.deplace(action) and not self.autoriser_marche:
            self.dog.do_action('sit', speed=60)
            return ("Je ne peux pas faire ca, la marche est desactivee "
                    "parce que je suis sur une table.")

        if self.occupe:
            self.stop()

        sequence = self.cfg.sequence(action)

        def _run():
            try:
                for e in sequence:
                    self._etape(e)
            except Exception as ex:      # une commande ratee ne doit pas tuer l'ecoute
                print(f"[action] '{action}' a echoue : {type(ex).__name__}: {ex}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        if bloquant:
            self._thread.join()
        return self.cfg.reponse(action)


if __name__ == "__main__":
    from pidog import Pidog
    action = sys.argv[1] if len(sys.argv) > 1 else "assis"
    dog = Pidog()
    try:
        time.sleep(1)
        ex = Executeur(dog, parler=print)
        phrase = ex.executer(action, bloquant=True)
        if phrase:
            print(f">> {phrase}")
    finally:
        dog.close()
