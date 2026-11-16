-- Private configuration and once-only, ordered public social lead onboarding.
CREATE TABLE crm.social_onboarding_config (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 owner_id uuid NOT NULL REFERENCES crm.users(id),
 profile_id text NOT NULL, accounts jsonb NOT NULL, credential_revision char(64) NOT NULL,
 group_url text NOT NULL, facebook_takeover boolean NOT NULL DEFAULT false,
 enabled boolean NOT NULL DEFAULT true, version integer NOT NULL DEFAULT 1,
 enabled_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.social_onboarding (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 profile_id text NOT NULL, account_id text NOT NULL, conversation_id text NOT NULL,
 participant_id text NOT NULL, platform text NOT NULL CHECK(platform IN ('whatsapp','facebook')),
 config_version integer NOT NULL, source jsonb NOT NULL, next_source jsonb,
 details jsonb NOT NULL DEFAULT '{}',
 contact_id uuid REFERENCES crm.contacts(id) ON DELETE SET NULL,
 deal_id uuid REFERENCES crm.deals(id) ON DELETE SET NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN (
 'pending','waiting','captured','question_reserved','audio_reserved','audio_accepted',
 'links_reserved','completed','unknown','blocked')),
 suppressed boolean NOT NULL DEFAULT false, asked boolean NOT NULL DEFAULT false,
 audio bytea, audio_receipt jsonb NOT NULL DEFAULT '{}', links_receipt jsonb NOT NULL DEFAULT '{}',
 error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(profile_id,account_id,conversation_id),
 CHECK(audio IS NULL OR octet_length(audio) BETWEEN 12 AND 2097152)
);
CREATE INDEX social_onboarding_pending ON crm.social_onboarding(state,created_at);
CREATE TABLE crm.social_welcome_audio (
 hash char(64) PRIMARY KEY, id uuid NOT NULL UNIQUE,
 state text NOT NULL CHECK(state IN ('synthesizing','ready')),
 data bytea CHECK(data IS NULL OR octet_length(data) BETWEEN 12 AND 2097152),
 created_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON crm.social_onboarding_config,crm.social_onboarding,crm.social_welcome_audio FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.social_onboarding_config,crm.social_onboarding,crm.social_welcome_audio TO jardines_crm_app;
