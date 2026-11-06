# Project state and next work

Updated: 2026-11-06. Read alongside [AGENTS.md](../AGENTS.md).
This is the handoff for AI coding tools; source code remains authoritative.

## Purpose and scope

A synthetic betting/payment fraud lab for learning Python services, REST API design
and CI/CD. Advanced SQL interview exercises are no longer the goal. Keep detection
SQL thin and expand features only when they serve the current learning goal.

## Implemented

The original phases 0–10 are implemented:

| Area | Current behavior |
|---|---|
| Data | 14 domain tables, simulation state, migration tracking and rule state; seven numbered migrations |
| Generator | Reproducible 14-day seed, shared five-minute backfill/live ticks, restart recovery, graceful shutdown and no future data |
| Fraud injection | `SETTLEMENT_ERROR`, `LATE_BET`, `STAKE_ESCALATION`, with ground truth in `fraud_labels` |
| API | Authenticated reads, player investigations, money/bets/events, idempotent risk checks, health/readiness and Postman collection |
| Panel | Login, player/money/session/link investigation, bets and events, filters, cursor paging and HTMX navigation |
| Rules | `SETTLEMENT_MISMATCH`, `LATE_BET`, `STAKE_ANOMALY`; incremental alerts and precision/recall scoring |
| Monitoring | Five Prometheus targets, four Grafana dashboards, nine alert rules and build identity for four Python services |
| Packaging | Docker Compose, four application images, migration/seed jobs and persistent data volumes |
| CI | Ruff, Gitleaks history scan, service/helper tests, Python 3.11.2 updater check and full-stack validation |
| Releases | Publish tested images to GHCR with full-SHA tags; promote current `main`, generator last as release pointer |
| Deployment | Pull-based systemd user timer, preflight, health/version checks, locking, release records and manual rollback |
| Maintenance | Weekly Dependabot PRs for Python requirements and GitHub Actions; no auto-merge configured |

## Last confirmed evidence

- Latest locally observed commit: `54f0c79930e6b35a22b0baa1da11fd4a8ff4df27`.
  This is a historical baseline, not a promise that it remains the newest commit.
- [CI](https://github.com/druidpwnz/antifraud_lab/actions/runs/40931775596) and
  [Images](https://github.com/druidpwnz/antifraud_lab/actions/runs/40932416177)
  succeeded for that SHA. The user confirmed automatic deployment of it.
- On 2026-11-06 the user reconfirmed that the project works and requested this
  documentation cleanup. No newer release SHA was supplied.
- Recorded test baseline: API 148, panel 141, rules/scoring 36, CI helpers 42;
  21 updater/health tests also passed on exact Python 3.11.2. These are prior
  results, not checks rerun during documentation cleanup.
- Stack verification covered 12 SQL invariants, 36 Postman requests/60 assertions,
  detection scoring, live generation, monitoring and image identity.
- Isolated Docker deployment A → B → rollback A preserved a database marker and
  the same PostgreSQL volume. This was a local fixture, not the real server.
- All four GHCR packages were made public; anonymous image manifest checks passed.
- Initial Dependabot runs succeeded and opened Ruff and setup-python PRs. Their
  current merge status has not been checked.

## Next work

No new application feature is currently selected. Documentation has been reorganized
into short landing pages, separate operating guides and a discoverable AI handoff.
These changes await user review and commit. Prior documentation edits recording
deployment success were incorporated into this handoff.

Operational follow-up, if not already completed by the user:

- Confirm timer behavior after logout/reboot and a real-server rollback followed
  by a forward update. Deployment is working; these individual checks were not
  separately reported. Ask for status when relevant rather than assuming failure.
- Finish repository protection/security settings and verify required checks on a
  Markdown-only PR and workflow approval on an outside contributor's PR.
- Review dependency PRs and merge only after the required checks pass.

See [GOING_PUBLIC.md](GOING_PUBLIC.md) for the owner checklist. Repository visibility
was last checked as private on 2026-10-29; verify current settings before advising
on changes. No project license has been selected.

## Future candidates, not an agreed implementation order

- Telegram notifications: the user previously wanted these; alerts currently live
  in Grafana. Agree on notification routing before implementing.
- Structured generator logging; current output uses plain prints.
- Richer devices/payment methods per player before realistic multi-account,
  passthrough or card-testing injection. Shared household data is honest noise.
- Multi-account rings need incident/cluster identity for meaningful scoring.
  Matched betting depends on linked rings. Bonus abuse needs populated bonuses.
- More realistic late-bet winner bias and takeover device/IP signals.
- Review fixed date floors in schema checks if changing the simulation date range.

The API already has a passthrough risk heuristic; that does not mean a planted
passthrough fraud scenario or a corresponding batch detector exists.

## Lessons to preserve

- Settlement detection calculates expected payout for won and lost bets; a won-only
  query missed paid losing bets. Void/half results are deliberately excluded because
  the generator does not produce them and their payout rules are untested.
- Timestamps can arrive out of order; rules use source IDs. Do not silently replace
  the single-writer assumption with concurrent writers.
- Prometheus retains old build labels briefly after replacement. Deployment probes
  and the Ops table select `topk by (job) (1, timestamp(antifraud_build_info))`;
  deployment probes also require fresh samples.
- Every PR, including Markdown-only PRs, runs CI so required checks report.
  Markdown-only direct pushes skip CI; `Images` is not a pre-merge required check.
- A failed deployment retains the last successful record and a pending recovery
  record. It does not automatically undo migrations; services can need recovery.
- The server runs Python 3.11.2 while application containers run 3.14. Keep host
  code compatible and manually reinstall stable updater scripts when they change.

## Documentation map

- [Development and testing](DEVELOPMENT.md)
- [API reference](API.md), [panel guide](ADMIN.md), [database guide](DATABASE.md)
- [Deployment and recovery](DEPLOYMENT.md), [GitHub owner checklist](GOING_PUBLIC.md)
- [Generator design](../generator/GENERATOR_BACKFILL.md) and
  [implemented fraud patterns](../generator/FRAUD_PATTERNS.md)

Private machine/account details belong in ignored local memory, not this file.
