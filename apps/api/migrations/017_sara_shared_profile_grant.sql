-- A trusted developer training action may advance only its own in-flight reply
-- snapshot; the application enforces the source-bound grant and revokes other jobs.
GRANT UPDATE(shared_profile_version) ON crm.whatsapp_agent_jobs TO jardines_crm_app;
