"""Pull dates, deadlines and obligations out of the inbox.

Pattern-based on purpose: a commitment extracted by regex can be pointed back
at the exact message it came from, which is what Part 7 demands. A model
summary can't do that as reliably.
"""
import re
from datetime import date, timedelta

# the run pretends to be the morning after the newest mail (Sep 9 2026, a Wed)
YEAR, MONTH = 2026, 9

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}

TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", re.I)


def _time_24(h, m, ap):
    h = int(h) % 12 + (12 if ap.lower().startswith("p") else 0)
    return f"{h:02d}:{int(m or 0):02d}"


def _next_weekday(name, after=date(2026, 9, 9)):
    """The next calendar date matching a weekday name, strictly after `after`."""
    d = after + timedelta(days=1)
    while d.weekday() != WEEKDAYS[name]:
        d += timedelta(days=1)
    return d


def extract(msg, by_id):
    """Return a list of commitment dicts for one message."""
    body = msg["body"]
    low = body.lower()
    out = []

    def add(title, day=None, time=None, extra_sources=None, note=None):
        srcs = [msg["id"]] + (extra_sources or [])
        out.append({"title": title, "date": day.isoformat() if day else None,
                    "time": time, "sources": srcs, "note": note})

    t = TIME_RE.search(body)
    hhmm = _time_24(*t.groups()) if t else None

    # explicit "September 15" style dates
    m = re.search(r"september\s+(\d{1,2})", low) or re.search(r"sep\s+(\d{1,2})", low)
    if m:
        d = date(YEAR, 9, int(m.group(1)))
        add(msg["subject"], d, hhmm)

    # "the 18th, 10:00am" / "target is the 20th" / "by the 12th" / "the 19th"
    for m in re.finditer(r"(?:the\s+|by the\s+|the\s+)(\d{1,2})(?:st|nd|rd|th)", low):
        d = date(YEAR, MONTH, int(m.group(1)))
        add(msg["subject"], d, hhmm)

    # "Tuesday the 15th at 3:00pm" -- weekday + day number
    m = re.search(r"(monday|tuesday|wednesday|thursday|friday)\s+the\s+(\d{1,2})(?:st|nd|rd|th)?", low)
    if m:
        d = date(YEAR, MONTH, int(m.group(2)))
        add(msg["subject"], d, hhmm)

    # bare weekday mentions: "Wednesday at 2:00pm", "Monday at 9:00am", "by Friday"
    for m in re.finditer(r"(monday|tuesday|wednesday|thursday|friday)\s+at\s+" + TIME_RE.pattern, low):
        d = _next_weekday(m.group(1))
        t2 = TIME_RE.search(m.group(0))
        add(msg["subject"], d, _time_24(*t2.groups()))

    m = re.search(r"by\s+(monday|tuesday|wednesday|thursday|friday)", low)
    if m:
        add(msg["subject"] + " (deadline)", _next_weekday(m.group(1)), None, note="deadline")

    m = re.search(r"deadline[^.]*\b(monday|tuesday|wednesday|thursday|friday)\b", low)
    if m:
        add(msg["subject"] + " (deadline)", _next_weekday(m.group(1)), None, note="deadline")

    # relative deadlines: "in 48 hours", "within 3-5 business days", "by month-end"
    m = re.search(r"(\d+)\s*hours?\b", low)
    if m and ("expires" in low or "confirm" in low):
        add(msg["subject"] + " (hold expires)", date(2026, 9, 9) + timedelta(days=int(m.group(1)) // 24), None, note="deadline")
    if "month-end" in low or "before month-end" in low:
        add(msg["subject"] + " (deadline)", date(2026, 9, 30), None, note="deadline")

    # "two days before the board review" -- the review's date lives in ANOTHER
    # message (m038), so this commitment legitimately cites two sources
    m = re.search(r"(\d+|two|three)\s+days?\s+before\s+the\s+([a-z ]+)", low)
    if m:
        n = {"two": 2, "three": 3}.get(m.group(1), int(m.group(1)) if m.group(1).isdigit() else 0)
        ref = m.group(2).strip()
        other = None
        for cand in by_id.values():
            if cand["id"] == msg["id"]:
                continue
            if "board review" in ref and "board review" in (cand["subject"] + cand["body"]).lower():
                other = cand
        if other:
            o_low = other["body"].lower()
            dm = re.search(r"the\s+(\d{1,2})(?:st|nd|rd|th)", o_low)
            if dm and n:
                d = date(YEAR, MONTH, int(dm.group(1))) - timedelta(days=n)
                add(msg["subject"], d, None, extra_sources=[other["id"]],
                    note=f"derived: {n} days before {ref} (date from {other['id']})")

    # PTO notices: "out Thursday and Friday next week"
    m = re.search(r"out\s+(monday|tuesday|wednesday|thursday|friday)\s+and\s+(monday|tuesday|wednesday|thursday|friday)\s+next week", low)
    if m:
        d1, d2 = _next_weekday(m.group(1)), _next_weekday(m.group(2))
        add(f"{msg['from'].split('@')[0]} OOO", d1, None, note=f"through {d2.isoformat()}")

    return out


def collect(by_id):
    """All commitments across the inbox, merged where several messages mean
    the same thing."""
    all_c = []
    from rules import is_noise
    for m in by_id.values():
        if is_noise(m):
            continue
        all_c.extend(extract(m, by_id))

    # merge: same date+time and overlapping subject words = one commitment.
    # (e.g. launch "the 20th" stated in m026 and restated in m036)
    merged = []
    for c in all_c:
        stop = {"your", "with", "from", "this", "that", "week", "reminder", "deadline"}
        c["subject_key"] = set(re.findall(r"[a-z]{4,}", c["title"].lower())) - stop
        twin = None
        for e in merged:
            if e["date"] == c["date"] and e["time"] == c["time"] and \
               (e["subject_key"] & c["subject_key"]):
                twin = e
                break
        if twin:
            twin["sources"] = sorted(set(twin["sources"]) | set(c["sources"]))
        else:
            merged.append(c)
    for c in merged:
        c.pop("subject_key", None)
    return sorted(merged, key=lambda c: (c["date"] or "9999", c["time"] or ""))


def conflicts(commitments):
    """Pairs of commitments at the same date+time."""
    out = []
    for i, a in enumerate(commitments):
        for b in commitments[i + 1:]:
            if a["date"] and a["time"] and a["date"] == b["date"] and a["time"] == b["time"]:
                out.append((a, b))
    return out
