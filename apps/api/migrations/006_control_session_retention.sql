-- Revocation checks use live-session joins, not destructive audit-history cascades.
-- Keep the original initiating session hash after logout for immutable attribution.
ALTER TABLE crm.hermes_runs DROP CONSTRAINT hermes_runs_session_hash_fkey;
ALTER TABLE crm.hermes_proposals DROP CONSTRAINT hermes_proposals_session_hash_fkey;
