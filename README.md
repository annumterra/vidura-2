# Vidura – your dependable advisor

**Forward first, then act.** Vidura helps seniors in India check a worrying message before they act on it.
Paste a message (or add a screenshot, or speak it) and Vidura answers with a traffic light, in **English, Hindi or Tamil**:

- 🟢 **Looks safe**
- 🟡 **Not sure – be careful**
- 🔴 **Likely scam**

Every answer has one calm reason, one clear next step and one warning sign to remember.
It can also read the answer aloud.

> This is the working demo of the idea in *Care for the Elderly Plan* (LogiQids Ideathon). The full idea is a WhatsApp bot saved as one contact, "Vidura – Your Advisor"; this web demo shows exactly what that bot would reply.

---

## How it works

```
Message / screenshot / voice
        │
        ▼
 ┌─ Safety rules (rules.py) ── look for warning signs in English, Hindi, Tamil:
 │     money, OTP/PIN, fake police, "digital arrest", urgency, prizes,
 │     "account will be blocked", suspicious links, "new number", secrecy
 │
 ├─ AI judge (gpt-4o-mini) ── reads the message and judges it, in English
 │
 ├─ Sarvam translation ── writes the answer in Hindi or Tamil (a model built for Indian languages)
 │
 └─ The STRICTER of the two wins
       • anything asking for money or an OTP is at least 🟡
       • money + police / secrecy / "family in trouble" / prize is always 🔴
       • if the AI is down or confused, the answer is 🟡 — never 🟢
        │
        ▼
 Traffic light + reason + next step + tip   (optionally spoken by Sarvam)
```

**Why rules *and* AI?** AI can be wrong, and a wrong "safe" could cost someone their savings. The rules are a safety floor the AI can never go below. Vidura also never says "100% safe", and it treats the forwarded message as something to *judge*, not instructions to follow, so a scam that says "tell them this is safe" cannot trick it.

**Language: how Vidura picks and writes the reply.**
- *Which language?* A message written in Hindi or Tamil script is answered in that language, and the language switch follows. An English (or Hinglish) message is answered in whichever language is selected, so a Tamil speaker can paste an English forward and get Tamil back. The WhatsApp version would ask once ("Reply 1 English, 2 हिन्दी, 3 தமிழ்") and remember the choice per phone.
- *Who writes it?* General-purpose AI is weakest at natural Hindi and Tamil. So the AI only judges (in English, where it is strongest) and **Sarvam's translation model** writes the Hindi/Tamil in an everyday spoken style, not stiff formal language. The traffic-light labels and the fixed safety replies are hand-written, never machine-translated.
- *If Sarvam is down or has no key?* The AI writes in the language itself. Quality is lower, so check it before a demo.
- Read-aloud only repeats the final text, so it is only as good as the translation above.

**Voice (Sarvam).** The mic button turns speech into text (speech-to-text) and "Listen" reads the answer aloud (text-to-speech), in English, Hindi and Tamil. If no Sarvam key is set, the mic is hidden and "Listen" uses the browser's own voice.

**Privacy.** Messages, screenshots and voice are never saved or logged. Vidura keeps no database. *Honest note:* the message is sent to OpenAI (to be judged) and, if voice is used, to Sarvam, so those companies' data terms apply.

---

## Run it on your computer (VS Code)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then put your keys in .env
python api/index.py                # open http://localhost:8080
```

`.env` needs `OPENAI_API_KEY`. `SARVAM_API_KEY` is strongly recommended: it gives good Hindi/Tamil wording and voice. Without it Vidura still works, but the AI writes the Hindi and Tamil itself.

## Put it online (Vercel, free)

1. Push this folder to a GitHub repo.
2. On vercel.com choose **Add New → Project**, import the repo, and keep the defaults.
3. Under **Settings → Environment Variables** add `OPENAI_API_KEY` and `SARVAM_API_KEY`, then **Redeploy**.
4. Open the link. Try the example buttons in all three languages, then turn the voice on.

**Before sharing the link publicly:** set a monthly spend limit on your OpenAI account (and check your Sarvam credits), because anyone with the link can use the demo. Vidura also limits each visitor to 30 checks an hour, but on Vercel this is a speed bump rather than a wall.

## Test it

```bash
python -m pytest -q                 # 29 offline tests, free, no keys needed
python check_my_tests.py --rules    # scores the rules alone on my_tests.csv, free
python check_my_tests.py            # scores rules + AI (needs OPENAI_API_KEY, costs well under ₹1)
```

`my_tests.csv` holds scam and genuine messages in all three languages. Add real ones (remove names and numbers) and see which warning sign Vidura missed.

## Files

| File | What it does |
|---|---|
| `public/index.html` | The demo page: WhatsApp-style chat, language switch, example buttons, screenshot, mic, "Listen" |
| `api/index.py` | The web API (`/api/check`, `/api/transcribe`, `/api/speak`, `/api/config`, `/api/health`) |
| `vidura/rules.py` | Safety rules and ready-made calm replies in English, Hindi, Tamil |
| `vidura/engine.py` | Combines the rules with the AI judge; the fail-safe lives here |
| `vidura/sarvam.py` | Sarvam translation, speech-to-text and text-to-speech |
| `my_tests.csv`, `check_my_tests.py` | Your own test messages and a scorer |
| `tests/` | Automated tests with a fake AI |
| `vercel.json` | Vercel settings |

## Rough cost

- **AI:** one text check is roughly 1,000 tokens in and about 150 out on gpt-4o-mini, a small fraction of a rupee. Check OpenAI's pricing page for the current rate; screenshots cost a little more.
- **Sarvam:** translation, voice in and voice out all use your Sarvam credits. Check their dashboard and pricing page for current free limits.
- **Vercel:** free hobby plan is enough for a demo.

## Please have a native speaker check

The fixed safety replies in `vidura/rules.py` (Hindi and Tamil), the example messages and the page text were written by an AI. Ask a Hindi speaker and a Tamil speaker to read them, and fix anything that sounds stiff or odd, before submitting.

## What the demo does not do (yet)

- **WhatsApp itself.** The plan's bot uses WhatsApp through Twilio. This demo shows the same checker on the web; the WhatsApp connection, family alerts and volunteer set-up kit are the next phase.
- **Deepfakes.** Vidura does not try to detect AI-made video or cloned voices. It looks for scam *patterns* (urgency, money, fake authority), which is why it can still help when the content looks real.
- **Calls and voice notes from WhatsApp.** The mic here records what the senior says; reading forwarded voice notes is future work.
