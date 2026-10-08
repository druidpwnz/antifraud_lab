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
| 6 | API — FastAPI | **done** — 15 endpoints, 140 tests, Postman collection |
| 7 | Admin panel — Flask + Jinja + HTMX, over the API | **done** — players, bets, events; 140 tests |
| 8 | Compose, for real | **next** — planned |
| 9 | Grafana + Prometheus — fraud alerting | not started |
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

## Phase 8 — Compose, for real (next)

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
| Stopping | Exec-form `CMD` so Python is PID 1 and gets SIGTERM; `stop_grace_period` long enough for the generator to finish its hour | `live.py` already finishes the hour and commits on SIGTERM — this lets it |
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
  `CATCH_UP=0` in `.env` skips it.
- **The first `up -d` waits for the seed.** The generator depends on the seed having
  *finished*, so `docker compose up -d` only returns after the backfill — about
  half a minute — not at once.
- **A reboot ignores `depends_on`.** Docker restarts `unless-stopped` containers by
  itself, in no particular order, and does not run `migrate` or `seed`. A generator
  that starts before Postgres crashes and is restarted with a growing back-off until
  Postgres is up — seen in step 4, and harmless: each simulated hour is one
  transaction, so an interrupted hour is rolled back and redone.
- **`exec` and a local file.** `docker compose exec postgres psql -f db/tests/…`
  looks for the file *inside* the container. Feed it on stdin instead:
  `docker compose exec -T postgres psql -U antifraud -d antifraud < db/tests/invariants.sql`
  (`-T`: no terminal, so stdin can be a file).
- **A local database can be older than the code.** Step 3 found the local
  `antifraud` differs from a fresh seed from the first days on: it was generated
  before later generator tuning. Ids picked from it (example bets, Postman
  variables) do not exist in a fresh dataset. Regenerate locally after generator
  changes: `bash reset.sh && (cd generator && python backfill.py)`.
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
- [ ] 5. Compose, web half: `api`, `admin`, networks, ports, healthchecks, `.env.example`
- [ ] 6. Proof on a clean clone
- [ ] 7. Docs: a quick start at the top of this README, this section, the service READMEs

### Proof it works

- From a fresh `git clone` in another folder — so nothing untracked can help:
  `cp .env.example .env && docker compose up -d`, then `docker compose ps` shows
  every long-running service healthy and `migrate` / `seed` exited 0.
- The Postman collection passes under Newman against the compose API. The seed is
  deterministic — two fresh backfills are identical, table by table (checked in step
  3) — so a local database regenerated with the current code has the same ids.
- `invariants.sql`, run with `docker compose exec`, passes all twelve checks.
- The panel logs in with the demo user from `.env.example`, and shows data.
- `docker compose restart generator`: it resumes from `sim_state`, no gap, no repeat.
- `docker compose down && docker compose up -d`: same data, `seed` skips.
- `docker compose down -v && docker compose up -d`: a fresh dataset, same ids.
- The panel container cannot reach Postgres at all (`db` network only).

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
