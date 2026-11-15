-- Internal editable drafts, independent of provider review and delivery state.
CREATE TABLE crm.campaign_drafts (
 slug varchar(80) PRIMARY KEY,
 document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
 version integer NOT NULL DEFAULT 1 CHECK (version > 0),
 updated_by uuid NOT NULL REFERENCES crm.users(id),
 updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON crm.campaign_drafts TO jardines_crm_app;
