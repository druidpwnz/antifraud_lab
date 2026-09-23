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
| 3 | Fraud injector — more patterns | 1 of 3 done |
| 4 | Live generator | next |
| 5 | Thin alerting (fills `alerts`) | not started |
| 6 | API — FastAPI | the main event |
| 7 | Flask admin panel | optional |
| 8 | Compose, for real | not started |
| 9 | Grafana + Prometheus — fraud alerting | not started |
| 10 | CI | not started |

Done so far: 14-table schema with constraints that hold, a seeded reproducible
backfill (90 days = 9.7k players, 650k bets, ~10 min), `SETTLEMENT_ERROR` injection
with ground truth in `fraud_labels`, and `db/tests/backfill_checks.sql` — nine
invariants that must read 0 at any dataset size.

---

## Decisions

**1. One web framework or two? — SETTLED.** FastAPI for the API, Flask-Admin as a
separate small service against the same database. Two services, as a real back
office has: the public API and the internal admin panel are rarely the same app.

**2. Does the admin panel share models with the API?** Flask-Admin wants SQLAlchemy
models. The API can use raw SQL. Sharing one models package between two services
means a shared library; not sharing means writing the tables twice. Either is fine;
pick one knowingly.

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

- [ ] Read `sim_state.sim_time` on startup; `INSERT ... ON CONFLICT (id) DO UPDATE`
      on every tick (the backfill/live split you already decided)
- [ ] Time compression from `.env`:

```
TICK_SECONDS=1
SIM_MINUTES_PER_TICK=5     # ~one simulated hour per 12 real seconds
```

- [ ] Rebuild in-memory state from the database at startup: players, balances,
      open bets. Archetypes need no storage — `players.archetype_for(id)` derives
      them from the seed
- [ ] Graceful shutdown (SIGTERM), structured logging
- [ ] Prometheus counters: rows written per second, sim lag behind wall clock

**The thing to watch:** the handoff. Nothing should look different in the data on
either side of `sim_state.sim_time`. Re-run `backfill_checks.sql` after the live
generator has run for an hour — every invariant must still read 0.

---

## Phase 5 — Thin alerting

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

## Phase 6 — API (the main event)

FastAPI over the same database. This is where the time goes now.

**Endpoints**

- [ ] `GET /players/{id}/risk` — score plus contributing alerts
- [ ] `GET /alerts` — filter by `rule_code`, `severity`, `since`; paginated
- [ ] `POST /alerts/{id}/review` — mark confirmed or false positive
- [ ] `POST /transactions` — score a transaction inline, return a decision

**The parts that are actually the learning**

- [ ] **Pagination** — limit/offset vs cursor, and why cursor survives inserts
- [ ] **Status codes that mean something** — 400 vs 404 vs 409 vs 422, and when
      Pydantic returns 422 for you
- [ ] **Idempotency** on `POST /transactions` — an `Idempotency-Key` header, stored
      so a retry returns the first answer instead of scoring twice
- [ ] **API-key auth** via header, as a dependency rather than per-endpoint code
- [ ] **Error shape** — one consistent JSON error body across every failure
- [ ] **Pydantic request and response models** — where validation actually lives
- [ ] **Connection pooling** — one pool for the app, not a connection per request
- [ ] **OpenAPI** — read what FastAPI generates and fix what it gets wrong

**Proof it works**

- [ ] Postman collection committed: environment variables, auth header, tests
      asserting status codes and response shape
- [ ] `pytest` against a test database: happy path, 404, 422, bad key, idempotent
      replay

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
- [ ] Apply migrations, run a short backfill (`DAYS=3`), run
      `db/tests/backfill_checks.sql` and fail the build if any invariant is non-zero
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
