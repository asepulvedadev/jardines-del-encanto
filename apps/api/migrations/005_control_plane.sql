-- Application extensions contain typed actions, never executable host code.
CREATE TABLE crm.control_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('skill','tool','plugin','script','connection')),
    name varchar(120) NOT NULL,
    description varchar(1000) NOT NULL DEFAULT '',
    definition jsonb NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- One optional override per canonical tool; ambiguous duplicate toggles are forbidden.
CREATE UNIQUE INDEX control_tool_action ON crm.control_items ((definition->>'action'))
    WHERE kind='tool';
CREATE TABLE crm.control_connections (
    key text PRIMARY KEY CHECK (key IN ('hermes','zernio','facebook','instagram','tiktok','whatsapp','telegram')),
    enabled boolean NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0)
);
INSERT INTO crm.control_connections(key,enabled) VALUES
 ('hermes',false),('zernio',true),('facebook',true),('instagram',true),
 ('tiktok',true),('whatsapp',true),('telegram',true);
CREATE TABLE crm.hermes_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    session_hash text NOT NULL REFERENCES crm.sessions(token_hash) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    prompt varchar(8000) NOT NULL,
    state text NOT NULL DEFAULT 'issued' CHECK (state IN ('issued','claimed','finished','failed')),
    calls integer NOT NULL DEFAULT 0 CHECK (calls BETWEEN 0 AND 12),
    reply varchar(16000),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '120 seconds'
);
CREATE TABLE crm.hermes_proposals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    session_hash text NOT NULL REFERENCES crm.sessions(token_hash) ON DELETE CASCADE,
    run_id uuid REFERENCES crm.hermes_runs(id) ON DELETE CASCADE,
    action text NOT NULL,
    arguments jsonb NOT NULL,
    revisions jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','expired')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '10 minutes'
);
CREATE TABLE crm.hermes_calls (
    run_id uuid NOT NULL REFERENCES crm.hermes_runs(id) ON DELETE CASCADE,
    call_id varchar(80) NOT NULL,
    request jsonb NOT NULL,
    response jsonb NOT NULL,
    PRIMARY KEY (run_id,call_id)
);
CREATE TABLE crm.control_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    action text NOT NULL,
    arguments jsonb NOT NULL,
    proposal_id uuid REFERENCES crm.hermes_proposals(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON crm.control_items,crm.control_connections,crm.hermes_runs,
 crm.hermes_proposals,crm.hermes_calls,crm.control_audit FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON crm.control_items,crm.hermes_runs,crm.hermes_proposals TO jardines_crm_app;
GRANT SELECT, UPDATE ON crm.control_connections TO jardines_crm_app;
GRANT SELECT, INSERT ON crm.hermes_calls,crm.control_audit TO jardines_crm_app;
