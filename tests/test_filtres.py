"""Filtres anti-boucle — aucun materiel requis.

    python3 tests/test_filtres.py

Le chien s'entendait lui-meme : il jouait la demo, captait ses propres
aboiements, Whisper transcrivait « PiDog. », le LLM choisissait `demo`, et la
boucle repartait. Ces filtres coupent le cycle.
"""
import importlib.util, os, sys
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "pi"))
sys.path.insert(0, RACINE)
# charger pidog_ears sans declencher son main
spec = importlib.util.spec_from_file_location("pe", os.path.join(RACINE, "pi", "pidog_ears.py"))
pe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pe)

ok=tot=0
def v(nom, obtenu, attendu):
    global ok,tot
    tot+=1; bon = obtenu==attendu; ok+=bon
    print(f"  {'OK ' if bon else 'ECHEC'} {nom:<52} -> {obtenu}{'' if bon else f' (attendu {attendu})'}")

print("-- mot de reveil seul = ne demande rien --")
for t in ("PiDog.", "PiDog ?", "pidog", "PiDog !", "pi dog."):
    v(f"« {t} »", len(pe.reste_apres_reveil(t)) < pe.MOTS_INSUFFISANTS, True)
print("-- vraies commandes = acceptees --")
for t in ("PiDog danse", "PiDog fais le loup", "PiDog, donne la patte"):
    v(f"« {t} »", len(pe.reste_apres_reveil(t)) >= pe.MOTS_INSUFFISANTS, True)
print("-- hallucinations de Whisper --")
v("« PiDog aboie. PiDog aboie. »", pe.hallucination("PiDog aboie. PiDog aboie."), True)
v("« PiDog tu as un moteur. » x2", pe.hallucination("PiDog tu as un moteur. PiDog tu as un moteur."), True)
v("phrase normale a deux segments", pe.hallucination("PiDog danse. Puis assis."), False)
v("phrase simple", pe.hallucination("PiDog danse"), False)
print(f"\n=> {ok}/{tot} tests passes")
sys.exit(0 if ok==tot else 1)
