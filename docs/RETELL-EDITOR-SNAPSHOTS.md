# Complete Retell editor snapshots

This local-only extension supports modal editing without copying clipped provider
snapshots into write drafts. It is not a dashboard-parity claim and does not perform
writes, approvals, microphone access, paid tests or deployment.

## Authenticated API contract

`POST /crm/retell/editor` accepts exactly:

```json
{ "revision": 1, "kind": "instructions", "id": "llm_example", "version": 7 }
```

`kind` is `agent` or `instructions`. IDs are nonempty, bounded provider identifiers;
version is optional, a strict nonnegative integer (including zero). Query parameters,
extra fields, arbitrary endpoints and URLs are rejected. Existing administrator
sessions, exact Origin/CSRF checks, bounded request bodies and private/no-store
responses apply. Parent BFF integration must admit only this exact POST route.

The fixed reads are `getAgent` and `getRetellLLM`. Configuration writes still use
normal exact broker proposals and human approval. Export: `editor.snapshot(data,admin)`.
The response is:

```json
{
  "provider": "retell",
  "status": "completed",
  "endpoint": "getRetellLLM",
  "data": {
    "llm_id": "llm_example",
    "version": 7,
    "general_prompt": "Exact complete text"
  },
  "editor": {
    "complete_fields": ["general_prompt", "begin_message"],
    "blocked_fields": { "general_tools": "editor_field_private" }
  }
}
```

The shortened metadata above is illustrative: a real response partitions **every**
reviewed update-schema root into `complete_fields` or `blocked_fields`. Safe known
absent fields belong to `complete_fields` but are absent from `data`. A blocked root
is entirely absent from `data`; it is never redacted and then labelled complete.
Only roots permitted by `updateAgent`/`updateRetellLLM`, plus exact resource identity
and valid returned version, are exposed. Unknown provider roots are ignored.
A requested pinned version must match the returned version exactly.

## Safety and limits

The dedicated gateway `POST /editor-read` accepts the existing exact prepared-read
payload, restricted to the two reads above. It reuses the normal execution schema
check, durable reservation and configuration/key-rotation lock. A private internal
projection flag is not a request field; normal `/execute` results retain their
existing partial/redacted semantics.

The editor projection consumes the original provider object, not `safe_output` or
`service.safe_result`. Each root is checked against its strict pinned update schema,
including OpenAPI nullable values. It preserves safe nulls, empty arrays, empty
objects and strings exactly. Sensitive children, actual provider-key occurrences,
credential-like values, credential-bearing/private URLs, unknown fixed-object
children, excessive depth/size and schema mismatches block the **entire root**.
Public nonprivate URLs are validated without rewriting the returned value.

Per string: at most 16,000 characters. Per array: at most 100 elements. Per object:
at most 200 entries. Per root: at most 3,000 nodes and depth 20. The complete gateway
response, including editor metadata, is at most 96 KiB of serialized JSON. A field
that would exceed the total budget is blocked rather than truncated. Unicode is
counted as encoded JSON bytes for the budget, not JavaScript string length.

The API validates complete/blocked coverage and schema values again. It shares the
existing three-read concurrency semaphore. Current actor/session, enabled connection
version, provider revision and schema hash are checked before and after dispatch.
An 85-second operational budget bounds follow-on work; existing DB/transport limits
still apply, not a hard realtime guarantee under arbitrary OS stalls. The prepared
and completed `retell.editor_read` audits contain endpoint, stage and revisions only.
Read snapshots are not persisted in proposals, chat, audit, database or the
inventory cache. Explicitly edited values enter the existing proposal/approval
contract only when the administrator requests review.

UI callers must treat a returned complete root as the only prefill source. Blocked
roots remain unavailable and must not be silently deleted when saving other fields.
Missing completeness metadata fails closed. A legacy partial inventory response is
not a complete editor snapshot. Modal drafts and provider execution remain separate.

## Activation boundary

The application image alone cannot activate this protocol on production. The owner
must separately authorize installation of the reviewed root-owned gateway source
with `/editor-read`. No root policy, key, volume, registry, schema, environment,
dependency or migration is changed by this source work. Existing configured provider
credentials remain exclusively in private gateway state. Do not copy them into the
API or Hermes, or mutate another project's gateway.

Until that reviewed gateway update is installed, the new editor API fails safely as
unavailable; it must not fall back to partial provider data. Root gateway source and
application UI/API should be deployed as a compatible unit with an administrator
checkpoint and existing project isolation checks. Rollback to the old API leaves the
new gateway's normal `/execute` behavior intact.

## Verification

New tests use local fake gateway/vendor objects only. Missing-module/method RED was
observed before implementation. The gateway tests verify exact long prompts, known
absence, nulls, whole-root private/unknown/oversized blocking, private URL variants,
identity/version, total Unicode JSON budget, strict protocol and normal-execute
compatibility. Pure API tests verify models, routes, complete coverage, metadata-only
audits and post-read session/connection/provider/schema invalidation. Guarded DB
cases are authored for the parent's serial isolated CRM runner and are not run by
this unit. Real provider completeness and deployed runtime installation remain
separate verification obligations.
