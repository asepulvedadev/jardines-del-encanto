# Project-private Zernio HTTPS egress

The production API stays on the internal `app` and `data` networks. A separate
credential-free CONNECT relay joins `app` and the project-only `zernio_egress`
network. No host port is published, and API core readiness does not depend on the
relay. This does not change the Hermes profile or grant new OAuth scopes.

## Fixed transport contract

`app.social.transport.https_connection(host, timeout)` accepts exactly:

- `zernio.com`
- `mcp.zernio.com`

With `ZERNIO_HTTPS_PROXY` absent, the helper preserves direct HTTPS for local use.
It ignores ambient `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` settings. If the
project variable is present, its only valid value is
`http://zernio-egress:8080`; even alternate schemes, ports, paths, credentials,
trailing slashes, and empty values are rejected with `ValueError`.

Proxy mode creates `http.client.HTTPSConnection('zernio-egress', 8080, timeout=...)`
and calls `set_tunnel(target, 443)`. Python establishes an HTTP CONNECT tunnel,
then wraps that stream in verified TLS using the **target** hostname for SNI and
certificate validation. Credentials are sent only inside this end-to-end TLS
connection. The relay has no certificates, trust-root overrides, OAuth grants,
REST keys, DB connections, or customer storage.

The existing REST/MCP adapters retain their fixed application paths, methods, and
scope checks and must sanitize helper/configuration exceptions. The relay cannot
inspect encrypted inner HTTP paths or methods without terminating TLS; it rejects
all **outer** methods except CONNECT and all request targets except the exact two
host:443 authorities. It is not a general HTTP or MCP forwarding endpoint.

## Relay limits and fail-closed behavior

| Boundary | Limit |
| --- | --- |
| Accepted targets | Exact `zernio.com:443`, `mcp.zernio.com:443` |
| CONNECT headers | 4 KiB; 3-second total deadline |
| Accepted headers | Optional single matching Host; required for HTTP/1.1 |
| Request body/framing | Denied before tunnel establishment |
| Active tunnel handlers | 8, bounded before creating a worker thread |
| Concurrent DNS work | 4; no unbounded executor queue |
| DNS result | At most 16 TCP addresses; every address must be public/global |
| DNS wait | 2 seconds; stuck work retains its capacity slot until completion |
| Connect attempt | 3 seconds, also bounded by overall lifetime |
| Tunnel traffic | 2 MiB aggregate across both directions |
| Tunnel idle/lifetime | 5 seconds / 30 seconds |
| Forwarding buffer | At most 16 KiB per read |

DNS validation rejects private, loopback, link-local, reserved, multicast,
unspecified, mapped IPv4, and scoped IPv6 addresses. A mixed public/private answer
is rejected in full. Connections use the already-vetted numeric sockaddr, never a
second lookup of the hostname. Public DNS changes therefore cannot turn a checked
answer into an unchecked private destination.

No request line, host header, authorization value, DNS response, encrypted payload,
upstream error, or traceback is logged. Failure responses contain only generic
status lines and empty bodies. After CONNECT succeeds, limits close the opaque
stream rather than injecting plaintext into TLS. The relay does not follow
redirects; application adapters already reject unexpected vendor response statuses.

## Root-owned production policy

`ops/crm.compose.yaml` reuses the existing `jardines-api:${RELEASE}` image solely as
a Python runtime and replaces its command with `python /policy/egress.py`.
The service runs as UID/GID 10001 with read-only storage, all capabilities dropped,
no-new-privileges, 96 MiB memory and swap cap, 0.25 CPU, 32 PIDs, and a 4 MiB
non-executable tmpfs. It mounts only this root-owned policy file, read-only:

`/srv/jardines-del-encanto/zernio-policy/egress.py`

The bind has `create_host_path: false`; a missing reviewed policy cannot become an
automatically created directory or load an application release's arbitrary file.
There is no env-file, secret, database/customer volume, Docker socket, or published
port on this service. Only this service joins the new `zernio_egress` network.
The API retains its existing networks and gains only the fixed proxy variable and
`ZERNIO_MCP_OAUTH_ENABLED=1`; its database readiness dependency is unchanged.

Parent/operator deployment is separate from these local changes. Install the
reviewed policy with root ownership and runtime-readable/non-writable permissions
only **after** Nginx OAuth callback logging is sanitized. Then recreate the optional
relay with the intended release image, verify constrained egress and read-only
OAuth access, and activate the reviewed production policy. A stored OAuth token or
successful TCP CONNECT is not proof of authorization, account identity, or permission
to publish or send messages.

## Verification without vendor calls

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_zernio_egress.py
RELEASE=0000000000000000000000000000000000000000 \
  docker compose -f ops/crm.compose.yaml config --no-env-resolution --quiet
```

`--no-env-resolution` intentionally avoids reading absent/private production env
files while still validating Compose syntax and topology. No image pull, service
activation, provider credential, OAuth token, database, or foreign network request
is needed for these checks.

The suite verifies target/configuration denial, private/mixed DNS rejection,
header overflow, bounded admission and stuck DNS capacity, vetted-IP connection,
aggregate bytes/deadlines, direct HTTPS compatibility, and default verified TLS.
A real loopback TLS fixture sends an HTTP request through the actual CONNECT relay,
proves the trusted target certificate succeeds, and proves a different target
hostname fails certificate verification. Only fixture DNS/dial destinations and a
self-signed test CA are substituted; TLS itself is not mocked. This optional fixture
uses an already installed `openssl` executable and explicitly skips if unavailable.
Its dummy certificate/key scratch directory is printed and retained for parent cleanup;
no files are installed globally and no real credentials are used.
