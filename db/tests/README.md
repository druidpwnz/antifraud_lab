# db/tests

| File | What it is | Fails? |
|---|---|---|
| `invariants.sql` | Twelve things that must be true of the data at any size | **yes** — raises, psql exits non-zero |
| `profile.sql` | What the data looks like: counts, distributions, the margin | no — numbers to read |
| `constraints.sql` | The schema refusing bad inserts | **yes** — raises |

```bash
psql antifraud -v ON_ERROR_STOP=1 -f db/tests/invariants.sql      # must pass
psql antifraud -v ON_ERROR_STOP=1 -f db/tests/constraints.sql     # must pass
psql antifraud -P pager=off       -f db/tests/profile.sql > profile.txt
```

`invariants.sql` and `constraints.sql` are the CI steps. `profile.sql` is for eyes:
save it before changing the generator, save it again after, and diff.

**Why no expected counts anywhere.** With the live generator running, every count
grows continuously, so a number committed here would be wrong within the hour. Only
things that hold at *any* size can be asserted.

**Why these files may read `fraud_labels` and `rules/` may not.** A test needs to
tell "planted on purpose" from "broken by accident" — that is what the `NOT EXISTS`
joins are doing. A detection rule that reads the ground truth is not detecting
anything.
