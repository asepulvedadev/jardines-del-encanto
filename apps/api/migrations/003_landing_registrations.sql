-- Additive public capture audit. Existing contacts, stages and administrator actors stay intact.
CREATE TABLE crm.landing_registrations (
    contact_id uuid PRIMARY KEY REFERENCES crm.contacts(id),
    code varchar(16) NOT NULL UNIQUE CHECK (code ~ '^JDE-[A-F0-9]{12}$'),
    consent_version text NOT NULL CHECK (consent_version = 'landing-contact-v1'),
    consent_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.landing_limits (
    key text PRIMARY KEY,
    attempts integer NOT NULL DEFAULT 1,
    window_start timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON crm.landing_registrations, crm.landing_limits FROM PUBLIC;
GRANT SELECT, INSERT ON crm.landing_registrations TO jardines_crm_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON crm.landing_limits TO jardines_crm_app;
