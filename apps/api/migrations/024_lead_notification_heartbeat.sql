-- Shared liveness survives operator status reads in a separate process.
ALTER TABLE crm.lead_notice_config ADD COLUMN worker_last_tick timestamptz;
