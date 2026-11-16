-- Shared published agent configuration and isolated synthetic conversation runs.
CREATE TABLE crm.sara_profile (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 version integer NOT NULL CHECK(version>0), document jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.sara_profile_versions (
 version integer PRIMARY KEY, document jsonb NOT NULL,
 actor_id uuid REFERENCES crm.users(id) ON DELETE SET NULL,
 source text NOT NULL CHECK(source IN ('web','whatsapp_developer')),
 author varchar(160) NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.sara_simulations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), request_id uuid NOT NULL,
 owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
 title varchar(120) NOT NULL, input jsonb NOT NULL, input_hash char(64) NOT NULL,
 profile_version integer NOT NULL, profile jsonb NOT NULL,
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','processing','completed','failed','unknown')),
 transcript jsonb NOT NULL DEFAULT '[]', error varchar(100),
 created_at timestamptz NOT NULL DEFAULT now(), claimed_at timestamptz, finished_at timestamptz,
 UNIQUE(owner_id,request_id)
);
CREATE INDEX sara_simulation_queue ON crm.sara_simulations(created_at) WHERE status='queued';
CREATE INDEX sara_simulation_owner ON crm.sara_simulations(owner_id,created_at DESC);
REVOKE ALL ON crm.sara_profile,crm.sara_profile_versions,crm.sara_simulations FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.sara_profile TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.sara_profile_versions TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.sara_simulations TO jardines_crm_app;
GRANT UPDATE(status,transcript,error,claimed_at,finished_at) ON crm.sara_simulations TO jardines_crm_app;
ALTER TABLE crm.whatsapp_agent_jobs ADD COLUMN shared_profile_version integer NOT NULL DEFAULT 1;
