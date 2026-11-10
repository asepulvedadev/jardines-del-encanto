# Bootstrap verification — 2026-11-10

This is observed evidence for the infrastructure foundation, not certification of the
whole shared host or a claim that the CRM is implemented.

## Observed checks

- Ten deployment regression tests passed: strict SSH grammar, invalid-command exit,
  rollback admission, previous-pointer preservation, stale-deploy rejection, atomic
  extraction retry and missing builder resource-policy rejection.
- Four API tests passed: liveness, DB-aware readiness, unavailable-DB redaction and
  absent private endpoints/docs. Ruff, TypeScript and production Next.js builds passed.
- Production web/API Docker images built with the pinned Node 24 / Python 3.13 bases.
  All three services became healthy in a local full-stack test. Readiness was also
  reached from the host, not merely from inside the containers.
- An isolated local restore rehearsal recovered a test row from a logical backup.
- [Initial real CI/CD run](https://github.com/asepulvedadev/jardines-del-encanto/actions/runs/42849536835)
  verified commit `56078de044439dfaa42f955eafb33d8ea66f330a`, smoke-tested the complete
  stack on GitHub's runner and deployed it successfully to the VPS.
- The dedicated CI key rejected an arbitrary `id` command with exit 2; it did not open
  a shell. Its account has no Docker-group membership. Production environment admits
  only `main`, and the GitHub token defaults to read-only permissions.
- Actual VPS builder limits: 3 GiB memory, 3 GiB combined memory/swap, two CPU cores,
  and 512 PIDs. The backup timer is active. The backup service succeeded, and a backup's
  checksum, compression and restore into a separate temporary database were verified.
- Hermes's pinned image ran offline and reported `Hermes Agent v0.23.1`, upstream
  `3b421578`, Python `3.14.9`. No provider credentials or messaging channel were added.

## Corrections made before acceptance

1. Docker's internal-only bridge did not publish the web loopback port. The web service
   now also joins a project-only ingress bridge; API/data networks remain internal.
2. An independent review found unbounded shared-host builds and non-atomic extraction.
   Both were fixed, covered by regression tests and passed a scoped independent recheck.
3. Host `install` rejected the absent numeric Hermes UID as an owner name. Provisioning
   now creates the directory first and applies numeric ownership with `chown`.
4. The initial successful workflow warned that older action generations targeted
   Node 20. The action pins were updated to verified official Node-24-based releases.

## Limits and pending work

- API tests currently emit an upstream Starlette warning about its legacy `httpx`
  TestClient integration. Tests pass; no runtime business endpoint depends on it.
- No deliberate failed production release or destructive production restore was injected.
  Failure recovery is regression-tested; local restoration used isolated test data.
- No production domain, HTTPS vhost, customer authentication, CRM, public lead form,
  off-host backup destination or autonomous AI/channel is active yet.
- Host-wide firewall, unrelated services and existing Nginx configuration were not changed.
  Existing-service health and identities are compared again after final deployment.
