# Development and testing

Run these commands from the repository root unless a command changes directory.
The home-server checkout is managed by the updater; develop in a separate checkout.

## Docker workflow

```bash
cp .env.example .env                 # first setup only; keep an existing .env
docker compose up -d --build
docker compose logs -f api
docker compose up -d --build api     # rebuild after a local API change
docker compose down                 # keep database and monitoring volumes
```

On a development checkout, update sources with `git pull --ff-only`, review changes
in `.env.example`, then rebuild. On the managed server, follow the
[deployment guide](DEPLOYMENT.md) instead.

## Local Python setup

Use Python 3.14 and a local PostgreSQL instance for application development.
The PostgreSQL account must be able to create the development/test databases.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lint.txt -r api/requirements-dev.txt \
  -r admin/requirements-dev.txt -r rules/requirements-dev.txt \
  -r generator/requirements.txt
```

For a new development database, create it once and apply migrations:

```bash
createdb antifraud
DATABASE_URL='dbname=antifraud' python db/migrate.py
DATABASE_URL='dbname=antifraud' python generator/backfill.py
```

Backfill requires an empty or already seeded database; it refuses a partial seed.
Use service guides for starting the [API](API.md#local-development),
[panel](ADMIN.md#local-development), [generator](../generator/README.md) and
[rules](../rules/README.md). Local commands use libpq connection settings; set
`DATABASE_URL` or `PG*` variables as appropriate. Host PostgreSQL is separate from
the Compose database, which has no published port.

## Tests and lint

Create a dedicated test database once. Apply migrations again after adding one:

```bash
createdb antifraud_test
DATABASE_URL='dbname=antifraud_test' python db/migrate.py
python -m ruff check .
(cd admin && python -m pytest -q)
python -m pytest -q ci/tests
(cd api && TEST_DATABASE_URL='dbname=antifraud_test' python -m pytest -q)
(cd rules && TEST_DATABASE_URL='dbname=antifraud_test' python -m pytest -q)
```

API fixtures truncate the test dataset and reject database names without `_test`.
Rules fixtures roll their test transactions back. Run the API and rules suites
sequentially when sharing this test database. Panel and CI helper tests need no
running API or database; helper fixtures create their own temporary resources.

For data and detection checks, see [db/tests](../db/tests/README.md).
[GitHub CI](../ci/README.md) also runs the real stack, Postman collection,
scoring gate, live generator and monitoring checks in a disposable environment.
Host updater changes must also pass tests on Python 3.11.2.

## Configuration and data

- Keep `.env` local. Compare it with `.env.example` after updates; new variables
  are not copied automatically. Do not overwrite an existing server configuration.
- Demo passwords and keys are public. Set your own credentials before sharing
  access; use HTTPS with `SECURE_COOKIES=1` for a remotely exposed panel.
- `POSTGRES_PASSWORD` and `GRAFANA_ADMIN_PASSWORD` initialize stored accounts on
  the first start. For existing data, changing `.env` alone does not rotate them:
  change the PostgreSQL role password separately; reset Grafana with
  `docker compose exec grafana grafana cli admin reset-admin-password <new>`.
  Keep `.env` synchronized with the stored accounts.
- Generate panel password hashes with
  `docker compose exec admin flask --app app hash-password <name>`. Put entries
  into the single-quoted `ADMIN_USERS` value. Development containers must be
  recreated to pick up environment changes; `restart` alone does not load them.
- `docker compose down -v` and `bash reset.sh` delete data. Use them only for a
  disposable lab, never as an update procedure. Prefer a separate test database.
- Grafana's Fraud dashboard has an **Admin panel** URL variable. Set it to the
  address reachable from your browser when using a remote host or another port.

## Contribution workflow

Use a feature branch and pull request. Review dependency updates, wait for CI,
then merge. Successful code pushes to `main` publish images for the server timer.
See the [GitHub owner checklist](GOING_PUBLIC.md) for repository settings and
[AGENTS.md](../AGENTS.md) for coding constraints.
