-- db/tests/profile.sql
--
-- What the generated data LOOKS like. Nothing here passes or fails - these are
-- numbers to read, and to compare before and after a change to the generator.
--
--     psql antifraud -P pager=off -f db/tests/profile.sql > profile.txt
--
-- No expected values are written down, on purpose: with the live generator running
-- every count grows continuously, so any number committed here would be wrong within
-- the hour. The checks that must hold at any size live in invariants.sql.
--
-- The useful habit: save the output before changing the generator, save it again
-- after, and diff the two.

SET TIME ZONE 'UTC';

\echo === players, devices, households ===

SELECT count(*) AS players,
       count(*) FILTER (WHERE status = 'active') AS active,
       min(registered_at)::date AS first_registration,
       max(registered_at)::date AS last_registration
FROM players;

-- One device usually means one person. These are the exceptions, and they are all
-- honest households - which makes every one of them a false positive for the
-- linked-accounts rule.
SELECT players_on_device, count(*) AS devices
FROM (
    SELECT device_id, count(DISTINCT player_id) AS players_on_device
    FROM sessions
    GROUP BY device_id
) per_device
GROUP BY players_on_device
ORDER BY players_on_device;

SELECT device_id,
       count(DISTINCT player_id) AS players,
       array_agg(DISTINCT player_id ORDER BY player_id) AS player_ids
FROM sessions
GROUP BY device_id
HAVING count(DISTINCT player_id) >= 2
ORDER BY players DESC, device_id
LIMIT 10;


\echo === the daily curve (should peak in the evening, quiet at night) ===

SELECT EXTRACT(HOUR FROM registered_at)::int AS utc_hour,
       count(*) AS registrations
FROM players
GROUP BY utc_hour
ORDER BY utc_hour;


\echo === odds drift ===

SELECT count(DISTINCT selection_id) AS selections,
       count(*)                     AS odds_rows,
       round(count(*)::numeric / count(DISTINCT selection_id), 1) AS rows_per_selection
FROM odds_history;

-- Opening price vs latest price per selection.
-- The frame matters: the DEFAULT frame for a window with ORDER BY is
--   RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW,
-- so last_value() would return the current row, not the last one in the partition.
WITH price AS (
    SELECT selection_id,
           first_value(odds) OVER w AS opening_odds,
           last_value(odds)  OVER w AS latest_odds,
           row_number()      OVER w AS rn
    FROM odds_history
    WINDOW w AS (PARTITION BY selection_id
                 ORDER BY changed_at
                 ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
)
SELECT count(*)                                 AS selections,
       round(avg(latest_odds - opening_odds), 4) AS avg_drift,
       max(abs(latest_odds - opening_odds))      AS biggest_move
FROM price
WHERE rn = 1;

-- the bookmaker's margin built into the prices: sum(1/odds) per market should be
-- about 1.06, whatever the market type
SELECT m.type, round(avg(sum_prob), 3) AS avg_sum_of_implied_probabilities
FROM (
    SELECT market_id, sum(1 / current_odds) AS sum_prob
    FROM selections GROUP BY market_id
) x
JOIN markets m ON m.id = x.market_id
GROUP BY m.type
ORDER BY m.type;


\echo === money in and out ===

SELECT direction, status, count(*), sum(amount)
FROM transactions
GROUP BY direction, status
ORDER BY direction, status;

SELECT sum(amount) FILTER (WHERE direction = 'deposit'    AND status = 'approved')  AS deposited,
       sum(amount) FILTER (WHERE direction = 'withdrawal' AND status <> 'rejected') AS withdrawn,
       count(*)    FILTER (WHERE direction = 'withdrawal')::numeric
         / nullif(count(*) FILTER (WHERE direction = 'deposit'), 0)                 AS withdrawals_per_deposit
FROM transactions;

-- how long a deposit takes to clear, in seconds, and a withdrawal, in hours
SELECT min(EXTRACT(EPOCH FROM processed_at - created_at))::int      AS deposit_min_seconds,
       round(avg(EXTRACT(EPOCH FROM processed_at - created_at)), 1) AS deposit_avg_seconds,
       max(EXTRACT(EPOCH FROM processed_at - created_at))::int      AS deposit_max_seconds
FROM transactions
WHERE direction = 'deposit' AND processed_at IS NOT NULL;

SELECT round(min(EXTRACT(EPOCH FROM processed_at - created_at) / 3600), 1) AS wd_min_hours,
       round(avg(EXTRACT(EPOCH FROM processed_at - created_at) / 3600), 1) AS wd_avg_hours,
       round(max(EXTRACT(EPOCH FROM processed_at - created_at) / 3600), 1) AS wd_max_hours
FROM transactions
WHERE direction = 'withdrawal' AND processed_at IS NOT NULL;


\echo === betting ===

SELECT count(*)                  AS bets,
       round(avg(stake), 2)      AS avg_stake,
       round(avg(total_odds), 2) AS avg_odds,
       sum(stake)                AS turnover
FROM bets;

SELECT legs, count(*) AS bets
FROM (SELECT bet_id, count(*) AS legs FROM bet_selections GROUP BY bet_id) per_bet
GROUP BY legs
ORDER BY legs;

SELECT status, count(*) AS bets FROM bets GROUP BY status ORDER BY status;


\echo === settlement and the margin ===

SELECT count(*) FILTER (WHERE status = 'finished')  AS finished,
       count(*) FILTER (WHERE status = 'scheduled') AS still_scheduled,
       count(*)                                    AS events
FROM events;

SELECT result, count(*) AS settlements, sum(payout) AS paid
FROM settlements
GROUP BY result
ORDER BY result;

-- The margin, three ways. Read them together, never the first one alone.
--   realised       - what actually happened, fraud included
--   honest_only    - planted bets excluded: what the book would have earned
--   fraud_cost     - the gap, which is what the planted fraud cost the operator
--
-- The realised number is noisy on small datasets: at DAYS=3 it has read -0.187,
-- +0.079 and +0.130 with correct data every time, because a couple of winning combos
-- at long odds move it by several points. It only settles down in the hundreds of
-- thousands of settled bets.
SELECT round(1 - sum(s.payout) / sum(b.stake), 4) AS realised,
       round(1 - sum(s.payout) FILTER (WHERE NOT planted)
               / sum(b.stake)  FILTER (WHERE NOT planted), 4) AS honest_only,
       sum(s.payout) FILTER (WHERE planted) AS paid_on_planted_rows,
       count(*) AS settled_bets
FROM bets b
JOIN settlements s ON s.bet_id = b.id
CROSS JOIN LATERAL (
    SELECT EXISTS (
        SELECT 1 FROM fraud_labels f
        WHERE (f.entity_type = 'settlement' AND f.entity_id = s.id)
           OR (f.entity_type = 'bet'        AND f.entity_id = b.id)
    ) AS planted
) p;


\echo === planted fraud (ground truth - rules/ must never read this table) ===

-- How many rows land here is RATE x OPPORTUNITIES, so it grows with the dataset.
-- The three rates are NOT comparable with each other: STAKE_ESCALATION needs a
-- player with both a betting history and a balance worth emptying, which is only
-- ~6% of active player-hours, so its rate is much higher than the others'.
SELECT pattern_code,
       entity_type,
       details ->> 'variant' AS variant,
       count(*)              AS planted
FROM fraud_labels
GROUP BY pattern_code, entity_type, variant
ORDER BY pattern_code, variant;

-- as a share of what it could have hit - this is the number to sanity-check against
-- reality. Half a percent of settlements being wrong would be an incident.
SELECT round(100.0 * (SELECT count(*) FROM fraud_labels WHERE pattern_code = 'SETTLEMENT_ERROR')
                   / nullif((SELECT count(*) FROM settlements), 0), 3) AS pct_of_settlements,
       round(100.0 * (SELECT count(*) FROM fraud_labels WHERE pattern_code = 'LATE_BET')
                   / nullif((SELECT count(*) FROM bets), 0), 3)        AS pct_of_bets,
       round(100.0 * (SELECT count(DISTINCT b.player_id) FROM fraud_labels f
                      JOIN bets b ON b.id = f.entity_id
                      WHERE f.pattern_code = 'STAKE_ESCALATION')
                   / nullif((SELECT count(*) FROM players), 0), 3)     AS pct_of_players_taken_over;

-- What the obvious settlement rule can even see. A rule's WHERE clause decides what
-- it is blind to: looking only at won bets makes every lost_bet_paid invisible, at
-- any threshold.
SELECT f.details ->> 'variant' AS variant,
       count(*)                                  AS planted,
       count(*) FILTER (WHERE s.result = 'won')  AS visible_to_the_won_bet_rule,
       count(*) FILTER (WHERE s.result <> 'won') AS invisible,
       sum(s.payout - (f.details ->> 'correct_payout')::numeric) AS overpaid
FROM fraud_labels f
JOIN settlements s ON s.id = f.entity_id AND f.entity_type = 'settlement'
GROUP BY variant
ORDER BY variant;

-- STAKE_ESCALATION: the planted bets against the player's own history, and how many
-- ORDINARY bets are bigger than the smallest planted one. That second number is the
-- whole argument for a per-player window function over a fixed stake threshold.
SELECT count(*)                                                    AS planted,
       round(avg((details ->> 'multiple_of_average')::numeric), 1)  AS avg_multiple_of_own_average,
       min((details ->> 'stake')::numeric)                          AS smallest,
       max((details ->> 'stake')::numeric)                          AS biggest,
       (SELECT count(*) FROM bets b
        WHERE b.stake > (SELECT min((details ->> 'stake')::numeric)
                         FROM fraud_labels WHERE pattern_code = 'STAKE_ESCALATION')
          AND NOT EXISTS (SELECT 1 FROM fraud_labels f2
                          WHERE f2.entity_type = 'bet' AND f2.entity_id = b.id)
       ) AS honest_bets_that_are_bigger
FROM fraud_labels
WHERE pattern_code = 'STAKE_ESCALATION';

-- LATE_BET: how far after kickoff, and do they win more often than honest bets?
-- A real late bettor knows something the book does not, so a win rate well above the
-- honest one would be a second signal. Ours picks at random, so it is not there yet.
SELECT count(*)                                                     AS planted,
       round(avg((details ->> 'seconds_after_kickoff')::int) / 60.0) AS avg_minutes_late,
       count(*) FILTER (WHERE st.result = 'won')                     AS won,
       count(*) FILTER (WHERE st.bet_id IS NULL)                     AS not_settled_yet
FROM fraud_labels f
LEFT JOIN settlements st ON st.bet_id = f.entity_id
WHERE f.pattern_code = 'LATE_BET' AND f.entity_type = 'bet';


\echo === where the simulated clock is ===

SELECT sim_time, updated_at, now() - updated_at AS since_last_tick,
       sim_time - now() AS sim_clock_ahead_of_real_time
FROM sim_state;
