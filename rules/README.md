# Detection rules

Every minute, the runner scans new source rows and writes findings to `alerts`.
It never reads `fraud_labels`; those labels are used only to score detection quality.

| Rule | Finds | Severity |
|---|---|---|
| `SETTLEMENT_MISMATCH` | Payout differs from the expected result by more than one cent | High |
| `LATE_BET` | Bet placed after a match kicked off | High |
| `STAKE_ANOMALY` | Stake at least 8× the prior-50-bet average, with at least 15 prior bets | Medium |

From the repository root:

```bash
docker compose logs -f rules
docker compose exec -T postgres psql -U antifraud -d antifraud < db/scoring.sql
```

For local development with the venv active and database migrated:

```bash
(cd rules && DATABASE_URL='dbname=antifraud' python runner.py)
(cd rules && TEST_DATABASE_URL='dbname=antifraud_test' python -m pytest -q)
```

Tests use a dedicated test database and roll back their transactions.
See [development setup](../docs/DEVELOPMENT.md) and [SQL checks](../db/tests/README.md).

## Extending rules

A rule returns `player_id, source_id, window_start, window_end, details` for source
IDs in `(last_id, upto]`. Add its SQL under `sql/`, register it in `RULES`, and test
both fraudulent and honest examples. A new scored pattern also needs a migration
updating the `rule_scores` view.

Avoid literal percent signs in SQL comments: psycopg parses placeholders there too.

Alerts and the cursor commit together; duplicate findings use `ON CONFLICT DO NOTHING`.
The ID cursor assumes one source writer committing in order. Timestamps are not
reliable cursors because generated activity can arrive out of timestamp order.

## Rescan after a rule change

New SQL normally sees only new rows. After deploying it, reset the selected cursor
when existing data also needs evaluation:

```bash
docker compose exec rules python runner.py --rescan SETTLEMENT_MISMATCH
```

The next scheduled run rescans the source. Existing alerts are retained, including
their original details; new findings can trigger Grafana alerts. Managed servers
receive rule updates through the updater; local development uses an image rebuild.
