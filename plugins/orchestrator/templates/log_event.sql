-- The app event table (MODEL.md section 12.5), PostgreSQL. The app writes warnings, errors
-- and lifecycle events here, plus a heartbeat row every few minutes, so the agent can read
-- what happened after active development ends, with the read-only role alone.
--
-- Everything written here must already be free of secrets and personal data: the agent
-- reads it. Apply it as the project's next migration, under the migration role.

CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.log_event (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at       timestamptz NOT NULL DEFAULT now(),
    level    text        NOT NULL CHECK (level IN ('debug', 'info', 'warn', 'error')),
    source   text        NOT NULL,  -- the process or component: 'web', 'worker', ...
    event    text        NOT NULL,  -- a stable name: 'startup', 'shutdown', 'heartbeat', 'job_failed', ...
    message  text        NOT NULL DEFAULT '',
    context  jsonb       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS log_event_at_idx ON ops.log_event (at);
CREATE INDEX IF NOT EXISTS log_event_event_at_idx ON ops.log_event (event, at);

-- Retention: run on a schedule (a cron job, or the app at startup and daily). The WHERE
-- keeps it a bounded delete. 30 days by default.
CREATE OR REPLACE FUNCTION ops.prune_log_event(keep interval DEFAULT interval '30 days')
RETURNS bigint
LANGUAGE sql
AS $$
    WITH gone AS (
        DELETE FROM ops.log_event WHERE at < now() - keep RETURNING 1
    )
    SELECT count(*) FROM gone;
$$;

-- The latest heartbeat per source. When it is old, the app is down: the human checks the
-- hosting platform.
CREATE OR REPLACE VIEW ops.heartbeat AS
SELECT source, max(at) AS last_seen, now() - max(at) AS age
FROM ops.log_event
WHERE event = 'heartbeat'
GROUP BY source;

-- The read-only role (MODEL.md section 12.3, rule 4) gets the schema like this. Replace
-- <readonly_role> with the project's role, or move these lines to the migration that
-- creates the role.
-- GRANT USAGE ON SCHEMA ops TO <readonly_role>;
-- GRANT SELECT ON ops.log_event, ops.heartbeat TO <readonly_role>;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA ops GRANT SELECT ON TABLES TO <readonly_role>;
