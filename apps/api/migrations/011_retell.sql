-- Retell is a separate private provider and starts disabled.
ALTER TABLE crm.control_connections DROP CONSTRAINT control_connections_key_check;
ALTER TABLE crm.control_connections ADD CONSTRAINT control_connections_key_check
 CHECK (key IN ('hermes','zernio','facebook','instagram','tiktok','whatsapp','telegram','elevenlabs','retell'));
INSERT INTO crm.control_connections(key,enabled) VALUES ('retell',false);
CREATE TABLE crm.retell_session_claims (
 proposal_id uuid PRIMARY KEY REFERENCES crm.hermes_proposals(id) ON DELETE CASCADE,
 owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
 session_hash text NOT NULL REFERENCES crm.sessions(token_hash) ON DELETE CASCADE,
 claimed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX retell_session_claims_owner ON crm.retell_session_claims(owner_id);
REVOKE ALL ON crm.retell_session_claims FROM PUBLIC;
GRANT SELECT,INSERT ON crm.retell_session_claims TO jardines_crm_app;
