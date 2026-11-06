# API

FastAPI access to players, balances, payments, bets and events, plus idempotent
risk checks for proposed deposits and withdrawals.

Start the lab using the [root quick start](../README.md#quick-start), then open
http://localhost:8000/docs and authorize with a key from `API_KEYS`.
Keys from `API_READ_KEYS` allow reads only. Requests use `X-API-Key`.

```bash
docker compose logs -f api
docker compose up -d --build api     # development checkout
```

The API uses cursor pagination, decimal strings for money, UTC timestamps and
`application/problem+json` errors. `/health` checks the process; `/ready` also
checks database access.

- [API reference, local setup and Postman](../docs/API.md)
- [Development and test setup](../docs/DEVELOPMENT.md#tests-and-lint)
- [Postman collection](postman/antifraud.postman_collection.json)

Tests: from `api/`, run `python -m pytest -q` against a migrated
`antifraud_test` database. Fixtures replace its data; never use a real database.
