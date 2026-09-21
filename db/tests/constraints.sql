-- tests/constraints.sql
BEGIN;

CREATE FUNCTION pg_temp.expect_error(label text, stmt text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    cname text;
BEGIN
    EXECUTE stmt;
    RAISE EXCEPTION 'FAIL: % — insert succeeded', label;
EXCEPTION
    WHEN integrity_constraint_violation THEN
        GET STACKED DIAGNOSTICS cname = CONSTRAINT_NAME;
        RAISE NOTICE 'PASS: %  (%)', label, cname;
END $$;

-- fixtures
INSERT INTO players (country, currency) VALUES ('ZZ', 'EUR');

-- tests
SELECT pg_temp.expect_error('negative stake', $sql$
    INSERT INTO bets (player_id, stake, currency, total_odds)
    VALUES ((SELECT id FROM players WHERE country = 'ZZ'), -10, 'EUR', 2.0)
$sql$);

ROLLBACK;
