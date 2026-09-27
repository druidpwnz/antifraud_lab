# finishing matches, paying bets
#
# Runs at the START of each hour, before players do anything. A match that kicked off
# more than 2 hours ago is over, its bets are paid, and only then can that money be
# staked again - so a payout is always credited before it can be spent.

import random
from datetime import timedelta
from decimal import Decimal

import config
import events
import fraud
import helpers


def finish_events(conn, hour):
    """Play out every match that is over by now and decide all of its selections."""
    finished = conn.execute(
        """
        SELECT id, start_time
        FROM events
        WHERE status = 'scheduled'
          AND start_time + interval '2 hours' <= %s
        ORDER BY id
        """,
        (hour,),
    ).fetchall()

    for event_id, start_time in finished:
        probabilities = events.probabilities_for(event_id)
        home_goals = min(helpers.poisson(probabilities["home_goals_avg"]), config.MAX_GOALS)
        away_goals = min(helpers.poisson(probabilities["away_goals_avg"]), config.MAX_GOALS)

        selections = conn.execute(
            """
            SELECT s.id, s.outcome, m.type
            FROM selections s
            JOIN markets m ON m.id = s.market_id
            WHERE m.event_id = %s
            ORDER BY s.id
            """,
            (event_id,),
        ).fetchall()

        for selection_id, outcome, market_type in selections:
            won = selection_won(market_type, outcome, home_goals, away_goals)
            conn.execute(
                "UPDATE selections SET status = %s WHERE id = %s",
                ("won" if won else "lost", selection_id),
            )

        conn.execute("UPDATE markets SET status = 'settled' WHERE event_id = %s", (event_id,))
        conn.execute(
            "UPDATE events SET status = 'finished', finished_at = %s WHERE id = %s",
            (start_time + timedelta(minutes=config.MATCH_MINUTES), event_id),
        )


def selection_won(market_type, outcome, home_goals, away_goals):
    """Did this selection win, given the final score?"""
    if market_type == "1x2":
        if home_goals > away_goals:
            return outcome == "home"
        if home_goals < away_goals:
            return outcome == "away"
        return outcome == "draw"

    if market_type == "total_goals":            # the line is 2.5
        return outcome == ("over" if home_goals + away_goals > 2 else "under")

    if market_type == "both_teams_score":
        both_scored = home_goals > 0 and away_goals > 0
        return outcome == ("yes" if both_scored else "no")

    raise ValueError(f"unknown market type: {market_type}")


def settle_bets(conn, hour, balances):
    """Pay every open bet whose legs are all decided."""
    ready = conn.execute(
        """
        SELECT b.id, b.player_id, b.stake, b.total_odds, b.placed_at,
               bool_and(s.status = 'won') AS all_won,
               max(e.finished_at)         AS last_finish
        FROM bets b
        JOIN bet_selections bs ON bs.bet_id = b.id
        JOIN selections s      ON s.id = bs.selection_id
        JOIN markets m         ON m.id = s.market_id
        JOIN events e          ON e.id = m.event_id
        WHERE b.status = 'open'
        GROUP BY b.id, b.player_id, b.stake, b.total_odds, b.placed_at
        HAVING bool_and(s.status <> 'open')
        ORDER BY b.id
        """
    ).fetchall()

    for bet_id, player_id, stake, total_odds, placed_at, all_won, last_finish in ready:
        if all_won:
            result = "won"
            payout = (stake * total_odds).quantize(Decimal("0.01"))
        else:
            result = "lost"
            payout = Decimal("0.00")

        # The operator pays out a minute or ten after the last match ends - but never
        # before the bet was placed. A LATE_BET can be written after the final whistle,
        # and a settlement timestamped earlier than its own bet is nonsense.
        settled_at = min(
            max(last_finish, placed_at) + timedelta(seconds=random.randint(60, 600)),
            hour,
        )

        payout, planted = fraud.break_settlement(result, payout, stake, total_odds)

        settlement_id = conn.execute(
            """
            INSERT INTO settlements (bet_id, result, payout, settled_at)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (bet_id, result, payout, settled_at),
        ).fetchone()[0]

        if planted:
            fraud.label(conn, "settlement", settlement_id, "SETTLEMENT_ERROR",
                        settled_at, planted)
        conn.execute("UPDATE bets SET status = %s WHERE id = %s", (result, bet_id))

        if payout > 0:
            balances[player_id] = balances.get(player_id, Decimal("0.00")) + payout
