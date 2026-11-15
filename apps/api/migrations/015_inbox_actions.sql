-- Explicit, actor-bound confirmation and no-replay receipts for inbox writes.
CREATE TABLE crm.inbox_actions (
 id uuid PRIMARY KEY,
 actor_id uuid NOT NULL REFERENCES crm.users(id),
 profile_id varchar(160) NOT NULL,
 account_id varchar(160) NOT NULL,
 account_label varchar(200) NOT NULL,
 generation_hash char(64) NOT NULL,
 operation varchar(80) NOT NULL,
 arguments jsonb NOT NULL CHECK(jsonb_typeof(arguments)='object'),
 state varchar(20) NOT NULL DEFAULT 'prepared'
  CHECK(state IN ('prepared','sending','sent','rejected','unknown')),
 error varchar(80),
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT now() + interval '10 minutes',
 completed_at timestamptz
);
CREATE INDEX inbox_actor_history ON crm.inbox_actions(actor_id,created_at DESC);
REVOKE ALL ON crm.inbox_actions FROM PUBLIC;
GRANT SELECT,INSERT ON crm.inbox_actions TO jardines_crm_app;
GRANT UPDATE(state,error,completed_at) ON crm.inbox_actions TO jardines_crm_app;
