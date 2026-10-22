"""The rules runner - run it:  cd rules && python runner.py

Every RUN_EVERY_SECONDS it runs each detection rule once over the rows that have
arrived since its last run, and writes what it finds into `alerts`.

A rule is a plain SELECT in sql/<rule>.sql. It gets two parameters, %(last_id)s and
%(upto)s, and must look only at rows of its source table with an id in that range;
it returns one row per finding: player_id, source_id (the row the finding is about),
window_start, window_end, details. The
runner wraps it in an INSERT, so a rule file can be pasted into psql to see what it
would find.

Rules never read fraud_labels. That table is how planted fraud is scored afterwards
(db/scoring.sql) - a rule that read it would be scoring itself.
"""

import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

DSN = os.environ.get("DATABASE_URL", "dbname=antifraud")
RUN_EVERY_SECONDS = float(os.environ.get("RUN_EVERY_SECONDS", "60"))
SQL_DIR = Path(__file__).parent / "sql"


@dataclass(frozen=True)
class Rule:
    code: str          # alerts.rule_code
    severity: str      # alerts.severity
    source: str        # the table whose ids the rule walks through

    def query(self) -> str:
        text = (SQL_DIR / f"{self.code.lower()}.sql").read_text().strip()
        return text.removesuffix(";")


RULES = [
    Rule("SETTLEMENT_MISMATCH", "high", "settlements"),
    Rule("LATE_BET", "high", "bets"),
    Rule("STAKE_ANOMALY", "medium", "bets"),
]


@dataclass(frozen=True)
class Result:
    rule: str
    scanned: int       # source rows looked at this run
    created: int       # new alerts
    upto: int          # rule_state.last_id after the run


def run_rule(conn: psycopg.Connection, rule: Rule) -> Result:
    """One rule, once. Runs inside the caller's transaction and does not commit:
    the alerts and the new last_id are saved together, or neither is - a crash
    in between can neither lose rows nor alert on them twice."""
    conn.execute(
        "INSERT INTO rule_state (rule_code) VALUES (%s) ON CONFLICT DO NOTHING", (rule.code,)
    )
    # FOR UPDATE: a second runner started by mistake waits here instead of
    # scanning the same rows at the same time.
    last_id = conn.execute(
        "SELECT last_id FROM rule_state WHERE rule_code = %s FOR UPDATE", (rule.code,)
    ).fetchone()[0]

    source = sql.Identifier(rule.source)
    # Fixed at the start, so rows the generator commits while this runs are left
    # for the next run instead of being half-seen.
    #
    # Safe only because each source table has ONE writer, the generator, which
    # commits its rows in id order. With several writers, a row could commit after
    # a higher id was already passed - and be skipped for good.
    upto = conn.execute(sql.SQL("SELECT coalesce(max(id), 0) FROM {}").format(source)).fetchone()[0]
    if upto <= last_id:
        return Result(rule.code, 0, 0, last_id)

    scanned = conn.execute(
        sql.SQL("SELECT count(*) FROM {} WHERE id > %s AND id <= %s").format(source),
        (last_id, upto),
    ).fetchone()[0]

    # ON CONFLICT DO NOTHING: a finding is unique on (rule_code, player_id,
    # window_start, window_end, source_id) - migration 006 - so the same row found
    # twice is one alert, and two rows at the same moment are two.
    created = conn.execute(
        sql.SQL("""
            INSERT INTO alerts (player_id, source_id, rule_code, severity, window_start, window_end, details)
            SELECT player_id, source_id, %(rule_code)s, %(severity)s, window_start, window_end, details
            FROM (
            {query}
            ) AS found
            ON CONFLICT DO NOTHING
        """).format(query=sql.SQL(rule.query())),
        {"rule_code": rule.code, "severity": rule.severity, "last_id": last_id, "upto": upto},
    ).rowcount

    conn.execute(
        "UPDATE rule_state SET last_id = %s, updated_at = now() WHERE rule_code = %s",
        (upto, rule.code),
    )
    return Result(rule.code, scanned, created, upto)


def run_all(dsn: str = DSN) -> list[Result]:
    """Every rule once, each in its own transaction - one failing rule does not
    hold back the others' alerts."""
    results = []
    # A fresh connection every run: a minute apart it costs nothing, and a
    # Postgres restart in between needs no reconnect logic.
    with psycopg.connect(dsn, options="-c timezone=UTC") as conn:
        for rule in RULES:
            started = time.monotonic()
            with conn.transaction():
                result = run_rule(conn, rule)
            results.append(result)
            if result.scanned:
                print(f"{rule.code}: {result.scanned} new rows, {result.created} alerts, "
                      f"up to id {result.upto}, {time.monotonic() - started:.2f}s", flush=True)
    return results


running = True


def stop(signum, _frame):
    global running
    running = False
    print(f"signal {signum} - stopping after this run", flush=True)


def nap(seconds: float) -> None:
    """Sleep in short pieces, so a stop signal is acted on within a second."""
    end = time.monotonic() + seconds
    while running and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"rules: {', '.join(r.code for r in RULES)} - every {RUN_EVERY_SECONDS:g}s", flush=True)

    while running:
        started = time.monotonic()
        try:
            run_all()
        except psycopg.OperationalError as exc:
            # Postgres down or restarting: say so and try again next time, rather
            # than crash - the next run picks up from rule_state, nothing is lost.
            print(f"database unavailable, will retry: {str(exc).strip().splitlines()[0]}",
                  file=sys.stderr, flush=True)
        nap(RUN_EVERY_SECONDS - (time.monotonic() - started))

    print("stopped cleanly", flush=True)


if __name__ == "__main__":
    main()
