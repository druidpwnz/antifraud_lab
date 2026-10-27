# Prometheus metrics for the live generator
#
# Served on their own port (METRICS_PORT, 9100 in compose, never published); off
# when it is unset, as locally. Only live.py uses them - the backfill is a one-shot.
#
# Labels: `table` only, a fixed list. Never a player or a bet id: every label value
# is a time series of its own.

import os
import time

from prometheus_client import Counter, Gauge, Histogram, Info, disable_created_metrics, start_http_server

# Without this, every counter gets a second series, <name>_created, holding when the
# counter was made. Nothing here uses it; off, there are half as many series.
disable_created_metrics()
BUILD = Info("antifraud_build", "Source revision baked into this image.")
BUILD.info({"version": os.environ.get("BUILD_VERSION", "local")})

# The tables a tick adds rows to, counted by how far their newest id moved. The
# generator is their only writer, so the difference is exactly the rows it wrote.
TABLES = ["players", "sessions", "transactions", "bets", "settlements", "odds_history", "fraud_labels"]

TICKS = Counter("generator_ticks_total", "Ticks written.")
ROWS = Counter("generator_rows_written_total", "Rows written, by table.", ["table"])
TICK_DURATION = Histogram("generator_tick_duration_seconds", "Time to generate and commit one tick.")
SIM_TIME = Gauge("generator_sim_time_seconds", "The simulated clock (Unix time).")
CATCHING_UP = Gauge("generator_catching_up", "1 while catching up to the real clock, 0 once there.")
LAG = Gauge(
    "generator_lag_seconds",
    "How far the simulated clock is behind the real one. 5-10 minutes is normal: a "
    "tick is written once the tick after it has ended.",
)

for _table in TABLES:
    ROWS.labels(_table)          # every series exists from the start, at 0

_sim_time = None


def start(port, sim_time):
    set_sim_time(sim_time)
    # Worked out when Prometheus asks, not when a tick is written: a generator that
    # hangs shows a lag that keeps growing, instead of a value frozen at "fine".
    LAG.set_function(lambda: time.time() - _sim_time if _sim_time else 0.0)
    if port:
        start_http_server(port)


def set_sim_time(sim_time):
    global _sim_time
    _sim_time = sim_time.timestamp()
    SIM_TIME.set(_sim_time)


def newest_ids(conn):
    """{table: its newest id} - one query, an index lookup per table."""
    selects = ", ".join(f"(SELECT coalesce(max(id), 0) FROM {t})" for t in TABLES)
    return dict(zip(TABLES, conn.execute(f"SELECT {selects}").fetchone(), strict=True))


def tick_written(before, after, seconds, sim_time, catching_up):
    TICKS.inc()
    for table in TABLES:
        ROWS.labels(table).inc(after[table] - before[table])
    TICK_DURATION.observe(seconds)
    set_sim_time(sim_time)
    CATCHING_UP.set(1 if catching_up else 0)
