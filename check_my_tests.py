"""
Score Vidura on my_tests.csv.

  type      scam or genuine
  expected  green, yellow or red
  lang      en, hi or ta (the language of the reply)
  message   the message text

Needs OPENAI_API_KEY (put it in .env). Each check costs a tiny fraction of a rupee.

  python check_my_tests.py            # full check (rules + AI)
  python check_my_tests.py --rules    # rules only, free, no key needed
"""
import csv
import os
import sys

from vidura import engine, rules

EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def _load_dotenv(path=".env"):
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def rules_only_ai(text, image_b64, image_type, hints, lang):
    """Stand-in 'AI' that always says green, so any yellow/red comes from the rules alone."""
    return '{"verdict":"green","label":"-","reason":"-","next_step":"-","tip":""}'


def main(path="my_tests.csv", rules_only=False):
    _load_dotenv()
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    scams = caught = genuine = genuine_ok = exact = 0
    print()
    for i, row in enumerate(rows, 1):
        msg, kind = row["message"].strip(), row["type"].strip().lower()
        expected, lang = row["expected"].strip().lower(), (row.get("lang") or "en").strip().lower()
        r = engine.check_message(msg, lang=lang, ai=rules_only_ai if rules_only else None)
        got = r["verdict"]
        exact += got == expected
        if kind == "scam":
            scams += 1
            caught += got in ("yellow", "red")
        else:
            genuine += 1
            genuine_ok += got == "green"
        print(f"{i:2}. [{kind:7}] [{lang}] expected {EMOJI[expected]}  got {EMOJI[got]}  {'✅' if got == expected else '❌'}  ({r['source']})")
        print(f"    {msg[:90]}{'…' if len(msg) > 90 else ''}")
    print("=" * 50)
    print(f"Scams flagged yellow or red:      {caught} / {scams}")
    print(f"Genuine messages marked green:    {genuine_ok} / {genuine}")
    print(f"Exactly the colour expected:      {exact} / {len(rows)}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "my_tests.csv", rules_only="--rules" in sys.argv)
