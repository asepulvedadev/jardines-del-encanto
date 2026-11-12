-- ElevenLabs is isolated behind a private credential boundary and starts paused.
ALTER TABLE crm.control_connections DROP CONSTRAINT control_connections_key_check;
ALTER TABLE crm.control_connections ADD CONSTRAINT control_connections_key_check
 CHECK (key IN ('hermes','zernio','facebook','instagram','tiktok','whatsapp','telegram','elevenlabs'));
INSERT INTO crm.control_connections(key,enabled) VALUES ('elevenlabs',false);
CREATE TABLE crm.voice_catalog (
 id boolean PRIMARY KEY DEFAULT true CHECK(id),
 revision integer NOT NULL CHECK(revision>=0),
 catalog jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.voice_artifacts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
 proposal_id uuid UNIQUE REFERENCES crm.hermes_proposals(id) ON DELETE SET NULL,
 kind text NOT NULL CHECK(kind IN ('input','output')),
 filename varchar(120) NOT NULL,
 mime_type varchar(80) NOT NULL,
 size integer NOT NULL CHECK(size BETWEEN 1 AND 2097152 AND size=octet_length(data)),
 data bytea NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(kind!='input' OR size<=524288)
);
CREATE INDEX voice_artifacts_owner ON crm.voice_artifacts(owner_id);
CREATE TABLE crm.voice_session_claims (
 proposal_id uuid PRIMARY KEY REFERENCES crm.hermes_proposals(id) ON DELETE CASCADE,
 owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
 claimed_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON crm.voice_catalog,crm.voice_artifacts,crm.voice_session_claims FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.voice_catalog TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.voice_artifacts,crm.voice_session_claims TO jardines_crm_app;
