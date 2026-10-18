"""
Sarvam AI helpers: speech-to-text (mic) and text-to-speech (read-aloud).

Both need SARVAM_API_KEY. Without it, the website simply hides the mic button
and uses the browser's own voice for "Listen".
"""
import logging
import os

import requests

log = logging.getLogger("vidura")

BASE = "https://api.sarvam.ai"
STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v3")
TTS_MODEL = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3")
# Speaker names must match the TTS model (bulbul:v3 names: priya, kavya, shubh, ...).
TTS_SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER", "priya")
TIMEOUT = float(os.environ.get("SARVAM_TIMEOUT", "20"))

TRANSLATE_MODEL = os.environ.get("SARVAM_TRANSLATE_MODEL", "mayura:v1")
# modern-colloquial = how people actually speak; "formal" sounds stiff to many seniors.
TRANSLATE_MODE = os.environ.get("SARVAM_TRANSLATE_MODE", "modern-colloquial")

LANG_CODES = {"en": "en-IN", "hi": "hi-IN", "ta": "ta-IN"}


def enabled() -> bool:
    return bool(os.environ.get("SARVAM_API_KEY"))


def _headers():
    return {"api-subscription-key": os.environ.get("SARVAM_API_KEY", "")}


def transcribe(audio_bytes: bytes, filename: str, content_type: str, lang: str) -> str:
    """Turn a short voice recording into text. Returns the transcript."""
    data = {"model": STT_MODEL, "language_code": LANG_CODES.get(lang, "unknown")}
    # saaras:v3 supports a mode; plain transcription is what we want.
    if STT_MODEL == "saaras:v3":
        data["mode"] = "transcribe"
    r = requests.post(
        f"{BASE}/speech-to-text",
        headers=_headers(),
        files={"file": (filename or "voice.webm", audio_bytes, content_type or "audio/webm")},
        data=data,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return (r.json().get("transcript") or "").strip()


def speak(text: str, lang: str) -> str:
    """Turn text into speech. Returns base64-encoded WAV audio."""
    text = (text or "").strip()[:1500]
    payload = {
        "text": text,
        "language_code": LANG_CODES.get(lang, "en-IN"),
        "model": TTS_MODEL,
        "speaker": TTS_SPEAKER,
        "pace": 0.9,  # a little slower, kinder for listeners
    }
    r = requests.post(f"{BASE}/text-to-speech", headers=_headers(), json=payload, timeout=TIMEOUT)
    if r.status_code in (400, 422) and "language_code" in payload:
        # Older API docs call this field target_language_code; retry once.
        payload["target_language_code"] = payload.pop("language_code")
        r = requests.post(f"{BASE}/text-to-speech", headers=_headers(), json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    audios = r.json().get("audios") or []
    return audios[0] if audios else ""


def translate(text: str, lang: str) -> str:
    """Translate short English text into Hindi or Tamil with Sarvam's translation model."""
    payload = {
        "input": text.strip()[:1000],
        "source_language_code": "en-IN",
        "target_language_code": LANG_CODES[lang],
        "model": TRANSLATE_MODEL,
        "numerals_format": "international",
    }
    if TRANSLATE_MODEL == "mayura:v1":  # only this model supports modes
        payload["mode"] = TRANSLATE_MODE
    r = requests.post(f"{BASE}/translate", headers=_headers(), json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return (r.json().get("translated_text") or "").strip()
