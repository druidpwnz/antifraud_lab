# one simulated hour
#
# Backfill and the live generator run exactly this, so there is one code path and
# no chance of the two modes producing subtly different data. The order matters:
# money arrives (settled bets, approved withdrawals) before anyone can spend it.

from datetime import timedelta

import betting
import config
import events
import fraud
import payments
import players
import settlement


def one_hour(conn, hour, all_players, balances):
    """Run one simulated hour. Returns how many fixtures were created."""
    hour_end = hour + timedelta(hours=1)
    fixtures = 0

    if hour.hour == 0:
        # keep the schedule FIXTURE_DAYS_AHEAD days ahead of today
        fixtures = events.create_fixtures_for_day(
            conn, hour, hour + timedelta(days=config.FIXTURE_DAYS_AHEAD + 1)
        )

    # matches finish, bets are paid and withdrawals clear before anyone acts, so
    # money is credited before it can be staked again
    payments.process_withdrawals(conn, hour)
    settlement.finish_events(conn, hour)
    settlement.settle_bets(conn, hour, balances)

    active = players.create_sessions(conn, hour, all_players)
    active += players.create_players(conn, hour, all_players)

    events.move_odds(conn, hour)
    payments.create_deposits(conn, hour_end, active, balances)

    open_selections = betting.load_open_selections(conn, hour_end)
    betting.create_bets(conn, hour_end, active, balances, open_selections)

    fraud.maybe_late_bets(conn, hour, hour_end, active, balances)
    fraud.maybe_stake_escalation(conn, hour_end, active, balances, open_selections)

    payments.create_withdrawals(conn, hour_end, active, balances)
    players.close_sessions(conn, active, hour_end)

    return fixtures
