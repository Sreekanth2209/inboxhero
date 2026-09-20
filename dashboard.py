"""Three-pane run summary: pending actions / flagged / commitments.

Written as dashboard.json + dashboard.html from a real run's data --
nothing in either file is assembled by hand.
"""
import html
import json

import trace
from commitments import collect, conflicts
from config import DASHBOARD_HTML, DASHBOARD_JSON


def build(decisions, drafts, pending, flagged, by_id, cap="R6"):
    commitments = collect(by_id)
    clashes = conflicts(commitments)

    data = {
        "pending_actions": [
            {"message": p["msg"], "proposed": p["kind"],
             "to": p["to"], "why_needs_human": p["why"]}
            for p in pending
        ],
        "flagged": [
            {"message": f["id"], "attempted": f["attempt"],
             "did_instead": "flagged and left in place; nothing sent or deleted"}
            for f in flagged
        ],
        "commitments": commitments,
        "conflicts": [
            {"when": f"{a['date']} {a['time']}",
             "items": [a["title"], b["title"]],
             "sources": sorted(set(a["sources"] + b["sources"]))}
            for a, b in clashes
        ],
    }
    DASHBOARD_JSON.write_text(json.dumps(data, indent=2))
    _write_html(data)
    for c in commitments:
        trace.log(cap, "commitment", title=c["title"], date=c["date"],
                  time=c["time"], sources=c["sources"])
    for cf in data["conflicts"]:
        trace.log(cap, "conflict", when=cf["when"], items=cf["items"])
    return data


def _write_html(data):
    e = html.escape

    def rows(items, cols):
        out = []
        for it in items:
            out.append("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in cols(it)) + "</tr>")
        return "\n".join(out) or f"<tr><td colspan='4'><i>none</i></td></tr>"

    commitments_html = []
    for c in data["commitments"]:
        commitments_html.append(
            f"<tr><td>{e(c['date'] or '')}</td><td>{e(c['time'] or '')}</td>"
            f"<td>{e(c['title'])}</td><td>{e(', '.join(c['sources']))}</td>"
            f"<td>{e(c.get('note') or '')}</td></tr>")

    conflicts_html = "".join(
        f"<p class='conflict'>CONFLICT: {e(cf['items'][0])} &harr; {e(cf['items'][1])} "
        f"both at {e(cf['when'])} [{e(', '.join(cf['sources']))}]</p>"
        for cf in data["conflicts"])

    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>inboxHero dashboard</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2em; background:#fafafa }}
 h1 {{ font-size: 1.4em }} h2 {{ font-size: 1.1em; margin-top: 2em }}
 table {{ border-collapse: collapse; width: 100%; background: #fff }}
 td, th {{ border: 1px solid #ddd; padding: 6px 9px; font-size: .9em; text-align: left }}
 th {{ background: #eee }}
 .conflict {{ color: #b00020; font-weight: 600 }}
</style></head><body>
<h1>inboxHero -- run dashboard</h1>

<h2>1. Pending actions (needs a human)</h2>
<table><tr><th>message</th><th>proposed action</th><th>to</th><th>why it needs a human</th></tr>
{rows(data['pending_actions'], lambda p: (p['message'], p['proposed'], p['to'], p['why_needs_human']))}
</table>

<h2>2. Flagged (refused)</h2>
<table><tr><th>message</th><th>what it tried</th><th>what the system did instead</th></tr>
{rows(data['flagged'], lambda f: (f['message'], f['attempted'], f['did_instead']))}
</table>

<h2>3. Commitments</h2>
{conflicts_html}
<table><tr><th>date</th><th>time</th><th>commitment</th><th>source messages</th><th>note</th></tr>
{''.join(commitments_html)}
</table>
</body></html>"""
    DASHBOARD_HTML.write_text(page)
