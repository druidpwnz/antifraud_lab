# Antifraud Lab rules runner

Detection. Every minute it runs each rule over the rows that have arrived since its
last run, and writes what it finds into `alerts`. Rules never read `fraud_labels` —
that table is only for scoring them afterwards (`db/scoring.sql`).

The design decisions are in the main [README](../README.md) (phase 9).

## The rules

| Rule | File | Source | Finds | Severity |
|---|---|---|---|---|
| `SETTLEMENT_MISMATCH` | `sql/settlement_mismatch.sql` | settlements | a **won** bet paid more or less than stake × odds (by more than a cent) | high |
| `LATE_BET` | `sql/late_bet.sql` | bets | a bet placed after one of its matches kicked off | high |
| `STAKE_ANOMALY` | `sql/stake_anomaly.sql` | bets | a stake ≥ 8× the player's average over their previous 50 bets, after at least 15 | medium |

`SETTLEMENT_MISMATCH` is written the obvious way on purpose: a *losing* bet that was
paid is invisible to it. Scoring shows the cost; phase 9 step 8 fixes it.

## How a run works

For each rule, in one transaction:

1. read `rule_state.last_id` — how far it got last time (locked, so two runners
   cannot scan the same rows)
2. fix `upto` = the newest id in its source table now
3. run the rule's `SELECT` over ids in `(last_id, upto]`, and `INSERT` each finding
   into `alerts` — `ON CONFLICT DO NOTHING`, so the same row found twice is one alert
4. set `last_id = upto`

The alerts and the new `last_id` commit together, so a crash between runs can
neither lose rows nor alert on them twice. Ids, not timestamps: the generator
writes 5–10 minutes behind its own clock and dates settlements back to the end of
the match, so timestamps do not arrive in order — ids do. That holds because each
source table has one writer, the generator, committing in id order.

A rule returns `player_id, source_id, window_start, window_end, details`. `source_id`
is the row the finding is about (a settlement, a bet); alerts are unique on
`(rule_code, player_id, window_start, window_end, source_id)`.

## Run it

With Docker it is the `rules` service, started by `docker compose up -d`:

```bash
docker compose logs -f rules          # one line per rule that found new rows
docker compose exec -T postgres psql -U antifraud -d antifraud < db/scoring.sql
```

Without Docker, with the venv active and the database migrated:

```bash
pip install -r rules/requirements-dev.txt
cd rules && python runner.py                       # DATABASE_URL, RUN_EVERY_SECONDS
psql antifraud -f db/scoring.sql
```

## Test it

```bash
cd rules && pytest
```

Against `antifraud_test` (or `TEST_DATABASE_URL`), migrated to at least 006. Every
test runs in one transaction that is rolled back, so the database — and the API's
test data in it — is left as it was.

## Adding a rule

1. `sql/<rule_code in lower case>.sql` — a `SELECT` returning the five columns above,
   looking only at ids `> %(last_id)s` and `<= %(upto)s` of its source table
2. a `Rule(...)` line in `RULES` in `runner.py`
3. tests: it finds its shape, and leaves the honest version alone
4. if it is meant to catch a planted pattern: a line in `rule_pattern` in the
   `rule_scores` view — a new migration with `CREATE OR REPLACE VIEW`, copying
   `db/migrations/007_rule_scores.sql` (never edit an applied migration)

**No percent sign in a rule's comments.** psycopg reads `%(...)s` as a placeholder
even inside an SQL comment.
