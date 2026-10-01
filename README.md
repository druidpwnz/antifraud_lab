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
| 6 | API — FastAPI | **done** — 12 endpoints, 94 tests, Postman collection |
| 7 | Admin panel — Flask + Jinja + HTMX, over the API | **next** |
| 8 | Compose, for real | not started |
| 9 | Grafana + Prometheus — fraud alerting | not started |
| 10 | CI/CD — GitHub Actions | not started |

Done so far: 14-table schema with constraints that hold, a seeded reproducible
backfill (90 days = 9.7k players, 650k bets, ~10 min), three planted fraud patterns
with ground truth in `fraud_labels`, a live generator that carries on from the
backfill, and `db/tests/invariants.sql` — twelve checks that must hold at any dataset
size, which raise and exit non-zero when they do not.

The API is in [`api/`](api/README.md): read access to players, money, bets and
events, plus idempotent risk checks, with 94 tests and a Postman collection.

---

## Decisions

**1. One web framework or two? — SETTLED.** FastAPI for the API; plain Flask with
Jinja templates and HTMX for the admin panel. Two services, as a real back office
has: the public API and the internal panel are rarely the same app. (Flask-Admin was
the first plan, and was dropped: it generates CRUD screens straight from database
models, which is the opposite of the next decision.)

**2. Does the admin panel touch the database? — SETTLED: no.** The panel is an API
client like any other. It reads through `/v1`, so every rule — auth, validation,
the card fingerprint never leaving — lives in exactly one place, and the panel
proves the API is enough to build a real product on. Where the panel needs
something the API cannot do, the API is extended; the panel never reaches round it.

**3. Alerts before or after the API? — SETTLED: after.** The API ships without alert
endpoints; phase 5 and the alert endpoints come back in a later update.

**4. CI/CD — SETTLED: GitHub Actions.** The repo is already on GitHub, so the
pipeline lives next to the code as workflow files in `.github/workflows/`, versioned
and reviewed like any other file. Postgres runs as a service container, images go to
the GitHub Container Registry (`ghcr.io`) using the workflow's own `GITHUB_TOKEN` —
no second account, no long-lived registry password — and anything secret lives in
GitHub Actions secrets, never in the repo.

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

## Phase 6 — API (done)

FastAPI over the same database, in `api/`. psycopg 3 with raw SQL and a connection
pool, no ORM. No alert endpoints yet — those come back with phase 5.

**How to run it, every endpoint, and the Postman setup: [`api/README.md`](api/README.md).**
This section is the design and the reasons for it.

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

All 12 are built and tested. The full reference — parameters, status codes, what
each returns — is in [`api/README.md`](api/README.md#endpoints).

- [x] `GET /health` (no DB) and `GET /ready` (`SELECT 1`, 503 if the DB is down)
- [x] `GET /v1/players`, `GET /v1/players/{id}`
- [x] `GET /v1/players/{id}/balance`, `/transactions`, `/bets`
- [x] `GET /v1/bets/{id}` — nested legs and settlement
- [x] `GET /v1/events`, `GET /v1/events/{id}` — nested markets and selections
- [x] `POST /v1/risk-checks`, `GET /v1/risk-checks/{id}`

### Build order — one step at a time, reviewed before the next

- [x] 1. Skeleton: settings, pool, `/health`, `/ready`
- [x] 2. Problem+json errors and API-key auth
- [x] 3. Players with cursor pagination
- [x] 4. Player balance, transactions, bets
- [x] 5. Bets and events with nested response models
- [x] 6. Migration 003 and risk checks with idempotency
- [x] 7. Postman collection in `api/postman/`, built alongside each step
- [x] 8. Docs: this section, `api/README.md`

Tests were written with each step, against a separate `antifraud_test` database:
94 in the end, 16 of them for the risk rules alone with no database at all.

**Postman:** `api/postman/`, 24 requests with 38 checks, and a `local` environment
whose `apiKey` is empty in git. Edits made in the app reach git only when exported
back over the JSON. The same collection runs from the command line with Newman,
which is what phase 10 CI will use. The setup problems met along the way —
environment dropdown, the Vault, re-import not replacing — and their fixes are in
[`api/README.md`](api/README.md#problems-we-hit-and-the-fix).

### What was found by testing, not by planning

- `Decimal("0")` serialises as `"0"`, so money got its own type that always has two
  decimals.
- A bet with two settlement rows would appear twice in a list and break paging — so
  the join is `LEFT JOIN LATERAL … LIMIT 1`, and a test proves a plain join fails.
- `HTTPStatus.UNPROCESSABLE_CONTENT` only exists from Python 3.13; the code uses 422.
- Whether FastAPI commits before or after sending the response has changed between
  versions, so the write endpoint commits explicitly before it answers.

**Proof it works:** `/docs` shows every endpoint with its schemas and errors; `pytest`
passes; the Postman collection passes under Newman; and `db/tests/invariants.sql` still passes
after risk checks have run, which shows the API never disturbed generator data.

---

## Phase 7 — Admin panel (next)

A back office for looking into players, their money, bets and matches. Flask renders
Jinja templates; HTMX swaps pieces of the page without a JavaScript framework; every
byte of data comes from the API.

```
browser ──HTML──> Flask panel ──HTTP + X-API-Key──> FastAPI ──> Postgres
```

**The browser never talks to the API.** HTMX requests go to Flask, and Flask calls
the API server-side. The API key lives only in the panel's environment — it never
appears in a page, a cookie or a network request the browser can see.

### What it does

| Page | Uses | API today? |
|---|---|---|
| Players — filter by country/status, load more | `GET /v1/players` | yes |
| Player — balance, transactions, bets in tabs | `/balance`, `/transactions`, `/bets` | yes |
| Player — devices and IPs | `GET /v1/players/{id}/sessions` | **new** |
| Player — linked accounts | `GET /v1/players/{id}/linked` | **new** |
| Bets — every player, newest first, filter by status and stake | `GET /v1/bets` | **new** |
| Bet — legs, match, settlement | `GET /v1/bets/{id}` | yes |
| Events — upcoming, in kickoff order | `GET /v1/events?sort=start_time` | **extended** |
| Event — markets and prices | `GET /v1/events/{id}` | yes |

Deliberately read-only. Running risk checks and a review queue are left for later.

### API extensions (built first, in `api/`, with tests and Postman requests)

- [x] **Scoped API keys, and a real 403.** `API_KEYS` keeps full access (read + create
      risk checks); a new `API_READ_KEYS` is read-only. The panel gets a read key —
      least privilege: a leaked panel key cannot create anything. A read key on
      `POST /v1/risk-checks` is **403**, not 401: "I know who you are, and you may
      not do this". Backward compatible — existing keys keep working.
- [x] **`GET /v1/bets`** — bets across all players, filters `status`, `min_stake`,
      `placed_after`. The admin view of "what is happening now".
- [x] **`order=desc` on lists** — newest first. The cursor records which direction
      it was made for, and a cursor used the wrong way round is a 400.
- [x] **`GET /v1/events?sort=start_time`** — kickoff order. (`sort`, not `order`:
      since step 2 `order` means the direction.) That breaks the simple
      `id > cursor` rule: the cursor must carry `(start_time, id)` and the query
      becomes a row comparison, `(start_time, id) > (%s, %s)`, with an index to
      match — migration `004_events_kickoff_order.sql`.
- [x] **`GET /v1/players/{id}/sessions`** — logins with IP, device and user agent.
- [x] **`GET /v1/players/{id}/linked`** — other players sharing a device or a payment
      method, and which of the two they share. The API compares fingerprints
      *server-side* and returns only the link — so the panel can investigate
      multi-accounting without the fingerprint ever leaving the database.

### How the panel is built

- **Flask app factory** (`create_app()`), one blueprint per area.
- **`api_client.py`** — one `httpx.Client` for the whole app (connection reuse, like
  the API's pool), the key in its default headers, a timeout on every call. It turns
  problem+json into an `ApiError(status, detail)` the views can act on:
  API 404 → panel 404 page; API 401/403 → the panel is misconfigured, logged,
  shown as a 500; API down or timing out → "API unavailable" with a retry.
- **HTMX patterns**, each mapping onto something the API already does:
  - *live filter*: the filter form re-requests the table body on change
  - *load more*: the last row carries `next_cursor` and fetches the next page into
    place — cursor pagination and HTMX fit each other exactly
  - *lazy tabs*: a player's transactions and bets load when the tab is opened
  - one URL, two answers: a normal request gets the full page, an `HX-Request`
    gets only the fragment — every page still works with JavaScript off
- **Login** with Flask-Login. Users come from `ADMIN_USERS` (usernames and password
  hashes — the panel has no database). A `flask hash-password` command makes the
  hashes. Session cookie `HttpOnly` and `SameSite=Lax`, `SECRET_KEY` from env.
- **CSRF** protection on the POST forms (login, logout) with Flask-WTF.
- **Money and time** are shown exactly as the API sends them: money strings are
  never turned into floats, times are shown in UTC.
- **Material Design 3 through [Beer CSS](https://www.beercss.com)** — plain CSS classes,
  no JavaScript build, made for server-rendered pages. Google's own Material Web was
  ruled out: those are JavaScript web components that expect a bundler.
- **htmx, Beer CSS, its icon font and Roboto are vendored** into `static/vendor/`,
  pinned — no CDN, so the panel works offline and nothing third-party loads in an
  admin tool. A strict Content-Security-Policy (`default-src 'self'`, no inline
  scripts or styles, no eval) enforces it, and blocks the CDN fallback Beer CSS has
  in its `@font-face` rules. Roboto is vendored because Beer CSS otherwise uses
  whatever font the viewer has installed — on a machine with only Roboto Bold, every
  word on the page came out bold.

### Layout

```
admin/
  requirements.txt      flask, flask-login, flask-wtf, httpx, pytest
  .env.example          API_URL, API_KEY (a read key), SECRET_KEY, ADMIN_USERS
  app/
    __init__.py         create_app()
    config.py
    api_client.py
    auth.py             login, logout, hash-password
    views/              players, bets, events
    templates/          base, login, one folder per area, partials start with _
    static/             vendor/ (htmx, Beer CSS, Roboto - see its README), app.css
  tests/
```

Run with `flask --app app run --port 5000 --debug` from `admin/`.

### Build order — one step at a time, reviewed before the next

- [x] 1. API: scoped keys and the 403
- [x] 2. API: `GET /v1/bets` and `order=desc`
- [x] 3. API: events in kickoff order (the two-column cursor)
- [x] 4. API: `/players/{id}/sessions` and `/players/{id}/linked`
- [x] 5. Panel skeleton: app factory, config, API client, base template, error pages
- [x] 6. Login
- [x] 7. Players: list with filters and load-more, player page with tabs
- [x] 8. Bets and events pages
- [ ] 9. Docs: `admin/README.md`, this section

### Proof it works

- **API extensions:** pytest and Postman requests, as in phase 6.
- **Panel:** pytest with Flask's test client, and the API replaced by
  `httpx.MockTransport` — so panel tests need no API running and no database. They
  check: every page needs a login; a full page vs an HTMX fragment; load-more passes
  the cursor on; an API 404 becomes a panel 404; an API outage becomes a friendly
  page; **the API key never appears in any HTML the panel returns**.
- **End to end:** API and panel running together over the real generated data.

---

## Phase 8 — Compose, for real

`docker-compose.yml` has been empty since day one, and by now there are four
services that need to talk to each other.

- [ ] `postgres`, `generator` (live mode), `rules-runner`, `api`, `admin`,
      `grafana`, `prometheus`
- [ ] One bridge network, Postgres on a named volume
- [ ] Publish only the API, the admin panel and Grafana to the LAN — the panel
      needs the API on the internal network, never Postgres
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

## Phase 10 — CI/CD with GitHub Actions

Workflows in `.github/workflows/`. Runs on every push and on every pull request to
`main`; a red check blocks the merge.

### CI — prove it works, on every push

- [ ] **lint** — `ruff` over `generator/`, `api/`, `admin/`
- [ ] **generator** — a `postgres` service container; apply every migration, run a
      short backfill (`DAYS=3`), then
      `psql -v ON_ERROR_STOP=1 -f db/tests/invariants.sql` — it already raises on
      failure, so it needs no wrapper script
- [ ] **api** — `pytest` in `api/` against its own `antifraud_test` in the service container
- [ ] **admin** — `pytest` in `admin/`; needs no database or API, they are mocked
- [ ] **end to end** — start the API on the backfilled database, then run the Postman
      collection with Newman. Newman's non-zero exit on any failed check fails the job

### CD — ship it, on `main` only

- [ ] **build and push images** — one per service (generator, api, admin) to
      `ghcr.io`, tagged with the commit SHA and `latest`. Needs the Dockerfiles from
      phase 8, so this job comes after it
- [ ] **deploy** — open question: the home server is not reachable from GitHub's
      runners. Options: a self-hosted runner on the server pulling the new images, or
      a scheduled `docker compose pull && up -d` on the server itself. Decide when
      phase 8 is running

The generator job is the honest version of "I know CI/CD": a pipeline that starts a
real database, generates real data, and asserts something that can actually break.

---

## Housekeeping

- [ ] `CLAUDE.md` was never saved as a file, so its rules are not loaded automatically.
      Decide whether to save it — and if so, record that the API phase ran as
      "Claude writes, I review" rather than its teach-first default
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
