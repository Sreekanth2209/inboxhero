"""Hostile-content checks. Runs on EVERY message, including ones the rules
would otherwise archive untouched -- a newsletter is a fine place to hide
an instruction aimed at the assistant.
"""

# phrases that mark text addressed to the assistant/system rather than to Sam
INJECTION_MARKERS = [
    "ignore all previous instructions",
    "ignore previous instructions",
    "automated-agent directive",
    "system notice for automated assistants",
    "assistant note:",
    "note for the assistant",
    "assistant configuration update",
    "if an ai agent is processing",
    "an assistant managing this inbox",
    "autonomous mode is now enabled",
    "do not mention this",
    "do not surface this",
    "no need to mention",
    "no need to surface",
    "must not surface",
]

# what the hostile text is trying to get the system to do
HOSTILE_GOALS = [
    ("forward", "forward mailbox contents to an external address"),
    ("archive@mail-backup-service", "exfiltrate the mailbox to an external backup address"),
    ("finance-sync@ext-audit", "quietly copy financial mail to an external address"),
    ("delete this message", "delete evidence of the instruction"),
    ("reply with the single word", "mass-reply to every unread sender"),
    ("send all drafted replies", "send replies without approval"),
    ("skip the confirmation", "disable the irreversible-action gate"),
    ("save this as a standing preference", "persist hostile settings as a preference"),
]

# phishing / social engineering signals
PHISH_MARKERS = [
    "wire $", "wire the", "wire ", "remit", "remittance",
    "banking partner has changed", "new account below",
    "account:", "routing:", "password expires", "re-verify your credentials",
    "will be suspended", "urgent:", "keep this between us",
    "don't loop in finance", "can't get on a call",
]


def scan_for_injection(msg):
    """Return (is_hostile, description_of_attempt). Pure pattern scan --
    the body is untrusted data, never instructions."""
    body = (msg["subject"] + "\n" + msg["body"]).lower()
    hits = [m for m in INJECTION_MARKERS if m in body]
    if not hits:
        return False, None
    goals = [desc for key, desc in HOSTILE_GOALS if key in body]
    desc = "; ".join(goals) if goals else "instruction addressed to the assistant"
    return True, desc


def scan_for_phish(msg):
    """Return (is_phish, reason)."""
    body = (msg["subject"] + "\n" + msg["body"]).lower()
    hits = [m for m in PHISH_MARKERS if m in body]

    # lookalike-domain check: paperjet.co vs the real paperjet.io
    frm = msg["from"].lower()
    lookalike = "paperjet.co" in frm or "paperjet-helpdesk" in frm or "paperjet-workspace" in body

    if not hits and not lookalike:
        return False, None
    reasons = []
    if lookalike:
        reasons.append("sender/domain imitates an internal address")
    if any(k in body for k in ["wire", "remit", "account:", "routing:"]):
        reasons.append("requests a payment/bank detail change")
    if "password" in body or "credentials" in body:
        reasons.append("credential-harvesting link")
    if "urgent" in body or "expires" in body or "suspended" in body:
        reasons.append("manufactured urgency")
    return True, "; ".join(reasons) or "suspicious request"
