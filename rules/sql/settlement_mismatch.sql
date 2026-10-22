-- SETTLEMENT_MISMATCH - a won bet paid more or less than stake x odds.
-- Source: settlements. Catches the planted SETTLEMENT_ERROR pattern.
--
-- Written the obvious way ON PURPOSE: WHERE result = 'won'. A losing bet that was
-- paid anyway - the other half of the pattern - is invisible to it. Scoring shows
-- what that costs (recall about a third); phase 9 step 8 fixes it.
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
        'payout',        s.payout,
        'expected',      round(b.stake * b.total_odds, 2),
        'difference',    s.payout - round(b.stake * b.total_odds, 2)
    ) AS details
FROM settlements s
JOIN bets b ON b.id = s.bet_id
WHERE s.id > %(last_id)s AND s.id <= %(upto)s
  AND s.result = 'won'
  AND abs(s.payout - b.stake * b.total_odds) > 0.01
