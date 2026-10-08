"""Apply the migrations a database does not have yet.

    python db/migrate.py                 # the database in DATABASE_URL (default: antifraud)
    DATABASE_URL="dbname=antifraud_test" python db/migrate.py
    python db/migrate.py --baseline      # a database migrated by hand before this existed

Every db/migrations/*.sql file runs once, in filename order, each in its own
transaction, and is recorded in the schema_migrations table. Run it again and it
applies only what is new - so migration 005 reaches a database that already has
data, which Postgres's /docker-entrypoint-initdb.d never does (that folder only runs
when the data volume is empty).

A failed migration rolls back completely and stops the run: the database is left
exactly as it was before that file, and the files after it are not tried.

A migration is never edited once it has been applied anywhere - the runner only
knows filenames, so an edit would silently not reach databases that already ran it.
Changes go in a new file.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"

# Any constant works; it only has to be the same in every copy of this script.
# Two runners started together (two `compose up` at once) would otherwise both see
# 003 as missing and both try to apply it.
LOCK_ID = 8_241_105


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--baseline", action="store_true",
        help="record every migration file as applied without running any - only for a "
             "database whose migrations were all applied by hand, with psql",
    )
    args = parser.parse_args()

    files = sorted(MIGRATIONS.glob("*.sql"))
    dsn = os.environ.get("DATABASE_URL", "dbname=antifraud")

    # autocommit, so that each `with conn.transaction()` below is a real BEGIN ...
    # COMMIT. Without it, psycopg opens a transaction at the first query, and every
    # transaction() after that is only a savepoint inside it: a failure in 004
    # would roll back 001-003 with it.
    with psycopg.connect(dsn, autocommit=True, options="-c timezone=UTC") as conn:
        # held until the connection closes
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}

        if args.baseline:
            baseline(conn, files, applied)
            return

        if not applied and table_exists(conn, "players"):
            # The schema is there but nothing is recorded: migrated by hand, before
            # this runner. Running 001 again would fail on "relation already exists".
            sys.exit("this database has tables but no record of migrations - it was migrated by "
                     "hand.\nIf every file in db/migrations has been applied to it, run once with "
                     "--baseline.")

        pending = [f for f in files if f.name not in applied]
        if not pending:
            print(f"up to date - {len(applied)} migrations applied")
            return
        for f in pending:
            apply(conn, f)
        print(f"done - applied {len(pending)}, {len(applied) + len(pending)} in total")


def apply(conn: psycopg.Connection, f: Path) -> None:
    print(f"applying {f.name}", flush=True)
    try:
        # One transaction: the file and its schema_migrations row commit together,
        # or neither does. With no parameters, psycopg sends the whole file as one
        # query, so a file of many statements runs as written.
        with conn.transaction():
            conn.execute(f.read_text())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,))
    except psycopg.Error as exc:
        sys.exit(f"{f.name} failed and was rolled back - nothing after it was tried:\n{exc}")


def baseline(conn: psycopg.Connection, files: list[Path], applied: set[str]) -> None:
    new = [f.name for f in files if f.name not in applied]
    with conn.transaction():
        for name in new:
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (name,))
    print(f"recorded {len(new)} migrations as applied, ran none: {', '.join(new) or '-'}")


def table_exists(conn: psycopg.Connection, name: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()[0]


if __name__ == "__main__":
    main()
