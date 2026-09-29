# Antifraud Lab API

FastAPI over the antifraud database: read access to the generated players, money,
bets and events, and one write endpoint — **risk checks** — that decides whether a
proposed deposit or withdrawal should go through.

The design decisions and the reasoning behind them are in the main
[README](../README.md#phase-6--api-done). This file is how to run it, what every
endpoint does, and how to use the Postman collection.

---

## Run it

From the repo root, once:

```bash
source .venv/bin/activate
pip install -r api/requirements.txt

# an existing database: apply the migration, keep the data
psql antifraud -v ON_ERROR_STOP=1 --single-transaction -f db/migrations/003_risk_checks.sql
# (a fresh one: bash reset.sh && python generator/backfill.py - reset.sh DROPS the database)

cp api/.env.example api/.env        # DATABASE_URL, API_KEYS, POOL_MIN, POOL_MAX
```

Then, from `api/`:

```bash
uvicorn app.main:app --reload --env-file .env
```

- Interactive docs: http://localhost:8000/docs — **Authorize** with a key from `API_KEYS`
- `--reload` watches the code, not `.env`. Change `.env`, restart uvicorn.
- Risk checks need `sim_state` to have a row, which the backfill writes. Without it,
  `POST /v1/risk-checks` answers 503.

## Test it

```bash
bash reset.sh antifraud_test        # once, and again after a new migration
cd api && pytest -q                 # 94 tests
```

- Tests run against **`antifraud_test`**, never `antifraud`. The fixture wipes it and
  loads a small known dataset at the start of every run, and refuses to do that to
  any database whose name does not end in `_test`.
- `tests/test_scoring.py` needs no database at all — the risk rules are pure
  functions, so those 16 tests run in a few hundredths of a second.

---

## Endpoints

Everything under `/v1` needs an `X-API-Key` header. Every error, of any kind, is
`application/problem+json` (see [Errors](#errors)).

| Method | Path | Query / body | Success | Errors |
|---|---|---|---|---|
| GET | `/health` | — | 200 | — |
| GET | `/ready` | — | 200 | 503 database unreachable |
| GET | `/v1/players` | `limit` `cursor` `country` `status` `registered_after` | 200 page | 400 401 422 |
| GET | `/v1/players/{id}` | — | 200 | 401 404 422 |
| GET | `/v1/players/{id}/balance` | — | 200 | 401 404 422 |
| GET | `/v1/players/{id}/transactions` | `limit` `cursor` `direction` `status` `since` | 200 page | 400 401 404 422 |
| GET | `/v1/players/{id}/bets` | `limit` `cursor` `status` | 200 page | 400 401 404 422 |
| GET | `/v1/bets/{id}` | — | 200 | 401 404 422 |
| GET | `/v1/events` | `limit` `cursor` `status` `league` `from` `to` | 200 page | 400 401 422 |
| GET | `/v1/events/{id}` | — | 200 | 401 404 422 |
| POST | `/v1/risk-checks` | header `Idempotency-Key`; body below | 201 new, 200 replay | 401 404 422 503 |

Any endpoint can also answer 500. A 422 on a `{id}` path means the id is not a
positive integer.
| GET | `/v1/risk-checks/{id}` | — | 200 | 401 404 422 |

What each one returns:

- **`/v1/players/{id}/balance`** — `balance`, plus the four amounts it is made of:
  `deposited` (approved), `withdrawn` (requested, pending included), `staked`, `paid_out`.
- **`/v1/players/{id}/transactions`** — each with its payment method nested (`type`,
  `last4`). The card **fingerprint is never sent**: it is what links accounts.
- **`/v1/players/{id}/bets`** — each with `payout` and `settled_at`, `null` while open.
- **`/v1/bets/{id}`** — every leg with its market and match, `odds_at_placement`
  (the price that counts, not today's), and the settlement or `null`.
- **`/v1/events`** — `from` inclusive, `to` exclusive; `from` must be before `to`.
- **`/v1/events/{id}`** — every market, each with its selections and `current_odds`.
- An **unknown player** is 404 on every `/players/{id}/…` endpoint — never an empty 200.

### Conventions

**Pagination.** Every list returns `{"items": [...], "next_cursor": "..."}`. Pass
`next_cursor` back as `cursor` for the next page; it is `null` on the last page.
Cursors are opaque — do not build one — and a garbage cursor is a 400. Ordered by
`id`, which is what keeps paging stable while the live generator inserts rows.

**Money** is a string with exactly two decimals: `"105.00"`, `"0.00"`. Odds and
market lines are strings too (`"2.250"`, `"2.50"`). Never parse them into floats.

**Time** is RFC 3339 UTC, `2026-08-12T10:00:00Z`. Time filters (`registered_after`,
`since`, `from`, `to`) must carry an offset — `2026-08-12T10:00:00` alone is a 422.

### Errors

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "Player 999999 does not exist.",
  "instance": "/v1/players/999999"
}
```

A 422 adds `"errors": [{"loc": ["query", "limit"], "msg": "...", "type": "less_than_equal"}]`.
A 500 only ever says `"Something went wrong on our side."` — the details go to the
server log. A missing or wrong key is the same 401 either way.

### Risk checks

```http
POST /v1/risk-checks
X-API-Key: dev-key-change-me
Idempotency-Key: 5b0c7e7a-2c1e-4d8e-9d1a-3f6e2b7c9a10
Content-Type: application/json

{"player_id": 1, "direction": "deposit", "amount": "250.00", "currency": "PLN"}
```

Unknown fields are rejected, `amount` must be positive with at most 2 decimals, and
`currency` must look like ISO 4217.

**Idempotency**

| Request | Answer |
|---|---|
| New `Idempotency-Key` | **201**, `Location: /v1/risk-checks/{id}` — scored and stored |
| Same key, same body | **200**, `Idempotent-Replayed: true` — the decision made then |
| Same key, different body | **422** |
| No `Idempotency-Key` | **422** |

`"50"` and `"50.00"` count as the same body. A replay is never re-scored, even if
the player's history has changed since.

**Rules.** Scored against the *simulated* clock (`sim_state.sim_time`).

| Rule | Code | Points |
|---|---|---|
| Player not active | `player_not_active` | decline |
| Currency is not the player's | `currency_mismatch` | decline |
| Withdrawal above the balance | `insufficient_funds` | decline |
| Amount over 10× the median approved deposit | `amount_far_above_usual` | 40 |
| 3+ deposits already in the last hour (deposits only) | `deposit_velocity` | 30 |
| Account under 24 h old and amount over 200 | `new_account_large_amount` | 25 |
| Withdrawal within 1 h of a deposit, under 10 % of it staked since | `passthrough` | 35 |

Score under 30 → `approve`, under 60 → `review`, otherwise `decline`. Any failing
hard rule is a decline with score 100, and all of them are reported, not just the first.

---

## Postman

`postman/antifraud.postman_collection.json` — 24 requests in five folders, 38 checks.
`postman/local.postman_environment.json` — `baseUrl`, and `apiKey` left empty.

### Setup

1. **Import** both files.
2. **Environments → local →** put your key in `apiKey`'s **Current value** → **Ctrl+S**.
3. Choose **local** in the **environment dropdown, top right**.
4. Start uvicorn, then collection **⋯ → Run collection**.

The collection holds the API key on its **Authorization** tab and every request
inherits it. `health` requests use **No Auth**, and *Wrong API key – 401* sets its own.

Requests pass values along: *first page* saves the cursor *next page* uses;
*player money → Bets* picks the bet *Bet detail* opens; *Events – scheduled* picks
the event; *Risk check – new* makes the `Idempotency-Key` the next two reuse. **Run
folders top to bottom**, or send the earlier request first.

### Problems we hit, and the fix

| Symptom | Cause | Fix |
|---|---|---|
| `getaddrinfo ENOTFOUND {{baseurl}}` | No environment is active. Opening one in the sidebar only *edits* it | Pick **local** in the dropdown, top right |
| Every `/v1` request is 401, `X-API-Key:` empty in the Console | `apiKey` has no **Current value** in the *active* environment | Fill Current value, **Ctrl+S** |
| Still empty after typing the key | Postman stored it in the **Vault**, which is `{{vault:apiKey}}`, not `{{apiKey}}` | Put the key in the environment instead; decline "move to Vault" |
| Two environments called `local` | Imported twice, or one created by hand | Delete the one without `baseUrl` |
| Re-import makes a second collection instead of replacing | Postman matches collections by `info._postman_id` | The file now has a fixed id; if Replace is still not offered, delete the old collection, then import |
| `Cannot read properties of undefined (reading 'map')` | Old scripts crashed on a non-page response (usually a 401) | Fixed: list requests now fail with `got 401: …` instead |
| Flatpak Postman hangs on sign-in | The browser cannot hand `postman://` back to the sandbox | Use Postman's own `.tar.gz` from postman.com |

The Console (**Ctrl+Alt+C**) shows the headers actually sent — check it first when
a request misbehaves.

### Keeping it in git

The JSON in `postman/` is the source of truth. Postman keeps its own copy in your
workspace, and edits made there do not reach git until you **Export** the collection
(v2.1) over the file. Before committing, `git diff api/postman/` — the environment's
`apiKey` must still be empty.

### Without the app: Newman

```bash
npx newman run api/postman/antifraud.postman_collection.json \
    -e api/postman/local.postman_environment.json \
    --env-var apiKey=dev-key-change-me
```

Same collection, same checks, no account, no run limit, and a non-zero exit code on
any failure — which is what CI will use.

---

## Layout

```
api/
  app/
    main.py            app, lifespan (pool), routers - the /v1 router carries the API-key check
    settings.py        environment variables
    db.py              connection pool and the get_conn dependency
    auth.py            X-API-Key check
    errors.py          problem+json for every failure
    pagination.py      opaque cursors, limit + 1 paging
    ledger.py          a player's balance - shared by /balance and the risk rules
    scoring.py         the risk rules, pure functions
    schemas/           request and response models
    routers/           health, players, bets, events, risk_checks
  tests/               94 tests against antifraud_test
  postman/             collection and environment
```
