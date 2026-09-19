import json
from datetime import datetime

from config import INBOX_FILE, OUTBOX_DIR, OWNER


def load_inbox():
    msgs = json.loads(INBOX_FILE.read_text())
    # index by id and keep original order
    by_id = {m["id"]: m for m in msgs}
    return msgs, by_id


def thread_of(msg, by_id):
    """All messages sharing a thread_id, oldest first."""
    tid = msg["thread_id"]
    return sorted(
        [m for m in by_id.values() if m["thread_id"] == tid],
        key=lambda m: m["timestamp"],
    )


def earlier_in_thread(msg, by_id):
    return [m for m in thread_of(msg, by_id) if m["timestamp"] < msg["timestamp"]]


def keyword_search(needle, by_id):
    """Cheap cross-thread lookup; used when a thread walk finds nothing."""
    needle = needle.lower()
    hits = []
    for m in by_id.values():
        hay = (m["subject"] + " " + m["body"]).lower()
        if needle in hay:
            hits.append(m)
    return sorted(hits, key=lambda m: m["timestamp"])


def is_sent_by_owner(msg):
    return msg["from"].strip().lower() == OWNER


def send_message(to, cc, subject, body, cited=None):
    """The ONLY function that writes to outbox/. Called only after the gate."""
    OUTBOX_DIR.mkdir(exist_ok=True)
    n = len(list(OUTBOX_DIR.glob("*.json"))) + 1
    fname = OUTBOX_DIR / f"sent_{n:03d}.json"
    payload = {
        "to": to,
        "cc": cc or [],
        "subject": subject,
        "body": body,
        "cited": cited or [],
        "sent_at": datetime.now().isoformat(timespec="seconds"),
    }
    fname.write_text(json.dumps(payload, indent=2))
    return fname
