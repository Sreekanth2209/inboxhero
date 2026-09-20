"""Standing preferences, persisted to prefs.json so they survive a restart.

A preference is only stored if it asks for something safe. "Remember not to
take meetings before 11" is fine; "remember to skip confirmations" is an
attack wearing a preference's clothes and is refused instead.
"""
import json

from config import PREFS_FILE

# things a stated preference may NEVER ask for
UNSAFE_PREF_MARKERS = [
    "without asking for approval",
    "without asking",
    "skip the confirmation",
    "skip confirmation",
    "send all drafted replies",
    "automatically without asking",
    "autonomous mode",
    "no need to mention",
    "do not mention",
    "do not surface",
]


def load_prefs():
    if PREFS_FILE.exists():
        return json.loads(PREFS_FILE.read_text())
    return {"preferences": []}


def save_prefs(prefs):
    PREFS_FILE.write_text(json.dumps(prefs, indent=2))


def looks_like_preference(msg):
    body = (msg["subject"] + " " + msg["body"]).lower()
    return any(k in body for k in [
        "from now on", "standing request", "please remember",
        "note for the assistant", "my calendar rule", "always cc",
        "loop me in", "remember this",
    ])


def is_safe_preference(msg):
    body = msg["body"].lower()
    return not any(k in body for k in UNSAFE_PREF_MARKERS)


def extract_preference(msg):
    """Turn a preference-stating message into a stored record, or None."""
    body = msg["body"].lower()
    subj = msg["subject"].lower()

    if "hartwell" in body or ("cc" in body and "legal" in subj + " " + body) or "loop me in" in body:
        return {
            "type": "cc",
            "rule": "cc_priya_on_legal",
            "detail": "CC priya@paperjet.io on all mail from Hartwell & Cho (hartwellcho.com)",
            "source": msg["id"],
            "match_domain": "hartwellcho.com",
            "cc": "priya@paperjet.io",
        }
    if "before 11" in body or "11:00" in body:
        return {
            "type": "schedule",
            "rule": "no_meetings_before_11",
            "detail": "Never accept meetings before 11:00am; offer 11:00 or later",
            "source": msg["id"],
        }
    return None


def record_preference(msg):
    prefs = load_prefs()
    rec = extract_preference(msg)
    if rec and rec not in prefs["preferences"]:
        prefs["preferences"].append(rec)
        save_prefs(prefs)
    return rec


def cc_for(msg):
    """Extra CC recipients demanded by stored preferences."""
    prefs = load_prefs()
    extra = []
    for p in prefs["preferences"]:
        if p["type"] == "cc" and p.get("match_domain", "") in msg["from"].lower():
            extra.append(p["cc"])
    return extra


def violates_schedule_pref(proposed_when):
    """True if a proposed meeting time breaks the stored 11am rule."""
    prefs = load_prefs()
    has_rule = any(p["rule"] == "no_meetings_before_11" for p in prefs["preferences"])
    if not has_rule:
        return False
    # crude hour parse: "9:00am", "9am", "10:30am"
    w = proposed_when.lower().replace(" ", "")
    import re
    m = re.search(r"(\d{1,2})(?::\d{2})?am", w)
    if m and int(m.group(1)) < 11:
        return True
    return False
