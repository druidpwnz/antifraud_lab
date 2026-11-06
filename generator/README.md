# Generator

Synthetic players, payments, sessions, football markets, bets and settlements.
A fixed seed creates reproducible history; live mode resumes from `sim_state`
and adds five-minute ticks without writing future activity.

Compose runs `backfill.py` through the `seed` job, then starts `live.py` as the
`generator` service. A completed seed is not generated again.

```bash
docker compose logs -f generator
```

For local development, after [database setup](../docs/DEVELOPMENT.md#local-python-setup):

```bash
DATABASE_URL='dbname=antifraud' python generator/backfill.py
DATABASE_URL='dbname=antifraud' python generator/live.py
```

- [Design and configuration](GENERATOR_BACKFILL.md)
- [Implemented fraud patterns](FRAUD_PATTERNS.md)
- [Data checks](../db/tests/README.md)

`config.py` holds simulation parameters. Live catch-up can be controlled through
`CATCH_UP` and `REAL_SECONDS_PER_SIM_HOUR`. Future patterns are tracked in
[project state](../docs/PROJECT_STATE.md#future-candidates-not-an-agreed-implementation-order).
