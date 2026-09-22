# intensity(), random helpers

import hashlib
import ipaddress
import math
import random
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP


HOUR_WEIGHTS = {
    0: 0.5, 1: 0.3, 2: 0.2, 3: 0.1, 4: 0.1, 5: 0.1,
    6: 0.2, 7: 0.3, 8: 0.4, 9: 0.5, 10: 0.6, 11: 0.7,
    12: 0.8, 13: 0.8, 14: 0.9, 15: 1.0, 16: 1.1, 17: 1.3,
    18: 1.5, 19: 1.8, 20: 2.0, 21: 2.0, 22: 1.5, 23: 1.0,
}

def intensity(dt):
    weight = HOUR_WEIGHTS[dt.hour]
    if dt.weekday() >= 5:          # Saturday, Sunday
        weight = weight * 1.4
    return weight

def poisson(mean):
    """Random count with this average - the standard model for "how many events
    in a time window" (arrivals per hour, goals per match). Knuth's algorithm."""
    limit = math.exp(-mean)
    count = 0
    product = random.random()
    while product > limit:
        count += 1
        product *= random.random()
    return count


def poisson_pmf(mean, k):
    """Chance of exactly k, for a Poisson with this average."""
    return math.exp(-mean) * mean ** k / math.factorial(k)


def how_many(per_hour, dt):
    # The old int(expected * noise) always returned 0 when expected was below ~0.7,
    # so nobody ever registered between 03:00 and 06:00.
    return poisson(per_hour * intensity(dt))


def chance(probability):
    return random.random() < probability

def pick_weighted(weights):
    # weights: dict like {"card": 70, "crypto": 15, "bank": 15}
    return random.choices(list(weights), weights=list(weights.values()))[0]

def random_time_in_hour(hour_start, min_second=0, max_second=3599):
    return hour_start + timedelta(seconds=random.randint(min_second, max_second))


# All random values go through `random`, so they follow the seed.
# (uuid.uuid4() and os.urandom() ignore the seed - never use them here.)

def random_ip():
    return ipaddress.ip_address(
        f"{random.randint(1, 223)}.{random.randint(0, 255)}."
        f"{random.randint(0, 255)}.{random.randint(1, 254)}"
    )

def random_device_id():
    return uuid.UUID(int=random.getrandbits(128), version=4)

def random_fingerprint():
    return hashlib.sha256(random.randbytes(16)).hexdigest()   # 64 hex chars

def random_last4():
    return f"{random.randint(0, 9999):04d}"


def money(value, minimum="0.01"):
    """Money as Decimal with 2 decimals - never float, or settlement maths drifts."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return max(amount, Decimal(minimum))


def after(player, min_seconds, max_seconds, limit):
    """Next timestamp for this player, `min_seconds`..`max_seconds` after their last
    action. Returns None if that would fall outside the current hour, so the player
    simply does nothing more this hour."""
    moment = player["clock"] + timedelta(seconds=random.randint(min_seconds, max_seconds))
    if moment >= limit:
        return None
    player["clock"] = moment
    return moment
