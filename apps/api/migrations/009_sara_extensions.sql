-- Existing administrator tools retain their canonical override semantics.
-- Sara definitions are additive aliases and can never change canonical permissions.
ALTER TABLE crm.control_items ADD COLUMN origin text NOT NULL DEFAULT 'human'
    CHECK (origin IN ('human','sara'));
ALTER TABLE crm.control_items ADD CONSTRAINT sara_extension_kind
    CHECK (origin != 'sara' OR kind IN ('skill','tool','plugin','script'));
DROP INDEX crm.control_tool_action;
CREATE UNIQUE INDEX control_tool_action ON crm.control_items ((definition->>'action'))
    WHERE kind='tool' AND origin='human';
CREATE INDEX control_sara_owner ON crm.control_items (actor_id,id) WHERE origin='sara';
