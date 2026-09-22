#!/bin/bash

dropdb --if-exists antifraud
createdb antifraud

for f in db/migrations/*.sql; do
    psql antifraud -v ON_ERROR_STOP=1 --single-transaction -f "$f"
done
