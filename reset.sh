#!/bin/bash
# Drop, recreate and migrate a database.
#     bash reset.sh                   # the main one, antifraud
#     bash reset.sh antifraud_test    # the one the API tests use

DB="${1:-antifraud}"

dropdb --if-exists "$DB"
createdb "$DB"

for f in db/migrations/*.sql; do
    psql "$DB" -v ON_ERROR_STOP=1 --single-transaction -f "$f"
done
