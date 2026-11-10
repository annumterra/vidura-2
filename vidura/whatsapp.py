"""
Vidura on WhatsApp (through Twilio).

Twilio calls POST /api/whatsapp every time someone messages the Vidura number.
The message is checked by the same engine as the website, and the answer is
sent back as the reply.

Handles: typed or forwarded text, screenshots (photos), and voice notes
(voice notes need SARVAM_API_KEY for speech-to-text).

Settings (Vercel -> Environment Variables):
  TWILIO_ACCOUNT_SID    from the Twilio console (needed to open photos / voice notes)
  TWILIO_AUTH_TOKEN     from the Twilio console (proves a request really came from Twilio)
  WHATSAPP_WEBHOOK_URL  optional: the exact URL typed into Twilio, only if replies
                        fail with a 403 "bad signature" in the Twilio logs

Privacy: like the website, nothing is saved, and phone numbers and messages
are never written to the logs.
"""
import base64
import hashlib
import hmac
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from xml.sax.saxutils import escape

import requests
from flask import Response

from . import engine, rules, sarvam

log = logging.getLogger("vidura")

# Twilio waits about 15 seconds for a reply. If the check takes longer than
# this, Vidura sends a careful "not sure" answer instead of no answer at all.
TIME_LIMIT = float(os.environ.get("VIDURA_WA_TIME_LIMIT", "12"))
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_AUDIO_BYTES = 3 * 1024 * 1024
MAX_TEXT = 3000
MAX_REPLY = 1500  # WhatsApp messages through Twilio must stay under 1,600 characters

_pool = ThreadPoolExecutor(max_workers=4)

ICONS = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

GREETINGS = {
    "hi", "hii", "hello", "hey", "namaste", "namaskar", "vanakkam", "start", "help",
    "नमस्ते", "नमस्कार", "வணக்கம்",
}

# Fixed messages (hand-written; ask a native speaker to check the Hindi and Tamil).
WELCOME = (
    "🙏 Namaste! I am *Vidura*, your dependable advisor.\n"
    "Forward me any message that worries you, or send a screenshot or a voice note. "
    "I will tell you if it looks safe.\n\n"
    "🙏 नमस्ते! मैं *विदुर* हूँ। कोई भी शक वाला संदेश मुझे फ़ॉरवर्ड करें, "
    "या उसका स्क्रीनशॉट या वॉइस नोट भेजें। मैं बताऊँगा कि वह सुरक्षित लगता है या नहीं।\n\n"
    "🙏 வணக்கம்! நான் *விதுரர்*. சந்தேகமான எந்தச் செய்தியையும் எனக்கு அனுப்புங்கள், "
    "அல்லது ஸ்கிரீன்ஷாட் அல்லது குரல் செய்தி அனுப்புங்கள். அது பாதுகாப்பானதா என்று சொல்கிறேன்."
)
UNSUPPORTED = (
    "I can check text, screenshots and voice notes. Please send one of those.\n"
    "मैं टेक्स्ट, स्क्रीनशॉट और वॉइस नोट जाँच सकता हूँ। कृपया इनमें से कोई भेजें।\n"
    "என்னால் உரை, ஸ்கிரீன்ஷாட், குரல் செய்தி ஆகியவற்றைச் சோதிக்க முடியும். அவற்றில் ஒன்றை அனுப்புங்கள்."
)
VOICE_FAILED = (
    "I could not understand the voice note. Please type the message or send a screenshot.\n"
    "मैं वॉइस नोट समझ नहीं पाया। कृपया संदेश लिखकर भेजें या स्क्रीनशॉट भेजें।\n"
    "குரல் செய்தியைப் புரிந்துகொள்ள முடியவில்லை. செய்தியை டைப் செய்யுங்கள் அல்லது ஸ்கிரீன்ஷாட் அனுப்புங்கள்."
)
TOO_BIG = (
    "That file is too big. Please send a smaller screenshot or a shorter voice note.\n"
    "यह फ़ाइल बहुत बड़ी है। कृपया छोटा स्क्रीनशॉट या छोटा वॉइस नोट भेजें।\n"
    "இந்தக் கோப்பு மிகப் பெரியது. சிறிய ஸ்கிரீன்ஷாட் அல்லது சுருக்கமான குரல் செய்தி அனுப்புங்கள்."
)
TOO_MANY = (
    "You have sent many messages this hour. Please try again a little later.\n"
    "इस घंटे बहुत सारे संदेश आ गए हैं। थोड़ी देर बाद फिर कोशिश करें।\n"
    "இந்த மணி நேரத்தில் நிறைய செய்திகள் வந்துவிட்டன. சிறிது நேரம் கழித்து மீண்டும் முயலுங்கள்."
)


class _TooBig(Exception):
    pass


# ---------- the reply ----------

def format_reply(r: dict) -> str:
    """Turn the engine's answer into one WhatsApp message."""
    parts = [f"{ICONS[r['verdict']]} *{r['label']}*", r.get("reason", "")]
    if r.get("next_step"):
        parts.append("👉 " + r["next_step"])
    if r.get("tip"):
        parts.append("💡 " + r["tip"])
    return "\n\n".join(p.strip() for p in parts if p and p.strip())[:MAX_REPLY]


def careful_fallback(text: str) -> str:
    """Used if checking failed or took too long. Never green; the rules still apply."""
    flags = rules.scan(text)
    lang = rules.detect_lang(text)
    verdict = rules.stricter("yellow", rules.floor_verdict(flags))
    return format_reply({
        "verdict": verdict,
        "label": rules.LABELS[verdict][lang],
        "reason": rules.rule_reason(flags, lang) if flags else rules.COULD_NOT_CHECK[lang],
        "next_step": rules.NEXT_STEPS[verdict][lang],
    })


def _is_greeting(text: str) -> bool:
    words = text.lower().split()
    return 0 < len(words) <= 3 and words[0].strip("!.,?🙏 ") in GREETINGS


def _download(url: str, limit: int) -> bytes:
    """Fetch a photo or voice note from Twilio (Twilio asks for the account login)."""
    auth = (os.environ.get("TWILIO_ACCOUNT_SID", ""), os.environ.get("TWILIO_AUTH_TOKEN", ""))
    r = requests.get(url, auth=auth, timeout=8, stream=True)
    r.raise_for_status()
    data = r.raw.read(limit + 1, decode_content=True)
    if len(data) > limit:
        raise _TooBig()
    return data


def answer(form: dict) -> str:
    """Work out the reply for one incoming WhatsApp message."""
    text = (form.get("Body") or "").strip()[:MAX_TEXT]
    try:
        num_media = int(form.get("NumMedia") or 0)
    except ValueError:
        num_media = 0

    if num_media == 0:
        if not text:
            return UNSUPPORTED
        if _is_greeting(text):
            return WELCOME
        return format_reply(engine.check_message(text))

    ctype = (form.get("MediaContentType0") or "").split(";")[0].strip().lower()
    url = form.get("MediaUrl0") or ""

    if ctype in engine.ALLOWED_IMAGE_TYPES:
        image = _download(url, MAX_IMAGE_BYTES)
        return format_reply(engine.check_message(text, base64.b64encode(image).decode(), ctype))

    if ctype.startswith("audio/") and sarvam.enabled():
        audio = _download(url, MAX_AUDIO_BYTES)
        try:
            heard = sarvam.transcribe(audio, "voice.ogg", ctype, "auto")  # "auto" -> Sarvam guesses the language
        except Exception as e:
            log.warning("WhatsApp voice note could not be transcribed: %s", type(e).__name__)
            return VOICE_FAILED
        if not heard:
            return VOICE_FAILED
        return format_reply(engine.check_message(f"{text}\n{heard}".strip()[:MAX_TEXT]))

    return UNSUPPORTED


# ---------- talking to Twilio ----------

def _public_url(req) -> str:
    """The URL Twilio called, which Twilio uses to sign the request."""
    override = os.environ.get("WHATSAPP_WEBHOOK_URL", "").strip()
    if override:
        return override
    proto = (req.headers.get("x-forwarded-proto") or "https").split(",")[0].strip()
    host = (req.headers.get("x-forwarded-host") or req.host).split(",")[0].strip()
    qs = req.query_string.decode()
    return f"{proto}://{host}{req.path}" + (f"?{qs}" if qs else "")


def signature_ok(req) -> bool:
    """True only if the request really came from our Twilio account."""
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    sig = req.headers.get("X-Twilio-Signature", "")
    if not token or not sig:
        return False
    payload = _public_url(req) + "".join(k + v for k, v in sorted(req.form.items(multi=True)))
    digest = base64.b64encode(
        hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(digest, sig)


def _twiml(message: str) -> Response:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f"<Response><Message>{escape(message)}</Message></Response>")
    return Response(xml, mimetype="text/xml")


def webhook(req, allowed) -> Response:
    """Flask handler body for POST /api/whatsapp. `allowed` is the app's rate limiter."""
    if not os.environ.get("TWILIO_AUTH_TOKEN"):
        return Response("WhatsApp is not switched on.", status=503)
    if not signature_ok(req):
        log.warning("Rejected a WhatsApp request without a valid Twilio signature")
        return Response("Forbidden", status=403)

    form = req.form.to_dict()  # a plain copy, safe to use outside the request
    if not allowed("wa:" + form.get("From", "?")):
        return _twiml(TOO_MANY)

    future = _pool.submit(answer, form)
    try:
        reply = future.result(timeout=TIME_LIMIT)
    except FutureTimeout:
        log.warning("WhatsApp check took too long; sent the careful answer")
        reply = careful_fallback(form.get("Body") or "")
    except _TooBig:
        reply = TOO_BIG
    except Exception as e:
        log.warning("WhatsApp check failed: %s", type(e).__name__)
        reply = careful_fallback(form.get("Body") or "")
    return _twiml(reply)
