#!/usr/bin/env python3
"""
Demos PiDog SANS DEPLACEMENT — sures sur une table.

Aucune demo n'appelle forward/backward/turn/trot/Walk/Trot : le chien reste
sur place. Il change quand meme d'assiette (assis/debout/couche) et remue les
pattes, donc laisser ~30 cm de marge autour de lui.

Usage :
    python3 demo_table.py            # liste les demos
    python3 demo_table.py 3          # joue la demo 3
    python3 demo_table.py reveil aboie
    python3 demo_table.py all        # enchaine tout
"""
import sys
import time

from pidog import Pidog
from pidog import preset_actions as pa


def reveil(d):
    """Reveil : s'assoit, s'etire, remue la queue, LED bleue."""
    d.rgb_strip.set_mode('listen', color='yellow', bps=0.6, brightness=0.8)
    d.do_action('sit', speed=60)
    d.wait_all_done()
    pa.stretch(d)
    d.wait_all_done()
    d.do_action('wag_tail', step_count=10, speed=90)
    d.rgb_strip.set_mode('breath', color='cyan', bps=0.8)
    time.sleep(2)
    d.tail_stop()


def aboie(d):
    """Aboie deux fois avec la posture."""
    d.do_action('sit', speed=60)
    d.wait_all_done()
    for _ in range(2):
        pa.bark_action(d, speak='single_bark_1')
        time.sleep(0.4)


def hurle(d):
    """Hurlement de loup."""
    d.do_action('sit', speed=60)
    d.wait_all_done()
    pa.howling(d)


def gratte(d):
    """Se gratte l'oreille avec la patte arriere."""
    pa.scratch(d)
    d.wait_all_done()


def patte(d):
    """Donne la patte, puis high five."""
    pa.hand_shake(d)
    d.wait_all_done()
    time.sleep(0.5)
    pa.high_five(d)
    d.wait_all_done()


def pompes(d):
    """Trois pompes."""
    d.legs_move([[45, -25, -45, 25, 80, 70, -80, -70]], speed=50)
    d.head_move([[0, 0, -20]], speed=90)
    d.wait_all_done()
    d.rgb_strip.set_mode('speak', color='blue', bps=2)
    for _ in range(3):
        pa.push_up(d, speed=92)
        pa.bark(d, [0, 0, -40])
        time.sleep(0.4)


def emotions(d):
    """Enchaine les mimiques : reflechit, se rappelle, s'affole, alerte, surprise."""
    d.do_action('sit', speed=60)
    d.wait_all_done()
    for name, fn in (('think', pa.think), ('recall', pa.recall),
                     ('fluster', pa.fluster), ('alert', pa.alert)):
        print(f"    -> {name}")
        fn(d)
        d.wait_all_done()
        time.sleep(0.4)
    print("    -> surprise")
    pa.surprise(d, status='sit')
    d.wait_all_done()


def danse(d):
    """Tortille du corps, secoue la tete, remue les pattes."""
    d.rgb_strip.set_mode('boom', color='pink', bps=2)
    pa.body_twisting(d)
    d.wait_all_done()
    pa.shake_head_smooth(d, amplitude=45, speed=90)
    d.wait_all_done()
    pa.feet_shake(d)
    d.wait_all_done()


def halete(d):
    """Halete comme un chien fatigue, puis se detend la nuque."""
    d.do_action('sit', speed=60)
    d.wait_all_done()
    pa.pant(d, speed=80)
    d.wait_all_done()
    pa.relax_neck(d)
    d.wait_all_done()


def dodo(d):
    """S'endort : se couche, tete qui tombe, LED qui s'eteint."""
    d.rgb_strip.set_mode('breath', color='white', bps=0.4, brightness=0.4)
    d.do_action('lie', speed=50)
    d.wait_all_done()
    d.do_action('doze_off', speed=30)
    time.sleep(4)
    d.legs_stop()
    d.speak('snoring')
    time.sleep(3)


DEMOS = [
    ('reveil',   reveil),
    ('aboie',    aboie),
    ('hurle',    hurle),
    ('gratte',   gratte),
    ('patte',    patte),
    ('pompes',   pompes),
    ('emotions', emotions),
    ('danse',    danse),
    ('halete',   halete),
    ('dodo',     dodo),
]


def liste():
    print("\nDemos PiDog sans deplacement (sur table) :\n")
    for i, (name, fn) in enumerate(DEMOS, 1):
        print(f"  {i:>2}. {name:<9} {fn.__doc__.strip()}")
    print("\n  all  enchaine toutes les demos")
    print("\nex: python3 demo_table.py 4     |     python3 demo_table.py danse dodo\n")


def resoudre(args):
    """Transforme les arguments (numeros ou noms) en liste de demos."""
    if 'all' in args:
        return DEMOS
    choisies = []
    for a in args:
        if a.isdigit() and 1 <= int(a) <= len(DEMOS):
            choisies.append(DEMOS[int(a) - 1])
        else:
            trouve = [d for d in DEMOS if d[0] == a.lower()]
            if trouve:
                choisies.append(trouve[0])
            else:
                print(f"!! demo inconnue : {a}")
    return choisies


def main():
    args = sys.argv[1:]
    if not args:
        liste()
        return

    choisies = resoudre(args)
    if not choisies:
        liste()
        return

    d = Pidog()
    try:
        time.sleep(1)
        for name, fn in choisies:
            print(f"\n>> {name} : {fn.__doc__.strip()}")
            fn(d)
            time.sleep(0.8)
        print("\n-- fin, retour en position assise")
        d.do_action('sit', speed=50)
        d.wait_all_done()
    except KeyboardInterrupt:
        print("\n-- interrompu")
    finally:
        d.close()
        print("close() OK")


if __name__ == '__main__':
    main()
