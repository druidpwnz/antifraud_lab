# the main loop - run this:  cd generator && python backfill.py
# Re-running it is safe: see the check at the top of the `with` block.

import random
import sys
from datetime import timedelta

import config
import db
import events
import tick


random.seed(config.SEED)

end = config.END
start = end - timedelta(days=config.DAYS)

all_players = []
balances = {}
events_created = 0

with db.connect() as conn:
    # Safe to run again - compose runs it on every `up`. sim_state is written last,
    # after the final day is committed, so it is the "backfill finished" marker:
    #   sim_state has a row          -> done before (the live generator may have
    #                                   moved it on since): nothing to do, exit 0
    #   players but no sim_state     -> a backfill died half-way: stop, loudly
    #   neither                      -> an empty database: generate
    seeded = conn.execute("SELECT sim_time FROM sim_state WHERE id = 1").fetchone()
    if seeded is not None:
        print(f"already seeded, sim_time {seeded[0]} - nothing to do")
        sys.exit(0)
    if conn.execute("SELECT EXISTS (SELECT 1 FROM players)").fetchone()[0]:
        sys.exit("players exist but sim_state is empty: an earlier backfill stopped half-way.\n"
                 "Start again from an empty database: bash reset.sh "
                 "(or, under compose: docker compose down -v)")

    # matches for the first days, so the loop has something to bet on from hour one
    for day_offset in range(config.FIXTURE_DAYS_AHEAD + 1):
        events_created += events.create_fixtures_for_day(
            conn, start, start + timedelta(days=day_offset)
        )

    hour = start
    while hour < end:
        events_created += tick.one_hour(conn, hour, all_players, balances)

        if hour.hour == 23:
            conn.commit()     # once per simulated day
            print("done", hour.date(), "players:", len(all_players), "events:", events_created)

        hour = hour + timedelta(hours=1)

    # remember where the simulated clock stopped, for the live generator
    conn.execute(
        """
        INSERT INTO sim_state (id, sim_time, seed, days)
        VALUES (1, %s, %s, %s)
        """,
        (end, config.SEED, config.DAYS),
    )
    conn.commit()
    print("sim_state:", end)
