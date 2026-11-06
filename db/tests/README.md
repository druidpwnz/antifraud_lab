# SQL checks

Run from the repository root against the intended development dataset.

| File | Purpose | Fails on a problem |
|---|---|---|
| `invariants.sql` | Twelve data invariants, valid at any dataset size | Yes |
| `constraints.sql` | Verify the schema rejects invalid inserts; rolls back | Yes |
| `scoring_gate.sql` | Minimum recall, nonempty ground truth and completed rule scans | Yes |
| `profile.sql` | Counts, distributions and margin for inspection | No |

```bash
docker compose exec -T postgres psql -U antifraud -d antifraud -v ON_ERROR_STOP=1 < db/tests/invariants.sql
docker compose exec -T postgres psql -U antifraud -d antifraud -v ON_ERROR_STOP=1 < db/tests/constraints.sql
docker compose exec -T postgres psql -U antifraud -d antifraud -v ON_ERROR_STOP=1 < db/tests/scoring_gate.sql
docker compose exec -T postgres psql -U antifraud -d antifraud -P pager=off < db/tests/profile.sql
```

Run the scoring gate after all three rules have processed the dataset. Required
recall: late bets 1.0, settlement mismatches 1.0, stake anomalies 0.85. The gate is
intended for a fixed seed with writers paused; a running generator can advance
source IDs between scans and the check. CI creates that fixed-seed environment.

Tests and scoring may read `fraud_labels` to distinguish deliberate fraud from
bugs. Detection rules may not. Avoid fixed row-count assertions on live data.
