#!/usr/bin/env python3
"""
Oreilles du PiDog : ecoute le micro, detecte la parole, envoie au Mac,
execute l'action reconnue.

Chaine : micro voiceHAT -> arecord (plug:mic) -> detection d'energie (VAD maison,
aucune dependance) -> WAV -> POST http://cerveau.local:8770/command -> le Mac fait
Whisper + Ollama -> {action} -> mouvements du robot.

Points durs traites :
- le device ALSA doit etre 'plug:mic' (le gain softvol n'est pas applique sur hw:)
- mot de reveil obligatoire : sinon le chien se declenche sur les conversations
- suppression d'echo : on n'ecoute pas pendant que le chien parle ou bouge
- le seuil de bruit est CALIBRE au demarrage, pas code en dur

Usage :
    python3 pidog_ears.py                # ecoute, marche interdite (table)
    PIDOG_MARCHE=1 python3 pidog_ears.py # au sol, patrouille autorisee
    python3 pidog_ears.py --calibrer     # mesure le bruit ambiant et sort
    python3 pidog_ears.py --test-audio   # enregistre 4s et les fait transcrire
"""
import io
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config      # noqa: E402

CFG = Config()                 # source de verite : commandes.json

# Adresse du cerveau. A definir : export PIDOG_MAC=http://192.168.x.x:8770
MAC = os.environ.get("PIDOG_MAC", "http://cerveau.local:8770")
MIC = os.environ.get("PIDOG_MIC", "plug:mic")
HP = os.environ.get("PIDOG_SPEAKER", "plug:speaker")
STT_LOCAL = os.environ.get("PIDOG_STT", "mac").lower() == "local"
MODELE_LOCAL = os.environ.get("PIDOG_WHISPER_LOCAL", "tiny")
VOLUME = os.environ.get("PIDOG_VOLUME")   # % PipeWire ; >100 = sur-amplification.
                                          # Non defini = on garde le reglage courant
                                          # (celui fait a la voix), on demute seulement.

RATE = 16000
TRAME_MS = 30
TRAME = RATE * TRAME_MS // 1000          # echantillons par trame
OCTETS_TRAME = TRAME * 2

DEBUT_PAROLE = 3      # trames bruyantes consecutives pour demarrer (~90 ms)
FIN_PAROLE = 25       # trames calmes consecutives pour arreter (~750 ms)
MAX_S = 8.0
MIN_S = 0.4
MARGE_BRUIT = 3.5     # seuil = bruit_ambiant * MARGE_BRUIT

BIAIS_LOCAL = CFG.biais()

MOTS_REVEIL = CFG.mots_reveil()            # <- commandes.json
FENETRE_CONVERSATION = CFG.fenetre_conversation()


def rms(bloc):
    n = len(bloc) // 2
    if not n:
        return 0.0
    ech = struct.unpack(f"<{n}h", bloc[:n * 2])
    return math.sqrt(sum(x * x for x in ech) / n)


def en_wav(trames):
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(b"".join(trames))
    w.close()
    return buf.getvalue()


class SttLocal:
    """faster-whisper sur le Pi 4. Le modele reste resident (le chargement
    coute 10-19 s). Necessite le venv ~/script/venv-stt."""

    def __init__(self, taille=MODELE_LOCAL):
        from faster_whisper import WhisperModel
        t0 = time.time()
        self.m = WhisperModel(taille, device="cpu", compute_type="int8", cpu_threads=4)
        self.taille = taille
        print(f"[stt-local] modele '{taille}' charge en {time.time()-t0:.1f}s")

    def transcrire(self, wav_bytes):
        t0 = time.time()
        segs, _ = self.m.transcribe(io.BytesIO(wav_bytes), language="fr",
                                    beam_size=1, vad_filter=True,
                                    initial_prompt=BIAIS_LOCAL)
        texte = " ".join(s.text.strip() for s in segs).strip()
        return texte, round(time.time() - t0, 2)


class Oreilles:
    def __init__(self, mic=MIC, mac=MAC):
        self.mic = mic
        self.mac = mac
        self.seuil = None
        self.proc = None
        self.sourde_jusqua = 0.0     # suppression d'echo
        self.stt = SttLocal() if STT_LOCAL else None

    # -- micro --------------------------------------------------------------
    def _ouvrir(self):
        self.proc = subprocess.Popen(
            ["arecord", "-D", self.mic, "-f", "S16_LE", "-r", str(RATE),
             "-c", "1", "-t", "raw", "-q"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def _fermer(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None

    def _trame(self):
        return self.proc.stdout.read(OCTETS_TRAME)

    def calibrer(self, secondes=2.0):
        """Mesure le bruit ambiant et en deduit le seuil de parole."""
        self._ouvrir()
        niveaux = []
        for _ in range(int(secondes * 1000 / TRAME_MS)):
            t = self._trame()
            if not t:
                break
            niveaux.append(rms(t))
        self._fermer()
        niveaux.sort()
        fond = niveaux[len(niveaux) // 2] if niveaux else 200.0   # mediane
        self.seuil = max(fond * MARGE_BRUIT, 350.0)
        return fond, self.seuil

    # -- reseau -------------------------------------------------------------
    def envoyer(self, wav, route="/command", timeout=90):
        req = urllib.request.Request(self.mac + route, data=wav,
                                     headers={"Content-Type": "audio/wav"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def interpreter(self, texte, timeout=30):
        req = urllib.request.Request(
            self.mac + "/interpret",
            data=json.dumps({"texte": texte}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def traiter(self, wav):
        """Retourne le dict {texte, action, ...} quel que soit le mode STT."""
        if self.stt is None:
            return self.envoyer(wav)                    # tout sur le Mac
        texte, lat = self.stt.transcrire(wav)           # STT ici, LLM sur le Mac
        if not texte:
            return {"texte": "", "action": "inconnu", "confiance": 0.0,
                    "latence_stt": lat}
        r = self.interpreter(texte)
        r.update(texte=texte, latence_stt=lat)
        return r

    def sante(self):
        with urllib.request.urlopen(self.mac + "/health", timeout=5) as r:
            return json.loads(r.read())

    # -- boucle --------------------------------------------------------------
    def ecouter(self, on_parole):
        """Boucle infinie : detecte une phrase, appelle on_parole(wav_bytes)."""
        if self.seuil is None:
            self.calibrer()
        self._ouvrir()
        tampon, calmes, bruyantes, enregistre = [], 0, 0, False
        try:
            while True:
                t = self._trame()
                if not t or len(t) < OCTETS_TRAME:
                    break
                if time.time() < self.sourde_jusqua:      # le chien parle : on ignore
                    tampon, enregistre, bruyantes = [], False, 0
                    continue

                fort = rms(t) > self.seuil
                if not enregistre:
                    bruyantes = bruyantes + 1 if fort else 0
                    tampon.append(t)
                    if len(tampon) > DEBUT_PAROLE * 2:
                        tampon.pop(0)                      # pre-roll glissant
                    if bruyantes >= DEBUT_PAROLE:
                        enregistre, calmes = True, 0
                else:
                    tampon.append(t)
                    calmes = 0 if fort else calmes + 1
                    duree = len(tampon) * TRAME_MS / 1000
                    if calmes >= FIN_PAROLE or duree >= MAX_S:
                        if duree >= MIN_S:
                            # filet de securite : aucune erreur de traitement
                            # (reseau, LLM, servo) ne doit arreter les oreilles
                            try:
                                on_parole(en_wav(tampon))
                            except Exception as e:
                                print(f"   !! phrase ignoree : {type(e).__name__}: {e}")
                        tampon, enregistre, bruyantes = [], False, 0
        finally:
            self._fermer()

    def se_taire_pendant(self, secondes):
        self.sourde_jusqua = time.time() + secondes


def parler(texte, oreilles=None):
    """Voix francaise via pico2wave. Rend le chien sourd pendant qu'il parle."""
    if not texte:
        return
    print(f"   PiDog> {texte}")
    wav = "/tmp/pidog_tts.wav"
    try:
        subprocess.run(["pico2wave", "-l", "fr-FR", "-w", wav, texte],
                       check=True, capture_output=True, timeout=10)
        duree = 0.0
        with wave.open(wav) as w:
            duree = w.getnframes() / w.getframerate()
        if oreilles:
            oreilles.se_taire_pendant(duree + 0.6)
        subprocess.run(["aplay", "-q", "-D", HP, wav], timeout=20,
                       capture_output=True)
    except Exception as e:
        print(f"   (voix indisponible : {type(e).__name__})")


def monter_le_son():
    """Prepare la sortie audio du robot.

    Deux pieges, tous deux constates apres un redemarrage :
    1. PipeWire choisit parfois la sortie HDMI comme sink par defaut -> le chien
       joue ses sons dans le vide. On force explicitement le haut-parleur du
       robot-hat (platform-soc_sound).
    2. Le volume revient a 40 % (-23,9 dB), le chien est alors inaudible.
    robot_hat.music_set_volume() ne sert a rien ici : elle lance
    `sudo amixer sset 'PCM'` (sudo refuse, et ce controle n'existe pas).
    PipeWire accepte >100 % (150 %=+10,6 dB) mais le petit HP gresille : eviter.
    """
    def pactl(*args, capture=False):
        return subprocess.run(["pactl", *args], capture_output=True,
                              text=True, timeout=5).stdout

    try:
        # 1. trouver le haut-parleur du robot parmi les sorties
        sinks = pactl("list", "sinks", "short")
        hp = next((l.split("\t")[1] for l in sinks.splitlines()
                   if "soc_sound" in l), None)
        if hp:
            actuel = pactl("get-default-sink").strip()
            if actuel != hp:
                print(f"[ears] sortie audio corrigee : {actuel} -> {hp}")
                pactl("set-default-sink", hp)
        else:
            print("[ears] !! haut-parleur du robot introuvable dans PipeWire")

        # 2. volume
        if VOLUME:
            pactl("set-sink-volume", "@DEFAULT_SINK@", f"{VOLUME}%")
        else:
            v = pactl("get-sink-volume", "@DEFAULT_SINK@")
            pct = int(re.search(r"(\d+)%", v).group(1)) if re.search(r"(\d+)%", v) else 0
            if pct < 90:      # revenu au defaut apres un reboot : on remonte
                print(f"[ears] volume a {pct}% -> 100%")
                pactl("set-sink-volume", "@DEFAULT_SINK@", "100%")
        pactl("set-sink-mute", "@DEFAULT_SINK@", "0")
        v = pactl("get-sink-volume", "@DEFAULT_SINK@")
        print(f"[ears] volume sortie : {v.split('/')[1].strip() if '/' in v else '?'}")
    except Exception as e:
        print(f"[ears] audio non configure ({type(e).__name__}: {e}) — son possiblement muet")


def contient_reveil(texte):
    t = texte.lower().replace("-", " ")
    return any(m in t for m in MOTS_REVEIL)


def main():
    args = sys.argv[1:]
    o = Oreilles()

    if "--calibrer" in args:
        fond, seuil = o.calibrer(3.0)
        print(f"bruit ambiant (mediane RMS) = {fond:.0f}   seuil parole = {seuil:.0f}")
        return

    try:
        print("[ears] serveur Mac :", o.sante())
    except Exception as e:
        print(f"[ears] !! Mac injoignable sur {MAC} : {e}")
        print("       lance sur le Mac : ~/.claude/skills/youtube-transcript/venv/bin/"
              "python ~/Documents/PiDog/stt_server.py")
        return

    if "--test-audio" in args:
        print("[ears] enregistrement 4 s — PARLEZ maintenant")
        o._ouvrir()
        trames = [o._trame() for _ in range(int(4000 / TRAME_MS))]
        o._fermer()
        niveaux = [rms(t) for t in trames if t]
        print(f"       RMS moyen={sum(niveaux)/len(niveaux):.0f} max={max(niveaux):.0f}")
        print("      ", o.envoyer(en_wav([t for t in trames if t]), "/stt"))
        return

    # ---- mode normal : robot + ecoute
    monter_le_son()

    from pidog import Pidog
    import pidog_actions

    dog = Pidog()
    time.sleep(1)
    ex = pidog_actions.Executeur(dog, cfg=CFG, parler=lambda t: parler(t, o))
    marche = "AUTORISEE" if ex.autoriser_marche else "INTERDITE (table)"

    fond, seuil = o.calibrer(2.0)
    mode = f"STT LOCAL ({MODELE_LOCAL})" if STT_LOCAL else "STT sur le Mac"
    print(f"[ears] bruit ambiant={fond:.0f} seuil={seuil:.0f} | marche {marche} | {mode}")
    print(f"[ears] dis « PiDog, ... » pour lui parler. Ctrl-C pour quitter.")
    dog.rgb_strip.set_mode('breath', color='cyan', bps=0.5)
    parler("Je suis prêt.", o)

    dernier_ordre = 0.0

    def sur_parole(wav):
        nonlocal dernier_ordre
        try:
            r = o.traiter(wav)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # TimeoutError n'herite PAS de URLError : sans ce cas, un simple
            # timeout tuait tout le processus d'ecoute.
            print(f"   !! Mac injoignable ou trop lent : {type(e).__name__}: {e}")
            return
        except Exception as e:
            print(f"   !! reponse illisible : {type(e).__name__}: {e}")
            return
        texte = (r.get("texte") or "").strip()
        if not texte:
            return
        en_conversation = (time.time() - dernier_ordre) < FENETRE_CONVERSATION
        reveil = contient_reveil(texte)
        marque = "REVEIL" if reveil else ("SUITE" if en_conversation else "ignore")
        print(f"   [{marque}] « {texte} »  -> {r.get('action')} "
              f"(conf {r.get('confiance')}, stt {r.get('latence_stt')}s)")
        if not (reveil or en_conversation):
            return
        action = r.get("action", "inconnu")
        if action == "inconnu":
            return
        dernier_ordre = time.time()
        dog.rgb_strip.set_mode('boom', color='yellow', bps=2)
        phrase = ex.executer(action)
        if phrase:
            parler(phrase, o)
        else:
            o.se_taire_pendant(1.5)
        dog.rgb_strip.set_mode('breath', color='cyan', bps=0.5)

    try:
        o.ecouter(sur_parole)
    except KeyboardInterrupt:
        print("\n[ears] arret")
    finally:
        ex.stop()
        dog.close()


if __name__ == "__main__":
    main()
