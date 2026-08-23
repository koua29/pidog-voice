#!/usr/bin/env python3
"""
Genere le tableau des commandes pour le README, depuis commandes.json.

Evite que la doc mente : la liste est toujours celle du fichier de config.

    python3 outils/lister_commandes.py            # affiche le tableau
    python3 outils/lister_commandes.py --injecter # met a jour le README
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config  # noqa: E402

DEBUT = "<!-- COMMANDES:debut -->"
FIN = "<!-- COMMANDES:fin -->"


def tableau(c):
    lignes = [f"| Commande | Ce qu'il fait | Dites par exemple |",
              "|---|---|---|"]
    for nom, cmd in c.commandes.items():
        if nom == "inconnu":
            continue
        intention = cmd["intention"].split(",")[0].strip().capitalize()
        exemples = [f"*« {c.nom()} {p.replace('{nom} ', '')} »*"
                    for p in cmd.get("phrases", [])[:2]]
        for ex in cmd.get("exemples", [])[:1]:
            exemples.append(f"*« {ex} »*")
        verrou = " 🔒" if cmd.get("deplace") else ""
        lignes.append(f"| `{nom}`{verrou} | {intention} | {', '.join(exemples) or '—'} |")
    lignes.append("")
    lignes.append("🔒 = déplace le robot : refusé tant que `PIDOG_MARCHE=1` n'est pas défini "
                  "(il est probablement sur une table).")
    return "\n".join(lignes)


def main():
    c = Config()
    t = tableau(c)
    if "--injecter" not in sys.argv:
        print(t)
        return 0
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "README.md")
    s = open(p, encoding="utf-8").read()
    if DEBUT not in s or FIN not in s:
        print(f"!! marqueurs {DEBUT} / {FIN} absents du README")
        return 1
    s = re.sub(re.escape(DEBUT) + r".*?" + re.escape(FIN),
               f"{DEBUT}\n{t}\n{FIN}", s, flags=re.S)
    open(p, "w", encoding="utf-8").write(s)
    print(f"README mis a jour : {len(c.commandes) - 1} commandes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
