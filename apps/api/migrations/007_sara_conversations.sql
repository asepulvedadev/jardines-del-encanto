-- Persistent owner-scoped Sara workspace; existing Hermes callers retain empty history.
ALTER TABLE crm.hermes_runs ADD COLUMN history jsonb NOT NULL DEFAULT '[]';
CREATE TABLE crm.sara_conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    title varchar(120) NOT NULL CHECK (length(trim(title)) > 0),
    active_message_id uuid,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(id, owner_id)
);
CREATE INDEX sara_conversations_owner_page ON crm.sara_conversations(owner_id,updated_at DESC,id DESC);
CREATE TABLE crm.sara_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL,
    owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    request_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('user','assistant')),
    content text NOT NULL CHECK (length(content) <= 16000 AND (role!='user' OR length(content)<=4000)),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','completed','failed')),
    run_id uuid REFERENCES crm.hermes_runs(id) ON DELETE SET NULL,
    results jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(conversation_id,owner_id) REFERENCES crm.sara_conversations(id,owner_id) ON DELETE CASCADE,
    UNIQUE(owner_id,request_id,role),
    UNIQUE(id,owner_id)
);
CREATE INDEX sara_messages_conversation_page ON crm.sara_messages(conversation_id,created_at DESC,id DESC);
CREATE TABLE crm.sara_attachments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
    filename varchar(120) NOT NULL,
    mime_type varchar(80) NOT NULL,
    size integer NOT NULL CHECK (size BETWEEN 1 AND 524288 AND size=octet_length(data)),
    kind text NOT NULL CHECK (kind IN ('document','audio')),
    data bytea NOT NULL,
    text text NOT NULL CHECK (length(text) BETWEEN 1 AND 16000),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(id,owner_id)
);
CREATE INDEX sara_attachments_owner ON crm.sara_attachments(owner_id);
CREATE TABLE crm.sara_message_attachments (
    message_id uuid NOT NULL,
    attachment_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    position integer NOT NULL CHECK (position BETWEEN 0 AND 3),
    FOREIGN KEY(message_id,owner_id) REFERENCES crm.sara_messages(id,owner_id) ON DELETE CASCADE,
    FOREIGN KEY(attachment_id,owner_id) REFERENCES crm.sara_attachments(id,owner_id) ON DELETE CASCADE,
    PRIMARY KEY(message_id,attachment_id),
    UNIQUE(message_id,position)
);
CREATE INDEX sara_message_attachment_reverse ON crm.sara_message_attachments(attachment_id);
REVOKE ALL ON crm.sara_conversations,crm.sara_messages,crm.sara_attachments,crm.sara_message_attachments FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.sara_conversations,crm.sara_messages TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.sara_attachments,crm.sara_message_attachments TO jardines_crm_app;
