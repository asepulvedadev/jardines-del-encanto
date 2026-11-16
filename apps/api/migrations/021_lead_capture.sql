-- Independent, additive intake ledger. Existing customers and stages are not rewritten.
CREATE TABLE crm.lead_capture_threads (
    profile_id varchar(160) NOT NULL,
    account_id varchar(160) NOT NULL,
    conversation_id varchar(512) NOT NULL,
    platform text NOT NULL CHECK (platform IN ('whatsapp','facebook')),
    participant_id varchar(512) NOT NULL,
    participant_name varchar(120),
    observed_marker char(64) NOT NULL,
    checked_marker char(64),
    scan_cursor varchar(4000),
    candidate_name varchar(120),
    candidate_phone varchar(16),
    form_phone boolean NOT NULL DEFAULT false,
    scope_match boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','registered','out_of_scope')),
    reason varchar(80),
    contact_id uuid REFERENCES crm.contacts(id),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(profile_id, account_id, conversation_id)
);
CREATE INDEX lead_capture_due ON crm.lead_capture_threads(next_attempt)
    WHERE checked_marker IS DISTINCT FROM observed_marker;
CREATE TABLE crm.lead_capture_scans (
    profile_id varchar(160) NOT NULL,
    account_id varchar(160) NOT NULL,
    scope varchar(40) NOT NULL,
    cursor varchar(4000),
    last_success timestamptz,
    last_error varchar(80),
    PRIMARY KEY(profile_id, account_id, scope)
);
REVOKE ALL ON crm.lead_capture_threads, crm.lead_capture_scans FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON crm.lead_capture_threads, crm.lead_capture_scans
    TO jardines_crm_app;
