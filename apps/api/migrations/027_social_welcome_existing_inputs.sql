-- Support the per-conversation rolling input budget without scanning its history.
CREATE INDEX social_onboarding_inputs_recent ON crm.social_onboarding_inputs(onboarding_id,created_at);
