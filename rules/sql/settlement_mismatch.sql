-- SETTLEMENT_MISMATCH - a settlement that paid something other than what its
-- result is worth. Source: settlements. Catches the planted SETTLEMENT_ERROR pattern.
--
--   won   should pay stake x odds
--   lost  should pay nothing
--
-- The first version said WHERE result = 'won', and was blind to every losing bet
-- that was paid anyway - about two thirds of the pattern (recall about 0.34).
-- Phase 9 step 8 fixed it: the expected payout now comes from the result.
--
-- Other results (void, half_won, half_lost) are left out: the generator never
-- writes them, and their payout rules would be guesses nothing tests.
--
-- To try any rule in psql: replace the last_id placeholder with 0 and the upto
-- one with 999999999. (No percent sign in these comments: psycopg would read it
-- as a placeholder, comment or not.)
SELECT
    b.player_id,
    s.id AS source_id,
    s.settled_at AS window_start,
    s.settled_at AS window_end,
    jsonb_build_object(
        'settlement_id', s.id,
        'bet_id',        b.id,
        'result',        s.result,
        'payout',        s.payout,
        'expected',      round(e.expected, 2),
        'difference',    s.payout - round(e.expected, 2)
    ) AS details
FROM settlements s
JOIN bets b ON b.id = s.bet_id
CROSS JOIN LATERAL (
    SELECT CASE s.result
               WHEN 'won'  THEN b.stake * b.total_odds
               WHEN 'lost' THEN 0
           END AS expected
) e
WHERE s.id > %(last_id)s AND s.id <= %(upto)s
  AND e.expected IS NOT NULL
  AND abs(s.payout - e.expected) > 0.01
