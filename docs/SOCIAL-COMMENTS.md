# Sara comment moderation

The application reconciles explicitly owner-approved Jardines Facebook ad threads
and organic TikTok videos every 300 seconds. It does not moderate a whole shared
brand profile. New posts require a fresh operator-reviewed source pin.

## Authorization and isolation

- Default profile `6ae35794a3d08c217a343392` only.
- Facebook Page `6af6692c45ef03d5f9965518`, MetaAds connection
  `6afb351878449c760a51a501`, TikTok `6afb3215050792ec90fe0f6a`.
- Additional private `ads-engagement-readonly.json`: Ads + Accounts + Engagement,
  global read-only, mode 0600 inside the existing private configuration volume.
  Never replace the current Inbox messaging credential with this read-only key.
- Owner-installed database policy pins both credential revisions and each exact
  post/creative caption hash. The runtime cannot update authorization or source
  identity. The enabled administrator, connection switches, source identity and
  published Sara knowledge version are rechecked before every external write.
- The argument-free `crm.lock_comment_moderation_owner()` takes read locks under
  the migration owner's rights. Its fixed SQL and fixed search path expose no
  write access or arbitrary queries. PUBLIC cannot execute it.
- `SARA_COMMENT_WORKER_ENABLED=1` AND an enabled owner policy are required.
  Missing configuration is inactive; this is not a desktop automation.

## Behavior

Sara's existing tool-free `/public-reply` subagent classifies each public comment
with a closed JSON schema. It receives only the comment and published knowledge,
not CRM history, credentials, developer permissions or tool access. A live smoke
probe verified the classifier output under the immutable public Sara floor.

- Confident inquiries receive a short public answer based on published knowledge.
- An explicitly requested private answer can be attempted on Facebook within
  seven days. TikTok comment-to-DM is never attempted.
- Legitimate complaints, pricing objections, doubts about legality and negative
  experiences remain visible for human review.
- Reversible hiding requires both >=98% model confidence and independent,
  narrow spam/abuse evidence. No permanent delete/ban route exists.
- Existing discussions, own comments, hidden comments, malformed timestamps,
  identity changes and malformed classifications do not receive automatic replies.
- One committed reservation per source/comment/action precedes any write. A crash,
  timeout or ambiguous provider result is never automatically replayed. Inspect
  `unknown`, `blocked` or remaining `reserved` rows before manual intervention.
- The classifier is limited to one new request per 30 seconds, leaving shared
  public-model capacity for WhatsApp. No more than 100 action reservations/day.

## Operations

`GET /api/crm/inbox/comment-moderation` requires an authenticated CRM administrator.
It exposes source scan times/errors, heartbeat, accepted/unknown action counts and
human-review counts; never credentials or raw provider errors.

Deployment uses the existing exact-main root deployment gate and additive migration
`025_social_comment_moderation.sql`. Provision the owner policy and source pins using
the privileged maintenance role only after inspecting the actual provider data.
Never add migration credentials to the API container. Preserve root policy overlays.

To pause, stop the project worker flag or disable the owner policy through privileged
maintenance. Do not remove historical observations or action reservations. Updating
source identities, owner policy or credentials requires explicit owner authorization.

A five-minute reconciliation interval is not a real-time freshness guarantee:
Zernio can cache comment lists for up to ten minutes. No comment-received webhook
subscription is silently added or changed by this worker.

Primary references: [ad comments](https://docs.zernio.com/platforms/meta-ads/ad-comments),
[comment reads and replies](https://docs.zernio.com/comments/reply-to-inbox-post),
[private replies](https://docs.zernio.com/comments/send-private-reply-to-comment).
