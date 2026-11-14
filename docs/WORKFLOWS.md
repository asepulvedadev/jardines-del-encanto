# Approved multichannel sequences

Local implementation contract. The owner requested a Leadgenerator-style combined
sequence connected to Zernio, Retell and the CRM, then confirmed creation after the
choice of automatic execution following initial approval. No production activation,
real outreach, credential change, commit or deployment is part of this local task.

## Product and authority

Add a Spanish `Secuencias` CRM workspace, visual builder, schedule and contact/run
history. Preserve Jardines' light/forest-green design. Take Leadgenerator's draft,
reviewed frozen run, durable per-contact cursor and no-replay semantics, not its
branding, email/LinkedIn qualification or provider identities. Contacts still need
only their existing name, phone and source; optional social conversation binding is
run metadata, never another required CRM contact field.

An administrator saves a versioned draft, selects at most 50 existing contacts,
prepares a frozen review, then explicitly approves exact recipients, sender accounts,
Retell agent/number, template/message content, schedule, action limits and outreach
consent. No sending occurs during saving/preparing. Activation grants only that
immutable run, not broad future automation or a browser-session impersonation.
A synchronous review is limited to 10 external contact × node plans and a 60-second
read-only preparation budget. CRM-only audiences may contain 50 contacts. Exceeding
either limit rejects the review without partial activation; errors are
`workflow_provider_review_limit` and `workflow_review_budget_exceeded`. The daily
action cap is separate from this review budget.
Grant lifetime is bounded (maximum 30 days); prepared review expires in 10 minutes.
Worker authority rechecks the enabled administrator and configured connections.
No automatic replay after an uncertain send/call or crashed reserved dispatch.

Initial triggers are explicit audience activation. Do not silently enroll future
leads, publish one social post per contact, generate unreviewed outbound AI copy,
start a model call, or bypass existing Colombian Retell route restrictions.
Sara can inspect sequences and propose draft/control actions through the existing
typed broker; human activation remains explicit in the sequence review.

## Shared HTTP contract

All routes below are under `/crm/workflows`, exposed as `/api/crm/workflows` only
through the strict existing gateway. Existing session/Origin/CSRF protections apply.
Mutation JSON limit 64 KiB only for definitions/preparation; no arbitrary paths/URLs.

- `GET /catalog` -> `{worker:{enabled:boolean,available:boolean},nodes:[{kind,label,available,reason?}],connections:[{key,name,available,reason?}]}`.
- `GET /definitions` -> `{workflows:Workflow[]}`.
- `POST /definitions` input `{name,description?,document}` -> Workflow.
- `PATCH /definitions/{id}` input `{version,name?,description?,document?}` -> Workflow.
- `POST /options` input `{provider:"zernio"|"retell",account_id?:string}` -> safe provider options.
- `POST /definitions/{id}/prepare` input `{version,contact_ids:string[],bindings?:[{contact_id,conversation_id,account_id}],consent_confirmed:boolean}` -> RunReview.
- `POST /runs/{id}/activate` input `{fingerprint,consent_confirmed:boolean}` -> Run.
- `POST /runs/{id}/pause|resume|stop` input `{version}` -> Run.
- `GET /runs` -> `{runs:Run[]}`; `GET /runs/{id}` -> RunDetail.

Workflow = `{id,name,description,document,version,created_at,updated_at}`.
Document = `{entry_id,nodes:Node[],schedule:{timezone:"America/Bogota",days:number[],start_time:"HH:MM",end_time:"HH:MM",daily_limit:number},stop_on_reply:boolean}`.
Schedule days use ISO 1 (Monday) through 7 (Sunday). Start is inclusive, end is
exclusive, and start must precede end; overnight windows are not supported in v1.
Daily limit is 1–100, default 20, in the fixed America/Bogota timezone.

Node = `{id,kind,label,position:{x:number,y:number},next_id?:string|null,on_true?:string|null,on_false?:string|null,settings:object}`.
Kinds/settings (strict per kind, max 20 nodes, DAG, all nodes reachable):

- `whatsapp_template`: `{account_id,template_name,language,parameters:string[]}`. Approved Meta template only.
- `social_message`: `{account_id,platform:"facebook"|"instagram"|"telegram"|"tiktok"|"whatsapp",text}`. Requires an exact existing conversation binding per recipient and a supported provider channel/window. Never infer a DM recipient from a CRM phone.
- `retell_call`: `{agent_id,from_number}`. One existing CRM recipient; preserve current route restrictions.
- `wait`: `{hours:number}` (0..720).
- `condition`: `{field:"stage"|"source",operator:"equals",value:string}`. Actual CRM state; absent data holds, never false.
- `crm_note`: `{body}`; `crm_task`: `{title,due_days:number}`.
- `end`: `{}`.
  Only fixed `{{nombre}}` and `{{celular}}` placeholders are supported. No eval,
  custom URLs, arbitrary executable nodes or unrestricted JSON tool execution.

RunReview = `{run:Run,fingerprint,expires_at,recipients:[{contact_id,name,phone,source,channel_recipient?}],steps:[{node_id,label,kind,description}],warnings:string[]}`.
Run = `{id,workflow_id,workflow_name,workflow_version,status,version,created_at,started_at?,expires_at?,counts:{total,completed,active,blocked,unknown,stopped}}`.
RunDetail = `{run:Run,recipients:[{contact_id,name,phone,status,current_node_id?,current_node_label?,due_at?,error?}],events:[{id,contact_id?,node_id?,kind,message,created_at}]}`.
Statuses: prepared,active,paused,completed,stopped,blocked,unknown. Step/event outcomes
must distinguish provider submission from delivery, answered call or sale.

## Provider adapter seam

`app.social.workflow` owns reviewed fixed-host Zernio methods only:

- `options(db, account_id=None)` -> `{available,reason?,accounts:[],templates:[],conversations:[]}`.
- `prepare(db,node,contact,binding=None,cache=None)` -> JSON-safe private frozen adapter plan, containing `summary` for review and no raw credentials. No sends.
- `dispatch(plan,request_id)` -> `{state:"completed"|"failed"|"unknown",receipt:object,error?:string}`; once only.
- `check(plan)` revalidates current provider identity/configuration; raises opaque HTTPException if changed/unavailable.
- `normalize_event(payload)` -> safe account/conversation/participant/event identity or None, used only after existing webhook authentication and deduplication.
  Node/contact parameters are plain dicts, node shape above; contact contains id/name/phone/source/stage. Bindings contain explicit account_id/conversation_id.
  The engine may persist private provider revisions/recipient identity, never tokens.
  Use current official Zernio docs for actual endpoints/shapes and existing TLS egress.
  OAuth accounts:read alone is not send authority. No live API requests during tests.
  Retell adapter stays in app.workflows and reuses existing reviewed freeze/prepare/
  execute_reserved validation; no bypass of consent, schema hash or recipient binding.

## Runtime and checks

Use additive migration 012, least-privilege grants, immutable run snapshots, per-contact
due cursors, unique run/contact/node reservations and SKIP LOCKED claims. Commit a
reservation before external I/O. Expired in-flight reservations become unknown and
held; they are never resent. Worker errors never dump credentials or raw vendor errors.
Background worker is explicitly enabled with CRM_WORKFLOWS_WORKER_ENABLED=1 and
stops on API shutdown. Activation requires actual worker readiness. Default is off;
UI must disclose that clearly. Local deterministic tests may call worker.tick directly.
Pause and stop prevent new dispatches but cannot cancel an already in-flight
provider operation. A late receipt must never reactivate a stopped run.
No production root policy changes in this task.

Reuse existing CRM service helpers for notes/tasks, fixed Retell gateway, and social
HMAC/replay protection. No new frontend/runtime dependencies without a named need.
Test auth/CSRF, strict graphs/bounds, stale reviews/versions, immutable audience and
provider revisions, consent, scheduling, step order, stop/pause, concurrent claims,
unknown outcomes/no replay, contact changes and verified stop-on-reply. Test with
mock providers and isolated jardines_crm_test only. Browser verification uses a local
synthetic fixture, never customers, paid providers or production chat.

Reference: local Leadgenerator campaign-workflow-studio and campaign-workflow-runtime.
Official Zernio sources: https://docs.zernio.com/platforms/whatsapp/inbox and
https://docs.zernio.com/messages/list-inbox-conversations .
