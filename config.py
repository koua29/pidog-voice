#!/usr/bin/env python3
"""
Lecture de commandes.json — source de verite unique de pidog-voice.

Utilise des deux cotes (Mac et Pi) pour que le biais Whisper, le prompt du LLM
et l'execution des mouvements ne puissent JAMAIS diverger.
"""
import json
import os

CHEMIN = os.environ.get(
    "PIDOG_CONFIG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "commandes.json"))


class Config:
    def __init__(self, chemin=CHEMIN):
        self.chemin = chemin
        with open(chemin, encoding="utf-8") as f:
            self.brut = json.load(f)
        self.commandes = self.brut["commandes"]
        self.reglages = self.brut.get("reglages", {})

    # -- pour Whisper --------------------------------------------------------
    def biais(self):
        """Phrases d'amorce. ⚠️ Whisper tronque a 223 tokens en gardant la FIN :
        verifier avec outils/verifier_config.py apres toute modification."""
        bouts = [self.reglages.get("prefixe_biais", "")]
        for c in self.commandes.values():
            bouts += [p.rstrip(".") + ". " for p in c.get("phrases", [])]
        return "".join(bouts).strip()

    # -- pour le LLM ---------------------------------------------------------
    def noms(self):
        return list(self.commandes)

    def catalogue(self):
        return {n: c["intention"] for n, c in self.commandes.items()}

    def exemples(self):
        """[(phrase, action)] pour le few-shot, dans l'ordre du fichier."""
        out = []
        for nom, c in self.commandes.items():
            for ex in c.get("exemples", []):
                out.append((ex, nom))
        return out

    def systeme(self):
        return (
            "Tu es l'interpreteur de commandes vocales d'un robot chien nomme PiDog.\n"
            "Le texte vient d'une reconnaissance vocale francaise et peut etre deforme "
            "(le nom 'PiDog' peut devenir 'pi dog', 'qui doit'...). Raisonne sur "
            "l'INTENTION, pas sur les mots exacts.\n\nActions possibles :\n"
            + "\n".join(f"- {n} : {d}" for n, d in self.catalogue().items())
            + "\n\nChoisis l'action dont la description colle le mieux. Ne reponds "
              "'inconnu' que si vraiment aucune ne convient.\n"
              "Reponds UNIQUEMENT par un JSON "
              "{\"action\": ..., \"confiance\": 0.0-1.0}."
        )

    def schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": self.noms()},
                "confiance": {"type": "number"},
            },
            "required": ["action", "confiance"],
        }

    # -- pour l'execution ----------------------------------------------------
    def sequence(self, nom):
        return self.commandes.get(nom, {}).get("sequence", [])

    def reponse(self, nom):
        return self.commandes.get(nom, {}).get("reponse")

    def deplace(self, nom):
        return self.commandes.get(nom, {}).get("deplace", False)

    def mots_reveil(self):
        return tuple(self.reglages.get("mot_reveil", ["pidog"]))

    def fenetre_conversation(self):
        return float(self.reglages.get("fenetre_conversation_s", 12.0))
