"""Cheap rules that decide obvious mail before any model is touched.

Receipts, newsletters, automated notifications and marketing mail can be
archived on the sender address + subject alone. A model call on these is
wasted money and latency.
"""

# sender fragments that are never a person writing to Sam
NOISE_SENDERS = [
    "no-reply", "noreply", "no_reply", "donotreply",
    "receipts@", "receipt+", "invoice+", "billing@", "orders@",
    "notifications@", "notify@", "alerts@", "newsletter@", "digest@",
    "updates@", "insights@", "feedback@", "info@", "hello@",
    "support@postmarkapp", "mailer-daemon", "checkin@",
    "security@accounts.google.com", "calendar-notification@",
    "notes@paperjet.io", "facilities@paperjet.io", "hr@paperjet.io",
    "status@paperjet-monitoring",
]

# subject fragments that mark automated mail even from a human-looking address
NOISE_SUBJECTS = [
    "receipt", "invoice", "order has shipped", "order is delivered",
    "your statement", "bill", "payout", "weekly", "daily digest",
    "digest", "unread messages", "new sign-in", "new login",
    "verification code", "password was changed", "screen time",
    "you appeared in", "you have new notifications", "monitor ok",
    "incident resolved", "usage", "invoice paid", "analytics",
    "recording is ready", "event was scheduled", "rate your recent",
    "renews soon", "campaign report", "course recommendations",
    "welcome back", "subscription to", "top 5", "2 new posts",
    "security digest", "check-in is open", "files are almost full",
    "comments",
]


def is_noise(msg):
    """True if the message is automated/bulk mail that needs no reading."""
    frm = msg["from"].lower()
    subj = msg["subject"].lower()
    if any(s in frm for s in NOISE_SENDERS):
        return True
    if any(s in subj for s in NOISE_SUBJECTS):
        return True
    return False


def noise_reason(msg):
    subj = msg["subject"].lower()
    if "receipt" in subj or "order" in subj or "invoice" in subj or "bill" in subj:
        return "automated receipt/invoice"
    if "newsletter" in msg["from"].lower() or "digest" in subj or "weekly" in subj:
        return "newsletter/digest"
    if "sign-in" in subj or "login" in subj or "password" in subj or "verification" in subj:
        return "automated security notice"
    return "automated notification"


# security notices that LOOK urgent but are just informational boilerplate
# (kept separate so phishing doesn't get swept in with them)
SECURITY_BOILERPLATE = ["your password was changed", "a new sign-in", "verification code"]
