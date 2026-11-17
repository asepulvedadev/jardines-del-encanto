-- Drafts are separate from identity and transport receipts. Existing input keys
-- bind each generated phase to one verified customer message.
ALTER TABLE crm.social_onboarding_inputs
 ADD COLUMN tiktok_replies jsonb NOT NULL DEFAULT '{}'
 CHECK(jsonb_typeof(tiktok_replies)='object');
