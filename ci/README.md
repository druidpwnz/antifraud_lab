# CI and image publishing

[GitHub Actions workflows](../.github/workflows/) validate changes, then publish
the images that passed the full-stack checks.

| CI job | Checks |
|---|---|
| `Lint, secrets, admin` | Ruff, Gitleaks history scan, panel/helper tests, shell syntax and systemd units |
| `API tests` | API behavior against disposable PostgreSQL |
| `Detection rule tests` | Detection and scoring against disposable PostgreSQL |
| `Updater on Python 3.11.2` | Host-updater and deployment-probe compatibility |
| `Full stack` | Compose, SQL invariants, Postman, scoring, live generation, monitoring and image identity |

CI runs on pull requests, code pushes and manual dispatch. Markdown-only direct
pushes skip CI; Markdown-only PRs run it so required checks can report.

A successful push run on this repository's `main` hands its tested images to
`Images`. That workflow publishes four full-SHA tags to GHCR without rebuilding.
It promotes `main` tags only for the current branch head, with generator last as
the release pointer. PR and manually dispatched CI runs do not publish images.

`check_images.py`, `check_monitoring.py` and `publish_images.sh` contain the helper
checks and publishing logic. Run their tests from the root:

```bash
python -m pytest -q ci/tests
```

Dependency PRs come from [Dependabot](../.github/dependabot.yml).
See [development setup](../docs/DEVELOPMENT.md), the
[GitHub settings checklist](../docs/GOING_PUBLIC.md) and the
[deployment guide](../docs/DEPLOYMENT.md).
