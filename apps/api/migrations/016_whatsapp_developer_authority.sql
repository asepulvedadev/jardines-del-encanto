-- Channel authority is explicit and revocable; no browser sessions are fabricated.
ALTER TABLE crm.whatsapp_agent ADD COLUMN owner_id uuid REFERENCES crm.users(id) ON DELETE SET NULL;
ALTER TABLE crm.hermes_runs ADD COLUMN authentication text NOT NULL DEFAULT 'browser'
 CHECK(authentication IN ('browser','whatsapp_developer'));
ALTER TABLE crm.hermes_runs ALTER COLUMN session_hash DROP NOT NULL;
ALTER TABLE crm.hermes_runs ADD CONSTRAINT hermes_authentication_binding CHECK(
 (authentication='browser' AND session_hash IS NOT NULL) OR
 (authentication='whatsapp_developer' AND session_hash IS NULL));
CREATE TABLE crm.whatsapp_developer_authority (
 run_id uuid PRIMARY KEY REFERENCES crm.hermes_runs(id) ON DELETE CASCADE,
 job_id uuid NOT NULL UNIQUE REFERENCES crm.whatsapp_agent_jobs(id) ON DELETE CASCADE,
 owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
 agent_version integer NOT NULL CHECK(agent_version>0),
 account_id varchar(160) NOT NULL, profile_id varchar(160) NOT NULL,
 conversation_id varchar(512) NOT NULL, participant_id varchar(32) NOT NULL,
 credential_revision char(64) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX whatsapp_developer_owner ON crm.whatsapp_developer_authority(owner_id,created_at);
REVOKE ALL ON crm.whatsapp_developer_authority FROM PUBLIC;
GRANT SELECT,INSERT ON crm.whatsapp_developer_authority TO jardines_crm_app;
