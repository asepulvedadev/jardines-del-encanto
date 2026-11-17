-- Additive: preserve historical welcome receipts and enforce durable opt-outs.
ALTER TABLE crm.social_onboarding
 ADD COLUMN registration_first boolean NOT NULL DEFAULT false,
 ADD COLUMN identity_confirmed boolean NOT NULL DEFAULT false,
 ADD COLUMN question_receipt jsonb NOT NULL DEFAULT '{}';

CREATE TABLE crm.social_opt_outs (
 profile_id text NOT NULL, account_id text NOT NULL, platform text NOT NULL,
 participant_id text NOT NULL, conversation_id text NOT NULL,
 event_id text NOT NULL, credential_revision char(64) NOT NULL,
 remote_state text NOT NULL DEFAULT 'pending' CHECK(remote_state IN ('pending','synced','blocked')),
 attempts integer NOT NULL DEFAULT 0, next_attempt timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(profile_id,account_id,platform,participant_id)
);
CREATE INDEX social_opt_outs_due ON crm.social_opt_outs(next_attempt) WHERE remote_state='pending';
REVOKE ALL ON crm.social_opt_outs FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.social_opt_outs TO jardines_crm_app;
