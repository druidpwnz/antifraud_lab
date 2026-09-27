# the main loop - run this:  cd generator && python backfill.py

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
    if conn.execute("SELECT EXISTS (SELECT 1 FROM players)").fetchone()[0]:
        sys.exit("database is not empty - run ./reset.sh first")

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
