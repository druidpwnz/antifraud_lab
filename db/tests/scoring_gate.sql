-- CI only: run after the seed and a complete detection pass, with the live
-- generator stopped. psql must use -v ON_ERROR_STOP=1 so an exception fails CI.
-- rule_scores excludes unscanned labels: check progress before trusting recall.
DO $$
DECLARE
    result record;
BEGIN
    FOR result IN
        WITH expected (rule_code, minimum_recall, source_max) AS (
            VALUES
                ('LATE_BET', 1.0, (SELECT coalesce(max(id), 0) FROM bets)),
                ('SETTLEMENT_MISMATCH', 1.0, (SELECT coalesce(max(id), 0) FROM settlements)),
                ('STAKE_ANOMALY', 0.85, (SELECT coalesce(max(id), 0) FROM bets))
        )
        SELECT e.*, s.planted, s.caught, r.last_id
        FROM expected e
        LEFT JOIN rule_scores s USING (rule_code)
        LEFT JOIN rule_state r USING (rule_code)
        ORDER BY e.rule_code
    LOOP
        IF result.last_id IS NULL OR result.last_id < result.source_max THEN
            RAISE EXCEPTION 'FAIL %: rule has not scanned the full seed (last_id %, source_max %)',
                result.rule_code, result.last_id, result.source_max;
        END IF;
        IF result.planted IS NULL OR result.planted = 0 OR result.caught IS NULL THEN
            RAISE EXCEPTION 'FAIL %: no scored ground truth', result.rule_code;
        END IF;
        -- The dashboard rounds recall to 3 decimals. Use counts here: 0.9996
        -- must not round up to a passing 1.000 when even one planted case was missed.
        IF result.caught < result.minimum_recall * result.planted THEN
            RAISE EXCEPTION 'FAIL %: caught % of %, below recall floor %',
                result.rule_code, result.caught, result.planted, result.minimum_recall;
        END IF;
        RAISE NOTICE 'PASS %: caught % of %, recall floor %',
            result.rule_code, result.caught, result.planted, result.minimum_recall;
    END LOOP;
END $$;
