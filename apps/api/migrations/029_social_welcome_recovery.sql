-- Private audit marker for explicitly owner-authorized unanswered-event recovery.
-- Ordinary signed webhooks retain their fifteen-minute enrollment cutoff.
ALTER TABLE crm.social_onboarding ADD COLUMN recovery_event_id varchar(200);
