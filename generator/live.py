# the live generator - run after backfill:  cd generator && python live.py
#
# Carries on from wherever sim_state says the backfill stopped, one tick
# (config.TICK_MINUTES of simulated time) at a time:
#   behind the real clock  - CATCH_UP=1: flat out until it is not;
#                            CATCH_UP=0: at REAL_SECONDS_PER_SIM_HOUR per simulated hour
#   caught up              - a tick is written once its sessions are over in the real
#                            world - the end of the tick plus helpers.SPILL - so
#                            nothing it writes is ever in the future
#
# It runs tick.one_tick(), the same function backfill.py runs, so the two modes
# cannot drift apart. Everything it needs that the backfill held in memory is either
# read back from the database (state.load) or derived from the seed and a row id.

import os
import random
import signal
import sys
import time
from datetime import UTC, datetime, timedelta

import config
import db
import helpers
import metrics
import state
import tick


def setting(name, default, cast=float):
    return cast(os.environ.get(name, default))


REAL_SECONDS_PER_SIM_HOUR = setting("REAL_SECONDS_PER_SIM_HOUR", config.REAL_SECONDS_PER_SIM_HOUR)
CATCH_UP = setting("CATCH_UP", int(config.CATCH_UP), int) == 1
# Prometheus metrics on this port (compose: 9100, not published); 0 = off
METRICS_PORT = setting("METRICS_PORT", "0", lambda v: int(v or 0))

running = True


def stop(signum, _frame):
    """SIGTERM/SIGINT: finish the tick in progress, commit, then exit."""
    global running
    running = False
    print(f"signal {signum} - finishing this tick", flush=True)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def nap(seconds):
    """Sleep, in short pieces: a stop signal does not cut a time.sleep() short, and
    waiting out the rest of a tick could outlast Docker's stop_grace_period."""
    end = time.monotonic() + seconds
    while running and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


with db.connect() as conn:
    row = conn.execute("SELECT sim_time FROM sim_state WHERE id = 1").fetchone()
    if row is None:
        sys.exit("sim_state is empty - run backfill.py first")
    sim_time = row[0]

    # The backfill's random state is long gone. Seeding from the resume point keeps
    # a restart at the same sim_time reproducible without repeating the backfill.
    random.seed(f"{config.SEED}:live:{sim_time.isoformat()}")

    all_players, balances = state.load(conn, sim_time)
    print(f"resuming at {sim_time} with {len(all_players)} players, "
          f"{sum(1 for b in balances.values() if b > 0)} of them funded", flush=True)

    # seconds per tick when catching up slowly (CATCH_UP=0)
    pace = REAL_SECONDS_PER_SIM_HOUR * helpers.TICK_SHARE
    caught_up = False

    metrics.start(METRICS_PORT, sim_time)
    ids = metrics.newest_ids(conn)

    while running:
        tick_end = sim_time + helpers.TICK
        wait = tick_end + helpers.SPILL - datetime.now(UTC)
        if wait > timedelta(0):
            # The tick's sessions are not over in the real world yet. Generating it now would
            # write sessions, bets and settlements stamped in the future - and the
            # one after it further still, at 300x real time with the defaults.
            if not caught_up:
                print(f"up to date - from now on each {config.TICK_MINUTES}-minute tick is "
                      f"written once its sessions are over; next at "
                      f"{tick_end + helpers.SPILL:%H:%M} UTC", flush=True)
                caught_up = True
            nap(wait.total_seconds())
            continue

        started = time.monotonic()
        tick.one_tick(conn, sim_time, all_players, balances)
        sim_time = tick_end

        conn.execute(
            """
            INSERT INTO sim_state (id, sim_time, seed, days, updated_at)
            VALUES (1, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE
            SET sim_time = EXCLUDED.sim_time, updated_at = now()
            """,
            (sim_time, config.SEED, config.DAYS),
        )
        conn.commit()

        behind = datetime.now(UTC) - sim_time
        ids_now = metrics.newest_ids(conn)
        metrics.tick_written(ids, ids_now, time.monotonic() - started, sim_time,
                             catching_up=behind > helpers.TICK + helpers.SPILL)
        ids = ids_now
        if behind <= helpers.TICK + helpers.SPILL:
            # caught up: the loop's next turn waits for the next tick to end
            print(f"{sim_time}  players {len(all_players)}  "
                  f"took {time.monotonic() - started:.1f}s", flush=True)
            continue

        if CATCH_UP:
            # still in the past: no sleep, get to the present first
            if sim_time.hour == 0 and sim_time.minute == 0:
                print(f"catching up: {sim_time.date()}, {behind.days} days behind", flush=True)
            continue

        if sim_time.minute == 0:
            print(f"{sim_time}  players {len(all_players)}  {behind.days} days behind",
                  flush=True)
        nap(pace - (time.monotonic() - started))

print("stopped cleanly")
