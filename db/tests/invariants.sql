-- db/tests/invariants.sql
--
-- Things that must be true of the generated data at ANY size, with or without the
-- live generator running. Every check must return 0 rows.
--
--     psql antifraud -v ON_ERROR_STOP=1 -f db/tests/invariants.sql
--
-- On success it prints a PASS line per check and exits 0. On the first failure it
-- raises, which with ON_ERROR_STOP=1 makes psql exit non-zero - so this file works
-- unchanged as a CI step.
--
-- These queries may join to fraud_labels. That is the one legitimate use of it: to
-- separate "planted on purpose" from "broken by accident". Nothing in rules/ ever may.

SET TIME ZONE 'UTC';

BEGIN;

CREATE FUNCTION pg_temp.must_be_zero(label text, query text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    found bigint;
BEGIN
    EXECUTE query INTO found;
    IF found = 0 THEN
        RAISE NOTICE 'PASS  %', label;
    ELSE
        RAISE EXCEPTION 'FAIL  %: % row(s)', label, found;
    END IF;
END $$;


-- ---------------------------------------------------------------- causality

SELECT pg_temp.must_be_zero('no session before its player registered', $q$
    SELECT count(*) FROM sessions s
    JOIN players p ON p.id = s.player_id
    WHERE s.started_at < p.registered_at
$q$);

SELECT pg_temp.must_be_zero('no transaction before its player registered', $q$
    SELECT count(*) FROM transactions t
    JOIN players p ON p.id = t.player_id
    WHERE t.created_at < p.registered_at
$q$);

SELECT pg_temp.must_be_zero('no bet before its player registered', $q$
    SELECT count(*) FROM bets b
    JOIN players p ON p.id = b.player_id
    WHERE b.placed_at < p.registered_at
$q$);

SELECT pg_temp.must_be_zero('nothing settled before it was placed', $q$
    SELECT count(*) FROM settlements s
    JOIN bets b ON b.id = s.bet_id
    WHERE s.settled_at < b.placed_at
$q$);


-- ------------------------------------------------------------------- money

SELECT pg_temp.must_be_zero('no player ends with a negative balance', $q$
    SELECT count(*) FROM (
        SELECT p.id,
               coalesce((SELECT sum(t.amount) FROM transactions t
                         WHERE t.player_id = p.id AND t.direction = 'deposit'
                           AND t.status = 'approved'), 0)
             - coalesce((SELECT sum(w.amount) FROM transactions w
                         WHERE w.player_id = p.id AND w.direction = 'withdrawal'
                           AND w.status <> 'rejected'), 0)
             - coalesce((SELECT sum(b.stake) FROM bets b
                         WHERE b.player_id = p.id), 0)
             + coalesce((SELECT sum(st.payout) FROM settlements st
                         JOIN bets b2 ON b2.id = st.bet_id
                         WHERE b2.player_id = p.id), 0) AS balance
        FROM players p
    ) x WHERE balance < 0
$q$);

-- The stronger version: the balance must never go negative at ANY moment, not only
-- at the end. Every money movement becomes one row, then a running total per player.
-- ORDER BY at, delta DESC settles ties by counting credits before debits.
SELECT pg_temp.must_be_zero('balance never goes negative at any moment', $q$
    WITH money AS (
        SELECT player_id, processed_at AS at, amount AS delta
        FROM transactions
        WHERE direction = 'deposit' AND status = 'approved'
      UNION ALL
        SELECT player_id, placed_at, -stake
        FROM bets
      UNION ALL
        SELECT player_id, created_at, -amount     -- reserved when requested,
        FROM transactions                         -- not when the payout is approved
        WHERE direction = 'withdrawal' AND status <> 'rejected'
      UNION ALL
        SELECT b.player_id, s.settled_at, s.payout
        FROM settlements s
        JOIN bets b ON b.id = s.bet_id
        WHERE s.payout > 0
    )
    SELECT count(*) FROM (
        SELECT sum(delta) OVER (PARTITION BY player_id
                                ORDER BY at, delta DESC
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running
        FROM money
    ) x WHERE running < 0
$q$);

SELECT pg_temp.must_be_zero('pending means not processed, and nothing else does', $q$
    SELECT count(*) FROM transactions
    WHERE (status = 'pending') <> (processed_at IS NULL)
$q$);


-- ------------------------------------------------------------------- betting

-- If this breaks, the settlement-mismatch rule starts flagging honest bets.
-- exp(sum(ln(x))) is how you multiply rows together in SQL; safe here because odds
-- are always > 1, so ln never sees zero or a negative.
SELECT pg_temp.must_be_zero('total_odds equals the product of the legs', $q$
    SELECT count(*) FROM (
        SELECT b.id, b.total_odds,
               round(exp(sum(ln(bs.odds_at_placement))), 3) AS legs_product
        FROM bets b
        JOIN bet_selections bs ON bs.bet_id = b.id
        GROUP BY b.id, b.total_odds
    ) x WHERE abs(total_odds - legs_product) > 0.001
$q$);

SELECT pg_temp.must_be_zero('every late bet was planted on purpose', $q$
    SELECT count(*) FROM (
        SELECT DISTINCT b.id
        FROM bets b
        JOIN bet_selections bs ON bs.bet_id = b.id
        JOIN selections s      ON s.id = bs.selection_id
        JOIN markets m         ON m.id = s.market_id
        JOIN events e          ON e.id = m.event_id
        WHERE b.placed_at >= e.start_time
    ) late
    WHERE NOT EXISTS (
        SELECT 1 FROM fraud_labels f
        WHERE f.entity_type = 'bet' AND f.pattern_code = 'LATE_BET'
          AND f.entity_id = late.id
    )
$q$);


-- ---------------------------------------------------------------- settlement

SELECT pg_temp.must_be_zero('every wrong payout on a won bet was planted', $q$
    SELECT count(*)
    FROM bets b
    JOIN settlements s ON s.bet_id = b.id
    WHERE s.result = 'won'
      AND abs(s.payout - b.stake * b.total_odds) > 0.01
      AND NOT EXISTS (
          SELECT 1 FROM fraud_labels f
          WHERE f.entity_type = 'settlement' AND f.entity_id = s.id
      )
$q$);

SELECT pg_temp.must_be_zero('every losing bet that was paid was planted', $q$
    SELECT count(*) FROM settlements s
    WHERE s.result = 'lost' AND s.payout <> 0
      AND NOT EXISTS (
          SELECT 1 FROM fraud_labels f
          WHERE f.entity_type = 'settlement' AND f.entity_id = s.id
      )
$q$);

SELECT pg_temp.must_be_zero('no bet is settled twice', $q$
    SELECT count(*) FROM (
        SELECT bet_id FROM settlements GROUP BY bet_id HAVING count(*) > 1
    ) d
$q$);

ROLLBACK;
