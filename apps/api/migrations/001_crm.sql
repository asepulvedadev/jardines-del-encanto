-- Explicit migration only. Never run schema changes on application startup.
CREATE SCHEMA IF NOT EXISTS crm;
REVOKE ALL ON SCHEMA crm FROM PUBLIC;
CREATE TABLE crm.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username varchar(80) NOT NULL UNIQUE,
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'admin' CHECK (role = 'admin'),
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    csrf_token text NOT NULL,
    expires_at timestamptz NOT NULL,
    last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_expiry ON crm.sessions(expires_at);
CREATE TABLE crm.login_limits (
    key text PRIMARY KEY,
    attempts integer NOT NULL DEFAULT 1,
    window_start timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.contacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(120) NOT NULL CHECK (length(trim(name)) > 0),
    phone varchar(16) NOT NULL UNIQUE CHECK (phone ~ '^\+[1-9][0-9]{7,14}$'),
    source text NOT NULL CHECK (source IN ('in_person','social_campaign','web','referral','whatsapp','other')),
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.deals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id uuid NOT NULL UNIQUE REFERENCES crm.contacts(id),
    stage text NOT NULL DEFAULT 'new' CHECK (stage IN ('new','contacted','visit','negotiation','won','lost')),
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX deals_stage ON crm.deals(stage, created_at DESC);
CREATE TABLE crm.activities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id uuid NOT NULL REFERENCES crm.deals(id),
    actor_id uuid NOT NULL REFERENCES crm.users(id),
    kind text NOT NULL CHECK (kind IN ('created','stage_changed','contact_updated','note','task_created','task_completed','task_reopened')),
    body varchar(2000) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX activities_deal_date ON crm.activities(deal_id, created_at DESC);
CREATE TABLE crm.tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id uuid NOT NULL REFERENCES crm.contacts(id),
    title varchar(160) NOT NULL CHECK (length(trim(title)) > 0),
    due_date date NOT NULL,
    completed boolean NOT NULL DEFAULT false,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tasks_contact ON crm.tasks(contact_id);
CREATE INDEX tasks_pending_due ON crm.tasks(due_date) WHERE NOT completed;
GRANT USAGE ON SCHEMA crm TO jardines_crm_app;
GRANT SELECT ON crm.users TO jardines_crm_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON crm.sessions, crm.login_limits TO jardines_crm_app;
GRANT SELECT, INSERT, UPDATE ON crm.contacts, crm.deals, crm.tasks TO jardines_crm_app;
GRANT SELECT, INSERT ON crm.activities TO jardines_crm_app;
