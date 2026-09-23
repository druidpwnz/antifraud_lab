-- db/tests/backfill_checks.sql
--
-- Sanity checks on generated data. Run after ./reset.sh + backfill.py:
--     psql antifraud -f db/tests/backfill_checks.sql
--
-- The "expect" numbers below are for SEED=42, DAYS=14, END=2026-09-01,
-- INJECT_FRAUD=True, SETTLEMENT_ERROR_RATE=0.0005. Change any of those and the
-- counts change. The checks that must read 0 hold at any size - those are the
-- ones that actually matter.


\echo === 1. causality: nothing happens before the player exists (both must be 0) ===

SELECT count(*) AS sessions_before_registration
FROM sessions s

JOIN players p ON p.id = s.player_id
WHERE s.started_at < p.registered_at;

SELECT count(*) AS deposits_before_registration
FROM transactions t
JOIN players p ON p.id = t.player_id
WHERE t.created_at < p.registered_at;


\echo === 2. shared devices: honest households (expect 1467 devices, 26 shared) ===

SELECT count(*) AS devices_total,
       count(*) FILTER (WHERE players_on_device >= 2) AS devices_shared
FROM (
    SELECT device_id, count(DISTINCT player_id) AS players_on_device
    FROM sessions
    GROUP BY device_id
) per_device;

-- how many players share a device, as a distribution rather than a row per device
SELECT players_on_device, count(*) AS devices
FROM (
    SELECT device_id, count(DISTINCT player_id) AS players_on_device
    FROM sessions
    GROUP BY device_id
) per_device
GROUP BY players_on_device
ORDER BY players_on_device;

-- a sample of the shared ones. This is the skeleton of the linked-accounts rule -
-- every row here is an honest household, so every one is a future false positive.
SELECT device_id,
       count(DISTINCT player_id) AS players,
       array_agg(DISTINCT player_id ORDER BY player_id) AS player_ids
FROM sessions
GROUP BY device_id
HAVING count(DISTINCT player_id) >= 2
ORDER BY players DESC, device_id
LIMIT 10;


\echo === 3. odds drift (expect 1316 selections, 10783 rows, max 19 changes) ===

SELECT count(DISTINCT selection_id) AS selections,
       count(*)                     AS odds_rows,
       max(changes)                 AS most_changes_on_one_selection
FROM (
    SELECT selection_id, count(*) OVER (PARTITION BY selection_id) AS changes
    FROM odds_history
) x;

-- Opening price vs latest price per selection.
-- The frame matters: the DEFAULT frame for a window with ORDER BY is
--   RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW,
-- so last_value() would return the current row, not the last one.
-- ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING fixes that.
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
SELECT count(*)                                AS selections,
       round(avg(latest_odds - opening_odds), 4) AS avg_drift,
       max(abs(latest_odds - opening_odds))      AS biggest_move
FROM price
WHERE rn = 1;          -- one row per selection


\echo === 4. deposit processing time (expect 4003 deposits, min 5s, avg 302.4s, max 600s) ===

SELECT count(*)                                                      AS deposits,
       min(EXTRACT(EPOCH FROM processed_at - created_at))::int        AS min_seconds,
       round(avg(EXTRACT(EPOCH FROM processed_at - created_at)), 1)   AS avg_seconds,
       max(EXTRACT(EPOCH FROM processed_at - created_at))::int        AS max_seconds
FROM transactions
WHERE direction = 'deposit'
  AND processed_at IS NOT NULL;


\echo === 5. bets (expect 15206 bets, avg stake 29.34, avg odds 8.40) ===

SELECT count(*)                  AS bets,
       round(avg(stake), 2)      AS avg_stake,
       round(avg(total_odds), 2) AS avg_odds,
       sum(stake)                AS turnover
FROM bets;

-- singles vs combos (expect 10672 / 1523 / 1570 / 1441)
SELECT legs, count(*) AS bets
FROM (
    SELECT bet_id, count(*) AS legs
    FROM bet_selections
    GROUP BY bet_id
) per_bet
GROUP BY legs
ORDER BY legs;

-- LATE BETTING: no bet may be placed after its match kicked off. Must be 0.
-- This is the future LATE_BET rule, run against honest data.
SELECT count(*) AS late_bets
FROM bets b
JOIN bet_selections bs ON bs.bet_id = b.id
JOIN selections s      ON s.id = bs.selection_id
JOIN markets m         ON m.id = s.market_id
JOIN events e          ON e.id = m.event_id
WHERE b.placed_at >= e.start_time;

-- total_odds must equal the product of the legs' odds at placement. Must be 0.
-- If this ever breaks, the settlement-mismatch rule starts flagging honest bets.
SELECT count(*) AS wrong_total_odds
FROM (
    SELECT b.id, b.total_odds, round(exp(sum(ln(bs.odds_at_placement))), 3) AS legs_product
    FROM bets b
    JOIN bet_selections bs ON bs.bet_id = b.id
    GROUP BY b.id, b.total_odds
) x
WHERE abs(total_odds - legs_product) > 0.001;

-- nobody staked money they did not have. Must be 0.
-- Balance = approved deposits - stakes + payouts. (Withdrawals join this in step 7.)
SELECT count(*) AS players_overdrawn
FROM (
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
) x
WHERE balance < 0;

-- The stronger version: the balance must never go negative at ANY moment, not just
-- at the end. Every money movement becomes one row, then a running total per player.
-- ORDER BY at, delta DESC settles ties by counting credits before debits.
-- Must be 0.
WITH money AS (
    SELECT player_id, processed_at AS at, amount AS delta
    FROM transactions
    WHERE direction = 'deposit' AND status = 'approved'
  UNION ALL
    SELECT player_id, placed_at, -stake
    FROM bets
  UNION ALL
    SELECT player_id, created_at, -amount          -- money is reserved when requested,
    FROM transactions                              -- not when the payout is approved
    WHERE direction = 'withdrawal' AND status <> 'rejected'
  UNION ALL
    SELECT b.player_id, s.settled_at, s.payout
    FROM settlements s
    JOIN bets b ON b.id = s.bet_id
    WHERE s.payout > 0
)
SELECT count(*) AS moments_with_negative_balance
FROM (
    SELECT sum(delta) OVER (PARTITION BY player_id
                            ORDER BY at, delta DESC
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running
    FROM money
) x
WHERE running < 0;


\echo === 6. settlement (expect 158 of 188 events finished, 12783 settlements) ===

SELECT count(*) FILTER (WHERE status = 'finished') AS finished,
       count(*) FILTER (WHERE status = 'scheduled') AS still_scheduled,
       count(*) AS events
FROM events;

SELECT b.status, count(*) AS bets
FROM bets b
GROUP BY b.status
ORDER BY b.status;

-- expect won 4335 / lost 8448
SELECT result, count(*) AS settlements, sum(payout) AS paid
FROM settlements
GROUP BY result
ORDER BY result;

-- SETTLEMENT MISMATCH: a won bet must pay exactly stake x total_odds, unless the
-- fraud injector planted an error there. Anything wrong AND unlabelled is a bug in
-- the generator. Must be 0.
--
-- Note what this join is doing: it is the ONLY legitimate use of fraud_labels.
-- rules/ may never join to it - that is cheating. Test files may, to separate
-- "planted on purpose" from "broken by accident".
SELECT count(*) AS unlabelled_wrong_payouts
FROM bets b
JOIN settlements s ON s.bet_id = b.id
WHERE s.result = 'won'
  AND abs(s.payout - b.stake * b.total_odds) > 0.01
  AND NOT EXISTS (
      SELECT 1 FROM fraud_labels f
      WHERE f.entity_type = 'settlement' AND f.entity_id = s.id
  );

-- a losing bet must pay nothing unless it was planted, and no bet may be settled
-- twice. Both must be 0.
SELECT (SELECT count(*) FROM settlements s
        WHERE s.result = 'lost' AND s.payout <> 0
          AND NOT EXISTS (SELECT 1 FROM fraud_labels f
                          WHERE f.entity_type = 'settlement' AND f.entity_id = s.id)
       ) AS unlabelled_losers_paid,
       (SELECT count(*) FROM (
            SELECT bet_id FROM settlements GROUP BY bet_id HAVING count(*) > 1
        ) d) AS bets_settled_twice;

-- nothing is settled before it was placed, or before the match ended. Must be 0.
SELECT count(*) AS settled_too_early
FROM settlements s
JOIN bets b ON b.id = s.bet_id
WHERE s.settled_at < b.placed_at;

-- THE MARGIN. Over 3 days this is MEANINGLESS - see the note below.
SELECT count(*)                            AS settled_bets,
       sum(b.stake)                        AS stakes,
       sum(s.payout)                       AS payouts,
       round(1 - sum(s.payout) / sum(b.stake), 4) AS margin
FROM bets b
JOIN settlements s ON s.bet_id = b.id;

-- Do not trust this number on a short run. At DAYS=3 it has read -0.187, +0.079
-- and +0.130 as other steps were added - the data was correct every time. A few
-- winning combos at long odds swing the whole thing: at DAYS=12 two payouts of
-- ~13700 each on 310000 staked moved it by 9 points on their own. There the
-- theoretical edge is +0.086 and the realised one +0.043. Judge it on a long run,
-- and prefer the theoretical margin (sum of stake x odds x implied probability)
-- if you want a number that settles down quickly.


\echo === 7. withdrawals (expect 1115: 1005 approved, 110 still pending) ===

SELECT direction, status, count(*), sum(amount)
FROM transactions
GROUP BY direction, status
ORDER BY direction, status;

-- the schema rule: pending means not processed yet, and nothing else does. Must be 0.
SELECT count(*) AS pending_rule_broken
FROM transactions
WHERE (status = 'pending') <> (processed_at IS NULL);

-- money in vs money out. Deposits must be clearly bigger - the difference is what
-- the bookmaker keeps plus what is still sitting in player balances.
SELECT sum(amount) FILTER (WHERE direction = 'deposit'    AND status = 'approved') AS deposited,
       sum(amount) FILTER (WHERE direction = 'withdrawal' AND status <> 'rejected') AS withdrawn
FROM transactions;

-- how long payouts take, in hours (expect 1 to 24)
SELECT round(min(EXTRACT(EPOCH FROM processed_at - created_at) / 3600), 1) AS min_hours,
       round(avg(EXTRACT(EPOCH FROM processed_at - created_at) / 3600), 1) AS avg_hours,
       round(max(EXTRACT(EPOCH FROM processed_at - created_at) / 3600), 1) AS max_hours
FROM transactions
WHERE direction = 'withdrawal' AND processed_at IS NOT NULL;


\echo === 8. planted fraud (ground truth - rules/ must never read this table) ===

-- How many rows land here is RATE x SETTLEMENTS, so it moves with DAYS as well as
-- with SETTLEMENT_ERROR_RATE. At DAYS=14 and rate 0.0005 that came out as 4 planted,
-- only 1 of them on a won bet - far too few to compute precision or recall from.
-- Raise the rate while DAYS is small; lower it again for the 90-day dataset.

SELECT pattern_code,
       details ->> 'variant' AS variant,
       count(*)              AS planted
FROM fraud_labels
GROUP BY pattern_code, variant
ORDER BY pattern_code, variant;

-- how much of the planted fraud the obvious rule can even see.
-- The WHERE clause of a rule decides what it is blind to: this one only looks at
-- won bets, so every 'lost_bet_paid' is invisible to it no matter the threshold.
SELECT f.details ->> 'variant' AS variant,
       count(*)                                    AS planted,
       count(*) FILTER (WHERE s.result = 'won')    AS visible_to_the_won_bet_rule,
       count(*) FILTER (WHERE s.result <> 'won')   AS invisible
FROM fraud_labels f
JOIN settlements s ON s.id = f.entity_id AND f.entity_type = 'settlement'
GROUP BY variant
ORDER BY variant;

-- the money involved
SELECT f.details ->> 'variant'                              AS variant,
       sum(s.payout)                                        AS actually_paid,
       sum((f.details ->> 'correct_payout')::numeric)       AS should_have_paid,
       sum(s.payout - (f.details ->> 'correct_payout')::numeric) AS overpaid
FROM fraud_labels f
JOIN settlements s ON s.id = f.entity_id AND f.entity_type = 'settlement'
GROUP BY variant
ORDER BY variant;
