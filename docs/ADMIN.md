# Admin panel guide

The panel is a server-rendered API client. It uses a read-only API key and never
connects to PostgreSQL. For Docker startup, see the [quick start](../README.md#quick-start).

## Local development

Complete [Python setup](DEVELOPMENT.md#local-python-setup) and start the API, then:

```bash
cp admin/.env.example admin/.env      # first setup only
cd admin
flask --app app hash-password <username>
```

Set these values in `admin/.env`:

| Setting | Purpose |
|---|---|
| `API_URL` | API address; default `http://127.0.0.1:8000` |
| `API_KEY` | A key from the API's `API_READ_KEYS` |
| `SECRET_KEY` | Fixed random signing secret |
| `ADMIN_USERS` | Comma-separated `name:hash` entries from `hash-password` |
| `SESSION_HOURS` | Session lifetime |
| `SECURE_COOKIES` | `0` for local HTTP; `1` when served over HTTPS |

Generate a secret with
`python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Start the panel from `admin/`:

```bash
flask --app app run --port 5000 --debug
```

Flask loads `.env` automatically. Restart after configuration changes.

## Docker users and configuration

Generate a password hash with:

```bash
docker compose exec admin flask --app app hash-password <username>
```

Add the output to the root `.env`'s single-quoted `ADMIN_USERS` value; the quotes
preserve `$` characters in hashes. Compose supplies `PANEL_API_KEY` to the panel and
registers it as read-only in the API. Use a development container recreation or the
managed deployment procedure to apply changed configuration.

The image uses Gunicorn with two workers and a master-process build-metrics
listener. Keep a fixed `SECRET_KEY` across workers. Use HTTPS and secure cookies
when exposing the panel remotely.

## Pages and behavior

| Page | Purpose |
|---|---|
| `/` | API connectivity/authentication status, refreshed every 30 seconds |
| `/players` | Filtered player list and lookup by ID |
| `/players/{id}` | Balance, transactions, bets, sessions and linked-player tabs |
| `/bets`, `/bets/{id}` | Bet filters, selections, settlement and payout warnings |
| `/events`, `/events/{id}` | Upcoming matches, markets, selections and odds |
| `/health` | Panel process health; no login or API dependency |

Lists load 25 rows at a time. Bet warnings identify late placement, paid losing bets
and incorrect winning payouts from API data. They are display checks; persistent
fraud detection belongs to the rules runner.

Normal requests return a full page; `HX-Request` returns the matching fragment.
Responses vary on that header. History restoration returns a full page so Back
navigation still works when HTMX's cache is empty. Filters, tabs and pagination
retain their URL parameters. HTML remains usable without JavaScript.

## Security and troubleshooting

Login and POST logout use CSRF protection. Cookies are HttpOnly and SameSite=Lax.
Templates escape data; CSP forbids inline scripts/styles. Frontend assets are
[vendored](../admin/app/static/vendor/README.md), so no CDN is needed.

| Symptom | Check |
|---|---|
| Panel misconfigured | API key rejected; use a configured read-only key and check logs |
| API unavailable | API process, `API_URL` and connectivity |
| Login does not stick | Secure cookies require HTTPS; local HTTP needs `SECURE_COOKIES=0` |
| Logout after restart / intermittent login | Set a stable `SECRET_KEY` for every worker |
| Nobody can log in | Complete `ADMIN_USERS` entry, including its full hash |
| Templates do not update locally | Enable `--debug` or restart the development server |

Tests replace the API with `httpx.MockTransport` and cover auth, error mapping,
filters, fragments, navigation, escaping and keeping API keys out of responses.
