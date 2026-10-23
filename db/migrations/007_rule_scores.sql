-- 007_rule_scores.sql
-- Precision and recall per detection rule, as a view: db/scoring.sql, the Grafana
-- Scoring dashboard and the rules tests all read this one definition, instead of
-- three copies of the query that could drift apart.
--
-- The only place alerts meet fraud_labels. Rules never read that table; scoring
-- must, or there is nothing to score against. (A dashboard is not a detection rule.)
--
--   planted    rows of the rule's pattern that the rule has had a chance to look at
--   detected   alerts the rule raised
--   caught     detected AND planted
--   precision  caught / detected - how many alerts were real
--   recall     caught / planted  - how much of the planted fraud was found
--
-- A new rule is added with CREATE OR REPLACE VIEW in a new migration, never by
-- editing this file.

SET TIME ZONE 'UTC';

CREATE VIEW rule_scores AS
-- Each rule against the pattern it is meant to catch. An alert's source_id is the
-- row it is about, of the same kind as the pattern's labelled entity.
WITH rule_pattern (rule_code, pattern_code, entity_type) AS (
    VALUES ('SETTLEMENT_MISMATCH', 'SETTLEMENT_ERROR', 'settlement'),
           ('LATE_BET',            'LATE_BET',         'bet'),
           ('STAKE_ANOMALY',       'STAKE_ESCALATION', 'bet')
),
detected AS (
    SELECT DISTINCT a.rule_code, a.source_id AS entity_id
    FROM alerts a
    JOIN rule_pattern rp USING (rule_code)
),
planted AS (
    -- Only up to where the rule has got to: fraud planted in rows it has not
    -- read yet is not "missed", it is "not looked at yet".
    SELECT rp.rule_code, f.entity_id
    FROM fraud_labels f
    JOIN rule_pattern rp ON rp.pattern_code = f.pattern_code AND rp.entity_type = f.entity_type
    JOIN rule_state rs   ON rs.rule_code = rp.rule_code
    WHERE f.entity_id <= rs.last_id
),
counts AS (
    SELECT rp.rule_code,
           (SELECT count(*) FROM planted p  WHERE p.rule_code = rp.rule_code) AS planted,
           (SELECT count(*) FROM detected d WHERE d.rule_code = rp.rule_code) AS detected,
           (SELECT count(*) FROM detected d JOIN planted p USING (rule_code, entity_id)
             WHERE d.rule_code = rp.rule_code)                                AS caught
    FROM rule_pattern rp
)
SELECT rule_code,
       planted,
       detected,
       caught,
       detected - caught AS false_alarms,
       planted - caught  AS missed,
       round(caught::numeric / nullif(detected, 0), 3) AS precision,
       round(caught::numeric / nullif(planted, 0), 3)  AS recall
FROM counts;

COMMENT ON VIEW rule_scores IS
    'Precision and recall per detection rule, against fraud_labels. See db/migrations/007_rule_scores.sql.';
