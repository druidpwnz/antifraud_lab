# Antifraud Lab — Build Plan

A self-contained fraud-detection lab running on the home server: a generator that
produces production-like betting and payment traffic with deliberately planted fraud,
a REST API over it, an admin panel, and Grafana dashboards.

**Goal (revised):** depth in **REST API design**, **Python services**, and **CI/CD**.
Advanced SQL is no longer the target — the rules layer stays deliberately thin.

---

## Status

| Phase | What | State |
|---|---|---|
| 0 | Repo, skeleton, compose | **compose still empty** |
| 1 | Schema — 14 tables + `sim_state` | **done** |
| 2 | Backfill generator | **done** |
| 3 | Fraud injector | **3 patterns done** |
| 4 | Live generator | **done** (no metrics yet) |
| 5 | Thin alerting (fills `alerts`) | **postponed** — after the API |
| 6 | API — FastAPI | **next** |
| 7 | Flask admin panel | optional |
| 8 | Compose, for real | not started |
| 9 | Grafana + Prometheus — fraud alerting | not started |
| 10 | CI | not started |

Done so far: 14-table schema with constraints that hold, a seeded reproducible
backfill (90 days = 9.7k players, 650k bets, ~10 min), `SETTLEMENT_ERROR` injection
with ground truth in `fraud_labels`, and `db/tests/invariants.sql` — twelve checks
that must hold at any dataset size, which raise and exit non-zero when they do not.

---

## Decisions

**1. One web framework or two? — SETTLED.** FastAPI for the API, Flask-Admin as a
separate small service against the same database. Two services, as a real back
office has: the public API and the internal admin panel are rarely the same app.

**2. Does the admin panel share models with the API? — SETTLED: no.** The API uses
psycopg 3 and raw SQL with a connection pool. Flask-Admin will get its own small
SQLAlchemy models when phase 7 starts.

**3. Alerts before or after the API? — SETTLED: after.** The API ships without alert
endpoints; phase 5 and the alert endpoints come back in a later update.

---

## Phase 3 — Fraud injector: two more patterns

`generator/FRAUD_PATTERNS.md` is the map: what each pattern plants, what it labels,
what it depends on. `SETTLEMENT_ERROR` is done.

Pick two of these three. All are buildable with the schema as it stands:

- [ ] **`LATE_BET`** — a bet written after `events.start_time`. The generator
      structurally prevents this, so the injector must bypass `load_open_selections`.
      Cheapest to build, and trivially checkable: the baseline query returns 0 on
      650k honest bets.
- [ ] **`STAKE_ESCALATION`** — weeks of small bets, then one very large one. Account
      takeover shaped. Needs no new tables, and competes with genuine high-roller
      noise, which makes it the most realistic of the three.
- [ ] **`MULTI_ACCOUNT`** — 3–6 accounts sharing a `device_id` or payment
      fingerprint, registered days apart. Needs `cluster_id` so the ring scores as
      one incident. Note the honest households already in the data (156 shared
      devices at 90 days) are exactly what makes this hard.

- [ ] Every planted row writes to `fraud_labels`
- [ ] `SETTLEMENT_ERROR_RATE` and friends scale with `DAYS` — rate x settlements is
      what decides whether there is anything to measure
- [ ] Update `FRAUD_PATTERNS.md` as each lands

**Skip:** `PASSTHROUGH` and `CARD_TESTING` need several payment methods per player;
`MATCHED_BETTING` needs `MULTI_ACCOUNT` first; `BONUS_ABUSE` needs the `bonuses`
table to be written to at all.

---

## Phase 4 — Live generator

The same code path as backfill, running forward from where backfill stopped.

- [x] Read `sim_state.sim_time` on startup; `INSERT ... ON CONFLICT (id) DO UPDATE`
      on every tick (the backfill/live split you already decided)
- [x] Time compression from the environment, with `config.py` defaults:

```
REAL_SECONDS_PER_SIM_HOUR=12   # 3600 = real time, 12 = one sim day per 5 minutes
CATCH_UP=1                     # run flat out until the sim clock reaches now
```

      Steps in whole simulated hours rather than the 5-minute ticks originally
      planned — that way live and backfill share `tick.one_hour()` exactly, instead of
      two loops that could drift apart.

- [x] Rebuild in-memory state from the database at startup — `state.load()`. Verified
      against the backfill's own in-memory state: 1526 players, zero mismatches on
      every field, balances exact to the cent
- [x] **The rule that made this possible:** anything the live generator needs is
      either in a table or derivable from (seed, row id). Archetypes, event goal
      probabilities and withdrawal due times are all derived; nothing lives only in
      a Python variable
- [x] Graceful shutdown (SIGTERM/SIGINT): finishes the hour, commits, exits
- [ ] Structured logging (plain prints for now)
- [ ] Prometheus counters: rows written per second, sim lag behind wall clock

**The thing to watch:** the handoff. Nothing should look different in the data on
either side of `sim_state.sim_time`. Run `db/tests/invariants.sql` after the live
generator has been going for a while — every check must still pass. (Done: it does,
across 134k bets written by two processes.)

---

## Phase 5 — Thin alerting (postponed until after the API)

Not the old phase 3. No window-function tuning, no threshold optimisation. This
exists for one reason: **`alerts` must have rows in it, or the API has nothing to
serve.**

- [ ] One small `.sql` file per planted pattern, each returning candidate alerts
      with a stable `rule_code` — the obvious query, not a clever one
- [ ] `rules-runner`: a loop that executes them on a schedule and upserts into
      `alerts`, deduped on `(player_id, rule_code, window_start, window_end)`
- [ ] Rules must never read `fraud_labels`
- [ ] One scoring query joining `alerts` to `fraud_labels` — precision and recall
      per rule. Keep it: it is the one number that makes the alerts credible, and
      it is a good thing to be able to show
- [ ] Expose Prometheus metrics from the runner: alerts created per `rule_code`,
      rows scanned, run duration, time since last successful run. These are what
      phase 9 alerts on

Budget: an evening, not a week. If a rule is hard, make it dumber.

---

## Phase 6 — API (next)

FastAPI over the same database, in `api/`. psycopg 3 with raw SQL and a connection
pool, no ORM. No alert endpoints yet — those come back with phase 5.

### The write endpoint is a risk check, not a transaction

`POST /transactions` would fight the live generator: its balances live in memory, so
a withdrawal created by the API would be debited in the ledger but not by the
generator, which would then overspend.

So the API writes **risk checks** instead: "should this deposit or withdrawal go
through?" It scores the proposed transaction against the player's real history,
returns `approve` / `review` / `decline` with reasons, and stores the decision in its
own table (`db/migrations/003_risk_checks.sql`). That is how a payment gateway calls
an antifraud service, and it never touches the generator's tables.

**"Now" is the simulated clock.** Velocity windows are measured against
`sim_state.sim_time`, not `now()`. `risk_checks.created_at` records the real call
time. The two clocks again.

### Design decisions

| Topic | Decision | Why |
|---|---|---|
| Versioning | `/v1` URL prefix | Explicit, visible in logs and in Postman |
| Endpoints | sync `def` + `psycopg_pool.ConnectionPool` | FastAPI runs them in a threadpool; async is a later refactor |
| Pagination | Cursor (keyset on `id`), opaque base64, `limit` 1–100 | The live generator inserts constantly — offset pagination would skip or repeat rows |
| Errors | RFC 9457 `application/problem+json` for every failure | One shape for 400/401/404/422/500; a 500 never leaks a stack trace |
| Auth | `X-API-Key`, keys from env `API_KEYS`, `hmac.compare_digest`, router dependency | Timing-safe; shows up as Authorize in `/docs` |
| Money in JSON | Strings (`"12.50"`) from `Decimal` | Floats corrupt money |
| Time in JSON | RFC 3339 UTC | The pool connects with `timezone=UTC` |
| Idempotency | `Idempotency-Key` on POST, stored with a SHA-256 of the body. 201 first time; 200 + `Idempotent-Replayed: true` on replay; 422 if the same key comes with a different body | Race-safe via `UNIQUE` + `INSERT … ON CONFLICT DO NOTHING` |
| Not exposed | `fraud_labels` | Ground truth never leaves the database |

### Endpoints

- [x] `GET /health` (no DB) and `GET /ready` (`SELECT 1`, 503 if the DB is down)
- [x] `GET /v1/players`, `GET /v1/players/{id}`
- [x] `GET /v1/players/{id}/balance`, `/transactions`, `/bets`
- [x] `GET /v1/bets/{id}` — nested legs and settlement
- [x] `GET /v1/events`, `GET /v1/events/{id}` — nested markets and selections
- [x] `POST /v1/risk-checks`, `GET /v1/risk-checks/{id}`

### Build order — one step at a time, reviewed before the next

1. Skeleton: settings, pool, `/health`, `/ready`
2. Problem+json errors and API-key auth
3. Players with cursor pagination
4. Player balance, transactions, bets
5. Bets and events with nested response models
6. Migration 003 and risk checks with idempotency
7. Postman collection in `api/postman/` — built alongside each step rather than at the end
8. Update README, STATUS, CLAUDE.md

Tests are written with each step, against a separate `antifraud_test` database.

**Postman collection:** `api/postman/`, with a `local` environment whose `apiKey`
is empty in git and filled in inside Postman. Edits made in the app have to be
exported back over the JSON to reach git. The same collection runs from the command
line with Newman, which is what phase 10 CI will use.

**Proof it works:** `/docs` shows every endpoint with its schemas and errors; `pytest`
passes; the Postman collection passes under Newman; and `db/tests/invariants.sql` still passes
after risk checks have run, which shows the API never disturbed generator data.

---

## Phase 7 — Flask admin panel (optional)

A back office over the same tables, built fast with third-party modules rather than
by hand. The point is learning the ecosystem, not the UI.

- [ ] `Flask-SQLAlchemy` models for the tables the admin touches
- [ ] `Flask-Admin` model views: alerts, players, transactions
- [ ] `Flask-Login` for a single admin user
- [ ] Custom action: confirm / mark false positive, calling the **API** rather than
      writing to the database directly — that keeps one path for writes and gives
      the API a real consumer

Cut this if time is short. It is the least transferable phase.

---

## Phase 8 — Compose, for real

`docker-compose.yml` has been empty since day one, and by now there are four
services that need to talk to each other.

- [ ] `postgres`, `generator` (live mode), `rules-runner`, `api`, `admin`,
      `grafana`, `prometheus`
- [ ] One bridge network, Postgres on a named volume
- [ ] Publish only the API, the admin panel and Grafana to the LAN
- [ ] Healthcheck on Postgres, `depends_on: condition: service_healthy` — a plain
      `depends_on` does not wait for the database to accept connections
- [ ] Migrations applied by an entrypoint, not by hand
- [ ] `.env` for credentials and simulation knobs, `.env.example` committed

---

## Phase 9 — Grafana + Prometheus: where fraud becomes an alert

Detected fraud surfaces here. Two alerting paths, and they are not interchangeable.

**Grafana alerting, on the Postgres datasource — per-entity alerts.**
Grafana runs SQL on a schedule and fires on the rows it gets back, so it can name a
player, a cluster or a settlement.

- [ ] Fire on a new high-severity row in `alerts`
- [ ] Fire on a settlement mismatch above a money threshold
- [ ] Fire on a device or fingerprint gaining a third distinct player
- [ ] Notification channel — whatever you actually read: Telegram, email, webhook

**Prometheus alerting — aggregate shape, never per entity.**
A Prometheus series is identified by its labels, so **`player_id`, `alert_id` and
`device_id` must never be labels** — that is unbounded cardinality and it will take
the instance down. Label by `rule_code` and `severity`, which are small fixed sets.

- [ ] Alert when the detection rate for a rule doubles or drops to zero
- [ ] Alert when the rules-runner has not completed a run in N minutes
- [ ] Alert when the live generator's sim clock falls behind wall clock
- [ ] Alert on API error rate and p99 latency

**Dashboards**

- [ ] *Fraud*: alerts per hour by rule, top risk players, flagged share of volume,
      alerts by status (new / confirmed / false positive)
- [ ] *Scoring*: planted vs detected vs missed per pattern, precision and recall as
      stat panels — this is where `fraud_labels` is allowed to appear, because a
      dashboard is not a detection rule
- [ ] *Money*: deposits vs withdrawals, turnover, house margin over time
- [ ] *Ops*: API latency and error rate, generator rows/sec, runner duration and lag
- [ ] Datasources, dashboards **and alert rules** provisioned as JSON in the repo,
      so nothing lives only inside Grafana's own database

---

## Phase 10 — CI

GitHub Actions on push:

- [ ] `ruff`
- [ ] `pytest` against a `postgres` service container
- [ ] Apply migrations, run a short backfill (`DAYS=3`), then
      `psql -v ON_ERROR_STOP=1 -f db/tests/invariants.sql` — it already raises on
      failure, so it needs no wrapper script
- [ ] API tests against the same container
- [ ] Build and push images

The backfill check is the honest version of "I know CI/CD": a test suite that runs a
real database, generates real data, and asserts something that can actually break.

---

## Housekeeping

- [ ] `CLAUDE.md` points at `PLAN.md`; the plan is this file. Rename one of them.
- [ ] Twelve `>= '2025-01-01'` CHECK floors in `001_schema.sql` — decide whether
      they earn their place, and whether a ceiling would catch more real bugs
- [ ] One device and one payment method per player is unrealistically clean. Needed
      before `PASSTHROUGH`, `CARD_TESTING` or a convincing `MULTI_ACCOUNT`
- [ ] `bonuses` is an empty table

## What was dropped, and why

The original phase 3 — eight detection rules built on window functions and CTEs,
with threshold tuning driven by precision and recall — was the centrepiece when the
target was a SQL interview. That target is gone, so it is now a liability: weeks of
work that no longer serves the goal.

What survives is phase 5: enough rules to populate `alerts`, plus the scoring query.
The generator, the schema and `fraud_labels` were never SQL-interview props — they
are what gives the API something real to serve.
