-- Explicitly enabled internal notifications; no historical contact backfill.
CREATE TABLE crm.lead_notice_config (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 epoch uuid NOT NULL DEFAULT gen_random_uuid(), enabled boolean NOT NULL DEFAULT false,
 owner_id uuid NOT NULL REFERENCES crm.users(id) ON DELETE CASCADE,
 profile_id text NOT NULL, account_id text NOT NULL, credential_revision char(64) NOT NULL,
 document_revision char(64) NOT NULL, recipients jsonb NOT NULL,
 activated_at timestamptz NOT NULL, next_hour timestamptz NOT NULL,
 next_daily timestamptz NOT NULL,
 CHECK(jsonb_array_length(recipients)=2)
);
CREATE TABLE crm.lead_notice_events (
 id text PRIMARY KEY, epoch uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('lead','hourly','daily')),
 contact_id uuid REFERENCES crm.contacts(id) ON DELETE CASCADE,
 cutoff timestamptz NOT NULL, payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.lead_notice_deliveries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 event_id text NOT NULL REFERENCES crm.lead_notice_events(id) ON DELETE CASCADE,
 recipient_phone text NOT NULL, conversation_id text,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','reserved','accepted','unknown','cancelled')),
 next_attempt timestamptz NOT NULL DEFAULT now(), error text,
 receipt jsonb NOT NULL DEFAULT '{}', reserved_at timestamptz, finished_at timestamptz,
 UNIQUE(event_id,recipient_phone)
);
CREATE INDEX lead_notice_due ON crm.lead_notice_deliveries(next_attempt) WHERE state='pending';
CREATE TABLE crm.lead_notice_templates (
 name text PRIMARY KEY, status text NOT NULL, provider_id text,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION crm.queue_new_lead_notice() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cfg crm.lead_notice_config; event_key text;
BEGIN
 SELECT * INTO cfg FROM crm.lead_notice_config WHERE singleton AND enabled;
 IF NOT FOUND THEN RETURN NEW; END IF;
 event_key := 'lead:' || NEW.id::text;
 INSERT INTO crm.lead_notice_events(id,epoch,kind,contact_id,cutoff,payload)
 VALUES(event_key,cfg.epoch,'lead',NEW.id,NEW.created_at,
        jsonb_build_object('name',NEW.name,'phone',NEW.phone,'source',NEW.source));
 INSERT INTO crm.lead_notice_deliveries(event_id,recipient_phone,conversation_id)
 SELECT event_key,r->>'phone',r->>'conversation_id' FROM jsonb_array_elements(cfg.recipients) r;
 RETURN NEW;
END $$;
CREATE TRIGGER lead_notice_contact_insert AFTER INSERT ON crm.contacts
 FOR EACH ROW EXECUTE FUNCTION crm.queue_new_lead_notice();
REVOKE ALL ON crm.lead_notice_config,crm.lead_notice_events,crm.lead_notice_deliveries,crm.lead_notice_templates FROM PUBLIC;
REVOKE ALL ON FUNCTION crm.queue_new_lead_notice() FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON crm.lead_notice_config,crm.lead_notice_events,crm.lead_notice_deliveries,crm.lead_notice_templates TO jardines_crm_app;
GRANT EXECUTE ON FUNCTION crm.queue_new_lead_notice() TO jardines_crm_app;
