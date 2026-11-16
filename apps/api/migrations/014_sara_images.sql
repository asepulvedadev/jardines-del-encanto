-- Private image concepts. External calls only follow committed processing claims.
CREATE TABLE crm.sara_image_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
 request_id uuid NOT NULL, payload_hash char(64) NOT NULL,
 prompt varchar(2000) NOT NULL CHECK(length(trim(prompt))>0),
 reference_ids jsonb NOT NULL CHECK(jsonb_typeof(reference_ids)='array' AND jsonb_array_length(reference_ids)<=3),
 reference_versions jsonb NOT NULL,
 image_size text NOT NULL CHECK(image_size IN ('1024x1024','1536x1024','1024x1536')),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','processing','completed','unknown','failed')),
 data bytea CHECK(octet_length(data)<=8388608),
 error varchar(80), created_at timestamptz NOT NULL DEFAULT now(),
 claimed_at timestamptz, finished_at timestamptz,
 UNIQUE(owner_id,request_id),
 CHECK((status='completed')=(data IS NOT NULL))
);
CREATE INDEX sara_images_owner_created ON crm.sara_image_jobs(owner_id,created_at DESC);
CREATE INDEX sara_images_queue ON crm.sara_image_jobs(created_at,id) WHERE status='queued';
CREATE INDEX sara_images_processing ON crm.sara_image_jobs(claimed_at) WHERE status='processing';
REVOKE ALL ON crm.sara_image_jobs FROM PUBLIC;
GRANT SELECT,INSERT ON crm.sara_image_jobs TO jardines_crm_app;
GRANT UPDATE(status,data,error,claimed_at,finished_at) ON crm.sara_image_jobs TO jardines_crm_app;
