# Database guide

## In Docker

The `migrate` service applies pending migrations before application startup. The
`seed` job then backfills an empty database or exits if the completed-seed marker
exists. PostgreSQL data uses the Compose `pgdata` volume (`antifraud_pgdata` for
the default project). `docker compose down` keeps it; adding `-v` deletes it.

```bash
docker compose exec postgres psql -U antifraud -d antifraud   # a psql prompt
docker compose run --rm migrate                            # development: apply migrations
```

The Compose database has no published host port; use `exec` to connect. Run
commands from the repository root. For SQL validation, see
[SQL checks](../db/tests/README.md).

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
nothing else — and not even that on the columns in `SECRET_COLUMNS` in `migrate.py`,
the things the API never returns either (today: `payment_methods.fingerprint`). On
such a table it gets every other column one by one, so `SELECT *` there is refused
and queries name their columns; a column added later is readable at once, and a
secret column that disappears (renamed?) stops the run rather than leak under its
new name. It is not a migration — a role belongs to the whole Postgres server,
and a database owner is usually not allowed to create one. When
`GRAFANA_DB_PASSWORD` is set — Compose sets it and runs as a superuser — the
runner creates the role if needed, sets its password and grants
`SELECT` on every table, at the end of every run: new tables are covered, and a
password changed in `.env` takes effect when the migration runner runs again.
Locally, without Grafana, leave it unset.

**Adding one:** a new file with the next number, `008_what_it_does.sql`, starting
with `SET TIME ZONE 'UTC';` like the others — a `timestamptz` literal in a migration
is read in the session's time zone, so without it the same file means different
moments on different machines. Never edit a file once it has been applied anywhere:
the runner only knows filenames, so an edit would not reach databases that already
ran it. Fix forward, in a new file.

**A database migrated by hand** may have tables but no `schema_migrations`.
The runner refuses to touch it rather than re-run `001`. If every file has been
applied to it, record them once without running anything:

```bash
python db/migrate.py --baseline
DATABASE_URL="dbname=antifraud_test" python db/migrate.py --baseline
```
