# Jardines del Encanto

Monorepo for a lot-sales landing page and an AI-native CRM in Acacías, Meta, Colombia.
**Current delivery: infrastructure foundation, not a finished sales application.**

## Quick start

Requires Node.js 24, npm, Python 3.13, uv 0.11.8 and Docker Compose.

```sh
npm ci
npm run dev
uv sync --project apps/api --frozen
uv run --project apps/api uvicorn app.main:app --app-dir apps/api --reload
```

The web development server uses port 3000. API liveness is `/health/live` on port 8000.
Readiness intentionally returns 503 until a database and its password file are configured.
Production uses the root-owned Compose policy; do not run it locally against real data.

| Location | Purpose |
| --- | --- |
| `apps/web` | Next.js App Router, React, TypeScript and Tailwind CSS |
| `apps/api` | Python / FastAPI API; database-aware health checks |
| `ops` | Reviewed deployment gate, fixed runtime policy and backups |
| `docs/PLAN.md` | Product roadmap, architecture and acceptance criteria |
| `DESIGN.md` | Canonical brand, landing, CRM and AI-interface design contract |
| `.agents/skills/jardines-ui` | Project-scoped UI guidance for future work |
| `docs/DESIGN-SOURCES.md` | Requested external design sources and pending review status |
| `docs/DEPLOY.md` | Quick deployment and recovery guide |
| `docs/SECURITY.md` | Security boundaries, responsibilities and remaining work |

## Verification

```sh
npm run typecheck && npm run build
uv run --project apps/api --frozen ruff check apps/api
uv run --project apps/api --frozen pytest apps/api/tests -q
python3 -m unittest discover -s tests -v
```

Pushes to `main` verify the code, build and smoke-test the whole stack on an ephemeral
GitHub runner, then deploy the exact commit using a restricted SSH identity.
Pull requests never receive production credentials.

No license grant is implied by public source visibility. Customer data, keys, private
commercial information and operational evidence do not belong in this repository.

Landing content, asset provenance and local checks: [LANDING.md](docs/LANDING.md).

Private CRM local setup and security: [CRM.md](docs/CRM.md).
