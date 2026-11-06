# API guide

Interactive OpenAPI documentation is served at http://localhost:8000/docs.
For Docker startup, see the [quick start](../README.md#quick-start).

## Local development

Complete [Python/database setup](DEVELOPMENT.md#local-python-setup), then:

```bash
cp api/.env.example api/.env          # first setup only
cd api
uvicorn app.main:app --reload --env-file .env
```

Set `DATABASE_URL`, `API_KEYS` and `API_READ_KEYS` in `api/.env`. Restart uvicorn
after changing environment settings. Risk checks require the backfill's
`sim_state` row; without it, new checks return 503.

## Endpoints

Everything under `/v1` needs an `X-API-Key` header, of one of two kinds:

| Key from | May | Who gets one |
|---|---|---|
| `API_KEYS` | read everything, and create risk checks | Postman, a payment gateway |
| `API_READ_KEYS` | read everything | the admin panel |

No key or a wrong key is **401**. A real read-only key on `POST /v1/risk-checks` is
**403** — the key is fine, it just may not do this, so retrying with it never helps.
The 403 comes before validation: a caller without the scope learns nothing about
what a valid request would look like.

Every error, of any kind, is
`application/problem+json` (see [Errors](#errors)).

| Method | Path | Query / body | Success | Errors |
|---|---|---|---|---|
| GET | `/health` | — | 200 | — |
| GET | `/ready` | — | 200 | 503 database unreachable |
| GET | `/v1/players` | `limit` `cursor` `order` `country` `status` `registered_after` | 200 page | 400 401 422 |
| GET | `/v1/players/{id}` | — | 200 | 401 404 422 |
| GET | `/v1/players/{id}/balance` | — | 200 | 401 404 422 |
| GET | `/v1/players/{id}/transactions` | `limit` `cursor` `order` `direction` `status` `since` | 200 page | 400 401 404 422 |
| GET | `/v1/players/{id}/bets` | `limit` `cursor` `order` `status` | 200 page | 400 401 404 422 |
| GET | `/v1/players/{id}/sessions` | `limit` `cursor` `order` | 200 page | 400 401 404 422 |
| GET | `/v1/players/{id}/linked` | `limit` `cursor` `order` | 200 page | 400 401 404 422 |
| GET | `/v1/bets` | `limit` `cursor` `order` `status` `min_stake` `placed_after` | 200 page | 400 401 422 |
| GET | `/v1/bets/{id}` | — | 200 | 401 404 422 |
| GET | `/v1/events` | `limit` `cursor` `order` `sort` `status` `league` `from` `to` | 200 page | 400 401 422 |
| GET | `/v1/events/{id}` | — | 200 | 401 404 422 |
| GET | `/v1/risk-checks/{id}` | — | 200 | 401 404 422 |
| POST | `/v1/risk-checks` | header `Idempotency-Key`; body below | 201 new, 200 replay | 401 **403** 404 422 503 |

Any endpoint can also answer 500. A 422 on a `{id}` path means the id is not a
positive integer.

What each one returns:

- **`/v1/players/{id}/balance`** — `balance`, plus the four amounts it is made of:
  `deposited` (approved), `withdrawn` (requested, pending included), `staked`, `paid_out`.
- **`/v1/players/{id}/transactions`** — each with its payment method nested (`type`,
  `last4`). The card **fingerprint is never sent**: it is what links accounts.
- **`/v1/players/{id}/bets`** — each with `payout` and `settled_at`, `null` while open.
- **`/v1/players/{id}/sessions`** — every login: `started_at`, `ended_at`, `ip`, `device_id`, `user_agent`.
- **`/v1/players/{id}/linked`** — other players who share a device or a payment method
  with this one, and how many of each. The device ids and card fingerprints are
  compared inside the database and never returned: the API says *that* two players
  share a card, never *which* card.
- **`/v1/bets`** — the same, across every player, each bet carrying its `player_id`.
  The back-office feed: usually asked for with `order=desc`.
- **`/v1/bets/{id}`** — every leg with its market and match, `odds_at_placement`
  (the price that counts, not today's), and the settlement or `null`.
- **`/v1/events`** — `from` inclusive, `to` exclusive; `from` must be before `to`.
  `sort=start_time` lists matches in kickoff order — with `status=scheduled` and
  `from`, that is "upcoming matches, soonest first".
- **`/v1/events/{id}`** — every market, each with its selections and `current_odds`.
- An **unknown player** is 404 on every `/players/{id}/…` endpoint — never an empty 200.

### Conventions

**Pagination.** Every list returns `{"items": [...], "next_cursor": "..."}`. Pass
`next_cursor` back as `cursor` for the next page; it is `null` on the last page.
Cursors are opaque — do not build one — and a garbage cursor is a 400. Ordered by
`id`, which is what keeps paging stable while the live generator inserts rows.

`order=asc` (the default) is oldest first, `order=desc` newest first. A cursor
remembers which one it was made for, and using it with the other is a 400 — "after
id 4812" means opposite things in the two directions. One difference worth knowing:
paging oldest first, rows created meanwhile turn up on a later page; paging newest
first, they never appear, because they are above where you started — start again
from the top to see them.

`/v1/events` also takes `sort=start_time`. Kickoff times repeat — about ten matches
share each one on a given day — so the id breaks ties and the cursor carries both:
the next page starts at `(start_time, id) > (last kickoff, last id)`, a row
comparison, and never skips a match that shares the last one's kickoff. A cursor
belongs to one sort as well as one order; using it with another is a 400.

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
X-API-Key: <full-access-key>
Idempotency-Key: <unique-request-id>
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

## Postman and Newman

Import the [collection](../api/postman/antifraud.postman_collection.json) and
[environment](../api/postman/local.postman_environment.json). Select the environment
and set `baseUrl`, `apiKey` and `readApiKey` to match the running API.
The committed environment keeps keys empty.

Run folders top to bottom: requests pass cursors, IDs and idempotency keys to later
requests. Default `playerId=1` and `linkedPlayerId=32` target a fresh seed; adjust
these for another dataset. The collection has 36 requests and 60 assertions.

Against a local Docker stack using demo keys, from the repository root:

```bash
npx newman@6.2.3 run api/postman/antifraud.postman_collection.json \
  -e api/postman/local.postman_environment.json \
  --env-var baseUrl=http://localhost:8000 \
  --env-var apiKey=demo-full-key-change-me \
  --env-var readApiKey=demo-read-key-change-me
```

If requests fail authentication, check the selected environment and the headers
actually sent in Postman's Console. A read-only key returns 403 on a write;
a missing or invalid key returns 401.

Export collection edits back to the repository's JSON (v2.1); Postman's workspace
copy does not update Git automatically. Keep environment keys empty when exporting.
