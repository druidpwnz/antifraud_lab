# Instructions for AI coding agents

Read [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) before planning work. It records
what is implemented, the last confirmed deployment and the remaining work.
Use the code and workflow files to verify details; old plans are not requirements.

## Collaboration

- Work in small, reviewable steps. Explain changes and commands in plain English.
- The user reviews, runs real-server commands and commits. Do not commit or push
  unless explicitly asked.
- Never start services, migrate, seed, reset or otherwise modify the user's real
  database or home-server deployment. Provide the commands for the user to run.
- Isolated, disposable local fixtures are allowed. Use a separate Compose project,
  ports and volumes, and clean up only resources created for that fixture.
- Keep credentials, `.env`, dumps and private `llm_memory/` files out of commits
  and public documentation. Do not copy private host details into tracked docs.

## Project map

| Path | Responsibility |
|---|---|
| `generator/` | Backfill, live simulation and fraud injection |
| `db/` | SQL migrations, scoring and data invariants |
| `api/` | FastAPI, authentication, pagination and risk checks |
| `admin/` | Flask/Jinja/HTMX API client; no direct database access |
| `rules/` | Incremental SQL detection and runner |
| `prometheus/`, `grafana/` | Metrics collection, dashboards and alerts |
| `ci/`, `.github/` | Validation, image publishing and dependency updates |
| `deploy/` | Python host updater and systemd user units |

## Constraints that changes must preserve

- Application images use Python 3.14. The host updater must also work on Python
  **3.11.2** and uses the standard library. Ruff has per-file Python targets.
- Money uses decimal arithmetic. The API serializes amounts as strings; never use
  floats for balances or payouts. Timestamps are timezone-aware UTC.
- The generator's backfill and live modes share `tick.one_tick()`. Keep the fixed
  seed/end reproducible. Live data must never be dated ahead of the real clock.
- Detection SQL must never read `fraud_labels`; only scoring and tests may do so.
- Rules scan source IDs and commit alerts with the cursor in one transaction.
  This assumes one writer per source table committing in ID order.
- The panel keeps its read-only API key on the server. Preserve CSRF protection,
  CSP, HTML escaping and full-page/HTMX-fragment behavior, including Back navigation.
- Add a new numbered migration for schema changes. Never edit an applied migration.
  The updater does not reverse migrations during application rollback.
- CI publishes the images that passed the stack checks, without rebuilding them.
  Publishing accepts only successful push runs from this repository's `main`.
- Managed deployment uses full-SHA image tags and a detached checkout. Keep `.env`
  and volumes intact. Installed updater scripts live outside the checkout so they
  remain available when rolling back to a commit without `deploy/`.

## Verification

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for setup and commands.
Run checks appropriate to the change; do not operate the real services to test it.

- Python: `python -m ruff check .` and affected pytest suites.
- API/rules tests: use a dedicated migrated `antifraud_test` database. API fixtures
  truncate their test dataset; never point tests at real data.
- Panel behavior: run its mocked tests; use an isolated browser fixture when a UI
  change needs interaction, layout or console verification.
- Generator/data changes: check SQL invariants and deterministic backfill output.
- Rules/scoring: check honest and fraudulent cases and the scoring gate.
- Updater: run helper tests on development Python and Python 3.11.2 when changing
  host code. Never use the user's deployment as a test fixture.
- Documentation: verify local links, commands against source, and `git diff --check`.

## Documentation maintenance

- READMEs are short entry points: purpose, essential commands and guide links.
- Put detailed usage in `docs/` or a focused component reference.
- Keep current state, dated verification evidence, open decisions and future plans
  in `docs/PROJECT_STATE.md`; do not restore completed build plans to the README.
- Update state after a meaningful milestone. Distinguish user-reported server
  results from local tests and GitHub checks; do not infer unreported outcomes.
- Git history retains completed build plans and debugging history. Preserve useful
  constraints here or in a reference guide rather than duplicating old narratives.
