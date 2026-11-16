-- Preserve the safest participant history when upgrading conversation-only intake.
-- Do not alter prior migration checksums or discard historical delivery receipts.
UPDATE crm.social_onboarding SET state='unknown',error='interrupted',audio=NULL
 WHERE state IN ('audio_reserved','links_reserved','question_reserved','website_reserved','group_reserved');

WITH canonical AS (
 SELECT DISTINCT ON (profile_id,account_id,platform,participant_id)
 profile_id,account_id,platform,participant_id,id
 FROM crm.social_onboarding
 ORDER BY profile_id,account_id,platform,participant_id,
 suppressed DESC,
 CASE
  WHEN state IN ('unknown','blocked') THEN 0
  WHEN group_receipt->>'status'='accepted' OR links_receipt->>'status'='accepted'
    OR (state='completed' AND welcome_required) THEN 1
  WHEN state='website_accepted' THEN 2
  WHEN state='audio_accepted' THEN 3
  WHEN state='completed' THEN 5
  ELSE 4
 END,created_at,id
)
UPDATE crm.social_welcome_claims c SET onboarding_id=o.id FROM canonical o
 WHERE (c.profile_id,c.account_id,c.platform,c.participant_id)=
       (o.profile_id,o.account_id,o.platform,o.participant_id);

-- Choose the original STOP row first, then spread its opt-out to every sibling.
UPDATE crm.social_onboarding o SET suppressed=true
 WHERE NOT o.suppressed AND EXISTS (
 SELECT 1 FROM crm.social_onboarding s WHERE s.suppressed AND
 (s.profile_id,s.account_id,s.platform,s.participant_id)=
 (o.profile_id,o.account_id,o.platform,o.participant_id));
UPDATE crm.social_onboarding o SET welcome_required=(o.id=c.onboarding_id)
 FROM crm.social_welcome_claims c
 WHERE (o.profile_id,o.account_id,o.platform,o.participant_id)=
       (c.profile_id,c.account_id,c.platform,c.participant_id);
CREATE INDEX social_onboarding_suppressed_participant
 ON crm.social_onboarding(profile_id,account_id,platform,participant_id) WHERE suppressed;
