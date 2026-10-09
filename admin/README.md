# Antifraud Lab admin panel

A read-only back office for looking into players, their money, bets and matches.
Flask renders Jinja templates, htmx swaps parts of the page, and every byte of data
comes from the [API](../api/README.md). The panel has no database and never touches
Postgres.

```
browser ──HTML──> Flask panel ──HTTP + X-API-Key──> FastAPI ──> Postgres
```

The design decisions are in the main [README](../README.md#phase-7--admin-panel-done).
This file is how to run it, what every page does, and how the pieces fit.

---

## Run it

### With Docker

The whole lab from the repo root — the panel comes up with the API and the database:

```bash
cp .env.example .env
docker compose up -d
```

http://localhost:5000, log in as `admin` / `demo-admin-password-change-me`. In
Docker the panel runs under gunicorn with two workers, reaches the API at
`http://api:8000`, and is not on the database network at all. Its settings are in
the root `.env`: `PANEL_API_KEY` (always made a read-only key by compose),
`SECRET_KEY`, `ADMIN_USERS`, `SESSION_HOURS`, `SECURE_COOKIES`.

A new user:

```bash
docker compose exec admin flask --app app hash-password anna
```

Put the printed line into `ADMIN_USERS` in `.env` — **inside the single quotes**,
comma-separated from the others; compose would read every `$` in a hash as a
variable otherwise — then `docker compose up -d` (`restart` would not read `.env`).

### Without Docker, for development

From the repo root, once:

```bash
source .venv/bin/activate
pip install -r admin/requirements-dev.txt   # requirements.txt alone is what the image installs
cp admin/.env.example admin/.env
```

Then fill in `admin/.env`:

1. **`API_KEY`** — a key from the API's **`API_READ_KEYS`** (in `api/.env`), not from
   `API_KEYS`. The panel only reads, so a leaked panel key cannot create anything.
   The two `.env.example` files already agree on `dev-read-key-change-me`.
2. **`SECRET_KEY`** — `python -c "import secrets; print(secrets.token_urlsafe(32))"`
3. **`ADMIN_USERS`** — one entry per person, made with:

   ```bash
   cd admin && flask --app app hash-password igor
   ```

   It asks for the password twice and prints `igor:scrypt:32768:8:1$…`. Paste that
   whole line after `ADMIN_USERS=`; several users are comma-separated.

Start the API first (see its README), then, from `admin/`:

```bash
flask --app app run --port 5000 --debug
```

Open http://localhost:5000 and log in. The home page's **API** card checks the API
every 30 seconds: green means reachable *and* the key is accepted.

- `flask run` reads `admin/.env` by itself (python-dotenv). Change `.env`, restart.
- `--debug` reloads code **and templates** on change. Without it Flask caches
  templates, and an edited template does not show until a restart.
- Ports: API on 8000, panel on 5000. `API_URL` is where the panel finds the API.

### In production

The same app, with three things different:

- `SECURE_COOKIES=1`, and the panel behind HTTPS — the session cookie is then never
  sent over plain http. (With it on and plain http, login never sticks.)
- A fixed `SECRET_KEY`. Without one the panel makes a random key at start-up and
  warns: every restart then logs everybody out.
- A real WSGI server instead of `flask run`, which is a development server. The
  Docker image runs gunicorn: `gunicorn --workers 2 "app:create_app()"`. With more
  than one worker a fixed `SECRET_KEY` is a must, not a nicety — each worker would
  make its own random key, and every other request would look logged out.

Passwords are only ever stored as hashes, in the environment. Adding or removing a
user is an edit to `ADMIN_USERS` and a restart; a removed user's session stops
working on their next request.

---

## Test it

```bash
cd admin && pytest -q               # 140 tests, about 4 seconds
```

No API and no database needed: the tests replace the API with
`httpx.MockTransport`, so each one says exactly what the API answers — a page of
players, a 404, a timeout — and checks what the panel does with it.

| File | What it covers |
|---|---|
| `test_skeleton.py` | layout and assets, the API status card, every API failure mapped to a panel page, security headers, **the API key never in any HTML**, no inline scripts or styles in any template |
| `test_login.py` | every page needs a login, wrong password, CSRF, `next=` only to local paths, cookie flags, logout is POST, the `hash-password` command |
| `test_players.py` | filters and cursor forwarded to the API, full page vs fragment, load more keeps the filters, tabs, the Back-button restore, XSS escaping, money and time formatting |
| `test_bets_events.py` | bets and events lists, stake validation, bet and event pages, the three bet warnings, links between pages, the filter trigger |

Each step was also driven in a real Chromium (Playwright) against the real API and
generated data: filters, load more, tabs, Back, phone width, and no console or CSP
errors.

---

## Pages

| Page | What it shows | API calls |
|---|---|---|
| `/` | API status card, refreshed every 30 s | `/ready`, `/v1/players?limit=1` |
| `/health` | `{"status": "ok"}` — no login, no API call. For Docker's healthcheck: an API outage must not get the panel restarted | none |
| `/players` | Players, newest first. Filters: country, status, order. "Player ID" box | `GET /v1/players` |
| `/players/32` | Status, country, currency; balance and its four parts; tabs | `/v1/players/32`, `/balance` |
| `/players/32?tab=transactions` | Deposits and withdrawals, method and last four digits | `/transactions?order=desc` |
| `/players/32?tab=bets` | The player's bets, each linking to its bet page | `/bets?order=desc` |
| `/players/32?tab=sessions` | Logins: IP, device, user agent | `/sessions?order=desc` |
| `/players/32?tab=linked` | Other players sharing a device or a payment method | `/linked` |
| `/bets` | Every player's bets, newest first. Filters: status, minimum stake, order. "Bet ID" box | `GET /v1/bets` |
| `/bets/654` | Stake, odds, result, payout; the legs and their matches; warnings | `GET /v1/bets/654` |
| `/events` | Matches in kickoff order, upcoming by default. Filters: status, league, order | `GET /v1/events?sort=start_time` |
| `/events/29` | Every market, every selection, current odds | `GET /v1/events/29` |

Every list shows 25 rows, then **Load more**. Every page links onward: a bet to its
player and its matches, a player's bet to the bet, a linked player to that player.

### The warnings on a bet page

A bet page says out loud three things anyone could check from the numbers on it:

- **Placed after kickoff** — a leg's match had already started
- **Settled as lost, but paid out**
- **Won, but paid X — stake × odds is Y** (more than a cent out)

This is not fraud detection — that is phase 9, in Prometheus. It is a few lines in
`views/bets.py` over the API's own data, and it never reads `fraud_labels` (the panel
cannot even reach it). In a fresh dataset (`SEED = 42`, `DAYS = 14`), bets 654, 525
and 771 show one each, in that order — and bet 664 shows two: a late bet that was
also paid the wrong amount.

---

## How a page works

### One URL, two answers

Every page is a normal URL that returns a whole page. When **htmx** asks for the
same URL it sends `HX-Request: true`, and gets only the piece it is replacing.

```
GET /players?country=PL                    → the whole page
GET /players?country=PL   HX-Request: true → just the table rows
```

The full page includes the same fragment template, so the two can never show
different things. And every page works with JavaScript off — htmx only makes it
quicker. Every response carries `Vary: HX-Request`, so a cache never hands out a
fragment where a page was asked for.

### Filters

Changing a dropdown re-asks the list URL with the form's values and swaps the table
body. The URL in the address bar follows (`hx-push-url`), so a filtered list can be
bookmarked, shared, or reloaded. Text fields (minimum stake) apply on **Enter**.

```html
hx-trigger="change from:(.filters select), submit"
```

- Selects on `change`, the form on `submit` — and *not* `change` on text fields too:
  Enter fires both, and every search would go out twice.
- `submit` as a trigger means htmx takes the submit over; without it the browser also
  does a full page load alongside htmx's request.
- A selector with a space has to be in brackets — `from:.filters select` is an
  `htmx:syntax:error` in the browser console, and filters silently stop working.
- `hx-sync="this:replace"`: a newer filter cancels a slower request still on its way.

### Load more

The last row of every table is a button holding the API's `next_cursor`. Clicking it
fetches the next page — its rows *and* a new load-more row — and puts them exactly
where the old row was (`hx-swap="outerHTML"`). On the last page there is no button.
The load-more URL keeps every filter, so page 2 of "PL, suspended" is still PL and
suspended.

This is why the API uses cursors: rows the live generator inserts meanwhile never
shift a page, so load more never repeats or skips a row.

### Tabs

The server renders the tab bar *and* the active tab's table together, and htmx swaps
both. So the server decides which tab is highlighted — no JavaScript for that. Each
tab is a real link (`/players/32?tab=bets`), pushed into the address bar: Back,
reload and bookmarks all land on the right tab. Switching tabs does not fetch the
player or the balance again.

### The Back button

htmx keeps snapshots of recent pages, and Back restores one. When the snapshot is
gone, htmx asks the server again with `HX-Request` *and*
`HX-History-Restore-Request`, and replaces the whole page with the answer — so for
that header the panel sends the full page, not a fragment (`app/htmx.py`).

### When something fails

| The API says | The panel shows |
|---|---|
| 404 | "Not found" with the API's message, as a 404 |
| 400 / 422 | "Bad request" with the API's message, as a 400 |
| 401 / 403 | "Panel misconfigured" as a 500, and logs *check API_KEY* — the user cannot fix it |
| other 5xx | "The API failed", with a retry button |
| nothing (down, timeout) | "API unavailable", with a retry button |

For an htmx request only the error card is sent, so it appears where the rows would
have gone, not as a page inside the page.

---

## Security

- **The API key never reaches the browser.** htmx talks to Flask; Flask talks to the
  API. A test fetches pages, fragments, error pages and the login page and checks
  the key is in none of them, body or headers.
- **Login** with Flask-Login against `ADMIN_USERS`. One message for a wrong name and a
  wrong password, and the same time taken for both, so neither gives away which
  usernames exist. `?next=` only ever redirects to a path on the panel itself.
- **Logout is a POST with a CSRF token**, never a link — otherwise any web page could
  log you out with `<img src="/logout">`. Login is CSRF-protected too (Flask-WTF).
- **Session cookie:** `HttpOnly`, `SameSite=Lax`, `Secure` with `SECURE_COOKIES=1`,
  lifetime `SESSION_HOURS`.
- **Content-Security-Policy:** `default-src 'self'`, no inline scripts or styles, no
  eval — so an injected `<script>` would not run even if escaping ever failed. htmx's
  own eval features are switched off in `base.html` to match. A test fails if any
  template gets a `style=` or an inline `<script>`.
- Jinja escapes everything; a test puts `<script>` in a user agent and checks it comes
  out as text.
- Also: `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`.

---

## Look

[Beer CSS](https://www.beercss.com) 5 — Material Design 3 in plain CSS classes, with no
JavaScript and no build step. Dark scheme (`<body class="dark">`). On a wide screen
the navigation is a drawer, on a tablet a rail, on a phone a bottom bar.

Beer CSS, htmx, the icon font and Roboto are **vendored** in `app/static/vendor/` —
no CDN, so the panel works offline and loads nothing third-party. Versions and the
one change made to `beer.min.css` are in [its README](app/static/vendor/README.md).
The panel's own CSS is `app/static/app.css`.

Status chips are **tonal** — a container and text of the same hue, the Material 3
way — from `tone-*` classes in `app.css`, with a light and a dark set.
`formatting.status_colour()` picks the hue: green for active / approved / won, amber
for suspended / pending, red for rejected / lost, and so on.

Money is formatted from the API's string (`"1234567.10"` → `1,234,567.10 PLN`), never
via a float. Times are always shown in UTC and say so: two people looking at the same
row must see the same time.

Three Beer CSS behaviours that cost time, and the fix:

- A `<header>` inside the page is moved to the layout's header area, centred at the
  top. Page headings are `<div class="page-header">` instead.
- An element whose child has a `no-margin` class gets `padding: 0.1px`, which beats
  `article`'s own padding — cards lost their padding. `app.css` puts it back.
- `nav > ul` is styled as a menu, so a plain list inside a `nav` row collapses to one
  word per line. Plain `<p>`s in a `<div>` instead.

---

## Problems we hit, and the fix

| Symptom | Cause | Fix |
|---|---|---|
| Every page says **Panel misconfigured** | The API rejects the panel's key (401/403). The panel log says *check API_KEY* | `API_KEY` must be in the API's `API_READ_KEYS` (or `API_KEYS`); restart the API after editing its `.env` |
| **API unavailable** | The API is not running, or `API_URL` points elsewhere | Start the API; check `API_URL` |
| Login form comes back, no error, never logged in | `SECURE_COOKIES=1` over plain http — the browser drops the cookie | `SECURE_COOKIES=0` locally |
| Logged out after every restart | No `SECRET_KEY`: a random one each start (the log warns) | Set `SECRET_KEY` |
| Nobody can log in | `ADMIN_USERS` empty, or the line was cut when pasting | Re-run `hash-password`, paste the whole line |
| An edited template does not change | Running without `--debug`: Flask caches templates | `--debug`, or restart |
| Every word on the page is bold | Beer CSS used the installed Roboto, and only Roboto Bold was installed | Fixed: Roboto is vendored as "Panel Roboto" |
| Four CSP errors on every page | Beer CSS's `@font-face` lists a CDN fallback; Chromium checks it against the CSP | Fixed: removed from `beer.min.css`, see the vendor README |
| Enter in "Minimum stake" sent two requests | The form listened for `change` from every field and the browser also submitted | Fixed: see [Filters](#filters) |
| `htmx:syntax:error` in the console, filters dead | A trigger selector with a space, not in brackets | `from:(.filters select)` |
| Phone pages scroll sideways | Five items did not fit the bottom bar | Fixed: logout is icon-only there |

Seen only in testing: Playwright's screenshots add `style=""` to hidden inputs, and if
htmx then snapshots that page, Back logs three inline-style CSP errors. A normal
browser never does this.

---

## Layout

```
admin/
  requirements.txt     what it needs to run: flask, flask-login, flask-wtf, httpx, python-dotenv, gunicorn
  requirements-dev.txt that, plus pytest - what the venv installs
  .env.example         API_URL, API_KEY, SECRET_KEY, API_TIMEOUT, ADMIN_USERS, SESSION_HOURS, SECURE_COOKIES
  app/
    __init__.py        create_app(): config, API client, login, blueprints, error pages, security headers
    config.py          settings from the environment
    api_client.py      one httpx client; problem+json -> ApiError, outage -> ApiUnavailable
    auth.py            login, logout, the login guard, the hash-password command
    htmx.py            is_htmx(), render() - one URL, two answers
    formatting.py      Jinja filters: money, when, status_colour, humanise, market
    views/             home, players, bets, events - one blueprint each
    templates/
      base.html        layout, navigation, CSP-safe htmx config
      _macros.html     filter form, dropdown, "go to ID" box
      _load_more.html  the last row of every paged table
      players/ bets/ events/ errors/   one folder per area; partials start with _
    static/
      app.css          the panel's own styles
      vendor/          Beer CSS, htmx, Roboto - see its README
  tests/               140 tests, the API mocked
```
