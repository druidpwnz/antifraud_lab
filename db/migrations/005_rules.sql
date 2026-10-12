-- 005_rules.sql
-- Phase 9: what the rules runner needs.
--
-- (Grafana's read-only login is not here: a role belongs to the whole Postgres
-- server, and the owner of this database may not be allowed to create one. See
-- set_up_grafana_reader() in db/migrate.py.)

SET TIME ZONE 'UTC';

-- How far each detection rule has looked. Every run reads only rows with an id
-- above last_id in the rule's own source table (settlements for
-- SETTLEMENT_MISMATCH, bets for LATE_BET and STAKE_ANOMALY), then moves last_id
-- up - in the same transaction as the alerts it wrote, so a crash cannot lose
-- rows or alert twice.
--
-- Ids, not timestamps: ids only ever grow, but timestamps do not arrive in order -
-- the generator writes 5-10 minutes behind its own clock, and a settlement is
-- dated back to the end of its match.
CREATE TABLE rule_state (
    rule_code   text PRIMARY KEY CHECK (rule_code ~ '^[A-Z0-9_]+$'),
    last_id     bigint NOT NULL DEFAULT 0 CHECK (last_id >= 0),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE rule_state IS
    'Per detection rule: the highest source-table id already checked. Written only by the rules runner.';
