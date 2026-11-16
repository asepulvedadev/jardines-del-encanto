-- Private, independently activated TikTok DM intake; existing channels keep their epoch.
CREATE TABLE crm.tiktok_intake_config (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 owner_id uuid NOT NULL REFERENCES crm.users(id), profile_id text NOT NULL,
 account_id text NOT NULL, credential_revision char(64) NOT NULL,
 group_url text NOT NULL, proof_event_id text NOT NULL REFERENCES crm.social_webhook_events(event_id),
 enabled boolean NOT NULL DEFAULT true, version integer NOT NULL DEFAULT 1,
 enabled_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE crm.social_onboarding DROP CONSTRAINT social_onboarding_platform_check;
ALTER TABLE crm.social_onboarding ADD CONSTRAINT social_onboarding_platform_check
 CHECK(platform IN ('whatsapp','facebook','tiktok'));
ALTER TABLE crm.social_onboarding
 ADD COLUMN introduction_receipt jsonb NOT NULL DEFAULT '{}',
 ADD COLUMN confirmation_receipt jsonb NOT NULL DEFAULT '{}';
ALTER TABLE crm.social_onboarding DROP CONSTRAINT social_onboarding_state_check;
ALTER TABLE crm.social_onboarding ADD CONSTRAINT social_onboarding_state_check CHECK(state IN (
 'pending','waiting','captured','question_reserved','audio_reserved','audio_accepted',
 'links_reserved','website_reserved','website_accepted','group_reserved',
 'introduction_reserved','introduction_accepted','confirmation_reserved','confirmation_accepted',
 'completed','unknown','blocked'));
CREATE TABLE crm.tiktok_reply_reservations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 onboarding_id uuid NOT NULL REFERENCES crm.social_onboarding(id),
 profile_id text NOT NULL, account_id text NOT NULL, participant_id text NOT NULL,
 phase text NOT NULL, source_message_id text NOT NULL DEFAULT '',
 message_id text, reserved_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(onboarding_id,phase,source_message_id)
);
CREATE INDEX tiktok_reply_budget ON crm.tiktok_reply_reservations
 (profile_id,account_id,participant_id,reserved_at);
REVOKE ALL ON crm.tiktok_intake_config,crm.tiktok_reply_reservations FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.tiktok_intake_config,crm.tiktok_reply_reservations TO jardines_crm_app;
