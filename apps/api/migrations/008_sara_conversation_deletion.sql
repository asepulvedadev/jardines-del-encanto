-- Only owner-checked routes may delete chats and their unshared private files.
-- Child messages/links cascade; immutable broker/audit history is retained.
GRANT DELETE ON crm.sara_conversations,crm.sara_attachments TO jardines_crm_app;
