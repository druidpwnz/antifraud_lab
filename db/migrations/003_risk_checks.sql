-- 003_risk_checks.sql
-- Decisions made by POST /v1/risk-checks: "should this deposit or withdrawal go
-- through?" The API writes here and nowhere else, so it can never disturb the
-- generator's tables.

SET TIME ZONE 'UTC';

CREATE TABLE risk_checks (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Idempotency. The client sends a key; a retry with the same key returns the
    -- stored decision instead of scoring again. UNIQUE is what makes that safe when
    -- two identical requests arrive at the same moment: only one INSERT can win.
    idempotency_key    text NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 1 AND 255),
    -- SHA-256 of the request body. Same key with a different body is a client bug,
    -- and is refused rather than silently answered with someone else's decision.
    request_hash       text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),

    player_id          bigint NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    direction          text NOT NULL CHECK (direction IN ('deposit', 'withdrawal')),
    amount             numeric(14,2) NOT NULL CHECK (amount > 0),
    currency           text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),

    decision           text NOT NULL CHECK (decision IN ('approve', 'review', 'decline')),
    score              int  NOT NULL CHECK (score BETWEEN 0 AND 100),
    reasons            jsonb NOT NULL DEFAULT '[]'::jsonb,

    sim_time_at_check  timestamptz NOT NULL,                -- the simulated clock
    created_at         timestamptz NOT NULL DEFAULT now()   -- the real one
);

CREATE INDEX risk_checks_player_idx ON risk_checks (player_id);

COMMENT ON TABLE risk_checks IS
    'Pre-transaction risk decisions made by the API. Written only by POST /v1/risk-checks; '
    'the generator never reads or writes it.';

COMMENT ON COLUMN risk_checks.sim_time_at_check IS
    'Simulated time the check was scored against (sim_state.sim_time). created_at is '
    'real wall-clock time - the two clocks are deliberately separate.';
