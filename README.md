# Antifraud Lab — Build Plan

A self-contained fraud-detection lab running on the home server: a generator that
continuously produces production-like betting and payment traffic (with deliberately
planted fraud patterns), SQL detection rules that hunt for them, an API, and Grafana
dashboards on top.

**Goal:** close the SQL / REST API / Python / CI-CD gaps in one project, and end up
with a fraud story that can be shown and discussed without touching employer data.

---

## Phase 0 — Repo and skeleton

- [ ] New private repo `antifraud-lab`
- [ ] Layout:

```
antifraud-lab/
  docker-compose.yml
  db/migrations/          # 001_schema.sql, 002_indexes.sql ...
  generator/              # python service
  rules/                  # SQL detection queries + runner
  api/                    # fastapi
  grafana/provisioning/   # datasources + dashboards as code
  prometheus/
  .github/workflows/
```

- [ ] Compose services: `postgres`, `generator`, `rules-runner`, `api`, `grafana`, `prometheus`
- [ ] One bridge network, Postgres on a named volume
- [ ] Publish only Grafana and the API to the LAN — nothing else
- [ ] `.env` for credentials and simulation knobs, `.env.example` committed

---

## Phase 1 — Schema

Model it like a real bookmaker back office, not a toy.

### Core tables

| Table | Key columns |
|---|---|
| `players` | id, registered_at, country, currency, status |
| `sessions` | player_id, started_at, ip, device_id, user_agent |
| `payment_methods` | player_id, type (card/crypto/bank), fingerprint (hashed PAN or wallet), last4, added_at |
| `transactions` | player_id, method_id, direction (deposit/withdrawal), amount, currency, status (pending/approved/rejected/chargeback), created_at, processed_at |
| `events` | sport, league, start_time, status |
| `markets` | event_id, type, status |
| `selections` | market_id, name, current_odds |
| `odds_history` | selection_id, odds, changed_at |
| `bets` | player_id, placed_at, stake, total_odds, status |
| `bet_selections` | bet_id, selection_id, odds_at_placement |
| `settlements` | bet_id, result, payout, settled_at |
| `bonuses` | player_id, type, granted_at, wagering_requirement, wagered_amount |

### The two tables that make the project work

| Table | Key columns |
|---|---|
| `alerts` | id, player_id, rule_code, severity, details `jsonb`, window_start, window_end, created_at, status (new/confirmed/false_positive) |
| `fraud_labels` | entity_type, entity_id, pattern_code, injected_at |

`fraud_labels` is the ground truth — the generator records everything it planted.
**Detection rules must never read this table.** It exists only to score the rules
afterwards: precision, recall and F1 per rule, threshold tuning backed by numbers.

### Tasks

- [ ] Write `001_schema.sql`
- [ ] Indexes: `(player_id, created_at)` on transactions, `(player_id, placed_at)` on bets,
      `(fingerprint)` on payment_methods, `(device_id)` on sessions
- [ ] Decide migration tooling — plain numbered `.sql` files applied by an entrypoint script
      is enough; Alembic only if the API grows ORM models

---

## Phase 2 — The generator (main build)

Two modes sharing one code path.

### Backfill

```
python -m generator backfill --days 90 --seed 42
```

90 days of history in a few minutes, written with explicit timestamps. Seeded RNG so the
dataset is reproducible — essential when a rule suddenly behaves differently.

### Live

Long-running loop with a time-compression factor:

```
TICK_SECONDS=1
SIM_MINUTES_PER_TICK=5     # ≈ one simulated hour per 12 real seconds
```

Set it to 1:1 to watch Grafana move in real time.

### Realism, in build order

1. **Daily and weekly shape** — traffic as a sine curve peaking in the evening, weekend
   multiplier. Uniform-random timestamps are the fastest way to ruin a fake dataset.
2. **Event schedule** — fixtures generated a few days ahead; bet volume spikes in the
   30 minutes before kickoff and collapses after. Odds drift between placement and start.
3. **Player archetypes** — casual (small stakes, weekends), regular, high-roller,
   dormant-then-returning. Each with a lifetime and a churn probability. Stakes log-normal,
   not uniform.
4. **Normal noise that looks suspicious** — honest players sharing an IP (household, office
   NAT), legitimate big wins. Without this the rules score 100% and teach nothing.

### Fraud injector

Separate module, per-pattern probabilities in config.

| Pattern | What the generator does |
|---|---|
| Multi-accounting | 3–6 accounts sharing `device_id` or payment fingerprint, registered within days, similar betting |
| Bonus abuse | deposit exactly the bonus minimum, wager the requirement on near-certain low-odds markets, withdraw |
| Matched betting / arb | linked accounts back opposite selections on the same market within minutes |
| Deposit–withdraw passthrough | large deposit, near-zero turnover, withdrawal within the hour, often to a different method |
| Card testing | many small deposits from different fingerprints, one IP, high rejection rate |
| Late betting | bet timestamp after event `start_time`, or against stale odds |
| Stake escalation | weeks of small bets, then a sudden huge one — account takeover |
| Settlement error | payout ≠ stake × odds, or a settled-void bet still paying out |

Build the settlement-error pattern — it is the bridge between this project and real
day-to-day work on bet settlement and payout accuracy.

- [ ] Every injected pattern writes a row to `fraud_labels`

### Tasks

- [ ] Player and session generation
- [ ] Event / market / odds generation with a moving schedule
- [ ] Bet placement and settlement
- [ ] Deposits and withdrawals with realistic approve/reject rates
- [ ] Fraud injector, one pattern at a time
- [ ] Graceful shutdown, structured logging, Prometheus counters (events generated per second)

---

## Phase 3 — Detection in SQL

One `.sql` file per rule, each returning candidate alerts with a stable `rule_code`.
Written with window functions and CTEs on purpose — this is the interview payload.

- [ ] **Deposit velocity** — deposits per player per rolling hour:
      `COUNT(*) OVER (PARTITION BY player_id ORDER BY created_at RANGE BETWEEN INTERVAL '1 hour' PRECEDING AND CURRENT ROW)`
- [ ] **Turnover ratio** — withdrawals ÷ stakes per player per day, flag below 0.1 with
      deposits above a floor
- [ ] **Linked accounts** — self-join `payment_methods` on fingerprint, and `sessions` on
      device_id, having ≥ 2 distinct players
- [ ] **Opposing bets** — self-join `bet_selections` on market where selections differ,
      players are in the same link cluster, and `placed_at` within 10 minutes
- [ ] **Stake anomaly** —
      `stake / AVG(stake) OVER (PARTITION BY player_id ORDER BY placed_at ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING)`
- [ ] **Settlement mismatch** — `ABS(payout - stake * total_odds) > 0.01` on won bets
- [ ] **Late bet** — `bets.placed_at > events.start_time`
- [ ] **Bonus abuse** — wagering completed almost entirely on odds below a threshold

### Rules runner

- [ ] Small service executing the rules on a schedule
- [ ] Upsert into `alerts`, deduped on (player, rule_code, window) so alerts don't spam
- [ ] Expose run duration and rows-flagged as Prometheus metrics

### Scoring

- [ ] One query joining `alerts` to `fraud_labels` → precision, recall, F1 per rule
- [ ] Tune thresholds against that number, record before/after in the README

---

## Phase 4 — API

FastAPI over the same database.

- [ ] `GET /players/{id}/risk` — score plus contributing alerts
- [ ] `GET /alerts?rule_code=&severity=&since=` — paginated, proper 400 / 404 / 422
- [ ] `POST /alerts/{id}/review` — mark confirmed or false positive
- [ ] `POST /transactions` — score a transaction inline, return a decision, honour an
      idempotency key
- [ ] API-key auth via header
- [ ] Postman collection committed alongside: environment variables, auth header, tests
      asserting status codes and response shape

---

## Phase 5 — Grafana

**Postgres datasource — business view**

- [ ] Alerts per hour by rule
- [ ] Top risk players table
- [ ] Precision / recall per rule as stat panels
- [ ] Deposits vs withdrawals over time
- [ ] Flagged share of total volume

**Prometheus datasource — ops view**

- [ ] API latency and error rate
- [ ] Generator events per second
- [ ] Rule-runner duration and lag

- [ ] Provision datasources and dashboards as JSON in the repo, so nothing lives only
      inside Grafana's own database

---

## Phase 6 — CI

GitHub Actions on push:

- [ ] `ruff` lint
- [ ] `pytest` against a `postgres` service container
- [ ] Apply migrations, seed a small dataset, run every rule, assert each one catches its
      planted pattern
- [ ] Build and push images

That test suite is the honest version of "I know CI/CD".

---

## Cut points

Phases 1–3 alone already make a strong SQL and antifraud portfolio piece. The API, Grafana
and CI are additions, not prerequisites. If time runs out, stop after the SQL rules and the
scoring query.

## Open decision before writing code

Does the generator write straight to Postgres, or publish to a queue that a consumer
persists? Straight to Postgres is simpler and is the recommended start. Swapping in Redis
Streams or NATS later is a natural **phase 7** if streaming experience becomes worth
claiming.
