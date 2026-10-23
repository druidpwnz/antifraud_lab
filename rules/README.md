# Antifraud Lab rules runner

Detection. Every minute it runs each rule over the rows that have arrived since its
last run, and writes what it finds into `alerts`. Rules never read `fraud_labels` —
that table is only for scoring them afterwards (`db/scoring.sql`).

The design decisions are in the main [README](../README.md) (phase 9).

## The rules

| Rule | File | Source | Finds | Severity |
|---|---|---|---|---|
| `SETTLEMENT_MISMATCH` | `sql/settlement_mismatch.sql` | settlements | a settlement that paid more or less than its result is worth — stake × odds when won, nothing when lost (by more than a cent) | high |
| `LATE_BET` | `sql/late_bet.sql` | bets | a bet placed after one of its matches kicked off | high |
| `STAKE_ANOMALY` | `sql/stake_anomaly.sql` | bets | a stake ≥ 8× the player's average over their previous 50 bets, after at least 15 | medium |

`SETTLEMENT_MISMATCH` was first written the obvious way, `WHERE result = 'won'`, on
purpose: a *losing* bet that was paid was invisible to it, and scoring showed recall
0.33. Phase 9 step 8 fixed it — see [Changing a rule](#changing-a-rule).

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

Against `antifraud_test` (or `TEST_DATABASE_URL`), migrated to at least 007. Every
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

## Changing a rule

The runner only reads rows above `last_id`, so a fixed rule sees only rows that
arrive *after* the fix. To run the new version over everything already there:

```bash
docker compose up -d --build rules                                  # the new SQL
docker compose exec rules python runner.py --rescan SETTLEMENT_MISMATCH
```

`--rescan` sets that rule's `last_id` back to 0 and exits; the running runner reads
the whole source table on its next run (a minute). It is safe to repeat: alerts
already raised hit `ON CONFLICT DO NOTHING`, so nothing is doubled — and they keep
the `details` they were written with. The new alerts get today's `created_at`, so
expect *High-severity detection* to fire for them, and *Detection rate shift* to
see the jump.

Measured on the 14-day seed (17,458 settlements, 78 planted errors):

| `SETTLEMENT_MISMATCH` | Detected | Caught | Missed | Precision | Recall | Overpaid, found |
|---|---|---|---|---|---|---|
| `WHERE result = 'won'` | 26 | 26 | 52 | 1.000 | 0.333 | 192.49 |
| expected payout from the result | 78 | 78 | 0 | 1.000 | **1.000** | 9,882.03 |

The two thirds it used to miss were also the expensive ones: a losing bet paid out
is the whole payout lost, not a 5–40% error.

**No percent sign in a rule's comments.** psycopg reads `%(...)s` as a placeholder
even inside an SQL comment.
