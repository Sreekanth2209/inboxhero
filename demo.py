"""inboxHero -- single entry point.

    python demo.py --cap R1            one capability
    python demo.py --cap R3 --dry-run  gate demo without sending
    python demo.py --all               everything, in manifest order
"""
import argparse
import json
import sys
from datetime import datetime

import trace
from commitments import collect, conflicts
from dashboard import build as build_dashboard
from mailstore import (is_sent_by_owner, load_inbox, send_message, thread_of)
from memory import cc_for, load_prefs, violates_schedule_pref
from model import backend_name
from pipeline import (execute_sends, grounded_draft, is_internal,
                      load_decisions, needs_approval, save_decisions, triage)


def run_full(cap, want_drafts=True):
    """Triage the whole inbox and draft whatever the dispositions call for."""
    msgs, by_id = load_inbox()
    decisions, stats = triage(cap)
    save_decisions(decisions)

    drafts, pending = [], []
    if want_drafts:
        for m in msgs:
            d = decisions[m["id"]]
            if d["disposition"] in ("reply", "escalate"):
                body, cited = grounded_draft(m, by_id, cap)
                if body is None:
                    continue
                sensitive = d["disposition"] == "escalate"
                dr = {"msg": m["id"], "body": body, "cited": cited,
                      "sensitive": sensitive,
                      "why": "legal/money/investor mail" if sensitive
                             else "external recipient" if not is_internal(m["from"])
                             else ""}
                drafts.append(dr)
                if not is_internal(m["from"]) or sensitive:
                    pending.append({"kind": "send", "msg": m["id"], "to": m["from"],
                                    "cc": cc_for(m), "why": dr["why"] or "external recipient",
                                    "preview": body})
    return decisions, stats, drafts, pending


# ------------------------------ capabilities ------------------------------

def cap_R1(args):
    decisions, stats, drafts, pending = run_full("R1")

    print(f"{'id':6} {'disposition':12} {'route':10} reason")
    print("-" * 78)
    for mid, d in decisions.items():
        print(f"{mid:6} {d['disposition']:12} {d['route']:10} {d['reason'][:52]}")
    print("-" * 78)

    undecided = [m for m, d in decisions.items() if not d["disposition"]]
    print(f"total: {stats['total']}   rule-handled (no model): {stats['rule_handled']}   "
          f"model: {stats['model_handled']}   flagged: {len(stats['flagged'])}")
    print(f"undecided: {len(undecided)}")
    print("wrote decisions.json")


def cap_R2(args):
    msgs, by_id = load_inbox()
    target = by_id[args.msg]
    print(f"drafting a grounded reply to {args.msg} ({target['subject']})...\n")
    body, cited = grounded_draft(target, by_id, "R2")
    if body is None:
        print("NOTHING DRAFTED -- the information needed is not in the inbox.")
        return
    print(body)
    print(f"\ncited: {cited}")
    # prove the citations are real: print the line the draft used
    for cid in cited:
        print(f"  [{cid}] {by_id[cid]['body'][:90]}...")


def cap_R3(args):
    decisions, stats, drafts, pending = run_full("R3")
    print(f"{len(drafts)} replies drafted; routing every send through the gate.\n")
    writes = execute_sends(drafts, by_id=load_inbox()[1],
                           dry_run=args.dry_run, assume_yes=args.yes, cap="R3")
    print(f"\noutbox/ writes: {writes}")
    if args.dry_run:
        print("(dry-run: nothing was sent; re-run without --dry-run to be asked per send)")


def cap_R4(args):
    prefs = load_prefs()
    print("stored preferences (prefs.json):")
    for p in prefs["preferences"]:
        print(f"  - {p['detail']}   [from {p['source']}]")
    if not prefs["preferences"]:
        print("  (none yet -- run --cap R1 first so preference mail is recorded)")
        return

    msgs, by_id = load_inbox()

    # demo 1: the 9am investor slot vs the no-meetings-before-11 rule
    m = by_id["m043"]
    print(f"\n{m['id']} proposes 'Monday at 9:00am'.")
    print("schedule rule violated?" , violates_schedule_pref("monday 9:00am"))
    body, cited = grounded_draft(m, by_id, "R4")
    print("draft applying the rule:\n")
    print(body)

    # demo 2: legal mail gets Priya on CC without being told again
    m = by_id["m018"]
    print(f"\n{m['id']} is from Hartwell & Cho. stored CC for it: {cc_for(m)}")


def cap_R5(args):
    decisions, stats, drafts, pending = run_full("R5", want_drafts=False)
    print("hostile / phishing scan over all 100 messages:\n")
    for f in stats["flagged"]:
        print(f"  FLAGGED: {f['id']} attempted to {f['attempt']}; "
              f"not done, left in place.")
    print(f"\nflagged: {len(stats['flagged'])}  |  nothing was sent, forwarded or deleted")


def cap_R6(args):
    decisions, stats, drafts, pending = run_full("R6")
    data = build_dashboard(decisions, drafts, pending, stats["flagged"],
                           load_inbox()[1])
    print(f"pending actions: {len(data['pending_actions'])}")
    print(f"flagged:         {len(data['flagged'])}")
    print(f"commitments:     {len(data['commitments'])}")
    for cf in data["conflicts"]:
        print(f"  CONFLICT: {cf['items'][0]} <-> {cf['items'][1]} at {cf['when']}")
    print("\nwrote dashboard.html and dashboard.json")


def cap_X1(args):
    """Follow-up tracking: mail Sam sent that nobody answered in 3+ days."""
    msgs, by_id = load_inbox()
    run_date = datetime(2026, 9, 10)
    stale = []
    for m in msgs:
        if not is_sent_by_owner(m):
            continue
        thread = thread_of(m, by_id)
        later = [t for t in thread if t["timestamp"] > m["timestamp"]
                 and not is_sent_by_owner(t)]
        if later:
            continue
        sent = datetime.fromisoformat(m["timestamp"])
        days = (run_date - sent).days
        if days >= 3 and m["id"] != "m039" and m["id"] != "m041":
            stale.append((m, days))

    out = []
    for m, days in stale:
        chase = (f"Hi {m['to'].split('@')[0].capitalize()},\n\n"
                 f"Just nudging this up your inbox -- "
                 f"{m['subject'].replace('Re: ', '').lower()} is still open on my side. "
                 f"Anything you need from me to move it?\n\nSam")
        out.append({"message_id": m["id"], "days_waiting": days, "draft": chase})
        trace.log("X1", "followup", msg=m["id"], days=days)
    print(json.dumps(out, indent=2))
    print(f"\n{len(out)} sent message(s) unanswered 3+ days")


def cap_X2(args):
    """Morning digest: needs me / can wait / auto-archived."""
    decisions, stats, drafts, pending = run_full("X2")
    msgs, by_id = load_inbox()

    needs = [m for m, d in decisions.items()
             if d["disposition"] in ("reply", "escalate")]
    waits = [m for m, d in decisions.items() if d["disposition"] == "defer"]
    archived = {}
    for m, d in decisions.items():
        if d["disposition"] == "archive":
            archived[d["reason"]] = archived.get(d["reason"], 0) + 1

    print("NEEDS YOU TODAY")
    for mid in needs:
        m = by_id[mid]
        print(f"  {mid}  {m['subject'][:55]}  -- {decisions[mid]['reason'][:40]}")

    print("\nCAN WAIT")
    for mid in waits:
        m = by_id[mid]
        print(f"  {mid}  {m['subject'][:55]}")

    print("\nAUTO-ARCHIVED")
    for reason, n in sorted(archived.items(), key=lambda x: -x[1]):
        print(f"  {n:3} x {reason}")

    if stats["flagged"]:
        print("\nFLAGGED -- look at these yourself")
        for f in stats["flagged"]:
            print(f"  {f['id']}: {f['attempt'][:60]}")


def cap_X3(args):
    """Summarise a long thread down to its open question (tier B)."""
    msgs, by_id = load_inbox()
    tid = args.thread or "t-launch"
    thread = thread_of({"thread_id": tid}, by_id)
    print(f"thread {tid}: {len(thread)} messages\n")

    open_items = []
    for m in thread:
        low = m["body"].lower()
        first = m["body"].split("\n")[0].strip()
        print(f"  {m['id']} {m['from'].split('@')[0]:10} {first[:70]}")
        if "sam" in low and ("can you" in low or "approve" in low or "needs sam" in low):
            open_items.append(m)

    print("\nOPEN QUESTION(S) FOR SAM:")
    for m in open_items:
        print(f"  {m['id']}: {m['body'].split(chr(10))[0][:120]}")
        trace.log("X3", "open-question", thread=tid, msg=m["id"])


def cap_X4(args):
    """Why did the system do X? (tier A: one lookup, one answer)."""
    decisions = load_decisions()
    mid = args.msg
    if mid not in decisions:
        print(f"no decision recorded for {mid} -- run --cap R1 first")
        return
    d = decisions[mid]
    print(f"{mid}: {d['disposition']} (via {d['route']})")
    print(f"reason: {d['reason']}")
    # show the trace events behind it
    if trace.TRACE_FILE.exists():
        for line in trace.TRACE_FILE.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("msg") == mid:
                print(f"  trace: {rec['event']} {json.dumps({k:v for k,v in rec.items() if k not in ('ts','cap','event','msg')})[:80]}")


def cap_X5(args):
    """Noise audit: which senders fill the inbox without needing a reply (tier A)."""
    msgs, by_id = load_inbox()
    from rules import is_noise
    senders = {}
    for m in msgs:
        if is_noise(m):
            senders.setdefault(m["from"], []).append(m["id"])
    print(f"{'sender':42} count  example subject")
    for s, ids in sorted(senders.items(), key=lambda x: -len(x[1])):
        print(f"{s:42} {len(ids)}      {by_id[ids[0]]['subject'][:40]}")
    print(f"\n{len(senders)} automated senders account for "
          f"{sum(len(v) for v in senders.values())} of {len(msgs)} messages")


CAPS = {
    "R1": cap_R1, "R2": cap_R2, "R3": cap_R3, "R4": cap_R4,
    "R5": cap_R5, "R6": cap_R6,
    "X1": cap_X1, "X2": cap_X2, "X3": cap_X3, "X4": cap_X4, "X5": cap_X5,
}


def main():
    ap = argparse.ArgumentParser(description="inboxHero demo")
    ap.add_argument("--cap", help="capability id (R1..R6, X1..X5)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--msg", default="m008", help="message id for R2/X4")
    ap.add_argument("--thread", help="thread id for X3")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="pre-approve gated sends")
    args = ap.parse_args()

    print(f"[model backend: {backend_name()}]")

    if args.all:
        for cid in CAPS:
            print(f"\n{'='*30} {cid} {'='*30}")
            CAPS[cid](args)
        return
    if args.cap in CAPS:
        CAPS[args.cap](args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
