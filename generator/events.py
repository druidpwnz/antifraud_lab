# fixtures, markets, selections, odds
#
# Fixtures are created a few days ahead, so there are always matches to bet on.
#
# The true probabilities are never stored. They are DERIVED from the seed and the
# event id, so settlement can recompute them for any event - including a match
# created by the backfill and settled hours later by the live generator, in a
# different process. Same rule as players.archetype_for().

import random
from decimal import Decimal

import config
import helpers


def create_fixtures_for_day(conn, created_at, day):
    """Create the matches played on `day`. Returns how many were created."""
    count = config.FIXTURES_PER_DAY
    if day.weekday() >= 5:
        count = int(count * config.WEEKEND_FIXTURE_MULTIPLIER)

    busy_teams = set()          # a team plays at most one match per day
    created = 0

    for _ in range(count):
        league = random.choice(list(config.LEAGUES))
        free = [t for t in config.LEAGUES[league] if t not in busy_teams]
        if len(free) < 2:
            continue
        home, away = random.sample(free, 2)
        busy_teams.update((home, away))

        kickoff_hour, kickoff_minute = random.choice(config.KICKOFF_TIMES)
        start_time = day.replace(hour=kickoff_hour, minute=kickoff_minute,
                                 second=0, microsecond=0)

        event_id = conn.execute(
            """
            INSERT INTO events (sport, league, home_team, away_team, start_time)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (config.SPORT, league, home, away, start_time),
        ).fetchone()[0]

        create_markets(conn, event_id, home, away, probabilities_for(event_id), created_at)
        created += 1

    return created


def probabilities_for(event_id):
    """Expected goals for each team, and the outcome chances that follow from them.

    Every market is priced from ONE model: goals are Poisson-distributed with these
    two averages. Settlement draws the real score from the same two numbers, so the
    prices and the results agree and the bookmaker keeps its margin. Pricing each
    market from an unrelated random number would hand players a winning edge on
    over/under and both-teams-to-score.

    Derived from (seed, event_id) rather than drawn from the global random stream,
    so any process can recompute it for any event at any time.
    """
    rng = random.Random(f"{config.SEED}:event:{event_id}")
    home_goals_avg = rng.uniform(0.9, 2.3)        # home advantage: a bit higher
    away_goals_avg = rng.uniform(0.6, 1.9)

    home_pmf = [helpers.poisson_pmf(home_goals_avg, k) for k in range(config.MAX_GOALS + 1)]
    away_pmf = [helpers.poisson_pmf(away_goals_avg, k) for k in range(config.MAX_GOALS + 1)]

    p_home = p_draw = p_away = p_over25 = 0.0
    for home_goals, chance_home in enumerate(home_pmf):
        for away_goals, chance_away in enumerate(away_pmf):
            both = chance_home * chance_away
            if home_goals > away_goals:
                p_home += both
            elif home_goals == away_goals:
                p_draw += both
            else:
                p_away += both
            if home_goals + away_goals > 2:
                p_over25 += both

    total = p_home + p_draw + p_away          # renormalise: goals above MAX_GOALS are cut off
    return {
        "home_goals_avg": home_goals_avg,
        "away_goals_avg": away_goals_avg,
        "home": p_home / total,
        "draw": p_draw / total,
        "away": p_away / total,
        "over25": p_over25 / total,
        "btts_yes": (1 - home_pmf[0]) * (1 - away_pmf[0]) / total,
    }


def create_markets(conn, event_id, home, away, probabilities, created_at):
    p = probabilities

    market_id = insert_market(conn, event_id, "1x2", Decimal("0"))
    insert_selection(conn, market_id, "home", home, p["home"], created_at)
    insert_selection(conn, market_id, "draw", "Draw", p["draw"], created_at)
    insert_selection(conn, market_id, "away", away, p["away"], created_at)

    market_id = insert_market(conn, event_id, "total_goals", Decimal("2.5"))
    insert_selection(conn, market_id, "over", "Over 2.5", p["over25"], created_at)
    insert_selection(conn, market_id, "under", "Under 2.5", 1 - p["over25"], created_at)

    market_id = insert_market(conn, event_id, "both_teams_score", Decimal("0"))
    insert_selection(conn, market_id, "yes", "Yes", p["btts_yes"], created_at)
    insert_selection(conn, market_id, "no", "No", 1 - p["btts_yes"], created_at)


def insert_market(conn, event_id, market_type, line):
    return conn.execute(
        "INSERT INTO markets (event_id, type, line) VALUES (%s, %s, %s) RETURNING id",
        (event_id, market_type, line),
    ).fetchone()[0]


def insert_selection(conn, market_id, outcome, name, probability, created_at):
    odds = odds_from_probability(probability)
    selection_id = conn.execute(
        """
        INSERT INTO selections (market_id, outcome, name, current_odds)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (market_id, outcome, name, odds),
    ).fetchone()[0]
    insert_odds_history(conn, selection_id, odds, created_at)
    return selection_id


def odds_from_probability(probability):
    """Decimal odds including the bookmaker margin: 1 / (probability * MARGIN)."""
    value = Decimal(1) / (Decimal(str(probability)) * Decimal(str(config.MARGIN)))
    return max(value.quantize(Decimal("0.01")), Decimal("1.01"))


def insert_odds_history(conn, selection_id, odds, changed_at):
    conn.execute(
        "INSERT INTO odds_history (selection_id, odds, changed_at) VALUES (%s, %s, %s)",
        (selection_id, odds, changed_at),
    )


def move_odds(conn, tick):
    """Odds drift on upcoming matches: every tick a few selections change price."""
    rows = conn.execute(
        """
        SELECT s.id, s.current_odds
        FROM selections s
        JOIN markets m ON m.id = s.market_id
        JOIN events e  ON e.id = m.event_id
        WHERE e.status = 'scheduled'
          AND e.start_time > %s
          AND s.status = 'open'
        ORDER BY s.id
        """,
        (tick,),
    ).fetchall()

    chance = helpers.per_tick(config.ODDS_MOVE_CHANCE)
    for selection_id, odds in rows:
        if not helpers.chance(chance):
            continue

        factor = Decimal(str(round(random.uniform(*config.ODDS_MOVE_RANGE), 4)))
        new_odds = max((odds * factor).quantize(Decimal("0.01")), Decimal("1.01"))
        if new_odds == odds:
            continue

        # second 0 of the tick belongs to fixture creation, so moves start at second 1
        # and each selection moves at most once per tick: (selection_id, changed_at) is UNIQUE
        changed_at = helpers.random_time_in_tick(tick, min_second=1)

        conn.execute(
            "UPDATE selections SET current_odds = %s WHERE id = %s",
            (new_odds, selection_id),
        )
        insert_odds_history(conn, selection_id, new_odds, changed_at)
