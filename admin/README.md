# Admin panel

A read-only investigation interface built with Flask, Jinja and HTMX.
Browse players, balances, transactions, sessions, linked accounts, bets and events.
Filters, tabs and load-more navigation keep their state in the URL.

```text
Browser → Flask panel → FastAPI → PostgreSQL
```

The panel has no direct database access. Its read-only API key stays on the server.

Start the lab using the [root quick start](../README.md#quick-start), then open
http://localhost:5000. Demo login: `admin` / `demo-admin-password-change-me`.

```bash
docker compose logs -f admin
docker compose up -d --build admin   # development checkout
```

- [Local setup, configuration and behavior](../docs/ADMIN.md)
- [Development and test setup](../docs/DEVELOPMENT.md)
- [Vendored assets and licenses](app/static/vendor/README.md)

Tests: from `admin/`, run `python -m pytest -q`. The API is mocked; no running
services or database are needed.
