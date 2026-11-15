-- Confirm the live participant identity alongside the immutable outgoing payload.
ALTER TABLE crm.inbox_actions ADD COLUMN context jsonb NOT NULL DEFAULT '{}'
 CHECK(jsonb_typeof(context)='object');
