# Sara application extensions

Sara can create, edit, install and test **declarative application extensions** through
its existing `jardines_app` tool. This does not install native Hermes packages or
permit Sara to program the application, provider boundary or runtime.

## Lifecycle

All calls use the existing authenticated broker and its live administrator identity.
The internal bearer flow also retains its per-run action scope, deduplication, call
and output budgets. Arguments are strict JSON; IDs and optimistic versions must
come from actual tool results or `control.catalog`.

| Action | Arguments | Confirmed result |
| --- | --- | --- |
| `control.extension.create` | `kind`, `name`, optional `description`, `definition` | Own disabled draft, version 1 |
| `control.extension.update` | `id`, `version`, changed `name`, `description` or `definition` | Own updated disabled draft, next version |
| `control.extension.install` | `id`, `version` | Enable a validated own extension, next version |
| `control.extension.test` | `id`, `version` | Validation report; no action dispatch or business effects |

These four lifecycle actions return immediately, without a business proposal. They
can only manage records created with `origin=sara` by the same administrator.
Existing human records cannot be adopted or edited through this lifecycle. An
administrator may still edit extensions in Settings using the existing control UI.
Failed validation/version checks roll back the entire operation. Successful lifecycle
operations are audited. `test` records an audit event but does not change the
extension version, call business tools, contact a provider or create proposals.

A successful `test` is **validation, not an executed workflow or integration test**.
The result explicitly returns `side_effects: false` and lists each action with its
approval requirement. Tools may leave required inputs for invocation; scripts must
contain valid complete step arguments. Validation cannot prove future record IDs or
versions will still exist when a workflow is used.

## Definitions

- **Skill:** `{"content":"# Workflow guidance"}`. Instructions are untrusted guidance,
  not executable code or authority to override operator rules.
- **Tool:** `{"action":"crm.workspace","defaults":{"limit":10}}`. Invocation merges
  these typed defaults with explicit arguments.
- **Plugin:** `{"actions":["crm.workspace"],"instructions":"Read before proposing."}`.
  This groups fixed application actions; it is not a native plugin, binary or package.
- **Script:** `{"steps":[{"action":"crm.workspace","arguments":{"limit":10}}]}`.
  Up to eight fixed typed steps; no Python, JavaScript, shell, URLs or imports.

Targets are restricted to `crm.workspace`, `crm.activities`, `crm.contact.create`,
`crm.contact.update`, `crm.deal.update`, `crm.note.create`, `crm.task.create`,
`crm.task.update` and `social.status`. No nested customization, `custom.*` indirection,
connection changes, social mutations, arbitrary endpoints or raw-code execution is
accepted. Unknown fields fail validation rather than being silently ignored.

## Installation and authority

Installation checks canonical administrator capability preferences. Sara aliases do
not override or replace a human tool preference, even when multiple aliases target
the same action. Disabling a canonical capability makes its aliases ineffective and
revokes associated pending proposals. Existing human-tool uniqueness is preserved.

Installed extensions and skill guidance become available on the **next chat turn**.
An active run keeps its frozen claim; creating/installing a new alias does not add
that alias to the current run. Editing an alias invalidates its old version and
requires installation again. Read results remain immediate; actual business changes
still produce exact session-bound proposals requiring administrator approval.

The runtime still has exactly one typed application tool, read-only application
code/runtime mounts and no shell, arbitrary filesystem/network tool, native plugin
loader, background worker or external package installer exposed to Sara.

## Verification

Regression coverage: `apps/api/tests/test_control_extensions.py`, existing control
plane/broker suites and `tests/test_hermes_operator_protocol.py`. Database tests only
run against the explicitly guarded `jardines_crm_test` database. Tests never use real
provider inference or real customer data. Migration 009 adds an origin marker and
an additive Sara-owner index without changing existing records' human ownership.

## Coordinated runtime rollout required

This implementation is local, not a production activation. A later authorized
release must apply migrations008/009 and install the reviewed root-owned
`operator.py` and `operator_protocol.py` policy files together, preserving their
individual read-only mounts. Restart both private operator services: the bridge
and provider each import the strict protocol. Do not publish the API changes alone:
an older root-owned protocol rejects the new `control.extension.*` action enum and
would reject otherwise ordinary text runs. Keep the former app and policy bundle
available for coordinated rollback; never weaken the protocol's allowlist or
broaden mounts to work around a mismatched release.

### Observed local verification

- Complete API suite:192 passed, existing Starlette TestClient deprecation warning.
- CRM gateway/UI suite:61 passed; TypeScript and production build passed.
- Runtime/infrastructure:82 tests (81 passed, one opt-in pinned-image test skipped
  in the ordinary host runner); the genuine pinned Hermes Docker run separately
  passed all14 tests with `--network none` and deterministic upstream transport.
- Independent fresh-snapshot verification:63 focused API tests passed and no
  reproducible change-caused blocker was found in deletion, permissions or races.
- Browser:390/1440 synthetic API checks observed picker keyboard/mouse behavior,
  Settings-only management and confirmed deletion/retry/draft/tombstone flows.
  No production, real provider inference, paid transcription or microphone test.
