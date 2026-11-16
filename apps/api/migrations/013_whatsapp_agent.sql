-- Dedicated public WhatsApp agent; never shares administrator conversations or tools.
CREATE TABLE crm.whatsapp_agent (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 version integer NOT NULL CHECK(version>0), enabled boolean NOT NULL DEFAULT false,
 enabled_at timestamptz, document jsonb NOT NULL, credential_revision char(64),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.whatsapp_agent_revisions (
 version integer PRIMARY KEY, document jsonb NOT NULL, author varchar(160) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.whatsapp_agent_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_id varchar(200) NOT NULL UNIQUE,
 account_id varchar(160) NOT NULL, profile_id varchar(160) NOT NULL,
 conversation_id varchar(512) NOT NULL, participant_id varchar(32) NOT NULL,
 message_id varchar(512) NOT NULL, agent_version integer NOT NULL,
 sent_at timestamptz NOT NULL, content varchar(2000) NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN
 ('pending','generating','reserved','completed','blocked','unknown')),
 reply varchar(1500), error varchar(100), receipt jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(), claimed_at timestamptz, finished_at timestamptz,
 UNIQUE(account_id,conversation_id,message_id)
);
CREATE INDEX whatsapp_agent_due ON crm.whatsapp_agent_jobs(created_at) WHERE state='pending';
CREATE INDEX whatsapp_agent_claims ON crm.whatsapp_agent_jobs(claimed_at) WHERE claimed_at IS NOT NULL;
CREATE INDEX whatsapp_agent_history ON crm.whatsapp_agent_jobs(account_id,conversation_id,created_at);
CREATE TABLE crm.whatsapp_agent_lessons (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid NOT NULL UNIQUE
 REFERENCES crm.whatsapp_agent_jobs(id) ON DELETE CASCADE,
 content varchar(1000) NOT NULL, author varchar(160) NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','approved','rejected')),
 created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz
);
REVOKE ALL ON crm.whatsapp_agent,crm.whatsapp_agent_revisions,
 crm.whatsapp_agent_jobs,crm.whatsapp_agent_lessons FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.whatsapp_agent TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.whatsapp_agent_revisions TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.whatsapp_agent_jobs TO jardines_crm_app;
GRANT UPDATE(state,reply,error,receipt,claimed_at,finished_at) ON crm.whatsapp_agent_jobs TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.whatsapp_agent_lessons TO jardines_crm_app;
GRANT UPDATE(state,resolved_at) ON crm.whatsapp_agent_lessons TO jardines_crm_app;
