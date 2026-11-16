# Internal lead notifications

Owner-authorized notices go only to the current **Johan and Andrés** developer
numbers already configured in Sara WhatsApp. They are separate from customer
replies and never give the public agent an outbound or administrator tool.

## Timing and content

- Each genuinely inserted CRM contact creates an atomic outbox event and one
  delivery per recipient. Phone-conflict replays produce no new event.
- Hourly reports are due at each `HH:00`, using `America/Bogota`.
- The daily closing report is due at **22:00 Colombia**, not midnight. It replaces
  the simultaneous hourly report to avoid two nearly identical messages.
- Reports contain cumulative totals, today's counts, the previous hour's count,
  and cumulative/today breakdowns for WhatsApp, Facebook and other/unconfirmed.
- A generic social campaign is counted as Facebook only when a persisted verified
  Facebook intake ledger links it to that contact. Never infer origin from a phone.
- New-lead notices contain only name, mobile and origin; reports use counts only.
- No historical per-contact backfill occurs on activation. After downtime, the
  scheduler emits only the latest hourly slot and the most recent due daily close.
  A report cutoff is exclusive; its daily period starts at Colombian midnight.

## Explicit production activation

Deploy the additive migration and worker through the normal verified CI release.
Then, inside the authorized project API maintenance session, call:

```python
from app.crm.database import connect
from app.social import lead_notifications as notices
with connect() as db:
    owner = db.execute("SELECT id FROM crm.users WHERE username=%s AND enabled AND role='admin'",
                       ('adminjardines',)).fetchone()
    notices.configure(db, owner['id'])
notices.submit_templates()  # Only with explicit owner authorization to submit to Meta.
print(notices.status())
```

No telephone numbers, invitations, credentials or contact data belong in Git.
Activation verifies the existing business account and exact developer identities,
pins credentials/recipient configuration, and never enables an unrelated channel.
Template submissions have durable once-only reservations; an unknown result is
not permission to submit again. Review can remain pending or be rejected by Meta.
Fresh approved template content/language is checked before sending outside the
verified 24-hour incoming window. Messages wait when approval is unavailable.
The sender's own outgoing messages do not extend that window.

`status()` exposes schedule, state counts and sanitized finite diagnostics without
contact names/phones. Accepted means provider acceptance, not delivered/read.
The worker checks every five seconds; provider latency and outages can delay sends.
It does not use Codex reminders or depend on an open browser/chat.

## Safety and rollback

Writes reserve durably before provider IO. A timeout, malformed receipt or crash
after reservation becomes `unknown` and is never blindly resent. Preparation/read
failures stay pending with bounded retry. Per-recipient receipts prevent resending
to one owner when only the other failed. A changed/disabled recipient account,
developer list, enabled owner or credentials cancels unsent old-authority jobs.
Notifications serialize using the same lock ordering as Sara revocation and sends.

To stop, set `crm.lead_notice_config.enabled=false` under advisory locks `9142040`
then `2026111105`, or set the project-only `CRM_INTERNAL_NOTICES_DISABLED=1` runtime
override. Do not reset events, reservations, contact data or the public Sara policy.
Reactivation uses a new epoch and does not replay old notifications.

## Verification

Use the existing isolated `jardines_crm_test` test environment:
`pytest apps/api/tests/test_lead_notifications.py -q` plus the CRM suite.
Fake-provider tests must never send real WhatsApp messages or submit Meta reviews.
Check real schedules and provider verdicts privately after deployment.
