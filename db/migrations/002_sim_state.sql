-- 002_sim_state.sql
-- Where the backfill stopped, so the live generator knows where to carry on.

SET TIME ZONE 'UTC';

CREATE TABLE sim_state (
    -- singleton: the CHECK is what makes "only ever one row" a rule the database
    -- enforces, instead of a convention you have to remember
    id           int PRIMARY KEY CHECK (id = 1),

    sim_time     timestamptz NOT NULL,                  -- the simulated clock
    seed         bigint NOT NULL,                       -- which run produced this data
    days         int NOT NULL CHECK (days > 0),
    generated_at timestamptz NOT NULL DEFAULT now(),    -- wall clock: when backfill ran
    updated_at   timestamptz NOT NULL DEFAULT now()     -- wall clock: last write

    -- No floor CHECK on sim_time on purpose: the twelve '>= 2025-01-01' floors in
    -- 001 are still an open question, so this file does not add a thirteenth.
);

COMMENT ON TABLE sim_state IS
    'One row only. The simulated clock plus the settings that produced this database. '
    'backfill.py INSERTs it once at the end of a run; the live generator UPSERTs '
    'sim_time and updated_at on every tick.';

COMMENT ON COLUMN sim_state.sim_time IS
    'Simulated time. generated_at and updated_at are real wall-clock time - the two '
    'clocks are deliberately separate.';
