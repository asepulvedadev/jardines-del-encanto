-- Private image delivery is permanently bound to its verified developer source.
CREATE TABLE crm.sara_image_deliveries (
 image_id uuid PRIMARY KEY REFERENCES crm.sara_image_jobs(id) ON DELETE CASCADE,
 owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
 origin_run_id uuid NOT NULL REFERENCES crm.whatsapp_developer_authority(run_id) ON DELETE CASCADE,
 binding jsonb NOT NULL CHECK(jsonb_typeof(binding)='object'),
 content_hash char(64) NOT NULL,
 byte_size integer NOT NULL CHECK(byte_size BETWEEN 57 AND 8388608),
 state text NOT NULL DEFAULT 'pending'
  CHECK(state IN ('pending','preparing','reserved','completed','blocked','unknown')),
 receipt jsonb NOT NULL DEFAULT '{}', error varchar(80),
 created_at timestamptz NOT NULL DEFAULT now(), claimed_at timestamptz, finished_at timestamptz
);
CREATE INDEX sara_image_delivery_pending ON crm.sara_image_deliveries(created_at,image_id) WHERE state='pending';
CREATE INDEX sara_image_delivery_claimed ON crm.sara_image_deliveries(claimed_at) WHERE state IN ('preparing','reserved');
REVOKE ALL ON crm.sara_image_deliveries FROM PUBLIC;
GRANT SELECT,INSERT ON crm.sara_image_deliveries TO jardines_crm_app;
GRANT UPDATE(state,receipt,error,claimed_at,finished_at) ON crm.sara_image_deliveries TO jardines_crm_app;
