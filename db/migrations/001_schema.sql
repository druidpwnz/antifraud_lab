

CREATE TABLE players (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    registered_at timestamptz NOT NULL DEFAULT now() CHECK (registered_at >= '2025-01-01'),  
    country text NOT NULL CHECK (country ~ '^[A-Z]{2}$'),  --check with regular ex
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),  --check with regular ex
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed','self_excluded'))
);


CREATE TABLE sessions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE RESTRICT,  --don't want to delete this after deleting player
    started_at timestamptz NOT NULL CHECK (started_at >= '2025-01-01'),
    ended_at timestamptz CHECK (ended_at > started_at),  --can nullable
    ip inet NOT NULL, -- inet type for ip
    device_id uuid NOT NULL,  --uuid type for device id
    user_agent varchar(512)  -- varchar because we need limit for limitless value
);

CREATE INDEX sessions_player_started_idx ON sessions (player_id, started_at DESC);
CREATE INDEX sessions_device_idx ON sessions (device_id);
CREATE INDEX sessions_ip_idx ON sessions (ip);


CREATE TABLE payment_methods (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE RESTRICT,  
    type text NOT NULL CHECK (type IN ('card', 'crypto', 'bank')), 
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),  --text for readability instead of bytea - sha256
    last4 text CHECK (last4 ~ '^[0-9]{4}$'),  --last 4 numbers of card
    added_at timestamptz NOT NULL DEFAULT now() CHECK (added_at >= '2025-01-01'),

    CHECK ((type = 'card') = (last4 IS NOT NULL)),  -- last4 present if and only if it's a card. Comparing two booleans with = is a neat way to express "both or neither"
    UNIQUE (player_id, fingerprint)  -- The UNIQUE (player_id, fingerprint) stops one player registering the same card twice
);

CREATE INDEX payment_methods_fingerprint_idx ON payment_methods (fingerprint);


CREATE TABLE transactions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE RESTRICT,  
    method_id bigint NOT NULL REFERENCES payment_methods(id) ON DELETE RESTRICT,  
    direction text NOT NULL CHECK (direction in ('deposit', 'withdrawal')),  
    amount numeric(14,2) NOT NULL CHECK (amount > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    status text NOT NULL CHECK (status in ('pending', 'approved', 'rejected', 'chargeback')), 
    created_at timestamptz NOT NULL DEFAULT now() CHECK (created_at >= '2025-01-01'),  
    processed_at timestamptz CHECK (processed_at >= created_at),  -- can be nullable

    CHECK ((status = 'pending') = (processed_at IS NULL))
);

CREATE INDEX transactions_player_created_idx ON transactions (player_id, created_at DESC);
CREATE INDEX transactions_created_idx ON transactions (created_at) WHERE status = 'approved';


CREATE TABLE events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sport text NOT NULL CHECK (sport IN ('football','tennis','basketball','hockey','esports')),    
    league text NOT NULL,
    home_team   text NOT NULL,
    away_team   text NOT NULL,
    start_time timestamptz CHECK (start_time >= '2025-01-01') NOT NULL,
    status text NOT NULL DEFAULT 'scheduled'
       CHECK (status IN ('scheduled','live','finished','cancelled','postponed')),
    finished_at timestamptz CHECK (finished_at > start_time),
    
    CHECK (home_team <> away_team),
    UNIQUE (league, home_team, away_team, start_time)
);

CREATE INDEX events_start_time_idx ON events (start_time);
CREATE INDEX events_status_start_idx ON events (status, start_time) WHERE status IN ('scheduled','live');


CREATE TABLE markets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,  -- don't need this after delete
    type text NOT NULL CHECK (type IN ('1x2','total_goals','both_teams_score','handicap','correct_score')),
    line numeric(5,2) NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','suspended','settled','void')),

    UNIQUE (event_id, type, line)
);

CREATE INDEX markets_event_idx ON markets (event_id);


CREATE TABLE selections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id bigint NOT NULL REFERENCES markets(id) ON DELETE CASCADE, 
    outcome text NOT NULL CHECK (
        outcome IN ('home','draw','away','over','under','yes','no')
        OR outcome ~ '^[0-9]{1,2}-[0-9]{1,2}$'),
    name text NOT NULL,
    current_odds numeric(6,2) NOT NULL CHECK (current_odds > 1.0),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','won','lost','void')),

    UNIQUE (market_id, outcome)
);


CREATE TABLE odds_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    selection_id bigint NOT NULL REFERENCES selections(id) ON DELETE CASCADE, 
    odds numeric(6, 2) NOT NULL CHECK (odds > 1.0),
    changed_at timestamptz NOT NULL DEFAULT now() CHECK (changed_at >= '2025-01-01'),

    UNIQUE (selection_id, changed_at)
);

CREATE INDEX odds_history_selection_changed_idx ON odds_history (selection_id, changed_at DESC);


CREATE TABLE bets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE RESTRICT,  
    placed_at timestamptz NOT NULL DEFAULT now() CHECK (placed_at >= '2025-01-01'),
    stake numeric(14,2) NOT NULL CHECK (stake > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    total_odds numeric(10,3) NOT NULL CHECK (total_odds > 1.0),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','won','lost','void','cashed_out'))
);

CREATE INDEX bets_player_placed_idx ON bets (player_id, placed_at DESC);


CREATE TABLE bet_selections (
    bet_id bigint NOT NULL REFERENCES bets(id) ON DELETE CASCADE,  
    selection_id bigint NOT NULL REFERENCES selections(id) ON DELETE RESTRICT, 
    odds_at_placement numeric(6,2) NOT NULL CHECK (odds_at_placement > 1.0),

    PRIMARY KEY (bet_id, selection_id)  --composite primary key because (bet_id, selection_id) is unique and never referenced by anything else
);

CREATE INDEX bet_selections_selection_idx ON bet_selections (selection_id);


CREATE TABLE settlements (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bet_id bigint NOT NULL REFERENCES bets(id) ON DELETE CASCADE,  
    result text NOT NULL CHECK (result IN ('won','lost','void','half_won','half_lost')),    
    payout numeric(14,2) NOT NULL CHECK (payout >= 0),
    settled_at timestamptz NOT NULL DEFAULT now() CHECK (settled_at >= '2025-01-01')
);

CREATE INDEX settlements_bet_idx ON settlements (bet_id);
CREATE INDEX settlements_settled_at_idx ON settlements (settled_at);


CREATE TABLE bonuses (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    type text NOT NULL CHECK (type IN ('welcome','reload','free_bet','cashback','loyalty')),    
    amount numeric(14,2) NOT NULL CHECK (amount > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    wagering_requirement numeric(14,2) NOT NULL CHECK (wagering_requirement >= 0),
    wagered_amount numeric(14,2) NOT NULL DEFAULT 0 CHECK (wagered_amount >= 0),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','expired','forfeited','cancelled')),
    granted_at timestamptz NOT NULL DEFAULT now() CHECK (granted_at >= '2025-01-01'),
    expires_at timestamptz CHECK (expires_at > granted_at),  --nullable
    completed_at timestamptz CHECK (completed_at >= granted_at)  --nullable
);

CREATE INDEX bonuses_player_granted_idx ON bonuses (player_id, granted_at DESC);
CREATE INDEX bonuses_active_idx ON bonuses (player_id) WHERE status = 'active';

--The two tables that make the project work

CREATE TABLE alerts(
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    rule_code text NOT NULL CHECK (rule_code ~ '^[A-Z0-9_]+$'),
    severity text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,  --jsonb format
    window_start timestamptz NOT NULL CHECK (window_start >= '2025-01-01'),
    window_end timestamptz NOT NULL CHECK (window_end >= window_start),
    created_at timestamptz NOT NULL DEFAULT now() CHECK (created_at >= '2025-01-01'),
    status text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'confirmed', 'false_positive')),
    reviewed_at timestamptz CHECK (reviewed_at >= created_at),

    UNIQUE (player_id, rule_code, window_start, window_end)
);

CREATE INDEX alerts_created_idx ON alerts (created_at DESC);
CREATE INDEX alerts_rule_status_idx ON alerts (rule_code, status);
CREATE INDEX alerts_open_idx ON alerts (player_id) WHERE status = 'new';


--Detection rules must never read this table.
CREATE TABLE fraud_labels(
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type  text NOT NULL CHECK (entity_type IN ('player','transaction','bet','settlement','session')),
    entity_id    bigint NOT NULL CHECK (entity_id > 0),
    pattern_code text NOT NULL CHECK (pattern_code ~ '^[A-Z0-9_]+$'),
    cluster_id uuid,  --Multi-accounting and matched betting involve several entities that belong to one planted incident.
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    injected_at timestamptz NOT NULL DEFAULT now() CHECK (injected_at >= '2025-01-01'),

    UNIQUE (entity_type, entity_id, pattern_code)
);

CREATE INDEX fraud_labels_pattern_idx ON fraud_labels (pattern_code);
CREATE INDEX fraud_labels_entity_idx ON fraud_labels (entity_type, entity_id);