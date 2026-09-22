# deposits, withdrawals
#
# Money is always Decimal, never float. balances is a dict player_id -> Decimal,
# kept in memory: it is the running balance the rest of the generator spends from.

import math
import random
from datetime import timedelta
from decimal import Decimal

import config
import helpers


def create_deposits(conn, hour_end, active_players, balances):
    """Players who are short of money top up. Only approved deposits add to the balance."""
    for player in active_players:
        balance = balances.setdefault(player["id"], Decimal("0.00"))
        settings = config.ARCHETYPES[player["archetype"]]

        if balance >= Decimal(str(settings["low_balance"])):
            continue

        first_deposit = player.get("deposit_count", 0) == 0
        deposit_chance = config.FIRST_DEPOSIT_CHANCE if first_deposit else settings["deposit_chance"]
        if not helpers.chance(deposit_chance):
            continue

        created_at = helpers.after(player, 30, 600, hour_end)
        if created_at is None:
            continue        # no time left in this hour

        amount = helpers.money(
            random.lognormvariate(settings["deposit_mu"], settings["deposit_sigma"]),
            minimum=config.MIN_DEPOSIT,
        )
        status = "rejected" if helpers.chance(config.DEPOSIT_REJECT_RATE) else "approved"

        # The provider answers seconds to minutes later. The player waits for that answer,
        # so their clock moves to processed_at - they cannot bet with money not yet credited.
        processed_at = min(created_at + timedelta(seconds=random.randint(5, 600)), config.END)
        player["clock"] = processed_at

        conn.execute(
            """
            INSERT INTO transactions
                (player_id, method_id, direction, amount, currency, status, created_at, processed_at)
            VALUES (%s, %s, 'deposit', %s, %s, %s, %s, %s)
            """,
            (player["id"], player["method_id"], amount, player["currency"],
             status, created_at, processed_at),
        )

        player["deposit_count"] = player.get("deposit_count", 0) + 1
        if status == "approved":
            balances[player["id"]] = balance + amount


def create_withdrawals(conn, hour_end, active_players, balances, pending_withdrawals):
    """Players sitting on a decent balance cash out.

    A withdrawal is created as 'pending' with no processed_at - that is what the
    CHECK in the schema demands - and the money leaves the balance immediately,
    the way a real operator reserves it. It is approved hours later.
    """
    for player in active_players:
        balance = balances.get(player["id"], Decimal("0.00"))
        settings = config.ARCHETYPES[player["archetype"]]
        typical_deposit = Decimal(str(round(math.exp(settings["deposit_mu"]), 2)))

        if balance < typical_deposit * Decimal(str(config.WITHDRAWAL_BALANCE_MULTIPLIER)):
            continue
        if not helpers.chance(config.WITHDRAWAL_CHANCE):
            continue

        created_at = helpers.after(player, 30, 900, hour_end)
        if created_at is None:
            continue

        share = Decimal(str(round(random.uniform(*config.WITHDRAWAL_SHARE), 4)))
        amount = min(helpers.money(balance * share, minimum=config.MIN_WITHDRAWAL), balance)

        transaction_id = conn.execute(
            """
            INSERT INTO transactions
                (player_id, method_id, direction, amount, currency, status, created_at)
            VALUES (%s, %s, 'withdrawal', %s, %s, 'pending', %s)
            RETURNING id
            """,
            (player["id"], player["method_id"], amount, player["currency"], created_at),
        ).fetchone()[0]

        balances[player["id"]] = balance - amount

        due_at = created_at + timedelta(hours=random.randint(*config.WITHDRAWAL_DELAY_HOURS))
        pending_withdrawals.append((due_at, transaction_id))


def process_withdrawals(conn, hour, pending_withdrawals):
    """Approve the withdrawals whose turn has come. Anything still waiting when the
    backfill ends simply stays pending - which is what a real database looks like."""
    still_waiting = []
    for due_at, transaction_id in pending_withdrawals:
        if due_at <= hour:
            conn.execute(
                """
                UPDATE transactions
                SET status = 'approved', processed_at = %s
                WHERE id = %s
                """,
                (due_at, transaction_id),
            )
        else:
            still_waiting.append((due_at, transaction_id))
    pending_withdrawals[:] = still_waiting
