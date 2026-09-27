# all numbers and lists in one place

from datetime import datetime, timezone

DSN = "dbname=antifraud"
SEED = 42

# The simulation ends at a FIXED moment, never datetime.now().
# Same SEED + same END = exactly the same data on every run (CI depends on this).
END = datetime(2026, 9, 1, tzinfo=timezone.utc)   # must be midnight UTC
DAYS = 14                 

NEW_PLAYERS_PER_HOUR = 5
COUNTRIES = ["UA", "PL", "DE", "GB", "ES"]
CURRENCY_BY_COUNTRY = {"UA": "UAH", "PL": "PLN", "DE": "EUR", "GB": "GBP", "ES": "EUR"}

# weight = share of new players; login_chance = chance to log in during an average hour
# weight       - share of new players
# login_chance - chance to log in during an average hour
# deposit_mu / stake_mu etc - log-normal amounts: median is exp(mu), a few are much bigger
# low_balance  - below this the player tops up
ARCHETYPES = {
    "casual": {
        "weight": 70, "login_chance": 0.02,
        "deposit_mu": 3.0, "deposit_sigma": 0.6, "low_balance": 20, "deposit_chance": 0.55,
        "bets_per_session": (1, 2), "stake_mu": 1.6, "stake_sigma": 0.7,
    },
    "regular": {
        "weight": 25, "login_chance": 0.06,
        "deposit_mu": 4.0, "deposit_sigma": 0.6, "low_balance": 60, "deposit_chance": 0.65,
        "bets_per_session": (2, 4), "stake_mu": 2.5, "stake_sigma": 0.7,
    },
    "highroller": {
        "weight": 5, "login_chance": 0.12,
        "deposit_mu": 6.0, "deposit_sigma": 0.7, "low_balance": 400, "deposit_chance": 0.75,
        "bets_per_session": (3, 6), "stake_mu": 4.5, "stake_sigma": 0.7,
    },
}

PAYMENT_TYPES = {"card": 70, "crypto": 15, "bank": 15}

# Honest noise, so the linked-accounts rule has real false positives to deal with.
# A "household" player copies the country and IP of an existing player,
# sometimes also their device (family tablet) or card (shared family card).
HOUSEHOLD_CHANCE = 0.03
HOUSEHOLD_SHARES_DEVICE = 0.5
HOUSEHOLD_SHARES_CARD = 0.2

NEW_IP_CHANCE = 0.15     # returning player logs in from another network (mobile, travel)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "BetApp/4.12.0 (Android 13; Pixel 7)",
    "BetApp/4.12.0 (iOS 17.5; iPhone15,2)",
]

# --- Step 3: fixtures, markets, odds -------------------------------------

SPORT = "football"          # football only for now: no draw in tennis means other markets

LEAGUES = {
    "Premier League": ["Arsenal", "Chelsea", "Liverpool", "Manchester City", "Manchester United",
                       "Tottenham", "Newcastle", "Aston Villa", "Brighton", "West Ham"],
    "La Liga":        ["Real Madrid", "Barcelona", "Atletico Madrid", "Sevilla", "Real Sociedad",
                       "Villarreal", "Valencia", "Athletic Bilbao", "Real Betis", "Girona"],
    "Bundesliga":     ["Bayern Munich", "Borussia Dortmund", "RB Leipzig", "Bayer Leverkusen",
                       "Eintracht Frankfurt", "Wolfsburg", "Freiburg", "Union Berlin", "Mainz", "Werder Bremen"],
    "Ekstraklasa":    ["Legia Warszawa", "Lech Poznan", "Rakow Czestochowa", "Pogon Szczecin", "Jagiellonia",
                       "Gornik Zabrze", "Cracovia", "Wisla Plock", "Piast Gliwice", "Widzew Lodz"],
    "Premier Liha":   ["Shakhtar Donetsk", "Dynamo Kyiv", "Zorya Luhansk", "Vorskla Poltava", "Kolos Kovalivka",
                       "Oleksandriya", "Veres Rivne", "Kryvbas", "Rukh Lviv", "Obolon Kyiv"],
}

KICKOFF_TIMES = [(13, 0), (15, 0), (17, 30), (19, 0), (21, 0)]   # UTC

FIXTURES_PER_DAY = 10
WEEKEND_FIXTURE_MULTIPLIER = 1.6
FIXTURE_DAYS_AHEAD = 2       # always at least this many days of upcoming matches

MATCH_MINUTES = 110          # kickoff to final whistle
MAX_GOALS = 10               # goal counts above this are ignored when pricing
MARGIN = 1.06                # bookmaker margin: without it random betting would break even
ODDS_MOVE_CHANCE = 0.10      # share of upcoming selections whose odds move in an hour
ODDS_MOVE_RANGE = (0.95, 1.05)

# --- Step 4: deposits ----------------------------------------------------

MIN_DEPOSIT = "5.00"
FIRST_DEPOSIT_CHANCE = 0.80      # a new player almost always funds the account
DEPOSIT_REJECT_RATE = 0.08       # declined by the payment provider

# --- Step 5: bets --------------------------------------------------------

MIN_STAKE = "1.00"
COMBO_CHANCE = 0.30          # the rest are singles
COMBO_LEGS = (2, 4)
BET_WINDOW_HOURS = 48        # players bet on matches starting within this window

# --- Step 7: withdrawals -------------------------------------------------

MIN_WITHDRAWAL = "10.00"
WITHDRAWAL_CHANCE = 0.45             # chance a player with money to spare cashes out
WITHDRAWAL_BALANCE_MULTIPLIER = 1.0  # only once the balance is this many typical deposits
WITHDRAWAL_SHARE = (0.3, 1.0)        # how much of the balance goes out (partial cashouts too)
WITHDRAWAL_DELAY_HOURS = (1, 24)     # payouts are not instant

# --- Fraud injection -----------------------------------------------------
# Every planted pattern writes a row to fraud_labels. That table is ground truth
# for scoring the rules afterwards - nothing in rules/ may ever read it.

INJECT_FRAUD = True

# Rate x settlements is what decides whether there is anything to measure.
# 0.005 (~1 in 200) suits DAYS=14; drop to 0.0005 for a 90-day dataset.
SETTLEMENT_ERROR_RATE = 0.005
SETTLEMENT_ERROR_OFFSET = (0.05, 0.40)   # how far off the payout is, as a share

LATE_BET_RATE = 0.01                # chance per active player per hour

# Account takeover shape: a long history of small bets, then one huge one.
# Only ~6% of active player-hours are eligible (needs a betting history AND a balance
# worth emptying), so this rate is much higher than the other patterns' to land a
# comparable number of plants.
STAKE_ESCALATION_RATE = 0.10        # chance per eligible active player per hour
ESCALATION_MIN_BETS = 15            # needs a history first, or there is no anomaly
ESCALATION_MIN_MULTIPLE = 8         # balance must be this many average stakes
ESCALATION_MULTIPLE = (10, 40)      # how many average stakes the big bet is

# --- Live generator ------------------------------------------------------
# Read from the environment so a container can change them without a rebuild;
# these are the defaults when the variable is not set.

REAL_SECONDS_PER_SIM_HOUR = 12      # 3600 = real time, 12 = one sim day per 5 minutes
CATCH_UP = True                     # run flat out until the sim clock reaches now
