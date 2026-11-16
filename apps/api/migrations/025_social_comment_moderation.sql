-- Owner-installed scope is read-only to the application and to Sara.
CREATE TABLE crm.comment_moderation_config (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 owner_id uuid NOT NULL REFERENCES crm.users(id),
 profile_id text NOT NULL, credential_revision char(64) NOT NULL,
 ads_revision char(64) NOT NULL, enabled boolean NOT NULL DEFAULT false,
 version integer NOT NULL DEFAULT 1, since_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE crm.comment_moderation_sources (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 account_id text NOT NULL, platform text NOT NULL CHECK(platform IN ('facebook','tiktok')),
 post_id text NOT NULL, ad_id text, content_hash char(64) NOT NULL,
 cursor text, next_scan_at timestamptz NOT NULL DEFAULT now(),
 last_scan_at timestamptz, last_error text,
 UNIQUE(account_id,post_id), CHECK((platform='facebook')=(ad_id IS NOT NULL))
);
CREATE INDEX comment_moderation_due ON crm.comment_moderation_sources(next_scan_at);
CREATE TABLE crm.comment_moderation_observations (
 source_id uuid NOT NULL REFERENCES crm.comment_moderation_sources(id),
 comment_id text NOT NULL, page_cursor text, content jsonb NOT NULL, content_hash char(64) NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','review','skipped','processed')),
 category text, confidence numeric, attempts integer NOT NULL DEFAULT 0,
 next_attempt timestamptz NOT NULL DEFAULT now(), error text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_id,comment_id)
);
CREATE INDEX comment_moderation_pending ON crm.comment_moderation_observations(next_attempt) WHERE state='pending';
CREATE TABLE crm.comment_moderation_actions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 source_id uuid NOT NULL, comment_id text NOT NULL,
 action text NOT NULL CHECK(action IN ('reply','private_reply','hide')),
 config_version integer NOT NULL, profile_version integer NOT NULL,
 content_hash char(64) NOT NULL,
 state text NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved','accepted','unknown','blocked')),
 receipt jsonb NOT NULL DEFAULT '{}', error text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(source_id,comment_id,action),
 FOREIGN KEY(source_id,comment_id) REFERENCES crm.comment_moderation_observations(source_id,comment_id)
);
CREATE TABLE crm.comment_moderation_runtime (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 next_model_at timestamptz NOT NULL DEFAULT now(), heartbeat_at timestamptz, last_error text
);
INSERT INTO crm.comment_moderation_runtime(singleton) VALUES(true);
REVOKE ALL ON crm.comment_moderation_config,crm.comment_moderation_sources,
 crm.comment_moderation_observations,crm.comment_moderation_actions,crm.comment_moderation_runtime FROM PUBLIC;
GRANT SELECT ON crm.comment_moderation_config,crm.comment_moderation_sources TO jardines_crm_app;
GRANT UPDATE(cursor,next_scan_at,last_scan_at,last_error) ON crm.comment_moderation_sources TO jardines_crm_app;
GRANT SELECT,INSERT ON crm.comment_moderation_observations,crm.comment_moderation_actions TO jardines_crm_app;
GRANT UPDATE(state,category,confidence,attempts,next_attempt,error,updated_at) ON crm.comment_moderation_observations TO jardines_crm_app;
GRANT UPDATE(state,receipt,error,updated_at) ON crm.comment_moderation_actions TO jardines_crm_app;
GRANT SELECT,UPDATE ON crm.comment_moderation_runtime TO jardines_crm_app;
-- Only this fixed, argument-free read can take owner/policy row locks. The runtime
-- receives no UPDATE privilege on either authorization table.
CREATE FUNCTION crm.lock_comment_moderation_owner() RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM crm.comment_moderation_config c
 JOIN crm.users u ON u.id=c.owner_id WHERE c.singleton AND c.enabled
 AND u.enabled AND u.role='admin' FOR SHARE OF c,u)
$$;
REVOKE ALL ON FUNCTION crm.lock_comment_moderation_owner() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION crm.lock_comment_moderation_owner() TO jardines_crm_app;
