#!/usr/bin/env python3
"""
Serveur STT + interpretation de pidog-voice — tourne sur le MAC.

Garde le modele faster-whisper resident en RAM et transcrit les WAV envoyes
par le robot. Biaise le vocabulaire vers les commandes PiDog via initial_prompt,
ce qui est indispensable : sans ca, Whisper transcrit "pidog" en "qui doit".

Endpoints
    GET  /health              -> {"ok": true, "model": "...", "charge": true}
    POST /stt   (corps = WAV) -> {"texte": "...", "latence": 0.34}
    POST /command (corps=WAV) -> {"texte": ..., "action": ..., "confiance": ...}
                                 (STT + interpretation Ollama en un seul aller-retour)

Lancement :
    ~/.claude/skills/youtube-transcript/venv/bin/python ~/Documents/PiDog/stt_server.py
"""
import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

PORT = int(os.environ.get("PIDOG_STT_PORT", 8770))
MODELE = os.environ.get("PIDOG_WHISPER", "small")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
LLM = os.environ.get("PIDOG_MODEL", "llama3.2:latest")
MAX_WAV = 8 * 1024 * 1024

CFG = Config()
ACTIONS = CFG.catalogue()
BIAIS = CFG.biais()          # <- genere depuis commandes.json, plus de doublon
SYSTEM = CFG.systeme()
SHOTS = CFG.exemples()
SCHEMA = CFG.schema()

print(f"[stt] chargement de faster-whisper '{MODELE}' ...", flush=True)
from faster_whisper import WhisperModel  # noqa: E402

_t0 = time.time()
MODEL = WhisperModel(MODELE, device="cpu", compute_type="int8")
print(f"[stt] modele pret en {time.time() - _t0:.1f}s", flush=True)


def transcrire(wav_bytes):
    import io
    t0 = time.time()
    segs, _ = MODEL.transcribe(
        io.BytesIO(wav_bytes), language="fr", beam_size=1,
        vad_filter=True, initial_prompt=BIAIS,
        # Sans ceci, Whisper part en boucle sur du bruit : constate le 23/08/2026,
        # « PiDog est fort. » repete 37 fois, 39 s de transcription — pendant
        # lesquelles le robot est sourd et ne peut plus recevoir « stop ».
        condition_on_previous_text=False,
        no_speech_threshold=0.5,
        compression_ratio_threshold=2.0)   # rejette les sorties trop repetitives
    texte = " ".join(s.text.strip() for s in segs).strip()
    return texte, round(time.time() - t0, 2)


def interpreter(texte):
    msgs = [{"role": "system", "content": SYSTEM}]
    for p, a in SHOTS:
        msgs += [{"role": "user", "content": p},
                 {"role": "assistant", "content": json.dumps({"action": a, "confiance": 0.95})}]
    msgs.append({"role": "user", "content": texte})
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat",
        data=json.dumps({
            "model": LLM, "messages": msgs, "stream": False, "think": False,
            "format": SCHEMA,
            "options": {"temperature": 0, "num_predict": 64},
        }).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    out = json.loads(data["message"]["content"])
    out["latence_llm"] = round(time.time() - t0, 2)
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _repondre(self, code, obj):
        corps = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _lire_wav(self):
        n = int(self.headers.get("Content-Length", 0))
        if not 44 < n <= MAX_WAV:
            self._repondre(400, {"erreur": f"taille WAV invalide : {n} octets"})
            return None
        return self.rfile.read(n)

    def do_GET(self):
        if self.path == "/health":
            self._repondre(200, {"ok": True, "model": MODELE, "llm": LLM,
                                 "routes": ["/stt", "/command", "/interpret"]})
        else:
            self._repondre(404, {"erreur": "route inconnue"})

    def do_POST(self):
        # /interpret : le Pi a deja transcrit en local, il n'envoie que du texte
        if self.path == "/interpret":
            n = int(self.headers.get("Content-Length", 0))
            if not 0 < n <= 8192:
                return self._repondre(400, {"erreur": "corps invalide"})
            try:
                texte = json.loads(self.rfile.read(n)).get("texte", "").strip()
            except Exception as e:
                return self._repondre(400, {"erreur": f"JSON illisible: {e}"})
            if not texte:
                return self._repondre(200, {"action": "inconnu", "confiance": 0.0})
            try:
                return self._repondre(200, interpreter(texte))
            except Exception as e:
                return self._repondre(200, {"action": "inconnu", "confiance": 0.0,
                                            "erreur": f"LLM: {type(e).__name__}: {e}"})
        if self.path not in ("/stt", "/command"):
            return self._repondre(404, {"erreur": "route inconnue"})
        wav = self._lire_wav()
        if wav is None:
            return
        try:
            texte, lat = transcrire(wav)
        except Exception as e:
            return self._repondre(500, {"erreur": f"STT: {type(e).__name__}: {e}"})
        if self.path == "/stt":
            return self._repondre(200, {"texte": texte, "latence": lat})
        if not texte:
            return self._repondre(200, {"texte": "", "action": "inconnu",
                                        "confiance": 0.0, "latence_stt": lat})
        try:
            out = interpreter(texte)
        except Exception as e:
            return self._repondre(200, {"texte": texte, "action": "inconnu",
                                        "confiance": 0.0, "latence_stt": lat,
                                        "erreur": f"LLM: {type(e).__name__}: {e}"})
        out.update(texte=texte, latence_stt=lat)
        self._repondre(200, out)

    def log_message(self, fmt, *a):
        print(f"[stt] {self.address_string()} {fmt % a}", flush=True)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print(f"[stt] ecoute sur http://0.0.0.0:{PORT}  (whisper={MODELE}, llm={LLM})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[stt] arret")
        srv.shutdown()
