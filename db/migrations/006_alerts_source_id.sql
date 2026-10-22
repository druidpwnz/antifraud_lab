-- 006_alerts_source_id.sql
-- Which row an alert is about, and a uniqueness that tells two findings apart.
--
-- alerts was made unique on (player_id, rule_code, window_start, window_end) - right
-- for a rule about a stretch of time ("4 deposits in an hour"), wrong for a rule
-- about one row. Two wrong payouts to the same player, settled in the same second -
-- common, the generator dates many settlements to the start of a tick - had the
-- same key, and the second was thrown away as a duplicate. Found by the rules tests
-- in phase 9 step 2.
--
-- source_id is the id of the row the finding is about, in the rule's source table
-- (a settlement, a bet). It joins the key, so two settlements are two alerts, and
-- the same settlement found twice is still one. A rule about a stretch of time
-- leaves it NULL, and NULLS NOT DISTINCT keeps those deduplicated as before.

SET TIME ZONE 'UTC';

ALTER TABLE alerts ADD COLUMN source_id bigint CHECK (source_id > 0);

ALTER TABLE alerts DROP CONSTRAINT alerts_player_id_rule_code_window_start_window_end_key;
ALTER TABLE alerts ADD CONSTRAINT alerts_finding_key
    UNIQUE NULLS NOT DISTINCT (rule_code, player_id, window_start, window_end, source_id);

COMMENT ON COLUMN alerts.source_id IS
    'The row the finding is about, in the rule''s source table (see RULES in rules/runner.py). NULL for a rule about a stretch of time.';
