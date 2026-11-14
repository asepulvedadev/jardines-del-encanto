-- Approved immutable sequence snapshots, independent grants, and no-replay reservations.
CREATE TABLE crm.workflow_definitions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(120) NOT NULL,
 description varchar(1000) NOT NULL DEFAULT '', document jsonb NOT NULL,
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.workflow_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workflow_id uuid NOT NULL REFERENCES crm.workflow_definitions(id),
 workflow_name varchar(120) NOT NULL, workflow_version integer NOT NULL,
 snapshot jsonb NOT NULL, fingerprint char(64) NOT NULL,
 prepared_by uuid NOT NULL REFERENCES crm.users(id), created_at timestamptz NOT NULL DEFAULT now(),
 review_expires_at timestamptz NOT NULL, started_at timestamptz,
 status text NOT NULL DEFAULT 'prepared' CHECK(status IN ('prepared','active','paused','completed','stopped','blocked','unknown')),
 version integer NOT NULL DEFAULT 1 CHECK(version>0)
);
CREATE TABLE crm.workflow_grants (
 run_id uuid PRIMARY KEY REFERENCES crm.workflow_runs(id), actor_id uuid NOT NULL REFERENCES crm.users(id),
 fingerprint char(64) NOT NULL, consent_confirmed boolean NOT NULL CHECK(consent_confirmed),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 CHECK(expires_at>created_at AND expires_at<=created_at + interval '30 days')
);
CREATE TABLE crm.workflow_recipients (
 run_id uuid NOT NULL REFERENCES crm.workflow_runs(id), contact_id uuid NOT NULL REFERENCES crm.contacts(id),
 status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','blocked','unknown','stopped')),
 current_node_id varchar(80), due_at timestamptz NOT NULL DEFAULT now(), error varchar(160),
 PRIMARY KEY(run_id,contact_id)
);
CREATE TABLE crm.workflow_steps (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL,
 contact_id uuid NOT NULL, node_id varchar(80) NOT NULL,
 state text NOT NULL CHECK(state IN ('reserved','completed','failed','unknown')),
 reserved_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 external boolean NOT NULL, receipt jsonb NOT NULL DEFAULT '{}',
 FOREIGN KEY(run_id,contact_id) REFERENCES crm.workflow_recipients(run_id,contact_id),
 UNIQUE(run_id,contact_id,node_id)
);
CREATE TABLE crm.workflow_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES crm.workflow_runs(id),
 contact_id uuid, node_id varchar(80), kind varchar(80) NOT NULL,
 message varchar(300) NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX workflow_active_runs ON crm.workflow_runs(created_at) WHERE status='active';
CREATE INDEX workflow_due_recipients ON crm.workflow_recipients(due_at,run_id) WHERE status='active';
CREATE INDEX workflow_inflight_steps ON crm.workflow_steps(reserved_at) WHERE state='reserved';
CREATE INDEX workflow_daily_dispatches ON crm.workflow_steps(run_id,reserved_at) WHERE external;
CREATE INDEX workflow_run_events ON crm.workflow_events(run_id,created_at);
REVOKE ALL ON crm.workflow_definitions,crm.workflow_runs,crm.workflow_grants,
 crm.workflow_recipients,crm.workflow_steps,crm.workflow_events FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.workflow_definitions TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.workflow_runs,crm.workflow_grants,crm.workflow_events TO jardines_crm_app;
-- The application cannot alter an approved audience, snapshot, fingerprint, grant or expiry.
GRANT UPDATE(status,version,started_at) ON crm.workflow_runs TO jardines_crm_app;
GRANT SELECT,INSERT,UPDATE ON crm.workflow_recipients,crm.workflow_steps TO jardines_crm_app;
