-- Preserve revocable channel provenance across delayed paid work. Never synthesize web authority.
ALTER TABLE crm.sara_image_jobs ADD COLUMN origin_kind text NOT NULL DEFAULT 'web'
 CHECK(origin_kind IN ('web','whatsapp_developer'));
ALTER TABLE crm.sara_image_jobs ADD COLUMN origin_run_id uuid;
ALTER TABLE crm.sara_image_jobs ADD CONSTRAINT image_origin_binding CHECK(
 (origin_kind='web' AND origin_run_id IS NULL) OR
 (origin_kind='whatsapp_developer' AND origin_run_id IS NOT NULL));
ALTER TABLE crm.sara_simulations ADD COLUMN origin_kind text NOT NULL DEFAULT 'web'
 CHECK(origin_kind IN ('web','whatsapp_developer'));
ALTER TABLE crm.sara_simulations ADD COLUMN origin_run_id uuid;
ALTER TABLE crm.sara_simulations ADD CONSTRAINT simulation_origin_binding CHECK(
 (origin_kind='web' AND origin_run_id IS NULL) OR
 (origin_kind='whatsapp_developer' AND origin_run_id IS NOT NULL));
-- No UPDATE grant on provenance: the runtime may reserve outcomes, never rewrite origin.
