# Minimal private CRM

**Scope:** minimal CRM prepared for the owner-authorized VPS release.
The existing public landing remains unchanged. `DESIGN.md` governs private UI density.

## What is included

| Workspace | Implemented behavior |
| --- | --- |
| Login | Private administrator access, no public signup, real PostgreSQL sessions |
| Overview | Actual customer/opportunity/task counts, pending work and recent activity |
| Customers | Create/edit/search: name, mobile number and acquisition source only |
| Pipeline | Kanban, drag between stages, keyboard-accessible stage selector and list view |
| Follow-ups | Customer-linked tasks with a date, complete and reopen actions |
| Customer drawer | Phone/WhatsApp handoff, commercial stage, notes, tasks and activity history |

Acquisition sources are Presencial, Campaña de redes, Página web, Referido, WhatsApp
and Otro. No email, ID document, address, budget or additional customer field is collected.
The API rejects unexpected input fields. Technical IDs, versions and timestamps are
not additional business form fields. A normalized mobile number is unique.

Creating a customer atomically creates its opportunity in **Nuevo**. The remaining
stages are Contactado, Visita, Negociación, Ganado and Descartado. Closing an opportunity
does not create a property sale, reserve a lot or certify payment. Notes and follow-ups
belong to commercial work, not extra mandatory customer profile fields.

There is no demo customer data, fabricated activity, CRM AI response, lot inventory,
WhatsApp automation or outbound message sending. WhatsApp buttons only open its external
website, with the exact validated customer number, on a deliberate user action.

## Local startup

Requirements: Node 24, Python 3.13 through `uv`, and Docker/Compose. These operations
create only the `jardines-crm-dev` Compose project and its dedicated database volume.
They must never be pointed at the shared VPS.

```sh
npm ci
uv sync --project apps/api --frozen
uv run --project apps/api python ops/dev/crm.py init
uv run --project apps/api python ops/dev/crm.py create-admin
# Enter the owner-selected password at the hidden prompts; never put it in a command.
```

The username defaults to `adminjardines`. The requested administrator was created in
the local database using the owner's password; no plaintext password is in source,
examples, documentation, browser storage or seed data. Creation refuses to overwrite an
existing account. Do not rerun `create-admin` to reset an existing password.

Use separate terminals:

```sh
uv run --project apps/api python ops/dev/crm.py api
uv run --project apps/api python ops/dev/crm.py web
# Open http://127.0.0.1:4320/login
```

The API binds to `127.0.0.1:8001`; PostgreSQL binds to `127.0.0.1:15432`.
The wrapper passes generated connection settings as server environment variables.
Local-only database passwords live under ignored `.local/crm/` (private parent directory).
That directory is also excluded from Docker build contexts. Never commit or publish it.
`CRM_ALLOW_INSECURE_HTTP=1` is accepted only for explicit localhost/127.0.0.1 origins.

Stop the terminals with Ctrl-C and stop only the development database with:

```sh
docker compose -f ops/dev/compose.yaml stop
```

Do not add `--volumes`: the named volume preserves local customers and the administrator.

## Database and security boundaries

- `crm` schema: users, sessions, login limits, contacts, deals, tasks, activities and
  migration history. No unrelated schema/table is modified.
- Migration owner `jardines_crm_migrator` is separate from runtime `jardines_crm_app`.
  Runtime has no DDL, user-write, contact-delete or activity-update/delete permission.
- `app.crm.manage migrate` applies checked SQL migrations explicitly, in one transaction
  under a PostgreSQL advisory lock. Applied migration checksum changes are rejected.
  Application startup never performs migrations or seeds/resets an administrator.
- [Argon2 password hashing](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
  uses `pwdlib[argon2]`; there is no password comparison or hashing implementation of our own.
- Sessions use random 256-bit tokens; only their SHA-256 verifiers are stored. Absolute
  expiry is eight hours, with a 30-minute idle timeout. Logout deletes the server session.
- Production cookies use `__Host-`, Secure, HttpOnly, SameSite=Lax and Path=/, with no
  Domain. CSRF uses an independent session token and exact configured Origin validation,
  including login. See [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
- Login throttling is shared in PostgreSQL: five attempts per username and 100 globally
  per 15-minute window. Two concurrent password checks per process bound Argon2 memory.
- Every private API operation authenticates an enabled administrator. The Next server
  validates sessions before rendering CRM data; it does not trust a client-side redirect.
- The browser sees a small same-origin, allowlisted BFF. It forwards only session/CSRF/origin
  headers to the configured backend, rejects non-JSON/oversized writes and never proxies
  arbitrary destinations. Responses and private server fetches are not cached.
- Record versions reject stale edits with 409. Business writes and their activity events
  share one transaction. The current conflict UI preserves the draft and asks the user to
  copy it and reload, rather than silently overwriting a newer edit.
- Queries use bound parameters; validation and database failures do not return credentials,
  submitted passwords, connection strings or raw SQL errors.

The workspace returns at most 500 records per section and visibly discloses truncation;
counts cover all records. The activity feed is bounded, while the drawer loads the
selected opportunity's latest 100 events. Server pagination is a follow-up before
larger volumes; this version is deliberately a small-team workspace.

## Verification

```sh
npm run typecheck
npm run test:crm:gateway       # Node 24 executes the TypeScript route handler directly
npm run test:crm               # 24 API tests, including real PostgreSQL persistence
npm run build
python3 -m unittest discover -s tests -p 'test_*.py'
LANDING_BASE_URL=http://127.0.0.1:4320 npm run test:web
```

The isolated integration test database is `jardines_crm_test`, not the local working
CRM database. Fixtures reset only that database's CRM tables. Without explicit test
connection settings, database tests skip; the wrapper and CI initialize them explicitly.
The CI job is configured to create a separate PostgreSQL Compose project and run these tests,
then removes only its ephemeral runner test volume in an `always()` cleanup step.

Browser checks exercise the actual Next → FastAPI → PostgreSQL path: protected access,
three-field customer creation, stage changes, note/task creation, task completion,
editing, reload persistence and logout. Widths 320, 390, 768 and 1440 px are checked;
the Kanban/table use labeled local scrolling rather than overflowing the page.
Native dialogs, persistent labels, keyboard stage changes and focus-return behaviors
are included. No full accessibility or penetration-test certification is claimed.

## VPS deployment

The owner authorized publishing this release to `main`, production deployment and the
administrator-only CRM credential/runtime upgrade. Follow [DEPLOY.md](DEPLOY.md) for
the root-owned policy and explicit migration gate. Never reuse another project's
credentials or copy local customer/session data.

1. Obtain authorization for this release and its PostgreSQL migration/runtime policy.
2. Back up and test recovery; provision dedicated migration/runtime credentials only
   within the project's database. Review grants before migration; do not run API queries
   as the existing bootstrap superuser.
3. Install reviewed root-owned configuration and private environment files. Set `CRM_DATABASE_URL`
   in the API and `CRM_ORIGIN` in API/web to the exact approved HTTPS origin; never use
   the local insecure flag in production. The web also needs its existing `API_BASE_URL`.
4. Apply migrations explicitly as the owner and bootstrap the administrator through
   hidden input. The password requested in chat should be rotated before public use.
5. Verify authenticated/unauthenticated flows, TLS/CSRF/cookies, backups, restore and
   the existing landing/sibling projects before publishing the CRM link.

MFA, password reset/change screens, user management, advanced reporting, pagination,
customer export/deletion/retention workflows and a production data-protection policy
are not part of this first version. Agree on those before collecting real customer
records at scale. Rolling back an application image does not roll back schema/data.

### Observed verification

The 24 API tests (including three independent concurrency/rollback probes), four
BFF handler tests, 10 existing deployment tests and three landing tests pass locally.
Both production Docker images build successfully. The complete authenticated browser
flow also passes against nonroot/read-only API and web containers with PostgreSQL.
The verifier found no reproducible blockers. Release-specific CI and production checks must be observed before reporting deployment
success. Known non-blocking test warnings are Starlette/httpx deprecation
and Node's module-type inference when executing the TypeScript handler directly.

Current production-build local preview: `http://127.0.0.1:4321/login`, served by
`jardines-crm-web-check` and `jardines-crm-api-check`. These are local verification
containers, not a VPS deployment. The standard development runner above uses port4320.
UI fixtures and their temporary administrator were removed from the working database;
only the requested administrator remains and customer/opportunity/task counts are zero.
HTML5 drag/drop and the list fallback also passed a PostgreSQL reload-persistence check.
Session memory registration was unavailable; source and this guide preserve the work.
