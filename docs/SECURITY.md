# Security boundaries

## Implemented controls

- A dedicated Compose project, internal application/data networks and database volume;
  only the web service also joins its project-specific ingress bridge for loopback publishing.
- Only `127.0.0.1:13400` is published. API and PostgreSQL have no published ports.
- Non-root web/API/DB processes, read-only roots, dropped capabilities, resource and
  PID limits, no-new-privileges, bounded logs and writable tmpfs paths.
- A dedicated project BuildKit worker capped at two CPU cores, 3 GiB memory/no extra
  swap and 512 PIDs. The deploy gate checks the worker's actual resource policy.
- A root-owned deployment policy, strict command grammar, fetched main-tip checks,
  serialized deployment, readiness verification and previous-image recovery.
- Exclusive deploy identity; forced command, no forwarding/PTY, no Docker-group access,
  no personal SSH key in CI, and verified SSH host keys.
- CI actions pinned to commits; read-only GitHub token; production credentials scoped
  to a `main`-only deployment environment. Fork PR verification does not deploy.
- Root-only secret parent directory. Mounted DB password file is readable inside only
  the two containers requiring it; its value is not stored in code or environment logs.
- Separate Hermes state and pinned image, no network or active gateway by default.

## Important limits

Docker isolation on a shared rootful daemon is **not VM isolation**. Host administrators
and compromised Docker daemon access can reach sibling projects. The CI key cannot
arbitrarily control Docker, but trusted `main` code supplies Dockerfiles and application
code; repository write access is production code-execution authority inside this project.
Do not grant write access to untrusted contributors. Never mount host sockets in Hermes.
The root-managed BuildKit worker uses the Docker container driver's privileged daemon;
it is administrative infrastructure, never exposed to Hermes or the deploy identity.
Runtime caps do not bound disk cache growth: monitor project images, backups and builder
cache and perform only explicitly scoped maintenance. Never prune the shared daemon.

Database bootstrap currently uses one DB identity for a health-only service. Before
business tables, create separate migration/runtime identities with least privilege.
There is no authentication yet, and no private data/API is exposed. Do not add customer
routes without server-side authorization, session security, rate limits and audit tests.

No claim is made that all existing services or the whole host have been hardened. The
bootstrap deliberately leaves shared SSH, firewall, Docker and Nginx policies unchanged.
Off-host disaster recovery, production domain/TLS, monitoring, data-protection policy,
AI provider and autonomous actions are pending and are not represented as complete.
