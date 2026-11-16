-- Private, source-bound paid synthesis. Never substitute a fabricated broker proposal.
CREATE TABLE crm.whatsapp_agent_audio (
 job_id uuid PRIMARY KEY REFERENCES crm.whatsapp_agent_jobs(id) ON DELETE CASCADE,
 owner_id uuid NOT NULL REFERENCES crm.users(id),
 voice_id varchar(128) NOT NULL, model_id varchar(128) NOT NULL,
 provider_revision integer NOT NULL CHECK(provider_revision>=0),
 connection_version integer NOT NULL CHECK(connection_version>0),
 state text NOT NULL CHECK(state IN ('synthesizing','reserved','completed','unknown')),
 data bytea, content_hash char(64),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((data IS NULL AND content_hash IS NULL) OR
        (octet_length(data) BETWEEN 12 AND 2097152 AND content_hash IS NOT NULL))
);
CREATE INDEX whatsapp_audio_budget ON crm.whatsapp_agent_audio(owner_id,created_at);
REVOKE ALL ON crm.whatsapp_agent_audio FROM PUBLIC;
GRANT SELECT,INSERT ON crm.whatsapp_agent_audio TO jardines_crm_app;
GRANT UPDATE(state,data,content_hash) ON crm.whatsapp_agent_audio TO jardines_crm_app;
