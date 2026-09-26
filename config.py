import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# try to pull a .env file in if python-dotenv is around, otherwise read it by hand
def _load_dotenv():
    env_file = BASE_DIR / ".env"
    print(f"env_file - {env_file}")
print(f"env_file - {enc_file}")
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_dotenv()

# model provider is entirely env-driven; nothing about it is hardcoded into the logic
MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "gemini")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-3.6-flash")
# seconds to sleep between model calls; free tier is ~15 rpm
CALL_GAP_SECONDS = float(os.environ.get("CALL_GAP_SECONDS", "4"))

INBOX_FILE = BASE_DIR / "inbox.json"
OUTBOX_DIR = BASE_DIR / "outbox"
PREFS_FILE = BASE_DIR / "prefs.json"
TRACE_FILE = BASE_DIR / "trace.jsonl"
DECISIONS_FILE = BASE_DIR / "decisions.json"
DASHBOARD_JSON = BASE_DIR / "dashboard.json"
DASHBOARD_HTML = BASE_DIR / "dashboard.html"

# the mailbox belongs to Sam; mail Sam wrote counts as "sent"
OWNER = "sam@paperjet.io"
OWNER_NAME = "Sam"

# the inbox ends on Sep 9 2026, so the run pretends it is the morning after.
# kept as a constant instead of date.today() so runs are reproducible
RUN_DATE = "2026-09-10"
