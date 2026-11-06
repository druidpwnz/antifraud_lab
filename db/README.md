# Database

PostgreSQL schema, migrations, scoring views and data validation.
The Compose database stays internal; application and monitoring data use persistent
volumes. Migrations run before seeding and application startup.

| Path | Purpose |
|---|---|
| `migrations/` | Numbered SQL schema changes |
| `migrate.py` | Transactional runner with `schema_migrations` tracking |
| `scoring.sql` | Detection precision/recall report |
| [tests/](tests/README.md) | Data invariants, constraints, profile and scoring gate |

From the repository root:

```bash
docker compose exec postgres psql -U antifraud -d antifraud
docker compose exec -T postgres psql -U antifraud -d antifraud < db/scoring.sql
```

Add a new migration for each schema change; never edit an applied migration.
See the [database guide](../docs/DATABASE.md) for the runner, baseline procedure
and Grafana's restricted read-only role.
