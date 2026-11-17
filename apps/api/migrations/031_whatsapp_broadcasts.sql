-- Additive campaign provenance. Existing sources, identities and stages remain unchanged.
CREATE TABLE crm.whatsapp_broadcasts (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES crm.users(id),
    fingerprint text NOT NULL,
    name varchar(120) NOT NULL,
    account_id varchar(160) NOT NULL,
    credential_revision text NOT NULL,
    template_name varchar(512) NOT NULL,
    template_language varchar(20) NOT NULL,
    template_revision text NOT NULL,
    template_payload jsonb NOT NULL,
    preview text NOT NULL,
    consent_note varchar(500) NOT NULL,
    state text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','preparing','sending','submitted','completed','failed','cancelled','unknown')),
    provider_id varchar(80),
    provider_status varchar(30),
    last_error varchar(80),
    stats jsonb NOT NULL DEFAULT '{}',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    attempted_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.whatsapp_broadcast_recipients (
    campaign_id uuid NOT NULL REFERENCES crm.whatsapp_broadcasts(id),
    contact_id uuid NOT NULL REFERENCES crm.contacts(id),
    phone varchar(16) NOT NULL,
    name varchar(120) NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    PRIMARY KEY (campaign_id, contact_id),
    UNIQUE (campaign_id, phone)
);
CREATE INDEX whatsapp_broadcast_contact ON crm.whatsapp_broadcast_recipients(contact_id, campaign_id);
CREATE TABLE crm.whatsapp_cold_leads (
    contact_id uuid PRIMARY KEY REFERENCES crm.contacts(id),
    campaign_id uuid NOT NULL REFERENCES crm.whatsapp_broadcasts(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON crm.whatsapp_broadcasts, crm.whatsapp_broadcast_recipients TO jardines_crm_app;
GRANT SELECT, INSERT ON crm.whatsapp_cold_leads TO jardines_crm_app;
