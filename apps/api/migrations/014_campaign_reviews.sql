-- Immutable review snapshots are separate from editable local drafts.
CREATE TABLE crm.campaign_reviews (
 id uuid PRIMARY KEY,
 slug varchar(80) NOT NULL REFERENCES crm.campaign_drafts(slug),
 version integer NOT NULL CHECK (version > 0),
 profile_id varchar(160) NOT NULL,
 account_id varchar(160) NOT NULL,
 account_label varchar(160) NOT NULL,
 name varchar(100) NOT NULL,
 snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
 image_sha256 char(64),
 media_token_hash char(64),
 media_expires_at timestamptz,
 status varchar(24) NOT NULL CHECK (status IN ('SUBMITTING','UNKNOWN','PENDING','APPROVED','REJECTED','IN_APPEAL','PAUSED','DISABLED','PENDING_DELETION')),
 provider_id varchar(160),
 category varchar(24),
 created_by uuid NOT NULL REFERENCES crm.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 checked_at timestamptz,
 UNIQUE (slug, version, profile_id, account_id),
 UNIQUE (profile_id, account_id, name)
);
CREATE INDEX campaign_reviews_history ON crm.campaign_reviews(slug, created_at DESC);
GRANT SELECT, INSERT, UPDATE ON crm.campaign_reviews TO jardines_crm_app;
