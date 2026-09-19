# inboxHero

**Repository:** https://github.com/Sreekanth2209/inboxhero

An agentic system that takes a 100-message inbox to zero: it decides what to
do with every message, does the parts it should do, and refuses the parts it
should not.

## Setup

```
pip install -r requirements.txt
cp .env.example .env    # add your GEMINI_API_KEY (optional — see below)
python demo.py --cap R1
```

The model is configured entirely through environment variables loaded in
`config.py` (see `.env.example`). If no Gemini key or library is present, the
code falls back to a deterministic local drafter/classifier so every command
in the manifest still runs — it just isn't the real model doing the work.

## Commands

```
python demo.py --cap R1            zero the inbox (decisions.json)
python demo.py --cap R2 --msg m008 grounded reply draft with citations
python demo.py --cap R3 --dry-run  show gated sends without sending
python demo.py --cap R3            same, but asks y/N per external send
python demo.py --cap R4            show stored preferences applied
python demo.py --cap R5            hostile-mail scan and refusals
python demo.py --cap R6            write dashboard.html + dashboard.json
python demo.py --cap X1..X5        own capabilities (see CAPABILITIES.md)
python demo.py --all               everything, in order
```

## Architecture

```mermaid
flowchart TD
    A[inbox.json<br/>100 messages] --> B[guard.py<br/>injection + phishing scan<br/>on EVERY message]
    B -->|hostile / phish| F[flag + refuse<br/>left in place, reported]
    B --> C{looks like a<br/>preference?}
    C -->|yes, and safe| P[memory.py<br/>store in prefs.json]
    C -->|no| D{owner-sent<br/>or noise?}
    D -->|yes| R[rules.py<br/>archive/defer by rule<br/>no model call]
    D -->|no| M[model.py<br/>classify + draft<br/>Gemini or local fallback]
    M -->|reply / escalate| G[grounded_draft<br/>thread-walk + cited ids]
    G --> H{gate()<br/>external or money/legal?}
    H -->|needs human| Q[y/N prompt<br/>or --dry-run shows it]
    H -->|internal| Q
    Q -->|approved| O[send_message<br/>outbox/*.json]
    M -->|archive / defer| R
    A --> K[commitments.py<br/>dates + conflicts]
    G --> K
    K --> DB[dashboard.py<br/>dashboard.html + .json<br/>pending / flagged / commitments]
    T[trace.py<br/>trace.jsonl<br/>every decision logged] -.-> B
    T -.-> M
    T -.-> H
```

Same pipeline as text:

```
inbox.json
   │
   ▼
guard.py          injection + phishing scan on EVERY message first
   │
   ▼
pipeline.py ────► rules.py      obvious mail archived by rule, no model
   triage()          │
                     ▼
                memory.py       standing preferences → prefs.json
                     │
                     ▼
                model.py        disposition + drafting (Gemini, or local
                                fallback when no key is configured)
                     │
                     ▼
                gate()          every send/delete passes here; external or
                     │          money/legal mail needs a human, --dry-run
                     ▼          shows the rest
            mailstore.send_message()  → outbox/*.json   (only writer)
                     │
                     ▼
            commitments.py + dashboard.py → dashboard.html/.json

trace.py writes trace.jsonl — every decision, read, draft, refusal and
gated decision lands there, tagged by capability.
```

- **Disposition vocabulary:** `reply`, `archive`, `defer`, `delegate`,
  `escalate`, `flag`. `flag` means "refused and left in place" — used for
  hostile and phishing mail, which is never deleted or acted on.
- **Reversible vs irreversible:** `send` and `delete` are irreversible (the
  store has no trash, and a sent mail can't be unsent). `draft`, `archive`,
  `defer`, `flag` are reversible and ungated.
- **Retrieval:** thread-walk — `context_for()` gives a draft only earlier
  messages from the same thread, plus a keyword fallback for cross-thread
  facts (the venue's "date you locked in" → the launch thread's 20th).
  Cited ids are logged as `read` events before the `draft` event.
- **Framework:** none — see Q4 below.

## Final Report

**1. What did you refuse to automate?**
The Hartwell & Cho signature requests (m018, m048, m055) get a drafted reply
but are `escalate`d — the send sits in the pending-actions pane until a human
approves it. Signing off on a legal amendment is the kind of wrong a draft
can't take back, so the line is drawn at anything touching legal or money:
the system prepares, the human commits.

**2. Where does untrusted text enter your system?**
Message bodies reach the model only as quoted fields inside a prompt
template (`CLASSIFY_PROMPT`/`DRAFT_PROMPT` in `model.py`) or as input to a
pure pattern scan (`guard.py`) — no code path ever interprets body text as a
command, and the preference parser (`memory.is_safe_preference`) refuses to
store anything that asks to weaken the gate, which is what m039 tries. An
attacker would have to defeat the architecture, not a prompt: get a
malicious action past `gate()` in `pipeline.py`, the only caller of
`send_message()`, and past the human answering it.

**3. Who is accountable when it sends the wrong thing?**
The human who approved the send — external and sensitive mail can't leave
without a `y` at the gate. `trace.jsonl` records the full chain for every
send: the `decision` that chose to reply, the `read` events showing which
messages grounded the draft, the `draft` event with cited ids, and the
`gate` event with the proposed action and the human's answer, so a bad send
can be traced back to which step failed.

**4. Name your own machinery.**
`triage()` in `pipeline.py` is the router (the part a framework would call a
crew/router), `grounded_draft()` and `execute_sends()` are the tasks,
`demo.py` capabilities are the agents' public interface, and `gate()` is the
human-in-the-loop. A framework would have given me built-in tool wiring and
agent memory; I built the gate and `prefs.json` memory myself. A framework
would have hurt here: the safety property (only `gate()` may call
`send_message()`) is easier to *see* and prove in 60 lines of plain pipeline
than inside an agent abstraction where tools self-select.

## What a full run produces

- `decisions.json` — disposition + reason + route for all 100 messages
- `trace.jsonl` — event log tagged by capability (the evidence file)
- `outbox/sent_*.json` — sends that passed the gate (0 under --dry-run)
- `prefs.json` — standing preferences, survives restarts
- `dashboard.html` / `dashboard.json` — three-pane run view
