-- Additive native-broadcast provenance; never rewrites contact identity or pipeline.
CREATE TABLE crm.native_template_campaigns (
    profile_id text NOT NULL,
    account_id text NOT NULL,
    broadcast_id varchar(24) NOT NULL,
    label text NOT NULL,
    template_name text NOT NULL,
    recipient_count integer NOT NULL CHECK(recipient_count BETWEEN 0 AND 10000),
    scan_skip integer NOT NULL DEFAULT 0 CHECK(scan_skip BETWEEN 0 AND 10000),
    complete boolean NOT NULL DEFAULT false,
    PRIMARY KEY(profile_id,account_id,broadcast_id)
);
CREATE TABLE crm.native_template_recipients (
    profile_id text NOT NULL,
    account_id text NOT NULL,
    broadcast_id varchar(24) NOT NULL,
    phone varchar(16) NOT NULL,
    sent_at timestamptz NOT NULL,
    PRIMARY KEY(profile_id,account_id,broadcast_id,phone),
    FOREIGN KEY(profile_id,account_id,broadcast_id)
        REFERENCES crm.native_template_campaigns(profile_id,account_id,broadcast_id)
);
CREATE INDEX native_template_recipient_phone ON crm.native_template_recipients(phone);
CREATE TABLE crm.template_lead_attribution (
    profile_id text NOT NULL,
    account_id text NOT NULL,
    broadcast_id varchar(24) NOT NULL,
    contact_id uuid NOT NULL REFERENCES crm.contacts(id) ON DELETE CASCADE,
    conversation_id varchar(512) NOT NULL,
    participant_id varchar(512) NOT NULL,
    label text NOT NULL,
    template_name text NOT NULL,
    sent_at timestamptz NOT NULL,
    reply_at timestamptz,
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','matched')),
    next_attempt timestamptz NOT NULL DEFAULT now(),
    last_error varchar(80),
    CHECK((state='matched') = (reply_at IS NOT NULL)),
    CHECK(reply_at IS NULL OR reply_at > sent_at),
    PRIMARY KEY(profile_id,account_id,broadcast_id,contact_id,conversation_id)
);
CREATE INDEX template_lead_matched ON crm.template_lead_attribution(contact_id)
    WHERE state='matched';
CREATE INDEX template_lead_due ON crm.template_lead_attribution(next_attempt)
    WHERE state='pending';
REVOKE ALL ON crm.native_template_campaigns,crm.native_template_recipients,
    crm.template_lead_attribution FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.native_template_campaigns,crm.native_template_recipients,
    crm.template_lead_attribution TO jardines_crm_app;
