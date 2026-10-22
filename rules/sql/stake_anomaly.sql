-- STAKE_ANOMALY - a stake at least 8x the player's own average over their previous
-- 50 bets, once they have 15 or more. Source: bets. Catches the planted
-- STAKE_ESCALATION pattern (the shape of an account takeover).
--
-- Per player, not a fixed amount: most planted bets are smaller than the biggest
-- honest ones, so "stake over 500" cannot tell them apart (generator/FRAUD_PATTERNS.md).
-- Honest high-rollers sometimes do this too - precision below 1 is expected.
WITH new_bets AS (
    SELECT id, player_id FROM bets WHERE id > %(last_id)s AND id <= %(upto)s
),
history AS (
    -- the whole history of every player with a new bet: the average needs the
    -- bets before the new ones, which an earlier run has already passed
    SELECT b.id, b.player_id, b.placed_at, b.stake,
           avg(b.stake) OVER previous   AS average_before,
           count(*)     OVER previous   AS bets_before
    FROM bets b
    WHERE b.player_id IN (SELECT player_id FROM new_bets)
    WINDOW previous AS (PARTITION BY b.player_id ORDER BY b.placed_at, b.id
                        ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING)
)
SELECT
    h.player_id,
    h.id AS source_id,
    h.placed_at AS window_start,
    h.placed_at AS window_end,
    jsonb_build_object(
        'bet_id',              h.id,
        'stake',               h.stake,
        'average_before',      round(h.average_before, 2),
        'multiple_of_average', round(h.stake / h.average_before, 1),
        'bets_before',         h.bets_before
    ) AS details
FROM history h
WHERE h.id IN (SELECT id FROM new_bets)
  AND h.bets_before >= 15
  AND h.stake >= 8 * h.average_before
