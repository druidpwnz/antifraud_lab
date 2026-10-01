-- 004_events_kickoff_order.sql
-- GET /v1/events?sort=start_time pages with a two-column cursor:
--     WHERE (start_time, id) > ($1, $2) ORDER BY start_time, id
-- An index on exactly (start_time, id) answers that with one index range scan, in
-- order, stopping after LIMIT rows - no sort step, however many events there are.

SET TIME ZONE 'UTC';

CREATE INDEX events_start_time_id_idx ON events (start_time, id);

-- The old single-column index is now redundant: (start_time, id) starts with
-- start_time, so it serves every query the old one did. Two indexes on the same
-- leading column cost every INSERT twice and help no SELECT.
DROP INDEX events_start_time_idx;
