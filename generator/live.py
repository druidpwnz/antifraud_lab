# the live generator - run after backfill:  cd generator && python live.py
#
# Carries on from wherever sim_state says the backfill stopped, one simulated hour
# at a time, sleeping between hours so the data arrives at a watchable rate.
#
# It runs tick.one_hour(), the same function backfill.py runs, so the two modes
# cannot drift apart. Everything it needs that the backfill held in memory is either
# read back from the database (state.load) or derived from the seed and a row id.

import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import config
import db
import state
import tick


def setting(name, default, cast=float):
    return cast(os.environ.get(name, default))


REAL_SECONDS_PER_SIM_HOUR = setting("REAL_SECONDS_PER_SIM_HOUR", config.REAL_SECONDS_PER_SIM_HOUR)
CATCH_UP = setting("CATCH_UP", int(config.CATCH_UP), int) == 1

running = True


def stop(signum, _frame):
    """SIGTERM/SIGINT: finish the hour in progress, commit, then exit."""
    global running
    running = False
    print(f"signal {signum} - finishing this hour", flush=True)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


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

    while running:
        started = time.monotonic()
        tick.one_hour(conn, sim_time, all_players, balances)
        sim_time = sim_time + timedelta(hours=1)

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

        behind = datetime.now(timezone.utc) - sim_time
        if CATCH_UP and behind > timedelta(hours=1):
            # still in the past: no sleep, get to the present first
            if sim_time.hour == 0:
                print(f"catching up: {sim_time.date()}, {behind.days} days behind", flush=True)
            continue

        print(f"{sim_time}  players {len(all_players)}  "
              f"took {time.monotonic() - started:.1f}s", flush=True)
        time.sleep(max(0.0, REAL_SECONDS_PER_SIM_HOUR - (time.monotonic() - started)))

print("stopped cleanly")
