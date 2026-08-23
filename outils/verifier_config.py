#!/usr/bin/env python3
"""
Verifie commandes.json AVANT de deployer. A lancer apres toute modification.

Controles :
  - JSON valide, champs obligatoires presents
  - le biais Whisper tient sous 223 tokens (sinon les 1eres commandes sautent)
  - les etapes de sequence n'utilisent que des verbes connus
  - les presets/actions references existent vraiment dans la lib pidog

    python3 outils/verifier_config.py            # controles hors-ligne
    <venv-whisper>/bin/python outils/verifier_config.py --tokens   # + budget tokens
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config  # noqa: E402

VERBES = {"action", "preset", "son", "led", "tete", "pattes", "pattes_stop",
          "pause", "dire", "repeter", "builtin", "args", "speed", "sens",
          "etapes", "attendre"}
BUILTINS = {"demo", "patrouille", "stop", "distance", "volume"}
ACTIONS_PIDOG = {"stand", "sit", "half_sit", "lie", "lie_with_hands_out", "forward",
                 "backward", "turn_left", "turn_right", "trot", "stretch", "push_up",
                 "doze_off", "nod_lethargy", "shake_head", "tilting_head_left",
                 "tilting_head_right", "tilting_head", "head_bark", "wag_tail",
                 "head_up_down"}
PRESETS = {"scratch", "hand_shake", "high_five", "pant", "body_twisting", "bark_action",
           "shake_head", "shake_head_smooth", "bark", "push_up", "howling",
           "attack_posture", "lick_hand", "waiting", "feet_shake", "sit_2_stand",
           "relax_neck", "nod", "think", "recall", "head_down_left", "head_down_right",
           "fluster", "alert", "surprise", "stretch"}

erreurs, avertis = [], []


def verifier_etape(nom, e, chemin="sequence"):
    for cle in e:
        if cle not in VERBES:
            erreurs.append(f"{nom}.{chemin}: verbe inconnu '{cle}'")
    if "action" in e and e["action"] not in ACTIONS_PIDOG:
        erreurs.append(f"{nom}: action pidog inconnue '{e['action']}'")
    if "preset" in e and e["preset"] not in PRESETS:
        erreurs.append(f"{nom}: preset inconnu '{e['preset']}'")
    if "builtin" in e and e["builtin"] not in BUILTINS:
        erreurs.append(f"{nom}: builtin inconnu '{e['builtin']}'")
    for sous in e.get("etapes", []):
        verifier_etape(nom, sous, chemin + ".etapes")


def main():
    c = Config()
    print(f"config : {c.chemin}")
    print(f"{len(c.commandes)} commandes, {len(c.exemples())} exemples few-shot")

    for nom, cmd in c.commandes.items():
        for champ in ("intention", "phrases", "exemples", "sequence"):
            if champ not in cmd:
                erreurs.append(f"{nom}: champ obligatoire '{champ}' manquant")
        for e in cmd.get("sequence", []):
            verifier_etape(nom, e)
        if cmd.get("deplace") and nom != "patrouille":
            avertis.append(f"{nom}: marque 'deplace' -> sera refuse si le robot est sur une table")

    if "inconnu" not in c.commandes:
        erreurs.append("la commande 'inconnu' est obligatoire (repli du LLM)")

    if "--tokens" in sys.argv:
        from faster_whisper import WhisperModel
        from faster_whisper.tokenizer import Tokenizer
        m = WhisperModel("small", device="cpu", compute_type="int8")
        tok = Tokenizer(m.hf_tokenizer, m.model.is_multilingual,
                        task="transcribe", language="fr")
        n = len(tok.encode(" " + c.biais()))
        limite = m.max_length // 2 - 1
        print(f"biais Whisper : {n}/{limite} tokens")
        if n > limite:
            erreurs.append(f"biais TRONQUE : {n} > {limite} tokens. Whisper garde la FIN, "
                           f"les premieres commandes seront perdues. Raccourcir 'phrases'.")
        else:
            print(f"  OK ({limite - n} tokens de marge)")
    else:
        print(f"biais Whisper : {len(c.biais())} caracteres "
              f"(relancer avec --tokens pour verifier le budget)")

    for a in avertis:
        print(f"  ! {a}")
    for e in erreurs:
        print(f"  X {e}")
    print("\n=> " + ("CONFIG INVALIDE" if erreurs else "config valide"))
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
