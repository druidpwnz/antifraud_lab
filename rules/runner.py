"""The rules runner - run it:  cd rules && python runner.py

After changing a rule:  python runner.py --rescan RULE_CODE  - the running runner
then reads that rule's whole source table again, with the new version.

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

import argparse
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from prometheus_client import Counter, Gauge, Histogram, Info, disable_created_metrics, start_http_server
from psycopg import sql

DSN = os.environ.get("DATABASE_URL", "dbname=antifraud")
RUN_EVERY_SECONDS = float(os.environ.get("RUN_EVERY_SECONDS", "60"))
# Prometheus metrics on this port (compose: 9100, not published); 0 = off
METRICS_PORT = int(os.environ.get("METRICS_PORT", "0") or 0)
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

# Without this, every counter gets a second series, <name>_created, holding when the
# counter was made. Nothing here uses it; off, there are half as many series.
disable_created_metrics()
BUILD = Info("antifraud_build", "Source revision baked into this image.")
BUILD.info({"version": os.environ.get("BUILD_VERSION", "local")})

# --- metrics. Labels: rule_code and severity only - a fixed, small set. Never a
#     player or a bet: every label value is a time series of its own. ---
ALERTS = Counter("rules_alerts_created_total", "Alerts written, by rule.", ["rule_code", "severity"])
SCANNED = Counter("rules_rows_scanned_total", "Source rows looked at, by rule.", ["rule_code"])
RUNS = Counter("rules_runs_total", "Runs of all rules, by outcome.", ["outcome"])
RUN_DURATION = Histogram("rules_run_duration_seconds", "Time for one run of all rules.")
LAST_SUCCESS = Gauge("rules_last_success_timestamp_seconds",
                     "When a run last finished without an error (Unix time).")
# Every series exists from the start, at 0: an alert on "no LATE_BET alerts for a
# day" must see a 0, not nothing at all.
for _rule in RULES:
    ALERTS.labels(_rule.code, _rule.severity)
    SCANNED.labels(_rule.code)
for _outcome in ("ok", "failed"):
    RUNS.labels(_outcome)


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


def rescan(conn: psycopg.Connection, code: str) -> None:
    """Send a rule back to the first row. For after the rule has changed: rows it
    already read are read again, by the new version. Alerts it already raised are
    not doubled - ON CONFLICT DO NOTHING - and keep the details they were written with."""
    if code not in {rule.code for rule in RULES}:
        sys.exit(f"unknown rule {code!r} - known: {', '.join(r.code for r in RULES)}")
    # Waits for a run in progress (it holds the row FOR UPDATE), so the run cannot
    # overwrite the 0 with its own upto a moment later.
    conn.execute(
        "UPDATE rule_state SET last_id = 0, updated_at = now() WHERE rule_code = %s", (code,)
    )


def record(rule: Rule, result: Result) -> None:
    """Count a rule's run - only once its transaction has committed, so the
    metrics never show alerts that were rolled back."""
    ALERTS.labels(rule.code, rule.severity).inc(result.created)
    SCANNED.labels(rule.code).inc(result.scanned)


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
            record(rule, result)
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
    parser = argparse.ArgumentParser(description="Antifraud Lab rules runner.")
    parser.add_argument("--rescan", metavar="RULE_CODE",
                        help="send one rule back to the first row, then exit; "
                             "the running runner reads everything again on its next run")
    args = parser.parse_args()
    if args.rescan:
        with psycopg.connect(DSN, options="-c timezone=UTC") as conn:
            rescan(conn, args.rescan)
        print(f"{args.rescan}: back to the first row - the next run reads it all again", flush=True)
        return

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if METRICS_PORT:
        start_http_server(METRICS_PORT)
    print(f"rules: {', '.join(r.code for r in RULES)} - every {RUN_EVERY_SECONDS:g}s", flush=True)

    while running:
        started = time.monotonic()
        try:
            with RUN_DURATION.time():
                run_all()
            RUNS.labels("ok").inc()
            LAST_SUCCESS.set_to_current_time()
        except psycopg.OperationalError as exc:
            # Postgres down or restarting: say so and try again next time, rather
            # than crash - the next run picks up from rule_state, nothing is lost.
            # LAST_SUCCESS stops moving, which is what the "runner stale" alert sees.
            RUNS.labels("failed").inc()
            print(f"database unavailable, will retry: {str(exc).strip().splitlines()[0]}",
                  file=sys.stderr, flush=True)
        nap(RUN_EVERY_SECONDS - (time.monotonic() - started))

    print("stopped cleanly", flush=True)


if __name__ == "__main__":
    main()
