# Generator design

Backfill and live generation share `tick.one_tick()`. The simulation models
players, sessions, deposits, betting, settlement and withdrawals with decimal
money and UTC timestamps.

## Clock and reproducibility

Defaults in `config.py`: `SEED=42`, `DAYS=14`, fixed end `2026-09-01T00:00:00Z`,
`TICK_MINUTES=5`. The tick size must divide 60 and is part of dataset identity.
The same seed, configuration and code produce the same backfill.

Hourly rates are scaled to a tick; probabilities use `1 - (1 - p) ** (5/60)`.
Sessions may start anywhere in a tick and finish by the end of the next tick.
Live mode waits until that whole window has passed in real time, so recent data
is normally five to ten minutes old and no generated row is in the future.

## Lifecycle

1. `backfill.py` creates fixtures and runs ticks up to the fixed end. It commits
   daily, then records `sim_state` as the completed-seed marker.
2. An existing marker makes backfill exit successfully without seeding again.
   Players without a marker indicate an incomplete seed; the script refuses to
   continue. Investigate or use a fresh disposable database rather than resetting
   an existing deployment.
3. `live.py` loads the clock and rebuilds state from stored rows and deterministic
   values derived from the seed and row IDs.
4. Each live tick commits activity and advances the simulation clock. A restart
   resumes from that clock; player sessions cannot overlap their previous session.
5. SIGTERM/SIGINT finishes and commits the current tick, then exits.

## Behavior and controls

| Setting | Meaning |
|---|---|
| `DATABASE_URL` | libpq connection string; an empty value uses `PG*` settings |
| `CATCH_UP=1` | Generate missed time as fast as possible until caught up |
| `CATCH_UP=0` | Pace catch-up using `REAL_SECONDS_PER_SIM_HOUR` |
| `METRICS_PORT` | Prometheus listener; `0` disables it locally |
| `config.py` | Archetypes, activity rates, timing, fixture and fraud parameters |

Casual, regular and high-roller archetypes produce different activity and amount
distributions. Honest households sometimes share devices or payment methods,
providing noise for linked-account investigations. Matches have priced markets,
combo bets keep placement odds, and withdrawals are limited by available funds.

## Validation

Run [SQL invariants](../db/tests/README.md) after changing generation logic and
compare profiles before/after. Check deterministic backfill output on two fresh
isolated databases when changing random draws, rates or tick ordering.

Do not use `fraud_labels` to make detection decisions. Injection writes labels;
scoring consumes them to evaluate independent rules. See
[FRAUD_PATTERNS.md](FRAUD_PATTERNS.md) for current patterns.
