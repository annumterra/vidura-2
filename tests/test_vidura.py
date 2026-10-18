"""
Offline tests: a fake AI stands in for OpenAI, so these are free and need no keys.
Run:  python -m pytest -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from vidura import engine, rules  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch):
    """Tests never touch real services, even if a .env with keys exists."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("SARVAM_API_KEY", "")


def fake_ai(verdict="green", **extra):
    reply = {"verdict": verdict, "label": "ok", "reason": "because", "next_step": "do this", "tip": "tip"}
    reply.update(extra)

    def _ai(text, image_b64, image_type, hints, lang):
        return json.dumps(reply)
    return _ai


def broken_ai(*a, **k):
    raise RuntimeError("no network")


# ---------- the rules are a floor the AI cannot go below ----------
SCAMS = {
    "en": "Inspector Sharma, Cyber Crime. You are under digital arrest. Transfer Rs 95,000 now. Do not tell your family.",
    "hi": "आप डिजिटल अरेस्ट में हैं। अभी 95,000 रुपये ट्रांसफर करें।",
    "ta": "நீங்கள் டிஜிட்டல் கைதில் உள்ளீர்கள். உடனே 95,000 ரூபாய் அனுப்புங்கள். குடும்பத்தினரிடம் சொல்லாதீர்கள்.",
}


@pytest.mark.parametrize("lang", ["en", "hi", "ta"])
def test_ai_saying_green_cannot_beat_rules(lang):
    r = engine.check_message(SCAMS[lang], lang=lang, ai=fake_ai("green"))
    assert r["verdict"] == "red"
    assert r["source"] == "ai+rules"
    assert r["reason"] == rules.RULE_REASONS["digital_arrest"][lang]


def test_money_alone_is_at_least_yellow():
    r = engine.check_message("Please pay Rs 500 to my UPI", lang="en", ai=fake_ai("green"))
    assert r["verdict"] in ("yellow", "red")


def test_otp_with_urgency_is_red():
    r = engine.check_message("Share your OTP immediately", lang="en", ai=fake_ai("green"))
    assert r["verdict"] == "red"


def test_family_message_can_be_green():
    r = engine.check_message("Beta, bhajan at the temple at 7 pm today. Will you come? - Nani",
                             lang="en", ai=fake_ai("green"))
    assert r["verdict"] == "green"


def test_ordinary_use_of_fine_is_not_money():
    assert "money" not in rules.scan("I am fine, how are you?")


# ---------- fail-safe ----------
@pytest.mark.parametrize("lang", ["en", "hi", "ta"])
def test_ai_failure_is_never_green(lang):
    r = engine.check_message("hello", lang=lang, ai=broken_ai)
    assert r["verdict"] == "yellow" and r["source"] == "fallback"
    assert r["reason"] == rules.COULD_NOT_CHECK[lang]


def test_ai_failure_still_uses_rules():
    r = engine.check_message(SCAMS["en"], lang="en", ai=broken_ai)
    assert r["verdict"] == "red"


def test_garbage_ai_reply_falls_back():
    r = engine.check_message("hello", lang="en", ai=lambda *a: "not json at all")
    assert r["verdict"] == "yellow" and r["source"] == "fallback"


def test_overconfident_wording_is_softened():
    r = engine.check_message("hello", lang="en", ai=fake_ai("green", reason="This is 100% safe"))
    assert "100%" not in r["reason"]


# ---------- language ----------
def test_language_detection():
    assert rules.detect_lang("नमस्ते आप कैसे हैं") == "hi"
    assert rules.detect_lang("வணக்கம் எப்படி இருக்கிறீர்கள்") == "ta"
    assert rules.detect_lang("hello there") == "en"


def test_every_rule_has_all_three_languages():
    for name, texts in rules.RULE_REASONS.items():
        assert set(texts) == set(rules.LANGS), name
    for table in (rules.NEXT_STEPS, rules.LABELS):
        for name, texts in table.items():
            assert set(texts) == set(rules.LANGS), name


# ---------- web routes ----------
@pytest.fixture()
def client(monkeypatch):
    from api import index
    index._hits.clear()
    index.app.config["TESTING"] = True
    return index.app.test_client()


def test_check_without_ai_key_fails_safe(client):
    r = client.post("/api/check", json={"text": "hello", "lang": "en"})
    assert r.status_code == 200
    assert r.get_json()["verdict"] == "yellow"


def test_check_rejects_empty(client):
    assert client.post("/api/check", json={"text": "  "}).status_code == 400


def test_check_does_not_leak_flags(client):
    j = client.post("/api/check", json={"text": SCAMS["en"], "lang": "en"}).get_json()
    assert "flags" not in j and j["verdict"] == "red"


def test_voice_off_without_key(client):
    assert client.get("/api/config").get_json()["voice"] is False
    assert client.post("/api/speak", json={"text": "hi"}).status_code == 503


def test_rate_limit(client):
    from api import index
    for _ in range(index.PER_USER_HOURLY):
        assert client.post("/api/check", json={"text": "hi"}).status_code == 200
    assert client.post("/api/check", json={"text": "hi"}).status_code == 429


# ---------- outside services (mocked, no network) ----------
class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_openai_request_and_parse(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        seen.update(url=url, headers=headers, body=json)
        reply = {"verdict": "yellow", "label": "x", "reason": "r", "next_step": "n", "tip": "t"}
        import json as _j
        return FakeResp({"choices": [{"message": {"content": _j.dumps(reply)}}]})

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(engine.requests, "post", fake_post)
    r = engine.check_message("hello", image_b64="QUJD", image_type="image/png", lang="ta")
    assert r["verdict"] == "yellow" and r["source"] == "ai"
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    assert seen["body"]["model"] == "gpt-4o-mini"
    assert "Tamil" in seen["body"]["messages"][0]["content"]
    parts = seen["body"]["messages"][1]["content"]
    assert any(p["type"] == "image_url" for p in parts)


def test_sarvam_calls(monkeypatch):
    from vidura import sarvam
    calls = []

    def fake_post(url, headers=None, json=None, files=None, data=None, timeout=None):
        calls.append((url, json, data))
        if url.endswith("/speech-to-text"):
            return FakeResp({"transcript": " नमस्ते "})
        return FakeResp({"audios": ["UklGRg=="]})

    monkeypatch.setenv("SARVAM_API_KEY", "k")
    monkeypatch.setattr(sarvam.requests, "post", fake_post)
    assert sarvam.transcribe(b"x", "v.webm", "audio/webm", "hi") == "नमस्ते"
    assert calls[0][2]["language_code"] == "hi-IN"
    assert sarvam.speak("hello", "ta") == "UklGRg=="
    assert calls[1][1]["language_code"] == "ta-IN" and calls[1][1]["model"] == "bulbul:v3"


# ---------- Hindi / Tamil go through Sarvam translation ----------
def recording_ai(log):
    def _ai(text, image_b64, image_type, hints, lang):
        log.append(lang)
        return json.dumps({"verdict": "yellow", "reason": "Banks never ask for OTP.",
                           "next_step": "Call your son.", "tip": "Urgency is a warning sign."})
    return _ai


def test_hindi_is_judged_in_english_then_translated():
    langs, seen = [], []

    def tr(text, lang):
        seen.append((text, lang))
        return "[" + lang + "] " + text

    r = engine.check_message("hello", lang="hi", ai=recording_ai(langs), translate=tr)
    assert langs == ["en"]                       # the AI judged in English
    assert r["source"] == "ai+translate"
    assert r["reason"].startswith("[hi] ") and r["tip"].startswith("[hi] ")
    assert r["label"] == rules.LABELS["yellow"]["hi"]   # hand-written, not translated
    assert len(seen) == 3


def test_english_is_never_translated():
    langs = []
    r = engine.check_message("hello", lang="en", ai=recording_ai(langs),
                             translate=lambda t, l: 1 / 0)
    assert langs == ["en"] and r["source"] == "ai"


def test_translation_failure_falls_back_to_ai_writing_directly():
    langs = []
    r = engine.check_message("hello", lang="ta", ai=recording_ai(langs),
                             translate=lambda t, l: 1 / 0)
    assert langs == ["en", "ta"]                 # tried English first, then asked for Tamil
    assert r["source"] == "ai" and r["verdict"] == "yellow"


def test_empty_translation_counts_as_failure():
    langs = []
    engine.check_message("hello", lang="hi", ai=recording_ai(langs), translate=lambda t, l: "")
    assert langs == ["en", "hi"]


def test_rules_override_uses_hand_written_text_not_translation():
    r = engine.check_message(SCAMS["hi"], lang="hi", ai=fake_ai("green"),
                             translate=lambda t, l: "TRANSLATED")
    assert r["verdict"] == "red" and r["source"] == "ai+rules"
    assert r["reason"] == rules.RULE_REASONS["digital_arrest"]["hi"]


def test_ai_down_does_not_retry_and_still_fails_safe():
    calls = []

    def dead(*a):
        calls.append(1)
        raise RuntimeError("down")

    r = engine.check_message("hello", lang="ta", ai=dead, translate=lambda t, l: "x")
    assert len(calls) == 1 and r["verdict"] == "yellow" and r["source"] == "fallback"


def test_sarvam_translate_request(monkeypatch):
    from vidura import sarvam
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        seen.update(url=url, body=json)
        return FakeResp({"translated_text": " வணக்கம் "})

    monkeypatch.setenv("SARVAM_API_KEY", "k")
    monkeypatch.setattr(sarvam.requests, "post", fake_post)
    assert sarvam.translate("Hello", "ta") == "வணக்கம்"
    assert seen["url"].endswith("/translate")
    b = seen["body"]
    assert b["source_language_code"] == "en-IN" and b["target_language_code"] == "ta-IN"
    assert b["model"] == "mayura:v1" and b["mode"] == "modern-colloquial"
