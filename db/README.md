# db

| Path | What it is |
|---|---|
| `migrations/` | The schema, one numbered `.sql` file per change |
| `migrate.py` | Applies the migrations a database does not have yet |
| `tests/` | SQL checks on the data — see [its README](tests/README.md) |

## In Docker

The `migrate` service runs `migrate.py` on every `docker compose up`, before
anything else touches the database; `seed` then backfills, only if the database is
empty. The data lives in the `antifraud_pgdata` volume: `docker compose down` keeps
it, `docker compose down -v` deletes it — the Docker version of `reset.sh` +
backfill.

```bash
docker compose exec postgres psql -U antifraud -d antifraud   # a psql prompt
docker compose run --rm migrate                               # apply a new migration now
```

Postgres is not published to the host, so a local `psql` cannot reach it — `exec`
goes in through Docker instead. The SQL checks in `tests/` run the same way; see
[its README](tests/README.md).

## Migrations

```bash
python db/migrate.py                                    # antifraud
DATABASE_URL="dbname=antifraud_test" python db/migrate.py
```

Run with the venv active. Each file runs once, in filename order, in its own
transaction, and is recorded in the `schema_migrations` table — so running it again
applies only what is new. A failing file rolls back completely and stops the run.
`reset.sh` and the compose stack's `migrate` service both use this script.

**`grafana_reader`** is a read-only role for Grafana: `SELECT` on every table and
nothing else. It is not a migration — a role belongs to the whole Postgres server,
and a database owner is usually not allowed to create one (step 1 of phase 9 found
that out locally). When `GRAFANA_DB_PASSWORD` is set — compose sets it, and runs as
a superuser — the runner creates the role if needed, sets its password and grants
`SELECT` on every table, at the end of every run: new tables are covered, and a
password changed in `.env` takes effect at the next `docker compose up -d`.
Locally, without Grafana, leave it unset.

**Adding one:** a new file with the next number, `005_what_it_does.sql`, starting
with `SET TIME ZONE 'UTC';` like the others — a `timestamptz` literal in a migration
is read in the session's time zone, so without it the same file means different
moments on different machines. Never edit a file once it has been applied anywhere:
the runner only knows filenames, so an edit would not reach databases that already
ran it. Fix forward, in a new file.

**A database migrated by hand** — with `psql`, before this script existed, like a
local `antifraud` from before phase 8 — has the tables but no `schema_migrations`.
The runner refuses to touch it rather than re-run `001`. If every file has been
applied to it, record them once without running anything:

```bash
python db/migrate.py --baseline
DATABASE_URL="dbname=antifraud_test" python db/migrate.py --baseline
```
