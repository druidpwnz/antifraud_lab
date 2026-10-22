-- LATE_BET - a bet placed after one of its matches had kicked off.
-- Source: bets. Catches the planted LATE_BET pattern; honest betting only ever
-- offers matches that have not started, so the baseline is clean.
--
-- A combo with two late legs is one finding, about the leg that started first.
SELECT DISTINCT ON (b.id)
    b.player_id,
    b.id AS source_id,
    b.placed_at AS window_start,
    b.placed_at AS window_end,
    jsonb_build_object(
        'bet_id',                b.id,
        'event_id',              e.id,
        'kickoff',               e.start_time,
        'seconds_after_kickoff', extract(epoch FROM b.placed_at - e.start_time)::int
    ) AS details
FROM bets b
JOIN bet_selections bs ON bs.bet_id = b.id
JOIN selections s      ON s.id = bs.selection_id
JOIN markets m         ON m.id = s.market_id
JOIN events e          ON e.id = m.event_id
WHERE b.id > %(last_id)s AND b.id <= %(upto)s
  AND b.placed_at > e.start_time
ORDER BY b.id, e.start_time
