-- scoring.sql - how good is each detection rule?
--
--     psql antifraud -f db/scoring.sql
--     docker compose exec -T postgres psql -U antifraud -d antifraud < db/scoring.sql
--
-- What the columns mean, and the query itself: the rule_scores view, in
-- db/migrations/007_rule_scores.sql. Grafana's Scoring dashboard reads the same view.

SELECT * FROM rule_scores ORDER BY rule_code;
