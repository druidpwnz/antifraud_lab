# the main loop - run this:  cd generator && python backfill.py

import random
import sys
from datetime import timedelta

import betting
import config
import db
import events
import payments
import players
import settlement


random.seed(config.SEED)

end = config.END
start = end - timedelta(days=config.DAYS)

all_players = []
balances = {}
pending_withdrawals = []
event_probs = {}        # event_id -> true outcome probabilities, memory only

with db.connect() as conn:
    if conn.execute("SELECT EXISTS (SELECT 1 FROM players)").fetchone()[0]:
        sys.exit("database is not empty - run ./reset.sh first")

    # matches for the first days, so the loop has something to bet on from hour one
    for day_offset in range(config.FIXTURE_DAYS_AHEAD + 1):
        events.create_fixtures_for_day(conn, start, start + timedelta(days=day_offset), event_probs)

    hour = start
    while hour < end:
        hour_end = hour + timedelta(hours=1)

        if hour.hour == 0:
            # keep the schedule FIXTURE_DAYS_AHEAD days ahead of today
            events.create_fixtures_for_day(
                conn, hour, hour + timedelta(days=config.FIXTURE_DAYS_AHEAD + 1), event_probs
            )

        # matches finish and bets are paid before anyone acts, so winnings are
        # credited before they can be staked again
        payments.process_withdrawals(conn, hour, pending_withdrawals)
        settlement.finish_events(conn, hour, event_probs)
        settlement.settle_bets(conn, hour, balances)

        active = players.create_sessions(conn, hour, all_players)
        active += players.create_players(conn, hour, all_players)
        events.move_odds(conn, hour)
        payments.create_deposits(conn, hour_end, active, balances)
        open_selections = betting.load_open_selections(conn, hour_end)
        betting.create_bets(conn, hour_end, active, balances, open_selections)

        payments.create_withdrawals(conn, hour_end, active, balances, pending_withdrawals)

        players.close_sessions(conn, active, hour_end)

        if hour.hour == 23:
            conn.commit()     # once per simulated day
            print("done", hour.date(), "players:", len(all_players), "events:", len(event_probs))

        hour = hour_end

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
