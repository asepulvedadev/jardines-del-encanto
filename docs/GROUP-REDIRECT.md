# Branded WhatsApp group link

`https://jardinesdelencanto.site/grupo` redirects GET and HEAD requests directly
to the owner's approved WhatsApp invitation:

`https://chat.whatsapp.com/FiK8zZOYcj75lggiCfsNaq?s=cl&p=i&iam=2`

The route uses a temporary HTTP 302 with `Cache-Control: no-store`, so a future
invitation replacement does not rely on clearing permanent browser redirects.
Its fixed destination ignores request parameters, preventing open redirects and
accidental forwarding of personal data. No intermediary page, database write,
message send, or existing campaign/agent configuration change is involved.
The redirect is excluded from indexing through its response header and does not
send a referrer. A successful redirect does not prove WhatsApp group membership
or that the invitation remains accepted by WhatsApp.

Implementation: `apps/web/app/grupo/route.ts`.
Check: `node --test tests/group-redirect.test.mjs`.
Publish only through a separately authorized project deployment.
