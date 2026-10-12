# Antifraud Lab — Build Plan

A self-contained fraud-detection lab running on the home server: a generator that
produces production-like betting and payment traffic with deliberately planted fraud,
a REST API over it, an admin panel, and Grafana dashboards.

**Goal (revised):** depth in **REST API design**, **Python services**, and **CI/CD**.
Advanced SQL is no longer the target — the rules layer stays deliberately thin.

---

## Quick start

Needs only Docker Engine with the Compose plugin — no Python, no Postgres:

```bash
git clone https://github.com/druidpwnz/antifraud_lab && cd antifraud_lab
cp .env.example .env
docker compose up -d
```

The first `up` builds three images and generates 14 days of history, about a
minute. Then the live generator catches up from 2026-09-01 to *now* — about eight
minutes, longer the later it is — and after that writes new data every five
minutes, never ahead of the real clock.

| What | Where | Login |
|---|---|---|
| Admin panel | http://localhost:5000 | `admin` / `demo-admin-password-change-me` |
| API, interactive docs | http://localhost:8000/docs | **Authorize** with `demo-full-key-change-me` |
| Database | `docker compose exec postgres psql -U antifraud -d antifraud` | — |

From another machine on the LAN, use this machine's address instead of `localhost`.

```bash
docker compose ps                    # everything Up / healthy; migrate and seed Exited (0)
docker compose logs -f generator     # watch it catch up
docker compose down                  # stop, KEEP the data
docker compose down -v               # stop and DELETE the data - the next up starts fresh
git pull && docker compose up -d --build     # after an update
```

**Before anyone but you can reach it,** change the passwords and keys in `.env` —
the demo values are public, in this repo. Do it before the first `up`:
`POSTGRES_PASSWORD` is only used when the database is created, so changing it later
does nothing until `down -v`. A new panel user:
`docker compose exec admin flask --app app hash-password <name>`, the printed line
into `ADMIN_USERS` (in single quotes), then `docker compose up -d`.

**After `git pull`,** compare `.env.example` with your `.env`
(`diff .env.example .env`): new variables are not copied over by themselves, and
compose refuses to start without them.

Developing without Docker — venv, local Postgres, `uvicorn --reload`, `flask run` —
is in the service READMEs: [`api/`](api/README.md), [`admin/`](admin/README.md),
[`db/`](db/README.md).

---

## Status

| Phase | What | State |
|---|---|---|
| 0 | Repo, skeleton, compose | **done** — compose in phase 8 |
| 1 | Schema — 14 tables + `sim_state` | **done** |
| 2 | Backfill generator | **done** |
| 3 | Fraud injector | **3 patterns done** |
| 4 | Live generator | **done** (no metrics yet) |
| 5 | Thin alerting (fills `alerts`) | **part of phase 9** — its first steps |
| 6 | API — FastAPI | **done** — 15 endpoints, 140 tests, Postman collection |
| 7 | Admin panel — Flask + Jinja + HTMX, over the API | **done** — players, bets, events; 140 tests |
| 8 | Compose, for real | **done** — one `docker compose up -d`, six services |
| 9 | Detection rules, Prometheus, Grafana — fraud alerting | **next** — planned |
| 10 | CI/CD — GitHub Actions | not started |

Done so far: 14-table schema with constraints that hold, a seeded reproducible
backfill (90 days = 9.7k players, 650k bets, ~10 min), three planted fraud patterns
with ground truth in `fraud_labels`, a live generator that carries on from the
backfill, and `db/tests/invariants.sql` — twelve checks that must hold at any dataset
size, which raise and exit non-zero when they do not.

The API is in [`api/`](api/README.md): read access to players, money, bets and
events, plus idempotent risk checks, with 140 tests and a Postman collection.

The admin panel is in [`admin/`](admin/README.md): a read-only back office over the
API — players with their money, logins and linked accounts, every bet, every match —
with a login, 140 tests and the API key kept out of the browser.

All of it runs with one `docker compose up -d` — see [Quick start](#quick-start).

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
CATCH_UP=1                     # behind the real clock: run flat out until it is not
REAL_SECONDS_PER_SIM_HOUR=12   # behind, with CATCH_UP=0: one sim day per 5 minutes
```

      **Never ahead of the real clock** — found in phase 8, when the panel showed
      bets settled five days in the future: once caught up, the loop went on at
      12 s per simulated hour, 300× real time, and nothing stopped it at *now*.
      Now a step is generated only once it has ended in the real world.

      Steps first went in whole simulated hours rather than the 5-minute ticks
      originally planned — that way live and backfill shared `tick.one_hour()`
      exactly, instead of two loops that could drift apart. Once the generator
      stopped at *now*, that meant a block of data once an hour, so the 5-minute
      ticks came back after all, still one function for both — see below.

- [x] Rebuild in-memory state from the database at startup — `state.load()`. Verified
      against the backfill's own in-memory state: 1526 players, zero mismatches on
      every field, balances exact to the cent
- [x] **The rule that made this possible:** anything the live generator needs is
      either in a table or derivable from (seed, row id). Archetypes, event goal
      probabilities and withdrawal due times are all derived; nothing lives only in
      a Python variable
- [x] Graceful shutdown (SIGTERM/SIGINT): finishes the tick, commits, exits
- [ ] Structured logging (plain prints for now)
- [ ] Prometheus counters: rows written per second, sim lag behind wall clock

**The thing to watch:** the handoff. Nothing should look different in the data on
either side of `sim_state.sim_time`. Run `db/tests/invariants.sql` after the live
generator has been going for a while — every check must still pass. (Done: it does,
across 134k bets written by two processes.)

### 5-minute ticks (done)

**The problem:** the live generator may not write the future, so it writes each
simulated hour once that hour has ended — and the panel, and phase 9's graphs, get a
block of data once an hour and nothing in between. Shorter steps make it arrive every
five minutes, never more than ten minutes old.

**The approach:** the step itself gets shorter — `tick.one_tick()` instead of
`tick.one_hour()`, still the one code path for backfill and live. Two other ways were
considered and dropped: generating the hour ahead and releasing its rows as their
timestamps pass (every `INSERT` would need a buffer, and the generator reads its own
writes — odds, ids, balances — so a crash halfway through an hour leaves rows that
are hard to undo), and keeping sessions an hour long across many small ticks (each
player's half-finished session would have to survive between ticks and restarts).

#### Decisions

| Topic | Decision | Why |
|---|---|---|
| Tick length | `TICK_MINUTES = 5` in `config.py`, must divide 60. Not an environment variable | The tick is part of what the dataset *is*: same seed + same tick = same data |
| Rates | Counts per hour (new players) are scaled by the tick: a Poisson mean × 5/60. Chances per hour (logging in, an odds move) become the chance per tick that gives the same per hour: `1 - (1 - p) ** (5/60)` | An hour holds as many registrations, logins and odds moves as before |
| Sessions | A session starts at any second of its tick and may run on into the next one, but is over by that one's end. Its actions are 10–45 s apart (were 20–900 s), so it lasts a few minutes. Per-session numbers — bets per session, deposit chance, the fraud rates — stay as they are | Starting only early in the tick (the first version) left the last minutes of every tick empty — a 5-minute sawtooth in any per-minute graph. A few-minute visit is what mobile betting looks like anyway |
| The work at the start of a step | Approving withdrawals, finishing matches and paying bets run every tick | A match is settled within 5 minutes of its end instead of up to an hour |
| Paying bets | `settle_bets` runs only in a tick where `finish_events` finished a match | It is the biggest cost that repeats every step — its query is 12 s of the 46 s backfill — and without a finished match it cannot find anything new |
| Fixtures | Created in the midnight tick, as now | — |
| Live pace | Writes a tick once the tick *after* it has ended too — when every session it starts is over — so the newest data is 5–10 minutes old. `REAL_SECONDS_PER_SIM_HOUR` keeps its meaning (12 s per simulated hour = 1 s per tick) | Nothing in the future, and no rhythm in the timestamps. The `.env` stays as it is |
| Restarts | A player's clock resumes at the end of their last session, not at `sim_time` | A session can now end after `sim_time`; resuming at `sim_time` could start a second, overlapping session |
| The dataset | Changes: new ids, so the Postman variables and the example ids in the READMEs are checked again. Still deterministic — two fresh seeds stay identical | Unavoidable: a different step draws the random numbers in a different order |

#### Traps to plan for

- **Everything in a session must end inside its window** — its tick and the next
  one. Today a payment method is added 30–300 s after registering and a deposit is
  processed up to 10 minutes after it is made — too long for that. Every delay
  inside a session shrinks, and a check after the change asserts that no row is
  later than its window, and that no player has two sessions at once.
- **An ordinary bet must never be placed after kickoff** — every late bet is
  planted, and an invariant checks it. With sessions running on into the next tick,
  bets are only offered on matches starting after the *session's* limit, not the
  tick's end.
- **`odds_history` has `UNIQUE (selection_id, changed_at)`.** At most one move per
  selection per tick, at second 1 or later — second 0 of midnight belongs to fixture
  creation, as now.
- **Twelve times as many steps.** Every per-step query runs 12× as often. Measured
  before the change: the 14-day backfill takes 46 s; the target is under 2 minutes,
  and the five-week catch-up not much over its ten minutes.
- **An existing database is hourly.** The live generator can carry on from one (an
  hour boundary is a tick boundary), but its history keeps the old shape — `docker
  compose down -v` for a consistent dataset.

#### Build order — one step at a time, reviewed before the next

- [x] 1. Baseline: on a throwaway stack, the current code's `profile.sql`, fraud
      labels per pattern, bets per session and backfill time — saved to compare with
- [x] 2. `TICK_MINUTES`, `tick.one_tick()`, every module taking the tick's start and
      end instead of an hour, the shorter session timings, and the backfill loop
- [x] 3. Compare with the baseline: invariants 12/12, no row outside its session's
      window, no overlapping sessions, two seeds identical table by table, backfill
      31 s → 48 s. Registrations, sessions and odds moves per hour stay as they were
      — but bets are up 28% (see below). Found in review: the first version started
      every session in its tick's first 2 minutes, so minutes 3–4 of every tick had
      no logins or sign-ups at all; now each minute of a tick gets a fifth of
      everything

      | 14-day backfill | hourly | 5-minute |
      |---|---|---|
      | players / sessions | 1544 / 9612 | 1567 / 10004 |
      | bets / bets per session | 15978 / 1.66 | 20458 / 2.05 |
      | deposits / withdrawals | 4203 / 1053 | 4797 / 1346 |
      | odds moves | 9544 | 10324 |
      | session length, average | 23.8 min | 2.8 min |
      | plants: late bet / settlement error / stake escalation | 19 / 78 / 30 | 37 / 78 / 51 |

      **Why more bets:** the hourly sessions were cut short. A session started up to
      :50, its actions were 20–900 s apart, and an action that fell past the end of
      the hour was dropped — so a high-roller's "3–6 bets per session" often came
      out as one or two. The short sessions fit, and `bets_per_session` now means
      what it says. The shape of the day is unchanged; every hour has about 28% more.
- [x] 4. `live.py`: waits for each tick; checked running — the tick 17:55–18:00 was
      written at 18:05:00, its newest row 18:04:32; a restart in the middle of the
      catch-up resumed at the next tick with no overlapping sessions; stop during
      the wait in under a second; catch-up from 2026-09-01 in 8 minutes (was ~10 —
      paying bets only after a finished match more than makes up for 12× the ticks)
- [x] 5. The new dataset's fallout: `linkedPlayerId` 11 → 32 (player 11 has no
      links any more), the panel README's example bets → 654, 525, 771 (one warning
      each) and event → 29 (482 no longer exists). Newman: 36 requests, 60
      assertions, 0 failed. The API and panel test suites do not depend on generated
      data — the API's write their own rows into `antifraud_test`, the panel's mock
      the API — so they cannot change
- [x] 6. Docs: this section, `GENERATOR_BACKFILL.md` (a note on top: it is the
      original hourly build plan), `FRAUD_PATTERNS.md` (rates per session, the stake
      escalation numbers measured again: 40 of 51 plants are smaller than the 20th
      biggest honest bet), the quick start, the comments in `docker-compose.yml`
      and `.env.example`

---

## Phase 5 — Thin alerting (postponed until after the API)

**Now part of [phase 9](#phase-9--detection-prometheus-grafana-where-fraud-becomes-an-alert-next),
as its first steps.** The plan below is what it grew from.

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

## Phase 7 — Admin panel (done)

A back office for looking into players, their money, bets and matches. Flask renders
Jinja templates; HTMX swaps pieces of the page without a JavaScript framework; every
byte of data comes from the API.

```
browser ──HTML──> Flask panel ──HTTP + X-API-Key──> FastAPI ──> Postgres
```

**How to run it, every page, and the problems met: [`admin/README.md`](admin/README.md).**
This section is the design and the reasons for it.

**The browser never talks to the API.** HTMX requests go to Flask, and Flask calls
the API server-side. The API key lives only in the panel's environment — it never
appears in a page, a cookie or a network request the browser can see.

### What it does

| Page | Uses | API before phase 7 |
|---|---|---|
| Players — filter by country/status, load more | `GET /v1/players` | yes |
| Player — balance, transactions, bets in tabs | `/balance`, `/transactions`, `/bets` | yes |
| Player — devices and IPs | `GET /v1/players/{id}/sessions` | **added** |
| Player — linked accounts | `GET /v1/players/{id}/linked` | **added** |
| Bets — every player, newest first, filter by status and stake | `GET /v1/bets` | **added** |
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
  - *server-rendered tabs*: a tab is a link (`?tab=bets`); htmx swaps the tab bar
    and its table together, so the server decides which tab is active, and the URL
    makes Back, reload and bookmarks land on the right tab
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
  requirements.txt      flask, flask-login, flask-wtf, httpx, python-dotenv, gunicorn
  requirements-dev.txt  that, plus pytest
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
- [x] 9. Docs: `admin/README.md`, this section

### Proof it works

- **API extensions:** pytest and Postman requests, as in phase 6.
- **Panel:** pytest with Flask's test client, and the API replaced by
  `httpx.MockTransport` — so panel tests need no API running and no database. They
  check: every page needs a login; a full page vs an HTMX fragment; load-more passes
  the cursor on; an API 404 becomes a panel 404; an API outage becomes a friendly
  page; **the API key never appears in any HTML the panel returns**.
- **End to end:** API and panel running together over the real generated data,
  driven in Chromium by Playwright: filters, load more with no duplicate rows, tabs,
  Back, phone width, and no console or CSP errors.

140 panel tests in the end. The API grew from 12 endpoints to 15 and from 94 tests to
140; the Postman collection to 36 requests with 60 checks.

### What was found by testing, not by planning

- **The Back button.** When htmx no longer has a page in its history cache, it asks
  the server again and replaces the *whole* page with the answer. "One URL, two
  answers" would have sent a fragment there; the panel now recognises that request
  (`HX-History-Restore-Request`) and sends the full page.
- **Enter in a filter field sent two requests** — the field's `change` and the
  form's native submit. Selects now trigger on change and text fields on submit.
  The first fix used a trigger selector with a space, which htmx's parser rejects —
  in the browser only, with every pytest green; a test now pins the string.
- **`when()` relabelled instead of converting:** a `+02:00` time was shown as UTC.
  The API only sends `Z`, so nothing showed — until a test with an offset.
- **Comparing ISO times as strings is wrong** once fractional seconds appear
  (`"…00.5Z"` sorts before `"…00Z"`); the late-bet warning parses them.
- **Beer CSS layout rules** — `<header>` moved to the top centre, `no-margin`
  children removing a card's padding, `nav > ul` styled as a menu — only showed up in
  screenshots. They are listed in `admin/README.md`.
- **Fonts and CSP.** A machine with only Roboto Bold made every word bold (Roboto is
  now vendored), and Beer CSS's CDN font fallback put four CSP errors on every page
  (removed from the vendored file).

---

## Phase 8 — Compose, for real (done)

**The goal:** on any machine with Docker, a fresh clone comes up with one copy and
one command, and nothing else installed — no Python, no Postgres:

```bash
git clone https://github.com/druidpwnz/antifraud_lab && cd antifraud_lab
cp .env.example .env
docker compose up -d
```

A few minutes later the database is created and migrated, 14 days of history are
generated, the live generator is ticking, and the API (`:8000`) and the panel
(`:5000`) answer on the LAN. `docker compose down` stops it and keeps the data;
`docker compose down -v` throws the data away, like `reset.sh` + backfill.

Local development stays as it is — venv, local Postgres, `flask run`, `uvicorn
--reload`. Compose is how the whole thing *runs*; nothing in it replaces the
dev loop.

### What runs

| Service | Image | Runs | Networks | Published |
|---|---|---|---|---|
| `postgres` | `postgres:18` | always | `db` | — |
| `migrate` | `antifraud/generator` | once per `up`, applies new migrations, exits | `db` | — |
| `seed` | `antifraud/generator` | once per `up`; backfills only an empty database | `db` | — |
| `generator` | `antifraud/generator` | always — the live generator | `db` | — |
| `api` | `antifraud/api` | always, uvicorn | `db`, `web` | `API_PORT`, 8000 |
| `admin` | `antifraud/admin` | always, gunicorn with 2 workers | `web` | `PANEL_PORT`, 5000 |

```
  ┌─ network db (internal: no way out) ──┐
  │  postgres <── migrate, seed,         │
  │     ^         generator              │
  │     └──────── api ───────────────────┼── network web ── admin
  └───────────────┼──────────────────────┘                    │
                :8000                                       :5000
```

### Decisions

| Topic | Decision | Why |
|---|---|---|
| Engine | Docker Engine + the Compose plugin (`docker compose`), Podman removed from this machine | The same tool GitHub Actions runs in phase 10. The compose file stays standard, so Podman could still read it elsewhere |
| Config | Root `.env.example` committed, filled with working demo values; `.env` uncommitted. Required values are `${VAR:?…}` in compose, so a missing one stops `up` with a message instead of starting half-configured | One copy step is the whole setup, and real secrets are never in git |
| Database user | One user, the owner, shared by the generator and the API — as locally | Simplest; a separate limited role for the API can come later |
| Connection settings | Services get `PGHOST`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`; libpq reads them by itself | No password inside a URL, so a password with `@` or `/` cannot break it. The generator's hard-coded `dbname=antifraud` becomes `DATABASE_URL` from env, defaulting to today's value |
| Images | One per Python service, built from this repo: `python:3.14-slim`, non-root user, runtime requirements only, `.dockerignore` | Small, and the same images phase 10 pushes to `ghcr.io` |
| One generator image, three jobs | `migrate`, `seed` and `generator` all run the generator image with a different command | They all need Python + psycopg + this repo's SQL; three images would be three copies |
| Start-up order | `postgres` healthy → `migrate` completes → `seed` completes → `generator`; the API waits for `migrate`; the panel waits for a healthy API | `depends_on` with `service_healthy` / `service_completed_successfully` — a plain `depends_on` only waits for a container to *start*, not for Postgres to accept connections |
| Migrations | `db/migrate.py`: applies each `db/migrations/*.sql` not yet recorded in a `schema_migrations` table, in order, one transaction each | Postgres's `/docker-entrypoint-initdb.d` only runs on an *empty* volume — migration 005 would never reach an existing one |
| Seeding | `seed` runs the backfill only when `sim_state` is empty, and exits 0 when it is already done | `up` after `down` must not fail or regenerate. Players present but no `sim_state` means a backfill died half-way: `seed` fails loudly and says to run `down -v` |
| Panel server | gunicorn, not `flask run` (a development server) | With several workers, `SECRET_KEY` *must* be fixed: a random key per worker would make every other request look logged out — another reason it is required |
| Networks | `db`: postgres, migrate, seed, generator, api. `web`: api, admin | The panel is not on the database network at all, so decision 2 — the panel never touches Postgres — is enforced by the network, not just by the code |
| Ports | Publish only the API and the panel, ports set in `.env`. Postgres is not published; `docker compose exec postgres psql` instead | Nothing on the LAN can reach the database |
| Postgres | `postgres:18` (as locally), named volume, healthcheck `pg_isready` | — |
| Health | `pg_isready`; the API's `/ready` (Python's urllib — the slim image has no curl); a new `/health` on the panel that needs no login and no API | Compose waits on these, and `docker compose ps` shows them |
| Stopping | Exec-form `CMD` so Python is PID 1 and gets SIGTERM; `stop_grace_period` long enough for the generator to finish its step | `live.py` already finishes the step and commits on SIGTERM — this lets it |
| Restarts | `unless-stopped` for long-running services, none for `migrate` and `seed` | A one-shot that restarts would run forever |

### Traps to plan for

- **postgres:18 moved its data directory.** The volume mounts at
  `/var/lib/postgresql`, not `/var/lib/postgresql/data` as in every older guide;
  mounted the old way, the data is not where the volume is.
- **`pg_isready` says ready too early.** On the first start the image runs a
  temporary server, socket only, to create the database — and `pg_isready` over the
  socket is happy with it, before the database exists (seen in step 2). The
  healthcheck asks over TCP, `pg_isready -h 127.0.0.1`, which only the real server
  answers.
- **`$` in `.env`.** Compose expands `$name` in `.env` values, and a password hash
  is full of `$`. `ADMIN_USERS` goes in single quotes, which compose leaves alone.
- **Docker publishes ports past firewalld.** It writes its own firewall rules, so a
  published port is reachable from the LAN whatever the firewalld zone says. What is
  published is decided in compose, nowhere else.
- **The clock keeps moving.** The backfill ends on a fixed date (2026-09-01) and the
  live generator catches up to *now* before it slows down. On a fresh machine that is
  five weeks of simulated hours — about ten minutes in step 4, slower than expected
  because each hour has more players than the last — and months from now it is
  longer and the dataset bigger. The API and panel work while it catches up.
  `CATCH_UP=0` catches up slowly instead, one simulated hour every 12 s. Either
  way it stops at *now*: after that each 5-minute tick is written once its sessions
  are over in the real world (it used to carry on at 300× real time into the
  future — fixed in phase 8).
- **The first `up -d` waits for the seed.** The generator depends on the seed having
  *finished*, so `docker compose up -d` only returns after the backfill — about
  half a minute — not at once.
- **A reboot ignores `depends_on`.** Docker restarts `unless-stopped` containers by
  itself, in no particular order, and does not run `migrate` or `seed`. A generator
  that starts before Postgres crashes and is restarted with a growing back-off until
  Postgres is up — seen in step 4, and harmless: each step of the live generator
  is one transaction, so an interrupted step is rolled back and redone.
- **`exec` and a local file.** `docker compose exec postgres psql -f db/tests/…`
  looks for the file *inside* the container. Feed it on stdin instead:
  `docker compose exec -T postgres psql -U antifraud -d antifraud < db/tests/invariants.sql`
  (`-T`: no terminal, so stdin can be a file).
- **A local database can be older than the code.** Step 3 found the local
  `antifraud` differs from a fresh seed from the first days on: it was generated
  before later generator tuning. Ids picked from it (example bets, Postman
  variables) do not exist in a fresh dataset. Regenerate locally after generator
  changes: `bash reset.sh && (cd generator && python backfill.py)`.
- **An old `.env` after an update.** `.env` is a copy, so it does not get the
  variables a newer `.env.example` adds — and every `${VAR:?}` then stops compose,
  even `docker compose ps`, naming the missing variable. Seen in step 5: copy it
  again (or add the new lines by hand). The data is in the volume, not in `.env`,
  so nothing is lost — as long as the `POSTGRES_*` values stay the same.
- **`hash-password` needs a terminal.** It asks for the password twice, hidden.
  `docker compose exec admin flask --app app hash-password <name>` gives it one;
  with `-T` or a pipe it aborts unless both lines come on stdin.
- **Two copies on one machine are one project.** `name: antifraud` is fixed, so
  `docker compose up -d` in a second clone does not start a second lab — it takes
  over the first one's containers and its `antifraud_pgdata` volume. To run a
  second copy beside the first, give it its own name and ports:
  `docker compose -p afproof up -d`, with `API_PORT` / `PANEL_PORT` changed in its
  `.env` (how step 6 ran).
- **`POSTGRES_PASSWORD` only counts once.** The image uses it when it creates the
  database, on an empty volume. Change it in `.env` afterwards and Postgres keeps
  the old one while the services start sending the new one — every connection
  fails. Set it before the first `up`; later, `down -v` (losing the data) or
  `ALTER USER` in `psql` first.
- **`restart` does not read `.env`.** `docker compose restart` restarts the same
  container with the same settings; `docker compose up -d` is what notices a
  changed `.env` and recreates just the services it affects.
- **The `docker` group is root.** Adding yourself to it means `docker` without `sudo`
  — and anything able to run `docker` can become root on the machine.

### Layout

```
docker-compose.yml        postgres, migrate, seed, generator, api, admin
.env.example              every variable compose uses, with demo values
db/migrate.py             the migration runner
generator/Dockerfile      also runs migrate and seed
generator/requirements.txt
api/Dockerfile
admin/Dockerfile
*/requirements-dev.txt    runtime requirements + pytest - what the venv installs
.dockerignore
```

Phase 9 adds `prometheus` and `grafana` to the same file; the rules runner comes
with phase 5.

### Build order — one step at a time, reviewed before the next

- [x] 1. Install Docker Engine + the Compose plugin, remove Podman — Docker 29.8, Compose 5.6
- [x] 2. Ready the code for containers: `DATABASE_URL` in the generator, requirements
      split into runtime and dev, `/health` on the panel, a re-runnable seed, and
      `db/migrate.py`
- [x] 3. Dockerfiles and `.dockerignore`; each image builds and starts — run by hand
      on a throwaway network: migrate, seed, live, API, panel; login through gunicorn's
      two workers; every container stops in under a second on SIGTERM
- [x] 4. Compose, data half: `postgres`, `migrate`, `seed`, `generator` — and
      `invariants.sql` passes inside it. Also checked: restart resumes with no gap,
      `down`/`up` keeps the data and the seed skips, the `db` network has no way out,
      and the generator survives Postgres disappearing under it
- [x] 5. Compose, web half: `api`, `admin`, networks, ports, healthchecks, `.env.example`
      — the API and the panel are healthy before the seed has finished; the panel's
      key is added to the API's read keys by compose, so they cannot drift apart
      (it reads, and a POST with it is 403); login holds across gunicorn's two
      workers; the panel container cannot even resolve `postgres`; with Postgres
      stopped `/ready` is 503 and the panel 503, and both recover by themselves
- [x] 6. Proof on a clean clone — every line of *Proof it works* below passed on a
      clone built with `--no-cache --pull` (61 s to all healthy). Newman found the
      one thing a fresh dataset breaks: `linkedPlayerId` was 5, picked from the old
      local database, and player 5 has no links on a fresh seed — now 11 (32 since
      the 5-minute ticks)
- [x] 7. Docs: a quick start at the top of this README, this section, the service READMEs

### Proof it works

- From a fresh `git clone` in another folder — so nothing untracked can help:
  `cp .env.example .env && docker compose up -d`, then `docker compose ps` shows
  every long-running service healthy and `migrate` / `seed` exited 0.
- The Postman collection passes under Newman against the compose API — 36
  requests, 60 assertions — while the generator is still catching up. The seed is
  deterministic — two fresh backfills are identical, table by table (checked in step
  3) — so a local database regenerated with the current code has the same ids.
- `invariants.sql`, run with `docker compose exec`, passes all twelve checks.
- The panel logs in with the demo user from `.env.example`, and shows data.
- `docker compose restart generator`: it resumes from `sim_state`, no gap, no repeat.
- `docker compose down && docker compose up -d`: same data, `seed` skips.
- `docker compose down -v && docker compose up -d`: a fresh dataset, same ids — the
  backfilled bets have the same fingerprint (md5 over id, player, stake, time) before and after.
- The panel container cannot reach Postgres at all (`db` network only).

### What was found by testing, not by planning

- `pg_isready` over the socket said "ready" while the first-start temporary server
  was still creating the database — the healthcheck asks over TCP (step 2).
- The local database was older than the generator code, so ids picked from it were
  wrong for a fresh seed; Newman caught `linkedPlayerId` (step 6).
- **The live generator ran into the future.** Once caught up it carried on at 300×
  real time; the panel showed bets settled five days ahead. It now waits for each
  step to end in the real world — an hour then, five minutes since the 5-minute
  ticks.
- An `.env` copied before an update lacks the new variables, and compose refuses to
  start at all — even `ps` (step 5).
- A second clone on the same machine is the *same* project, because the name is
  fixed — it would take over the first one's containers and data (step 6).
- Catching up five weeks took about ten minutes, not two and a half: every hour has
  more players than the last (step 4).

---

## Phase 9 — Detection, Prometheus, Grafana: where fraud becomes an alert (next)

**The goal:** planted fraud is found by simple rules, shows up on Grafana dashboards
within minutes, and fires alerts — and the whole lab is watched: a stopped generator,
a stuck rules runner or a failing API fires an alert too. Still one `docker compose
up -d`.

Phase 5, postponed until after the API, is the first part of this phase: without
rules nothing fills `alerts`, and the fraud dashboards and alerts would have nothing
to show.

```
 generator ──writes──>  postgres  <──reads── api
                        ^      ^
 rules ─reads, writes───┘      └──reads (read-only user)── grafana
        into alerts                                          │ dashboards,
                                                             │ alert rules
 generator, api, rules ──/metrics──> prometheus <──queries───┘
```

### Decisions

| Topic | Decision | Why |
|---|---|---|
| Rules | A new `rules` service: Python, one plain `.sql` file per rule in `rules/sql/`, run every minute, inserting into `alerts` with `ON CONFLICT DO NOTHING` on the existing `UNIQUE (player_id, rule_code, window_start, window_end)` | The obvious query, not a clever one — the budget is an evening per rule, not a week. A rule in its own file can be read, run in `psql` and diffed |
| First rules | One per planted pattern: `SETTLEMENT_MISMATCH`, `LATE_BET`, `STAKE_ANOMALY` | Something to score against `fraud_labels` from day one |
| What has been checked | A `rule_state` table (migration 005): per rule, the highest row id it has looked at. Each run reads only newer rows | Ids only grow. A timestamp would not do: the generator writes 5–10 minutes behind its own clock, and a settlement is backdated to the match |
| Ground truth | Rules never read `fraud_labels`. Scoring does — `db/scoring.sql` and the *Scoring* dashboard join `alerts` to it for precision and recall per rule | A dashboard is not a detection rule. Scoring is what makes the alerts believable |
| Metrics | `prometheus_client` in the generator, the API and the rules runner, each on its own port **9100, never published** — Prometheus reaches them over the compose networks | `/metrics` stays off the LAN, and the API's public port serves only the API |
| Labels | Only small fixed sets: `rule_code`, `severity`, `table`, HTTP method, **route template** (`/v1/players/{player_id}`), status. Never `player_id`, `bet_id`, a raw path | Every label value makes a new time series; ids would make millions and take Prometheus down |
| Alerting | All alert rules are **Grafana-managed**, on two datasources: per-entity ones on Postgres ("player 532: wrong payout"), aggregate ones on Prometheus ("LATE_BET detections dropped to zero"). No Alertmanager | One place to see and silence alerts. Telegram later is one contact point, not a second system |
| Notifications | None yet: alerts fire and show in Grafana's UI | Telegram comes later — then a bot token in `.env` and one provisioned contact point |
| Grafana's database access | A read-only Postgres role `grafana_reader`, `SELECT` only, set up by `db/migrate.py` when `GRAFANA_DB_PASSWORD` is set — role, password and grants, on every run. Not in a migration | Grafana's query editor runs any SQL it is given. With the owner's login, a typo could `DELETE` data. A role belongs to the whole server, and a local database owner may not create one |
| Provisioning | Datasources, dashboards (JSON) and alert rules (YAML) are files in `grafana/`, loaded at start-up | Nothing lives only inside Grafana's database; a fresh clone gets the same dashboards. Edit in the UI, export over the file, commit — like the Postman collection |
| Images | `prom/prometheus` and `grafana/grafana-oss`, exact versions pinned | Same reason as `postgres:18` — an upgrade is a decision, not a surprise |
| Ports | Grafana published on `GRAFANA_PORT` (3000), Prometheus on `PROMETHEUS_PORT` (9090), both from `.env`. Grafana's admin password in `.env` | The Prometheus UI (targets, raw queries) is worth having in a lab |
| Storage | Volumes `prometheus-data` (30 days of metrics) and `grafana-data` | Metrics survive `down`; `down -v` clears them with everything else |
| Networks | `rules`, Prometheus and Grafana on `db`; Prometheus and Grafana also on `web` (published ports; Telegram later needs the internet) | The admin panel still cannot reach Postgres |
| Not in this phase | Alerts in the API and the panel, and reviewing them (`new` → `confirmed` / `false_positive`) | A phase of its own — an API resource, a panel page and the review write. Until then every alert stays `new` |

### The first rules

| Rule | Finds | Severity | Expected |
|---|---|---|---|
| `SETTLEMENT_MISMATCH` | `ABS(payout - stake * total_odds) > 0.01 WHERE result = 'won'` — written the obvious way on purpose | high | Precision 1.0, recall about 0.33 — `lost_bet_paid` is invisible to it (see `generator/FRAUD_PATTERNS.md`) |
| `LATE_BET` | `bets.placed_at > events.start_time` on any leg | high | Precision and recall 1.0 — the baseline is clean |
| `STAKE_ANOMALY` | A stake at least 8× the player's average over their previous 50 bets, with at least 15 before it | medium | High recall; precision below 1 — honest high-rollers sometimes do this too |

Then the learning loop, as a step of its own: the *Scoring* dashboard shows
`SETTLEMENT_MISMATCH` missing two thirds, the rule is fixed to cover losing bets
that were paid, and recall goes to 1.0 on the next run.

### Alerts

| Alert | Datasource | Fires when |
|---|---|---|
| High-severity detection | Postgres | a new `high` or `critical` row in `alerts` — names the player |
| Big payout mismatch | Postgres | a `SETTLEMENT_MISMATCH` over a money threshold |
| Shared device | Postgres | a device gains a third distinct player (households make two common) |
| Detection rate shift | Prometheus | a rule's detections per hour double, or drop to zero, against the day before |
| Rules runner stale | Prometheus | no successful run for 10 minutes |
| Generator behind | Prometheus | the simulated clock more than 20 minutes behind the real one (5–10 is normal) |
| API errors / latency | Prometheus | 5xx above 1% of requests, or p99 above 1 s, for 5 minutes |

### Dashboards

- *Fraud*: detections per hour by rule, the players with the most alerts, flagged
  share of bets
- *Scoring*: planted vs detected vs missed per pattern, precision and recall
- *Money*: deposits vs withdrawals, turnover, the house margin over time
- *Ops*: API request rate, errors and latency by route; generator rows per second and
  lag; rules runner duration and last success

### Traps to plan for

- **Route, not path.** A label taken from the raw URL — `/v1/players/532` — is one
  series per player. The API's metrics label requests by FastAPI's route template.
- **Counters restart at zero** whenever a container restarts. Graphs and alerts use
  `rate()` / `increase()`, which handle that; a raw counter value means nothing.
- **Two clocks, again.** Dashboards on Postgres plot *simulated* time
  (`placed_at`), dashboards on Prometheus plot *real* time. Once the generator has
  caught up they agree within 10 minutes; during the catch-up they do not.
- **The first rules run scans everything** — 14 days of backfill plus the catch-up.
  `rule_state` makes the next run cheap; the first one is measured.
- **Grafana runs as uid 472.** A bind-mounted data folder owned by someone else
  stops it at start-up; a named volume avoids that.
- **Provisioned dashboards are read-only in the UI.** Changes are made, exported and
  committed — or they vanish at the next restart.
- **"No data" is not "OK".** An alert over a stopped service gets no data at all;
  each alert says what no data means (for *rules runner stale*, it means firing).
- **Inside the Postgres container nothing checks a password.** The official image
  trusts connections from `127.0.0.1` and the socket, so `docker compose exec
  postgres psql -U grafana_reader` gets in with any password, or none — found in
  step 1, when an old password still "worked". Logins are tested from another
  container, over the network, the way Grafana connects.
- **A metrics server in the API process** works with one uvicorn worker, which is
  what runs today. More workers would need `prometheus_client`'s multiprocess mode.

### Layout

```
rules/
  Dockerfile  requirements.txt
  runner.py               every minute: each rule, from its rule_state, into alerts
  sql/*.sql               one rule per file
  tests/                  each rule finds its shape in hand-made rows, and not an honest one
db/migrations/005_rules.sql   rule_state
db/scoring.sql            precision and recall per rule
prometheus/prometheus.yml scrape jobs
grafana/provisioning/     datasources, dashboard provider, alert rules
grafana/dashboards/*.json
```

### Build order — one step at a time, reviewed before the next

- [x] 1. Migration 005 (`rule_state`), and `migrate` setting up `grafana_reader` from
      `.env` on every run — checked: the reader reads every table and cannot insert,
      update, delete or create; a changed password works at the next run and the old
      one is refused; a second database on the same server migrates too. Found by
      running it locally: the role was first in the migration, and a local database
      owner may not create roles — `permission denied to create role`. A role is
      server-wide, so it moved to the runner, which only does it under compose
- [ ] 2. The rules runner and the three rules, with tests; `db/scoring.sql`; the
      `rules` service in compose — `alerts` fills, scoring prints numbers
- [ ] 3. Metrics in the generator, the API and the rules runner, with tests that
      the labels stay small
- [ ] 4. Prometheus in compose — every target `UP`
- [ ] 5. Grafana in compose, datasources provisioned — Explore answers from both
- [ ] 6. Dashboards: *Ops*, *Fraud*, *Scoring*, *Money*
- [ ] 7. Alert rules, provisioned — each one made to fire on purpose (stop the rules
      runner, stop the generator, ...) and to resolve again
- [ ] 8. The learning loop: fix `SETTLEMENT_MISMATCH`, watch recall go to 1.0
- [ ] 9. Docs: this section, the quick start (two new URLs), `.env.example`

### Proof it works

- From a fresh clone: `cp .env.example .env && docker compose up -d` — Grafana opens
  with four dashboards already there, and data in them.
- Every Prometheus target `UP`; no metric has a label with an id in it
  (`count by (__name__)` stays small).
- The *Scoring* dashboard agrees with `db/scoring.sql` run by hand.
- Each alert has been seen firing and resolving.
- `invariants.sql` still 12/12: the rules only ever write to `alerts` and `rule_state`.

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
