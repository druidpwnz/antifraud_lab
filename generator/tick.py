# one simulated tick - config.TICK_MINUTES of simulated time
#
# Backfill and the live generator run exactly this, so there is one code path and
# no chance of the two modes producing subtly different data. The order matters:
# money arrives (settled bets, approved withdrawals) before anyone can spend it.
#
# Sessions start anywhere in the tick and may run on into the next one, up to
# `limit`. So everything a tick writes is timestamped before limit, and the live
# generator writes a tick once limit has passed in the real world - nothing is ever
# in the future.

from datetime import timedelta

import betting
import config
import events
import fraud
import helpers
import payments
import players
import settlement


def one_tick(conn, tick, all_players, balances):
    """Run one tick, starting at `tick`. Returns how many fixtures were created."""
    tick_end = tick + helpers.TICK
    limit = tick_end + helpers.SPILL       # every session of this tick is over by then
    fixtures = 0

    if tick.hour == 0 and tick.minute == 0:
        # keep the schedule FIXTURE_DAYS_AHEAD days ahead of today
        fixtures = events.create_fixtures_for_day(
            conn, tick, tick + timedelta(days=config.FIXTURE_DAYS_AHEAD + 1)
        )

    # matches finish, bets are paid and withdrawals clear before anyone acts, so
    # money is credited before it can be staked again
    payments.process_withdrawals(conn, tick)
    if settlement.finish_events(conn, tick):
        # A bet can only become payable when one of its matches finishes, so a tick
        # that finished nothing has nothing new to pay - and skipping the query saves
        # the biggest cost that repeats every tick.
        settlement.settle_bets(conn, tick, balances)

    active = players.create_sessions(conn, tick, all_players)
    active += players.create_players(conn, tick, all_players)

    events.move_odds(conn, tick)
    payments.create_deposits(conn, limit, active, balances)

    open_selections = betting.load_open_selections(conn, limit)
    betting.create_bets(conn, limit, active, balances, open_selections)

    fraud.maybe_late_bets(conn, tick, limit, active, balances)
    fraud.maybe_stake_escalation(conn, limit, active, balances, open_selections)

    payments.create_withdrawals(conn, limit, active, balances)
    players.close_sessions(conn, active, limit)

    return fixtures
