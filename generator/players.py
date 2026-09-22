# players, sessions, payment methods
#
# Every player dict carries a "clock": the time of that player's latest action.
# A new action must happen after the clock, so a player's rows are always in the
# right order (no deposit before registration, no bet before deposit).
#
# The archetype is NOT stored anywhere. It is derived from the seed and the player
# id, so backfill and the live generator always agree on who is a high-roller
# without a column that a detection rule could cheat by reading.

import random
from datetime import timedelta

import config
import helpers


def archetype_for(player_id):
    """Which archetype this player is. Derived, never stored: the same seed and the
    same player id always give the same answer, in any process, in any order."""
    rng = random.Random(f"{config.SEED}:{player_id}")
    weights = {name: a["weight"] for name, a in config.ARCHETYPES.items()}
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def create_players(conn, hour, all_players):
    """Register this hour's new players. Returns them - they are active this hour."""
    new_players = []

    for _ in range(helpers.how_many(config.NEW_PLAYERS_PER_HOUR, hour)):
        # Registration no later than :50, so the sign-up flow finishes inside the hour.
        registered_at = helpers.random_time_in_hour(hour, max_second=3000)

        housemate = None
        if all_players and helpers.chance(config.HOUSEHOLD_CHANCE):
            housemate = random.choice(all_players)

        if housemate:
            country = housemate["country"]
            ip = housemate["ip"]
        else:
            country = random.choice(config.COUNTRIES)
            ip = helpers.random_ip()
        currency = config.CURRENCY_BY_COUNTRY[country]

        if housemate and helpers.chance(config.HOUSEHOLD_SHARES_DEVICE):
            device_id = housemate["device_id"]
            user_agent = housemate["user_agent"]
        else:
            device_id = helpers.random_device_id()
            user_agent = random.choice(config.USER_AGENTS)

        player_id = conn.execute(
            """
            INSERT INTO players (registered_at, country, currency)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (registered_at, country, currency),
        ).fetchone()[0]

        archetype = archetype_for(player_id)

        player = {
            "id": player_id,
            "country": country,
            "currency": currency,
            "archetype": archetype,      # memory only, never stored in the database
            "ip": ip,
            "device_id": device_id,
            "user_agent": user_agent,
            "clock": registered_at,
        }

        player["session_id"] = insert_session(conn, player, registered_at, ip)

        # Payment method is added 30 s - 5 min after registering.
        added_at = registered_at + timedelta(seconds=random.randint(30, 300))
        add_payment_method(conn, player, added_at, housemate)
        player["clock"] = added_at

        all_players.append(player)
        new_players.append(player)

    return new_players


def add_payment_method(conn, player, added_at, housemate=None):
    shares_card = (
        housemate is not None
        and housemate["method_type"] == "card"
        and helpers.chance(config.HOUSEHOLD_SHARES_CARD)
    )
    if shares_card:
        method_type = "card"
        fingerprint = housemate["fingerprint"]
        last4 = housemate["last4"]
    else:
        method_type = helpers.pick_weighted(config.PAYMENT_TYPES)
        fingerprint = helpers.random_fingerprint()
        last4 = helpers.random_last4() if method_type == "card" else None

    method_id = conn.execute(
        """
        INSERT INTO payment_methods (player_id, type, fingerprint, last4, added_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (player["id"], method_type, fingerprint, last4, added_at),
    ).fetchone()[0]

    player["method_id"] = method_id
    player["method_type"] = method_type
    player["fingerprint"] = fingerprint
    player["last4"] = last4


def create_sessions(conn, hour, all_players):
    """Some existing players log in this hour. Returns the ones who did."""
    active = []

    for player in all_players:
        login_chance = config.ARCHETYPES[player["archetype"]]["login_chance"]
        if not helpers.chance(login_chance * helpers.intensity(hour)):
            continue

        started_at = helpers.random_time_in_hour(hour, max_second=3000)
        if started_at <= player["clock"]:
            continue     # still busy with something from before - no login this hour

        if helpers.chance(config.NEW_IP_CHANCE):
            ip = helpers.random_ip()
        else:
            ip = player["ip"]

        player["session_id"] = insert_session(conn, player, started_at, ip)
        player["clock"] = started_at
        active.append(player)

    return active


def insert_session(conn, player, started_at, ip):
    return conn.execute(
        """
        INSERT INTO sessions (player_id, started_at, ip, device_id, user_agent)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (player["id"], started_at, ip, player["device_id"], player["user_agent"]),
    ).fetchone()[0]


def close_sessions(conn, active_players, hour_end):
    """End of the hour: each session ends a little after the player's last action."""
    for player in active_players:
        ended_at = player["clock"] + timedelta(seconds=random.randint(60, 900))
        ended_at = min(ended_at, hour_end)
        conn.execute(
            "UPDATE sessions SET ended_at = %s WHERE id = %s",
            (ended_at, player["session_id"]),
        )
