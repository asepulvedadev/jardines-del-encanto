-- Additive integration foundation: no customer schema changes or provider credentials.
CREATE TABLE crm.social_state (
    profile_id varchar(24) PRIMARY KEY,
    last_sync timestamptz,
    sync_warning varchar(160)
);
CREATE TABLE crm.social_connections (
    profile_id varchar(24) NOT NULL,
    account_id varchar(160) NOT NULL,
    platform text NOT NULL CHECK (platform IN ('facebook','instagram','tiktok','whatsapp','telegram')),
    username varchar(160) NOT NULL DEFAULT '',
    display_name varchar(160) NOT NULL DEFAULT '',
    status text NOT NULL CHECK (status IN ('connected','disconnected')),
    connected_at timestamptz,
    observed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(profile_id, account_id)
);
CREATE INDEX social_connections_profile_platform ON crm.social_connections(profile_id, platform);
CREATE TABLE crm.social_connection_intents (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    session_hash text NOT NULL,
    profile_id varchar(24) NOT NULL,
    platform text NOT NULL CHECK (platform IN ('facebook','instagram','tiktok','whatsapp','telegram')),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','completed')),
    before_ids jsonb NOT NULL,
    code varchar(160),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX social_intents_owner ON crm.social_connection_intents(actor_id, session_hash);
CREATE TABLE crm.social_webhook_events (
    event_id varchar(200) PRIMARY KEY,
    event varchar(120) NOT NULL,
    profile_id varchar(24),
    platform text CHECK (platform IN ('facebook','instagram','tiktok','whatsapp','telegram')),
    body jsonb NOT NULL,
    body_hash char(64) NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'received' CHECK (status = 'received')
);
CREATE INDEX social_events_profile_received ON crm.social_webhook_events(profile_id, received_at DESC);
REVOKE ALL ON crm.social_state, crm.social_connections, crm.social_connection_intents,
    crm.social_webhook_events FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON crm.social_state, crm.social_connections,
    crm.social_connection_intents TO jardines_crm_app;
GRANT SELECT, INSERT ON crm.social_webhook_events TO jardines_crm_app;
