"""
Vidura safety rules.

Simple keyword rules that run on every message. They set a minimum ("floor")
verdict, so even if the AI makes a mistake, a message asking for money or an
OTP can never be marked green.

Order of verdicts: green < yellow < red
Languages: English, Hinglish (Hindi typed in English letters), Hindi, Tamil.
"""
import re

# Each rule: name -> regex (checked on lower-cased text).
# Note: \b does not work well next to Indic scripts, so Hindi/Tamil words are
# matched without it.
PATTERNS = {
    "otp": (
        r"\botp\b|one[- ]time password|\bpin\b|\bcvv\b|password|"
        r"ओटीपी|पिन|पासवर्ड|"
        r"ஓடிபி|பின் எண்|கடவுச்சொல்"
    ),
    "money": (
        r"\bpay\b|payment|transfer|send money|\bupi\b|gpay|google pay|phonepe|paytm|"
        r"bank account|account number|deposit|pay (a |the )?fine|\bfine (of|amount)|penalty|"
        r"processing fee|refund|"
        r"₹|\brs\.?\s?\d|rupees|\bpaise\b|\bpaisa\b|paise bhej|"
        r"पैसे|रुपये|भुगतान|जमा कर|"
        r"பணம்|ரூபாய்|செலுத்த|கட்டணம்|அபராதம்|வங்கிக் கணக்கு|அனுப்பு"
    ),
    "authority": (
        r"police|\bcbi\b|enforcement directorate|customs|narcotics|\bncb\b|\brbi\b|"
        r"income tax|\bcourt\b|\bjudge\b|cyber cell|cyber crime|\btrai\b|"
        r"पुलिस|सीबीआई|अदालत|कोर्ट|कस्टम|"
        r"காவல்|போலீஸ்|சிபிஐ|நீதிமன்றம்|சுங்கத்துறை|சைபர் கிரைம்"
    ),
    "digital_arrest": (
        r"digital arrest|arrest warrant|you (are|will be) (under )?arrest|"
        r"stay on (the )?(video )?call|"
        r"डिजिटल अरेस्ट|गिरफ्तार|"
        r"டிஜிட்டல் கைத|கைது செய்|கைதாவீர்கள்"  # "கைத" covers கைது / கைதில் (case endings)
    ),
    "urgency": (
        r"urgent|immediately|within \d+ ?(minutes|mins|hours|hrs)|today itself|right now|"
        r"last chance|act now|\bturant\b|\bjaldi\b|"
        r"तुरंत|जल्दी|अभी के अभी|"
        r"உடனடியாக|உடனே|அவசரம்|இப்போதே"
    ),
    "prize": (
        r"lottery|lucky draw|you (have )?won|\bprize\b|\breward\b|cashback|\bkbc\b|"
        r"\binaam\b|इनाम|लॉटरी|"
        r"பரிசு|லாட்டரி|அதிர்ஷ்ட"
    ),
    "account_block": (
        r"\bkyc\b|account (will be |has been )?(blocked|suspended|closed|frozen)|"
        r"sim (will be |has been )?(blocked|deactivated)|"
        r"(electricity|bijli|power) (will be )?(cut|disconnected)|"
        r"बिजली.*(कट|काट)|खाता.*बंद|"
        r"கணக்கு.*(முடக்க|நிறுத்த|மூடப்)|மின்சாரம்.*(துண்டி|நிறுத்த)|சிம்.*(முடக்க|நிறுத்த)"
    ),
    "link": r"https?://|www\.|bit\.ly|tinyurl|\.apk\b",
    "family_emergency": (
        r"accident|hospital|in trouble|my new number|this is my new number|"
        r"lost my phone|"
        r"मुसीबत|अस्पताल|हादसा|नया नंबर|"
        r"விபத்து|மருத்துவமனை|புதிய எண்|புது நம்பர்|ஆபத்தில்"
    ),
    "secrecy": (
        r"don'?t tell anyone|do not tell (anyone|your family)|keep (this )?secret|"
        r"kisi ko mat batana|"
        r"किसी को मत बताना|किसी को न बताएं|"
        r"யாரிடமும் சொல்லாதீர்கள்|யாரிடமும் சொல்ல வேண்டாம்|ரகசியம்"
    ),
}

COMPILED = {name: re.compile(p, re.IGNORECASE) for name, p in PATTERNS.items()}

ORDER = {"green": 0, "yellow": 1, "red": 2}
LANGS = ("en", "hi", "ta")
LANG_NAMES = {"en": "English", "hi": "Hindi (Devanagari script)", "ta": "Tamil (Tamil script)"}


def scan(text: str) -> list:
    """Return the list of rule names found in the text."""
    if not text:
        return []
    t = text.lower()
    return [name for name, rx in COMPILED.items() if rx.search(t)]


def floor_verdict(flags: list) -> str:
    """The lowest verdict Vidura is allowed to give, based on the rules."""
    f = set(flags)
    # Strong combinations -> red
    if "digital_arrest" in f:
        return "red"
    if "money" in f and f & {"authority", "secrecy", "family_emergency", "prize"}:
        return "red"
    if "otp" in f and f & {"authority", "urgency", "account_block", "prize"}:
        return "red"
    # Single warning signs -> at least yellow
    if f & {"money", "otp", "account_block", "prize", "secrecy"}:
        return "yellow"
    if "link" in f and "urgency" in f:
        return "yellow"
    return "green"


def stricter(a: str, b: str) -> str:
    """Return whichever verdict is more cautious."""
    return a if ORDER[a] >= ORDER[b] else b


def _script_share(text: str, lo: str, hi: str) -> float:
    letters = sum(1 for ch in text if ch.isalpha())
    if not letters:
        return 0.0
    return sum(1 for ch in text if lo <= ch <= hi) / letters


def is_hindi(text: str) -> bool:
    """True if the message is mostly written in Devanagari script."""
    return _script_share(text or "", "ऀ", "ॿ") > 0.3


def is_tamil(text: str) -> bool:
    """True if the message is mostly written in Tamil script."""
    return _script_share(text or "", "஀", "௿") > 0.3


def detect_lang(text: str) -> str:
    if is_tamil(text):
        return "ta"
    if is_hindi(text):
        return "hi"
    return "en"


# Short, calm explanations used when the rules have to override the AI.
RULE_REASONS = {
    "digital_arrest": {
        "en": "Real police never arrest anyone over a video call or ask you to stay on a call.",
        "hi": "असली पुलिस कभी वीडियो कॉल पर गिरफ्तार नहीं करती और न ही कॉल पर बने रहने को कहती है।",
        "ta": "உண்மையான காவல்துறை வீடியோ அழைப்பில் யாரையும் கைது செய்யாது; அழைப்பிலேயே இருக்கவும் சொல்லாது.",
    },
    "authority": {
        "en": "Police, banks and government offices never ask for money or OTPs on WhatsApp.",
        "hi": "पुलिस, बैंक या सरकारी दफ़्तर कभी WhatsApp पर पैसे या OTP नहीं माँगते।",
        "ta": "காவல்துறை, வங்கி அல்லது அரசு அலுவலகம் WhatsApp-இல் பணமோ OTP-யோ கேட்காது.",
    },
    "otp": {
        "en": "Never share an OTP or PIN. No genuine person or bank will ask for it.",
        "hi": "OTP या PIN कभी किसी को न बताएं। कोई असली व्यक्ति या बैंक इसे नहीं माँगता।",
        "ta": "OTP அல்லது PIN-ஐ யாரிடமும் சொல்லாதீர்கள். உண்மையான வங்கியோ நபரோ அதைக் கேட்க மாட்டார்கள்.",
    },
    "family_emergency": {
        "en": "Scammers often pretend to be a family member in trouble. Call that person on their old number first.",
        "hi": "ठग अक्सर मुसीबत में फँसे परिवार वाले बनकर पैसे माँगते हैं। पहले उन्हें पुराने नंबर पर फ़ोन करें।",
        "ta": "மோசடிக்காரர்கள் பெரும்பாலும் ஆபத்தில் உள்ள உறவினர் போல நடித்துப் பணம் கேட்பார்கள். முதலில் அவரது பழைய எண்ணில் அழைத்துப் பாருங்கள்.",
    },
    "prize": {
        "en": "If you never entered a contest, you cannot win a prize. Asking for a fee to release a prize is a common trick.",
        "hi": "अगर आपने कोई प्रतियोगिता नहीं खेली, तो इनाम नहीं मिल सकता। इनाम के लिए फ़ीस माँगना आम धोखा है।",
        "ta": "நீங்கள் எந்தப் போட்டியிலும் கலந்துகொள்ளவில்லை என்றால் பரிசு கிடைக்காது. பரிசுக்குக் கட்டணம் கேட்பது பொதுவான மோசடி.",
    },
    "secrecy": {
        "en": "Being told to keep it secret from your family is a warning sign.",
        "hi": "परिवार से बात छिपाने को कहना एक खतरे का संकेत है।",
        "ta": "குடும்பத்தினரிடம் மறைக்கச் சொல்வது ஆபத்தின் அறிகுறி.",
    },
    "account_block": {
        "en": "Threats to block your account, SIM or electricity are used to make you panic.",
        "hi": "खाता, सिम या बिजली बंद करने की धमकी आपको डराने के लिए दी जाती है।",
        "ta": "கணக்கு, சிம் அல்லது மின்சாரம் துண்டிக்கப்படும் என்ற மிரட்டல் உங்களைப் பயமுறுத்தவே.",
    },
    "money": {
        "en": "This message asks for money. Check with someone you trust before paying.",
        "hi": "यह संदेश पैसे माँग रहा है। भुगतान से पहले किसी भरोसेमंद व्यक्ति से पूछें।",
        "ta": "இந்தச் செய்தி பணம் கேட்கிறது. பணம் செலுத்தும் முன் நம்பகமான ஒருவரிடம் கேளுங்கள்.",
    },
    "link": {
        "en": "It has a link and is rushing you. Don't click links in urgent messages.",
        "hi": "इसमें लिंक है और जल्दी करने को कहा गया है। ऐसे लिंक पर क्लिक न करें।",
        "ta": "இதில் இணைப்பு உள்ளது, அவசரப்படுத்தவும் செய்கிறது. அவசர செய்திகளில் உள்ள இணைப்புகளைத் தொடாதீர்கள்.",
    },
}

# Most serious reason first
REASON_PRIORITY = [
    "digital_arrest", "authority", "otp", "family_emergency",
    "prize", "secrecy", "account_block", "money", "link",
]

NEXT_STEPS = {
    "red": {
        "en": "Do not pay or share any OTP. Call a family member before doing anything.",
        "hi": "पैसे न भेजें और कोई OTP न बताएं। कुछ भी करने से पहले परिवार को फ़ोन करें।",
        "ta": "பணம் அனுப்பாதீர்கள், OTP சொல்லாதீர்கள். எதையும் செய்யும் முன் குடும்பத்தினரை அழையுங்கள்.",
    },
    "yellow": {
        "en": "Don't act yet. Ask a family member, or call the official number yourself.",
        "hi": "अभी कुछ न करें। परिवार से पूछें, या खुद आधिकारिक नंबर पर फ़ोन करें।",
        "ta": "இப்போது எதுவும் செய்யாதீர்கள். குடும்பத்தினரிடம் கேளுங்கள், அல்லது அதிகாரப்பூர்வ எண்ணை நீங்களே அழையுங்கள்.",
    },
}

LABELS = {
    "green": {"en": "Looks safe", "hi": "सुरक्षित लगता है", "ta": "பாதுகாப்பாகத் தெரிகிறது"},
    "yellow": {"en": "Not sure - be careful", "hi": "पक्का नहीं - सावधान रहें", "ta": "உறுதியாக இல்லை - கவனம்"},
    "red": {"en": "Likely scam", "hi": "धोखा लगता है", "ta": "மோசடி போலத் தெரிகிறது"},
}

COULD_NOT_CHECK = {
    "en": "I could not check this properly right now.",
    "hi": "मैं अभी इसे ठीक से जाँच नहीं पाया।",
    "ta": "இதை இப்போது சரியாகச் சோதிக்க முடியவில்லை.",
}


def rule_reason(flags: list, lang: str) -> str:
    for name in REASON_PRIORITY:
        if name in flags:
            return RULE_REASONS[name][lang]
    return RULE_REASONS["money"][lang]
