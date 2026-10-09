# Backfill Generator — Build Plan

> **This is the original build plan, written for hourly steps.** The generator now
> moves in 5-minute ticks — see "5-minute ticks" in the main [README](../README.md).
> The ideas below still hold; the names changed:
>
> | Here | Now |
> |---|---|
> | the main loop, hour by hour | `tick.one_tick()`, `config.TICK_MINUTES` (5) at a time — backfill and live run the same function |
> | `random_time_in_hour()` | `helpers.random_time_in_tick()` |
> | `how_many(per_hour, dt)` — things per hour | the same rate per hour, scaled to one tick |
> | a login chance per hour | `helpers.per_tick()` turns it into the chance per tick |
> | a session lasts until the end of the hour | a session starts anywhere in its tick and is over by the end of the next one; actions are `ACTION_GAP_SECONDS` apart |
> | settle every hour | settle in a tick that finished a match |

Simple, junior-friendly version: plain functions, one main loop, lists and dicts in
memory, no classes needed. Every step ends with a SQL query to check the work before
moving on.

---

## How the whole thing works

One script walks through time **hour by hour**, from 90 days ago up to now. For every
hour it does the same things in the same order:

1. new players register
2. some players log in (sessions)
3. some of them deposit
4. some of them place bets
5. finished matches get settled, winners get paid
6. some winners withdraw

Doing it in this order inside each hour keeps time correct automatically — nobody bets
before depositing, and no bet is settled before the match is over.

While it runs, it keeps simple Python lists and dicts in memory: all players, their
balances, their payment methods. That's the easy way for backfill. The live generator
will load the same information from the database when it starts.

---

## File layout

```
antifraud_lab/
  db/migrations/001_schema.sql
  reset.sh                  # drop db, create db, apply schema
  generator/
    config.py               # all numbers and lists in one place
    db.py                   # connect()
    helpers.py              # intensity(), random helpers
    players.py              # players, sessions, payment methods
    events.py               # fixtures, markets, selections, odds
    payments.py             # deposits, withdrawals
    betting.py              # placing bets
    settlement.py           # finishing matches, paying bets
    backfill.py             # the main loop — run this
```

Run it from inside the folder: `cd generator && python backfill.py`. Then normal imports
like `import players` just work.

---

## Step 0 — Setup

- [ ] `reset.sh` — `dropdb antifraud`, `createdb antifraud`, apply the schema. Run it
      before every backfill, because backfill expects an empty database.
- [ ] `config.py` — only constants:

```python
DSN = "dbname=antifraud"
SEED = 42
DAYS = 3                 # use 3 while developing, 90 at the end
NEW_PLAYERS_PER_HOUR = 5
COUNTRIES = ["UA", "PL", "DE", "GB", "ES"]
CURRENCY_BY_COUNTRY = {"UA": "UAH", "PL": "PLN", "DE": "EUR", "GB": "GBP", "ES": "EUR"}
```

- [ ] `db.py` — one function `connect()` returning `psycopg.connect(config.DSN)`.

**Two rules from day one:**

- **Seed once**, at the top of `backfill.py`: `random.seed(config.SEED)`. Same seed →
  same data every run. Makes bugs reproducible.
- **Always use timezone-aware datetimes**: `datetime.now(timezone.utc)`. A datetime
  without timezone is treated by Postgres as *local* time, and you'll get 2–3 hour shifts
  that are very confusing to debug.

**Check:** a tiny test script that connects and runs `SELECT 1`.

---

## Step 1 — The main loop and the daily curve

- [ ] In `helpers.py`:

```python
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

def how_many(per_hour, dt):
    expected = per_hour * intensity(dt)
    return int(expected * random.uniform(0.6, 1.4))
```

`how_many()` is what every step uses to decide "how many things happen this hour".

- [ ] Helper `random_time_in_hour(hour_start)` returning
      `hour_start + random seconds between 0 and 3599`.

- [ ] `backfill.py` — just the loop for now:

```python
end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
hour = end - timedelta(days=config.DAYS)

while hour < end:
    print(hour, how_many(config.NEW_PLAYERS_PER_HOUR, hour))
    hour = hour + timedelta(hours=1)
```

**Check:** it prints 72 lines for 3 days, with small numbers at night and bigger in the
evening.

---

## Step 2 — Players, sessions, payment methods

- [ ] `players.py` with `create_players(cur, hour, all_players)`.

For each new player this hour:

1. Pick a country, take its currency from the dict.
2. Pick an **archetype** — weighted: casual 70%, regular 25%, high-roller 5%.
   `random.choices(["casual","regular","highroller"], weights=[70,25,5])[0]`.
   Not stored in the database — lives only in memory and controls behaviour.
3. `INSERT INTO players ... RETURNING id` → `player_id = cur.fetchone()[0]`.
4. Insert one payment method: card 70%, crypto 15%, bank 15%. Cards also get a random
   `last4`.
5. Insert the first session at `registered_at`.
6. Append a dict to `all_players`:

```python
{"id": player_id, "currency": "UAH", "archetype": "casual",
 "method_id": method_id, "ip": ip, "device_id": device_id}
```

**Random values that must respect the seed:**

- `fingerprint`: `hashlib.sha256(str(random.random()).encode()).hexdigest()` — 64 hex
  chars, passes the CHECK.
- `device_id`: **not** `uuid.uuid4()` — that ignores the seed. Use
  `uuid.UUID(int=random.getrandbits(128), version=4)`.
- `ip`: `f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"`.

**Honest shared devices:** for about 3% of new players, reuse the `ip` of an existing
player (same household). Without this, the linked-accounts rule will look perfect later
and teach nothing.

- [ ] `create_sessions(cur, hour, all_players)`: each hour, some existing players log in
      again — casual rarely, high-rollers often. Most reuse their own `ip`/`device_id`;
      sometimes a new IP (mobile network). Returns the list of active players.

**Check:**

```sql
SELECT date_trunc('hour', registered_at) AS h, count(*)
FROM players GROUP BY 1 ORDER BY 1;          -- should show the daily wave

SELECT type, count(*) FROM payment_methods GROUP BY 1;   -- ~70/15/15
```

---

## Step 3 — Events, markets, selections, odds

**Start with football only.** Tennis has no draw, so it needs different markets — add
other sports later.

- [ ] In `config.py`: a dict of leagues → team lists (4–5 leagues, ~10 teams each).

- [ ] `events.py` → `create_fixtures_for_day(cur, day)` — called once per simulated day,
      at midnight. Creates fixtures **two days ahead**, so there are always upcoming
      matches. Before the main loop, call it for the first two days too.

For each fixture:

1. Pick a league and two **different** teams (`random.sample(teams, 2)`).
2. `start_time`: that day at a typical kickoff — 13:00, 15:00, 17:30, 19:00, 21:00.
3. Insert the event, then 3 markets: `1x2` (line 0), `total_goals` (line 2.5),
   `both_teams_score` (line 0).
4. Insert selections with odds, and the same odds into `odds_history`.

**Making odds, the simple way** — for 1x2:

```python
p_home = random.uniform(0.25, 0.60)
p_draw = random.uniform(0.20, 0.30)
p_away = 1 - p_home - p_draw
MARGIN = 1.06
odds_home = round(1 / (p_home * MARGIN), 2)
```

Same idea for over/under and yes/no with two probabilities. The margin is what makes the
bookmaker profitable — without it, random betting would win on average and fraud wouldn't
look different from normal play.

Keep the probabilities in memory (dict `event_id → {"p_home": ..., ...}`) — settlement
uses them to pick realistic results.

- [ ] `move_odds(cur, hour)` — each hour, for ~10% of selections on upcoming events,
      change odds by ±1–5%, update `selections.current_odds`, insert a row into
      `odds_history`.

**Check:**

```sql
-- every market should have a margin around 1.06
SELECT m.type, round(avg(sum_prob), 3)
FROM (
    SELECT market_id, sum(1 / current_odds) AS sum_prob
    FROM selections GROUP BY market_id
) x
JOIN markets m ON m.id = x.market_id
GROUP BY m.type;
```

---

## Step 4 — Deposits

- [ ] `payments.py` → `create_deposits(cur, hour, active_players, balances)`.

`active_players` = players who got a session this hour. `balances` = dict
`player_id → Decimal`.

For each active player whose balance is low:

- amount by archetype, using `random.lognormvariate()` — many small, a few big:
  - casual: `lognormvariate(3.0, 0.6)` → mostly 10–40
  - regular: `lognormvariate(4.0, 0.6)`
  - high-roller: `lognormvariate(6.0, 0.7)`
- status: approved 92%, rejected 8%
- `processed_at` = `created_at` + a few seconds to a few minutes
- only **approved** deposits add to the balance

**Money rule:** never keep money as float. Convert once:
`Decimal(str(round(amount, 2)))`. psycopg sends `Decimal` to `numeric` correctly.

**Check:**

```sql
SELECT status, count(*), round(avg(amount), 2)
FROM transactions WHERE direction = 'deposit' GROUP BY 1;
```

---

## Step 5 — Bets

- [ ] `betting.py` → `load_open_selections(cur, hour)` — once per hour, one query:
      selections whose event status is `scheduled` and `start_time` is between
      (hour end) and (hour end + 48h). Join selections → markets → events yourself.
      Returns a list of `(selection_id, current_odds, event_id)`.

- [ ] `create_bets(cur, hour, active_players, balances, open_selections)`.

For each active player with money:

1. How many bets: casual 1–2, regular 2–4, high-roller 3–6.
2. Single (70%) or combo (30%, 2–4 legs).
3. Combo legs must come from **different events** — keep a set of used event_ids while
   picking.
4. `total_odds` = multiply the legs' odds, round to 2 places.
5. Stake: lognormal by archetype, never more than the balance.
6. Insert bet (`RETURNING id`), then its `bet_selections` rows with
   `odds_at_placement` = current odds.
7. `balances[player_id] -= stake`

**Check:**

```sql
SELECT count(*) AS bets,
       round(avg(stake), 2) AS avg_stake,
       round(avg(total_odds), 2) AS avg_odds
FROM bets;

-- no bet placed after its match started (must return 0)
SELECT count(*)
FROM bets b
JOIN bet_selections bs ON bs.bet_id = b.id
JOIN selections s ON s.id = bs.selection_id
JOIN markets m ON m.id = s.market_id
JOIN events e ON e.id = m.event_id
WHERE b.placed_at >= e.start_time;
```

The second query is basically the future late-betting rule. Returning 0 now means normal
data is clean — later the fraud injector will make it return something.

---

## Step 6 — Settlement

- [ ] `settlement.py` → `finish_events(cur, hour)` — events where
      `start_time + 2 hours <= hour` and status is still `scheduled`:

1. Pick a score: home and away goals each from
   `random.choices([0,1,2,3,4], weights=[25,35,23,12,5])`. Optionally nudge with the
   stored probabilities — a favourite should win more often.
2. From the score, decide every selection: 1x2 → home/draw/away; total 2.5 →
   over/under; BTTS → yes/no.
3. Update `selections.status` to won/lost, `markets.status` to settled, event to
   finished with `finished_at` ≈ start + 1h50m.

- [ ] `settle_bets(cur, hour, balances)` — find open bets where **all** legs are decided:
      `GROUP BY bet_id HAVING bool_and(selection status <> 'open')`.

For each:

- any leg lost → bet lost, payout 0
- all legs won → bet won, payout = stake × total_odds
- insert into `settlements`, update `bets.status`, `balances[player_id] += payout`

Skip cancelled events and void bets for now — add them after everything else works.

**Check:**

```sql
-- the bookmaker should earn roughly 5–8% of stakes
SELECT round(1 - sum(s.payout) / sum(b.stake), 3) AS margin
FROM bets b JOIN settlements s ON s.bet_id = b.id;

-- no won bet with a wrong payout (must return 0)
SELECT count(*)
FROM bets b JOIN settlements s ON s.bet_id = b.id
WHERE s.result = 'won'
  AND abs(s.payout - b.stake * b.total_odds) > 0.01;
```

The second query is the future settlement-mismatch rule — 0 now, something later.

If the margin comes out negative, players are winning on average — usually the margin in
odds is missing, or scores don't follow the probabilities.

---

## Step 7 — Withdrawals

- [ ] `create_withdrawals(cur, hour, active_players, balances)`:

- active players with balance well above their usual deposit sometimes withdraw — ~30%
  chance
- amount: 50–100% of balance
- method: their usual one (fraud will later use a different one)
- status approved, `processed_at` = `created_at` + 1–24 hours
- `balances[player_id] -= amount`

**Check:**

```sql
SELECT direction, count(*), sum(amount)
FROM transactions WHERE status = 'approved' GROUP BY 1;
```

Deposits should be clearly bigger than withdrawals — that difference is the bookmaker's
money.

---

## Step 8 — Put it together

`backfill.py` final shape:

```python
random.seed(config.SEED)
conn = db.connect()
cur = conn.cursor()

all_players = []
balances = {}

# fixtures for the first two days before the loop
...

while hour < end:
    if hour.hour == 0:
        events.create_fixtures_for_day(cur, hour + timedelta(days=2))

    players.create_players(cur, hour, all_players)
    active = players.create_sessions(cur, hour, all_players)
    events.move_odds(cur, hour)
    payments.create_deposits(cur, hour, active, balances)
    open_sel = betting.load_open_selections(cur, hour)
    betting.create_bets(cur, hour, active, balances, open_sel)
    settlement.finish_events(cur, hour)
    settlement.settle_bets(cur, hour, balances)
    payments.create_withdrawals(cur, hour, active, balances)

    if hour.hour == 23:
        conn.commit()
        print("done", hour.date())

    hour = hour + timedelta(hours=1)

# remember where we stopped, for the live generator
cur.execute("INSERT INTO sim_state (id, sim_time) VALUES (1, %s)", (end,))
conn.commit()
```

Needs migration `002_sim_state.sql`:

```sql
CREATE TABLE sim_state (
    id       int PRIMARY KEY CHECK (id = 1),   -- only ever one row
    sim_time timestamptz NOT NULL
);
```

**Commit once per simulated day**, not after every insert — much faster, and if it
crashes you lose at most one day.

**Final check:** `./reset.sh && python backfill.py` with `DAYS = 90`, time it, then run
every check query from the steps above again on the big dataset.

---

## Later, after it all works

- [ ] **Fraud injection** — its own step, one pattern at a time, each writing to
      `fraud_labels`. Start with the easiest: a settlement error (change one payout after
      settling).
- [ ] **Bonuses** — welcome bonus on first deposit, wagering counter.
- [ ] **Speed** — if 90 days is slow, switch big inserts to `executemany`, then compare.
- [ ] **More sports, cancelled events, void bets.**

Build one step at a time. Don't start the next until its check query looks right.
