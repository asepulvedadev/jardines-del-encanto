-- Pin the owner-verified voice instead of silently following future provider defaults.
ALTER TABLE crm.social_onboarding_config ADD COLUMN voice jsonb NOT NULL DEFAULT '{}';
