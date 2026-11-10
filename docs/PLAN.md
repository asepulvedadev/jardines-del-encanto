# Product and delivery plan

## Outcome and scope

Jardines del Encanto sells lots in Acacías, Meta, Colombia. Build a focused public
website and a minimal private CRM where AI assists everyday work through controlled
tools rather than an unrestricted chatbot or direct database access.

The owner requested Next.js and current Tailwind for the frontend, Python for the
backend, a monorepo, a shared VPS, an isolated Hermes workspace, GitHub Actions
continuous deployment, and a quick deployment guide. **Phase 0 is the current scope.**
Later phases are proposals, not authorization to collect customer data or activate channels.

## Brand and verified content

- Reference: the owner's supplied marketing image, stored as `docs/brand-reference.png`.
- Working palette sampled visually: deep forest `#062619`, leaf `#658d24`, ivory `#f6f7f1`.
  These are provisional design tokens, not an official color specification.
- Preserve the identity's palms and typography when an original transparent logo is supplied.
  The attached poster is not a vector logo; do not distort or automatically recreate it.
- Product copy should be professional Colombian Spanish once the owner approves it.
  The current internal infrastructure placeholder is English.
- The poster is a visual reference, not proof of built amenities, current availability,
  prices, lot sizes, utility connections, legal status or investment returns.

## Architecture

```text
Visitor / authenticated salesperson
  -> HTTPS reverse proxy (existing host Nginx, new vhost only after domain selection)
  -> Next.js web (public site + private CRM routes)
  -> FastAPI business API
  -> PostgreSQL (no published database port)

Hermes (separate identity, state and runtime)
  -> future narrowly scoped CRM tool API
  -> human-approved actions + audit log
```

One npm workspace holds the frontend; the API has its own uv lockfile. Runtime images
are pinned by digest, JavaScript dependencies by exact versions + lockfile, Python by
uv lock + hashed production requirements. Stable versions were checked at bootstrap;
updates require a reviewed dependency change, not floating `latest` upgrades.

Use a modular Python backend with business modules for leads, inventory, sales and
AI tools. Keep authorization and transaction rules in the API, not in prompts or UI.
Start as one deployable API; avoid microservices, Redis and a separate queue until
durable workloads require them. PostgreSQL outbox/jobs are a possible next step,
not implemented infrastructure.

Hermes is independent of the API's Python environment. Its pinned upstream image may
use a different Python version. Do not copy credentials or profiles from other projects.

## Phase 0 — repository and safe infrastructure

Deliver a public monorepo, a health-only FastAPI backend, an internal Next.js preview,
PostgreSQL, project-local Docker networks/volume, resource caps, log rotation, daily
logical backups, a constrained deploy identity, locked CI actions, a deployment gate
and application-image rollback. Install a pinned Hermes image and isolated state;
do not activate an AI provider, messaging gateway or public dashboard.

Acceptance: CI succeeds, the full readiness chain passes, deployment is serialized,
arbitrary SSH commands are rejected, rollback selects a previously healthy release,
only the web loopback port is published, and pre-existing services retain their
observed health and container identities. Record actual evidence separately from intent.

## Phase 1 — approved public website

Create a restrained, mobile-first landing page using verified location, original
photos, approved amenities and clear contact/visit calls to action. Include map,
project overview, lot information, questions and privacy/consent content where approved.
Build lead capture in the API with validation, rate limiting, spam protection,
source attribution and deduplication. Do not display fabricated scarcity or prices.

Acceptance: keyboard-usable forms, responsive visual review, approved content,
working lead persistence and source attribution, public HTTPS and no exposed CRM data.
Select a domain and contact channel before publication.

## Phase 2 — minimal private CRM

Proposed core modules: leads/contacts, board and list pipeline, next action, assigned
salesperson, notes/activity timeline, visits, and lot inventory with approved status rules.
Initial roles: administrator and salesperson; confirm access boundaries with the owner.
Add authentication, secure sessions, server-side authorization and append-only audit
events before any private routes or customer information become reachable.

Acceptance: public users cannot read CRM data; salespeople cannot bypass assignment
rules; filtering and mobile flows work; audit events identify actor/action/time; lot
reservation conflicts cannot produce double allocations.

## Phase 3 — AI-native assistance

Give Hermes a project-specific persona, verified knowledge and tools such as lead
summary, follow-up draft, activity lookup, visit proposal and availability lookup.
Show proposed changes in the CRM with confirmation and an audit trail.

Treat incoming messages, uploaded documents and CRM notes as untrusted data, not
instructions. Require API-side scopes and validation for every action. Start with
read-only tools and drafts; do not allow autonomous contracts, lot reservations,
discounts, destructive actions, bulk messaging or financial promises.

Acceptance: no raw SQL or shell exposed to customer messages; no access to sibling
projects, deployment keys or host sockets; idempotent writes; confirmed tool actions;
model usage budget and observable failures; prompt-injection and scope-denial tests.

## Phase 4 — operations and growth

Only after actual workflow validation: approved WhatsApp integration, consent-based
follow-up scheduling, visit reminders, sales reporting, and document workflows.
Payments, financing, contracts and accounting require a separate business/legal scope.
Do not infer these from the word CRM.

Before real customer data: verified off-host encrypted backups, restore drill,
monitoring/alerts, data retention/deletion process, production access review and an
owner-approved incident response process. Local backups alone are not disaster recovery.

## Decisions still required

The owner must supply the production domain, original logo/photos, approved commercial
facts, contact number/channel, team roles and first sales workflow. AI provider/model,
spend limits, data retention and channel activation also remain unconfigured.
No fixed launch date or implementation estimate is promised without those decisions.

## Primary references

- [Next.js standalone deployment](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)
- [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/)
- [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use)
- [Docker security](https://docs.docker.com/engine/security/)
- [Hermes upstream Docker guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/docker.md)
