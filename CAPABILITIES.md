# CAPABILITIES.md — inboxHero

**Student:** Srikanth Janagam, evernorth-aai-1037964
**Repository:** https://github.com/Sreekanth2209/inboxhero

Run everything through one entry point:

```
python demo.py --cap R1        # one capability
python demo.py --all           # all of them, in the order below
```

---

## The system, in one paragraph

A single Python pipeline, no framework. Every message is scanned for hostile
content first — before anything else touches it — because a "newsletter" is
exactly where you'd hide an instruction to the assistant. Then the obvious
mail (receipts, newsletters, automated notifications, security boilerplate)
is dispatched by sender/subject rules without a model call, preferences are
recorded, and only what remains goes to the model for a disposition. Replies
are drafted against thread context with cited message ids, every send passes
through the approval gate before it can write to `outbox/`, and a final pass
builds the dashboard. State that must outlive a run — preferences, decisions,
the event trace — lives in small JSON files on disk.

## Design choices you were asked to state

- **Framework: none.** The work is a linear pipeline with one branch
  (rule-path vs model-path) plus one loop-back (the gate). A crew or graph
  would have been overhead; see Final Report Q4 in the README.
- **Retrieval: thread-walk.** An inbox already carries its own structure in
  `thread_id`, so walking the thread is both cheaper and more precise than
  embeddings here. Keyword search is the fallback only when a message points
  at a fact living in another thread (the venue asking for "the date you
  locked in" resolves against the launch thread).
- **Reversible vs irreversible.** `send` and `delete` are irreversible and
  gated. `draft`, `archive`, `defer` and `flag` are reversible and run without
  a prompt. Deleting counts as irreversible because the mock store has no
  trash — and because deleting is exactly what the hostile mail asks for.
- **Where the gate sits.** `send_message()` in `mailstore.py` is the only
  function that can write to `outbox/`, and it is only ever called after
  `gate()` in `pipeline.py` returns True. A hostile message can influence a
  draft's *text*; it cannot reach a send without passing the gate, which is
  the Part 6 defence.
- **Escalation line.** Approval is asked only for mail leaving paperjet.io
  and anything touching money or legal. Internal sends are logged through the
  gate but don't interrupt. The trade-off: a badly-worded internal reply can
  go out unreviewed, in exchange for not asking a human to approve fifteen
  things until they stop reading.

## Capabilities

| id | name | tier | one-line claim |
|----|------|------|----------------|
| R1 | Zero the inbox | B | every message gets one disposition + reason, none left |
| R2 | Grounded reply | B | drafts cite the earlier messages they drew on |
| R3 | Gate the irreversible | C | no send/delete without approval or --dry-run |
| R4 | Persistent preference | C | a stated preference survives a restart |
| R5 | Refuse embedded instructions | C | detects, refuses, flags, reports injections |
| R6 | Dashboard | C | three panes, commitments cited, conflicts surfaced |
| X1 | Follow-up tracking | B | unanswered sent mail, with a drafted chase |
| X2 | Morning digest | B | needs-you / can-wait / archived-by-category |
| X3 | Thread to open question | B | 9-message thread down to the one open ask |
| X4 | Why did you do that | A | explains any message's disposition + evidence |
| X5 | Noise audit | A | which automated senders fill the inbox |

The exact command, observable outcome and evidence for each is in
`capabilities.json` — the machine-readable version a marking script reads.
This file is for a human; the two are kept in step.

## Notes on the data

- `inbox.json` is a flat JSON array of 100 message objects with keys `id`,
  `thread_id`, `from`, `to`, `subject`, `timestamp`, `body`, `unread`.
  Assumption: `timestamp` order inside a thread is the conversation order.
- The mailbox belongs to Sam (`sam@paperjet.io`); owner-sent mail is treated
  as "sent" for follow-up tracking.
- Runs are anchored to 2026-09-10, the morning after the newest message, so
  relative dates ("Wednesday", "by Friday") resolve reproducibly.

## Final Report

The four required answers are in `README.md` (they were specified to live
there). In short: the system refuses to act on legal/financial mail alone
(Q1), untrusted text enters only as quoted data in a prompt or a pattern
scan, never as instructions, and the gate is the only path to `outbox/` (Q2),
accountability rests with whoever approved the send and is traceable
through the `gate` events in `trace.jsonl` (Q3), and `pipeline.py`'s
`triage()` is the router, `grounded_draft`/`execute_sends` are the tasks,
`gate()` is the human-in-the-loop a framework would have wrapped for me (Q4).
