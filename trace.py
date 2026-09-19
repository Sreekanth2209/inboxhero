import json
from datetime import datetime

from config import TRACE_FILE


def log(cap, event, **fields):
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "cap": cap, "event": event}
    rec.update(fields)
    with TRACE_FILE.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def clear():
    TRACE_FILE.write_text("")
