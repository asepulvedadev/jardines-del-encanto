-- Separate welcome progression from identity capture; preserve historical sends.
ALTER TABLE crm.social_onboarding
 ADD COLUMN website_receipt jsonb NOT NULL DEFAULT '{}',
 ADD COLUMN group_receipt jsonb NOT NULL DEFAULT '{}',
 ADD COLUMN welcome_required boolean NOT NULL DEFAULT true;
ALTER TABLE crm.social_onboarding DROP CONSTRAINT social_onboarding_state_check;
ALTER TABLE crm.social_onboarding ADD CONSTRAINT social_onboarding_state_check CHECK(state IN (
 'pending','waiting','captured','question_reserved','audio_reserved','audio_accepted',
 'links_reserved','website_reserved','website_accepted','group_reserved',
 'completed','unknown','blocked'));

-- Never replay an interrupted external side effect or an old combined-link send.
UPDATE crm.social_onboarding SET state='unknown',error='interrupted',audio=NULL
 WHERE state IN ('audio_reserved','links_reserved','question_reserved');
UPDATE crm.social_onboarding SET state='pending' WHERE state='waiting';

CREATE TABLE crm.social_welcome_claims (
 profile_id text NOT NULL, account_id text NOT NULL, platform text NOT NULL,
 participant_id text NOT NULL,
 onboarding_id uuid NOT NULL REFERENCES crm.social_onboarding(id) ON DELETE CASCADE,
 PRIMARY KEY(profile_id,account_id,platform,participant_id)
);
INSERT INTO crm.social_welcome_claims
 SELECT DISTINCT ON (profile_id,account_id,platform,participant_id)
 profile_id,account_id,platform,participant_id,id
 FROM crm.social_onboarding
 ORDER BY profile_id,account_id,platform,participant_id,
 (suppressed OR state IN ('completed','unknown','blocked')) DESC,created_at,id;
-- A participant may already have multiple historical threads. Retain every row,
-- but only its conservative canonical claim may continue an unfinished welcome.
UPDATE crm.social_onboarding o SET welcome_required=false
 FROM crm.social_welcome_claims c
 WHERE (o.profile_id,o.account_id,o.platform,o.participant_id)=
       (c.profile_id,c.account_id,c.platform,c.participant_id)
 AND o.id<>c.onboarding_id;

CREATE TABLE crm.social_onboarding_inputs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 onboarding_id uuid NOT NULL REFERENCES crm.social_onboarding(id) ON DELETE CASCADE,
 message_id text NOT NULL, source jsonb NOT NULL,
 processed boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(onboarding_id,message_id)
);
CREATE INDEX social_onboarding_inputs_pending ON crm.social_onboarding_inputs(onboarding_id,created_at,id)
 WHERE NOT processed;
INSERT INTO crm.social_onboarding_inputs(onboarding_id,message_id,source,created_at)
 SELECT id,source->>'message_id',source,created_at FROM crm.social_onboarding
 WHERE state NOT IN ('completed','unknown','blocked') AND NOT suppressed
 ON CONFLICT DO NOTHING;
INSERT INTO crm.social_onboarding_inputs(onboarding_id,message_id,source,created_at)
 SELECT id,next_source->>'message_id',next_source,created_at+interval '1 microsecond'
 FROM crm.social_onboarding WHERE next_source IS NOT NULL
 AND state NOT IN ('completed','unknown','blocked') AND NOT suppressed
 ON CONFLICT DO NOTHING;
REVOKE ALL ON crm.social_welcome_claims,crm.social_onboarding_inputs FROM PUBLIC;
GRANT SELECT,INSERT ON crm.social_welcome_claims TO jardines_crm_app;
GRANT SELECT,INSERT,UPDATE ON crm.social_onboarding_inputs TO jardines_crm_app;
