#!/bin/bash

dropdb antifraud
createdb antifraud

psql antifraud -v ON_ERROR_STOP=1 --single-transaction -f db/migrations/001_schema.sql