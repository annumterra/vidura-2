"""
Vidura - web API (runs on Vercel as one Python function, or locally).

Routes
  POST /api/check       paste a message / screenshot -> traffic-light verdict
  POST /api/transcribe  voice recording -> text (Sarvam)
  POST /api/speak       text -> spoken audio (Sarvam)
  GET  /api/config      which features are switched on
  GET  /api/health      simple "I'm alive" check

Privacy: messages, screenshots and voice are never saved or logged.
Vercel functions have no permanent disk, so there are no counters either.
"""
import base64
import logging
import os
import sys
import threading
import time
from collections import defaultdict, deque

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _load_dotenv(path):
    """Tiny .env reader for local runs (Vercel uses its own environment settings)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_dotenv(os.path.join(_ROOT, ".env"))

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

from vidura import engine, rules, sarvam  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vidura")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__)
# Vercel allows request bodies up to about 4.5 MB, so stay under that.
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

PER_USER_HOURLY = int(os.environ.get("VIDURA_PER_USER_HOURLY", "30"))
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_AUDIO_BYTES = 3 * 1024 * 1024
MAX_TEXT = 3000

# Best-effort rate limit. On Vercel each warm instance has its own memory, so
# this is a speed bump, not a wall. The real cost guard is the spend limit you
# set on your OpenAI / Sarvam accounts.
_lock = threading.Lock()
_hits = defaultdict(deque)


def allowed(key: str) -> bool:
    now = time.time()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= PER_USER_HOURLY:
            return False
        q.append(now)
        return True


def _client_key() -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or request.remote_addr or "?")


def _lang() -> str:
    lang = (request.values.get("lang") or "").strip().lower()
    return lang if lang in rules.LANGS else "en"


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return jsonify(
        voice=sarvam.enabled(),
        translate=sarvam.enabled(),
        ai=bool(os.environ.get("OPENAI_API_KEY")),
        languages=list(rules.LANGS),
    )


@app.post("/api/check")
def api_check():
    if not allowed("check:" + _client_key()):
        return jsonify(error="Too many checks from you this hour. Please try again a little later."), 429

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    image_b64 = data.get("image_b64") or None
    image_type = data.get("image_type") or None
    lang = data.get("lang") if data.get("lang") in rules.LANGS else None  # None = guess from the message

    if image_b64:
        if image_type not in engine.ALLOWED_IMAGE_TYPES:
            return jsonify(error="Please send a JPG or PNG screenshot."), 400
        try:
            if len(base64.b64decode(image_b64, validate=True)) > MAX_IMAGE_BYTES:
                return jsonify(error="That picture is too big. Please use a smaller screenshot."), 400
        except ValueError:
            return jsonify(error="That picture could not be read."), 400
    if not text and not image_b64:
        return jsonify(error="Please paste a message or add a screenshot."), 400
    if len(text) > MAX_TEXT:
        return jsonify(error="That message is very long. Please paste the main part (under 3000 letters)."), 400

    result = engine.check_message(text, image_b64, image_type, lang)
    result.pop("flags", None)
    return jsonify(result)


@app.post("/api/transcribe")
def api_transcribe():
    if not sarvam.enabled():
        return jsonify(error="Voice is not switched on."), 503
    if not allowed("voice:" + _client_key()):
        return jsonify(error="Too many requests this hour. Please try again a little later."), 429
    f = request.files.get("audio")
    if not f:
        return jsonify(error="No recording received."), 400
    audio = f.read(MAX_AUDIO_BYTES + 1)
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        return jsonify(error="That recording is empty or too long. Please keep it under 30 seconds."), 400
    try:
        text = sarvam.transcribe(audio, f.filename, f.mimetype, _lang())
    except Exception as e:
        log.warning("transcribe failed: %s", type(e).__name__)
        return jsonify(error="I could not understand the recording. Please try again or type the message."), 502
    return jsonify(text=text)


@app.post("/api/speak")
def api_speak():
    if not sarvam.enabled():
        return jsonify(error="Voice is not switched on."), 503
    if not allowed("voice:" + _client_key()):
        return jsonify(error="Too many requests this hour. Please try again a little later."), 429
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(error="Nothing to read."), 400
    lang = data.get("lang") if data.get("lang") in rules.LANGS else "en"
    try:
        audio = sarvam.speak(text, lang)
    except Exception as e:
        log.warning("speak failed: %s", type(e).__name__)
        return jsonify(error="Could not read this aloud right now."), 502
    return jsonify(audio_b64=audio, mime="audio/wav")


# Local development only: Vercel serves public/ by itself.
@app.get("/")
def index():
    return send_from_directory(os.path.join(ROOT, "public"), "index.html")


@app.get("/<path:name>")
def static_files(name):
    return send_from_directory(os.path.join(ROOT, "public"), name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
