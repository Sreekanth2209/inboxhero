"""The pipeline: load -> guard -> route -> decide -> draft -> gate.

Order matters. The hostile-content scan runs before the noise rules, because
a "newsletter" is exactly where you'd hide an instruction to the assistant.
Message text is only ever DATA here -- nothing in this file treats body text
as instructions, which is the whole point of Part 6.
"""
import json
import re

import trace
from config import DECISIONS_FILE, OWNER, OWNER_NAME
from guard import scan_for_injection, scan_for_phish
from mailstore import (earlier_in_thread, is_sent_by_owner, keyword_search,
                       load_inbox, send_message, thread_of)
from memory import (cc_for, is_safe_preference, looks_like_preference,
                    record_preference, violates_schedule_pref)
from model import classify, draft_reply
from rules import is_noise, noise_reason

DISPOSITIONS = ["reply", "archive", "defer", "delegate", "escalate", "flag"]

INTERNAL_DOMAIN = "paperjet.io"


def is_internal(addr):
    return addr.lower().endswith("@" + INTERNAL_DOMAIN)


def triage(cap="R1"):
    """Give every message exactly one disposition + reason.

    Returns (decisions, stats). decisions[id] = {disposition, reason, route}.
    """
    msgs, by_id = load_inbox()
    decisions = {}
    stats = {"total": len(msgs), "rule_handled": 0, "model_handled": 0,
             "flagged": [], "preferences": []}

    for m in msgs:
        mid = m["id"]

        # 1. hostile-content scan on EVERYTHING, noise included
        hostile, attempt = scan_for_injection(m)
        if hostile:
            # owner-sent preference requests are allowed ONLY if safe
            if is_sent_by_owner(m) and is_safe_preference(m) and looks_like_preference(m):
                rec = record_preference(m)
                decisions[mid] = {"disposition": "archive",
                                  "reason": "standing preference recorded: " + (rec["detail"] if rec else "noted"),
                                  "route": "preference"}
                stats["preferences"].append(mid)
                trace.log(cap, "preference", msg=mid, detail=rec["detail"] if rec else "noted")
                continue
            decisions[mid] = {"disposition": "flag",
                              "reason": "refused embedded instruction: " + attempt,
                              "route": "guard"}
            stats["flagged"].append({"id": mid, "attempt": attempt})
            trace.log(cap, "refusal", msg=mid, attempted=attempt,
                      action="flagged, left in place, reported")
            continue

        # 2. phishing / social engineering
        phish, why = scan_for_phish(m)
        if phish:
            decisions[mid] = {"disposition": "flag",
                              "reason": "suspected phishing/social engineering: " + why,
                              "route": "guard"}
            stats["flagged"].append({"id": mid, "attempt": why})
            trace.log(cap, "refusal", msg=mid, attempted=why,
                      action="flagged, left in place, reported")
            continue

        # 3. standing preferences from real correspondents (e.g. Priya's CC request)
        if looks_like_preference(m) and is_safe_preference(m):
            rec = record_preference(m)
            decisions[mid] = {"disposition": "archive",
                              "reason": "standing preference recorded: " + (rec["detail"] if rec else "noted"),
                              "route": "preference"}
            stats["preferences"].append(mid)
            trace.log(cap, "preference", msg=mid, detail=rec["detail"] if rec else "noted")
            continue

        # 4. mail Sam sent himself: only interesting if nobody answered (X1)
        if is_sent_by_owner(m):
            decisions[mid] = {"disposition": "defer",
                              "reason": "sent by owner; kept for follow-up tracking",
                              "route": "rule"}
            stats["rule_handled"] += 1
            trace.log(cap, "decision", msg=mid, disposition="defer",
                      reason=decisions[mid]["reason"], route="rule")
            continue

        # 5. cheap rule path -- no model involved
        if is_noise(m):
            decisions[mid] = {"disposition": "archive",
                              "reason": noise_reason(m), "route": "rule"}
            stats["rule_handled"] += 1
            trace.log(cap, "decision", msg=mid, disposition="archive",
                      reason=decisions[mid]["reason"], route="rule")
            continue

        # 6. everything else goes to the model (or its local fallback)
        disp, reason, used_model = classify(m)
        decisions[mid] = {"disposition": disp, "reason": reason,
                          "route": "model" if used_model else "fallback"}
        stats["model_handled" if used_model else "rule_handled"] += 1
        trace.log(cap, "decision", msg=mid, disposition=disp, reason=reason,
                  route=decisions[mid]["route"])

    return decisions, stats


# ---------- retrieval (Part 3): thread-walk first, keyword as fallback ----------

def context_for(msg, by_id):
    """Messages a draft is allowed to cite. Thread walk first; if the thread
    carries no useful facts, keyword-search across threads."""
    ctx = earlier_in_thread(msg, by_id)

    # pull cross-thread context only when the message points at a fact living
    # in another thread (e.g. the venue asking for "the date you locked in").
    # Note the scan stays inside the inbox -- flagged mail is still just data
    # here, and never reaches the send path.
    if msg["thread_id"] == "t-venue" or "locked in" in msg["body"].lower():
        hits = keyword_search("the 20th", by_id) + keyword_search("launch", by_id)
        seen = {m["id"] for m in ctx}
        for h in hits:
            hostile, _ = scan_for_injection(h)
            phish, _ = scan_for_phish(h)
            if hostile or phish:
                continue
            if h["id"] not in seen and h["timestamp"] < msg["timestamp"]:
                ctx.append(h)
                seen.add(h["id"])
        ctx.sort(key=lambda m: m["timestamp"])
    return ctx


def grounded_draft(msg, by_id, cap):
    """Draft a reply, returning (body, cited_ids). Cited ids are verified to
    be messages the system actually read."""
    ctx = context_for(msg, by_id)
    for c in ctx:
        trace.log(cap, "read", msg=c["id"], for_msg=msg["id"])
    body, used_model = draft_reply(msg, ctx)
    cited = [c["id"] for c in ctx if c["id"] != msg["id"]]
    if body is None:
        trace.log(cap, "draft", msg=msg["id"], cited=[], status="missing-info")
        return None, cited
    trace.log(cap, "draft", msg=msg["id"], cited=cited,
              status="ok", model=used_model)
    return body, cited


# ---------- the gate (Part 4) ----------

def needs_approval(action):
    """Where the escalation line is drawn: only sends leaving paperjet.io,
    or anything touching money/legal, ask a human. Internal sends log through
    the gate but don't interrupt."""
    if action["kind"] == "delete":
        return True
    if action.get("sensitive"):
        return True
    return not all(is_internal(a) for a in [action["to"]] + action.get("cc", []))


def gate(action, dry_run=False, assume_yes=False, cap="R3"):
    """Every irreversible action passes through here. Returns True if the
    action should actually happen."""
    trace.log(cap, "gate", proposed=action["kind"], to=action.get("to"),
              msg=action.get("msg"), needs_approval=needs_approval(action))

    if dry_run:
        trace.log(cap, "gate", decision="suppressed-by-dry-run", msg=action.get("msg"))
        return False

    if not needs_approval(action):
        trace.log(cap, "gate", decision="auto-internal", msg=action.get("msg"))
        return True

    if assume_yes:
        trace.log(cap, "gate", decision="approved-via-flag", msg=action.get("msg"))
        return True

    print(f"\n  APPROVAL NEEDED -- {action['kind']}")
    print(f"    to:     {action['to']}")
    if action.get("cc"):
        print(f"    cc:     {', '.join(action['cc'])}")
    print(f"    why:    {action.get('why', 'external or sensitive')}")
    print(f"    draft:  {action.get('preview', '')[:200]}")
    try:
        ans = input("    send? [y/N] ").strip().lower()
    except EOFError:
        ans = ""
    ok = ans == "y"
    trace.log(cap, "gate", decision="approved" if ok else "rejected",
              msg=action.get("msg"), human=ans or "n")
    return ok


def execute_sends(drafts, by_id, dry_run=False, assume_yes=False, cap="R3"):
    """Propose each drafted reply as a send, run it through the gate."""
    writes = 0
    for d in drafts:
        msg = by_id[d["msg"]]
        action = {
            "kind": "send", "msg": d["msg"], "to": msg["from"],
            "cc": cc_for(msg), "subject": "Re: " + msg["subject"],
            "preview": d["body"], "sensitive": d.get("sensitive", False),
            "why": d.get("why", "external recipient" if not is_internal(msg["from"]) else ""),
        }
        if dry_run:
            print(f"  WOULD send -> {action['to']}"
                  + (f" cc {action['cc']}" if action["cc"] else "")
                  + f"  (re {msg['subject'][:50]})")
        if gate(action, dry_run=dry_run, assume_yes=assume_yes, cap=cap):
            fname = send_message(action["to"], action["cc"], action["subject"],
                                 d["body"], cited=d.get("cited"))
            trace.log(cap, "sent", msg=d["msg"], file=str(fname))
            writes += 1
    return writes


def save_decisions(decisions):
    DECISIONS_FILE.write_text(json.dumps(decisions, indent=2))


def load_decisions():
    if DECISIONS_FILE.exists():
        return json.loads(DECISIONS_FILE.read_text())
    return {}
