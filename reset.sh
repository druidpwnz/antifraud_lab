#!/bin/bash
# Drop, recreate and migrate a database. Run with the venv active (needs psycopg).
#     bash reset.sh                   # the main one, antifraud
#     bash reset.sh antifraud_test    # the one the API tests use
#
# Migrations go through db/migrate.py, the same runner the compose stack uses, so
# the two can never apply them differently.

set -e
DB="${1:-antifraud}"

dropdb --if-exists "$DB"
createdb "$DB"
DATABASE_URL="dbname=$DB" python db/migrate.py
