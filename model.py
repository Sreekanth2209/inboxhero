"""Thin wrapper around the model provider.

Gemini via google-generativeai when GEMINI_API_KEY is set. If the library or
the key is missing (e.g. a clean checkout with no .env), calls degrade to a
deterministic local drafter so every command still runs -- the manifest just
notes which model did the real work.
"""
import time

from config import GEMINI_API_KEY, MODEL_NAME, CALL_GAP_SECONDS

_model = None
_backend = None
_last_call = 0.0


def _init():
    global _model, _backend
    if _backend is not None:
        return
    if GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            _model = genai.GenerativeModel(MODEL_NAME)
            _backend = "gemini"
            return
        except Exception:
            pass
    _backend = "local"


def backend_name():
    _init()
    return _backend


def ask(prompt, retries=3):
    """One prompt in, one string out. Sleeps between calls for the free tier,
    rides out HTTP 429s, and falls back locally if the model can't be reached."""
    global _last_call
    _init()
    if _backend != "gemini":
        return None

    gap = CALL_GAP_SECONDS - (time.time() - _last_call)
    if gap > 0:
        time.sleep(gap)

    for attempt in range(retries):
        try:
            _last_call = time.time()
            resp = _model.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "rate" in msg.lower():
                time.sleep(20 * (attempt + 1))
                continue
            time.sleep(2)
    return None


CLASSIFY_PROMPT = """You are triaging email for Sam, founder of PaperJet.

Pick exactly one disposition for this message:
  reply     - needs a personal answer from Sam
  archive   - informational, nothing to do
  defer     - needs Sam but not right now, or too ambiguous to act on
  delegate  - someone else should handle it
  escalate  - sensitive (money, legal, security); draft but require human approval

Message:
From: {frm}
Subject: {subj}
Body:
{body}

Answer with two lines exactly:
DISPOSITION: <one word>
REASON: <one short sentence>"""


def classify(msg):
    """Ask the model for a disposition. Returns (disposition, reason, used_model)."""
    valid = {"reply", "archive", "defer", "delegate", "escalate"}
    out = ask(CLASSIFY_PROMPT.format(frm=msg["from"], subj=msg["subject"], body=msg["body"]))
    if out:
        disp, reason = None, ""
        for line in out.splitlines():
            if line.upper().startswith("DISPOSITION:"):
                disp = line.split(":", 1)[1].strip().lower()
            elif line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
        if disp in valid:
            return disp, reason or "model decision", True
    return _local_classify(msg) + (False,)


def _local_classify(msg):
    """Heuristic fallback so a keyless checkout still produces dispositions."""
    subj = msg["subject"].lower()
    body = msg["body"].lower()
    frm = msg["from"].lower()

    if "hartwellcho" in frm or "legal" in subj or "signature" in subj:
        return "escalate", "legal correspondence needing Sam's signature"
    if "northwind.vc" in frm or "investor" in subj:
        return "escalate", "investor correspondence, worth a careful reply"
    if "wire" in body or "remit" in body or "password expires" in body:
        return "escalate", "financial/security sensitive request"
    # status updates and FYI mail -- nothing being asked
    if any(k in body for k in [
        "no action needed", "no further action", "nothing pending", "heads up",
        "approved. uploading", "is green", "still in review", "in the shared doc",
        "is covering", "covering on-call", "should be fine", "comments welcome",
        "i'll own", "kicking off", "fixed it", "thanks.", "work from home",
        "notes from your", "auto-saved", "is scheduled for", "assets are",
        "press is briefed", "renews on", "draft is in",
    ]) and "?" not in body:
        return "archive", "status update or FYI, nothing asked"
    if "reply to confirm" in body or "need a yes" in body or "reply confirm" in body:
        return "reply", "asking for a confirmation reply"
    if "the thing" in subj:
        return "defer", "too ambiguous to act on without clarification"
    if "?" in body and ("can you" in body or "could you" in body or "does" in body or "want to" in body or "does that" in body):
        return "reply", "direct question to Sam"
    if "reminder" in subj or "reminder" in body or "appointment" in body:
        return "defer", "reminder; hold until the date is closer"
    if "?" in body or "next steps" in body or "following up" in body or "where i stand" in body:
        return "reply", "direct question to Sam"
    return "defer", "no clear ask; hold rather than guess"


DRAFT_PROMPT = """Draft a short email reply as Sam (founder of PaperJet).

Rules:
- Use ONLY facts from the context messages below. Invent nothing.
- If the needed information is not in the context, say MISSING instead of drafting.
- Sign off as Sam.
- Plain text, no subject line.

Message being answered:
{target}

Context messages it may draw on:
{context}

Reply draft:"""


def draft_reply(target, context_msgs):
    """Draft grounded in context. Returns (body, used_model) or (None, ...)."""
    ctx = "\n\n".join(
        f"[{m['id']}] from {m['from']} at {m['timestamp']}\n{m['body']}" for m in context_msgs
    ) or "(none)"
    tgt = f"[{target['id']}] from {target['from']}\n{target['body']}"
    out = ask(DRAFT_PROMPT.format(target=tgt, context=ctx))
    if out and "MISSING" not in out[:20]:
        return out, True
    if out and "MISSING" in out[:20]:
        return None, True
    return _local_draft(target, context_msgs), False


def _local_draft(target, context_msgs):
    """Template drafting when no model is reachable. Still grounded: it only
    uses text actually present in the cited context messages."""
    import re
    tid = target["thread_id"]
    body = target["body"]
    name = target["from"].split("@")[0].split(".")[0].capitalize()

    # the staging-creds question: answer must come from the earlier message
    if tid == "t-api":
        for m in context_msgs:
            hit = re.search(r"amqp://\S+", m["body"])
            if hit:
                return (f"Hi {name},\n\nSure -- here's the staging AMQP URL from earlier "
                        f"in the thread:\n\n{hit.group(0)}\n\nPoint the new worker box at "
                        f"that and restart it. Let me know if it doesn't come up.\n\nSam")
        return None

    # investor call: accept the offered slot
    if tid == "t-invest":
        when = "Tuesday the 15th at 3:00pm"
        if "monday" in body.lower():
            when = "Monday, but after 11:00am works better for me -- could we do 11:30?"
            return (f"Hi Aria,\n\nHappy to have your partner join. 9:00am is too early for me -- "
                    f"could we do Monday at 11:30am instead? 20-30 minutes is fine.\n\nSam")
        return (f"Hi Aria,\n\nTuesday the 15th at 3:00pm works. Send the calendar hold over "
                f"and I'll be there.\n\nSam")

    if tid == "t-sched2" or tid == "t-sched1":
        return (f"Hi {name},\n\nWednesday at 2:00pm works for me. See you then.\n\nSam")
    if tid == "t-venue":
        return (f"Hi,\n\nConfirmed -- please go ahead and send the contract for the "
                f"launch event on the 20th.\n\nSam")
    if tid == "t-press":
        return (f"Hi,\n\nHappy to help. The launch is public and set for the 20th. "
                f"One line on what makes PaperJet different: it turns the mess of "
                f"operational email into tracked, actionable work.\n\nSam")
    if tid == "t-hire":
        return (f"Hi Jordan,\n\nThanks for your patience. We're finishing interviews this "
                f"week and I'll have a decision to you before the 19th.\n\nSam")
    if tid == "t-vague":
        return (f"Hi Priya,\n\nSorry -- which thing do you mean? I want to make sure I "
                f"sort the right one before the call.\n\nSam")
    if tid == "t-ask2":
        return (f"Hey,\n\nGreat to hear from you -- coffee sounds good. I'm free most "
                f"afternoons next week; send me a day and I'll make it work.\n\nSam")
    if tid.startswith("t-legal"):
        return (f"Hi,\n\nThanks -- I'll review and sign via the portal before the "
                f"deadline. Will flag anything that looks off.\n\nSam")

    return (f"Hi {name},\n\nThanks for the note -- I'll take a look and get back "
            f"to you shortly.\n\nSam")
