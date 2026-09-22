# connect() - the one place that knows how to reach the database

import psycopg

import config


def connect():
    # options=-c timezone=UTC: this connection reads and writes in UTC, whatever
    # timezone the machine running the generator happens to be in.
    return psycopg.connect(config.DSN, options="-c timezone=UTC")


if __name__ == "__main__":
    # quick check:  python db.py
    with connect() as conn:
        print(conn.execute("SELECT 1, now(), current_setting('TimeZone')").fetchone())
