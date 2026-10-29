# Going public

The repository was still private when checked on 2026-10-29. The four GHCR packages
are public and CI/Images have passed. Deployment on the home server was confirmed
by the user. This checklist prepares a future visibility change; committing it
does not change GitHub settings.

## Before changing visibility

- [ ] Review the full Git history and files that will become public. The local
  `.env`, database dumps and `llm_memory/` must stay untracked. The committed demo
  keys in `.env.example` are examples; the server uses its own credentials.
- [ ] Run the pinned Gitleaks scan against a full clone, not just the current tree:
  `gitleaks git --redact --log-opts="--all HEAD" .` using version 8.30.1. On
  2026-10-29 this passed over all 47 existing commits. Repeat after further commits.
  Keep `.gitleaksignore` limited to its reviewed example UUID fingerprint.
- [ ] Confirm the latest **CI** and **Images** runs succeeded, all four packages
  remain public, and the home server's Ops build versions agree.
- [ ] Choose a project license for the intended sharing terms. No project license
  has been selected in this step.
- [ ] Keep the account's Actions spending limit at $0; review current usage and
  artifact storage. The image artifact expires after one day and is deleted after
  successful publishing. Fork PR approval also controls unreviewed runner usage.

## Change visibility, then protect main

When ready, use **Settings → General → Danger Zone → Change repository visibility**.
This is a manual owner action. Branch protection is available for public
repositories on GitHub Free; private-repository availability depends on the plan.
[GitHub: protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

In **Settings → Branches**, add a protection rule for `main`:

- [ ] Require a pull request before merging. For a solo maintainer, leave required
  review approvals off unless another reviewer is available.
- [ ] Require these five status checks from **GitHub Actions**; use the exact job
  names after a recent PR run has reported them:

  | Required check | Proves |
  |---|---|
  | `Lint, secrets, admin` | Lint, history scan, panel/helper tests and unit-file validation |
  | `API tests` | API tests against Postgres |
  | `Detection rule tests` | Rules and scoring-gate tests against Postgres |
  | `Updater on Python 3.11.2` | Host-updater compatibility |
  | `Full stack` | The services work together and detection quality meets its floors |

- [ ] Require branches to be up to date before merging and apply the protection
  rules to administrators too (the "Do not allow bypassing" option).
- [ ] Keep force pushes and branch deletion disabled.

Do **not** require the `Images` workflow as a PR check: publishing follows a
successful push to `main`, after the merge. All PRs, including Markdown-only PRs,
now run CI. Markdown-only direct pushes still skip CI. Path-skipped workflows can
otherwise leave required checks pending and block merging.
[GitHub: skipped required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).

## Workflow approvals and permissions

In **Settings → Actions → General**:

- [ ] Require workflow approval for all outside collaborators. Read a fork's diff,
  especially workflow changes, before approving its first run.
- [ ] Keep the default workflow token permission read-only. Only the Images job
  requests package publishing and artifact deletion permissions in its YAML.
- [ ] Keep runners GitHub-hosted. The home server follows releases with its own
  timer and does not run pull-request jobs.
- [ ] Keep home-server credentials and `.env` out of Actions secrets. These
  workflows need only demo configuration and GitHub's temporary token.

Fork PRs run tests; they do not publish images or contact the server. The Images
workflow accepts only successful push runs from this repository's `main` and
downloads only that run's tested image artifact.
[GitHub: approving fork workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks).

## Secret scanning and dependency updates

- [ ] Review repository security settings after publication. Check secret-scanning
  alerts and enable push protection where available. Gitleaks stays in CI as well.
  [GitHub: secret scanning](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning).
- [ ] Enable the dependency graph, Dependabot alerts and security updates in the
  repository's security settings where available. Version updates are configured
  in [dependabot.yml](../.github/dependabot.yml) once this change is committed.
- [ ] Confirm the first Dependabot update run recognizes the manifests and opens
  PRs; watch **Insights → Dependency graph → Dependabot** for update errors.

Dependabot checks GitHub Actions and Python requirements on Mondays at 09:00
Europe/Kyiv. Each ecosystem has a two-open-version-PR limit. Action minor/patch
updates are grouped; shared Python packages are grouped by dependency name across
the five requirements directories. Major updates remain separate PRs. Security
update PR limits/scheduling are handled separately by GitHub.
[GitHub: Dependabot configuration](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).

Review the diffs and wait for all five CI checks before merging a dependency PR.
The merge triggers CI again on `main`, then image publishing and the home-server
timer. There is no auto-merge configured here. Docker image upgrades, Newman,
Gitleaks and tool versions written directly in shell commands remain manual
maintenance items; this configuration does not monitor them.

## Final proof

- [ ] Open a Markdown-only PR and confirm all five required checks report and it
  can merge after they pass.
- [ ] Open a PR from a fork and confirm outside-collaborator approval is required
  and no images are published from its run.
- [ ] After merging a change that triggers image publishing, let the timer pick up
  the new release and check **Ops → Running build versions** on the server.
- [ ] On the server, verify the timer after logout/reboot, then perform a rollback
  and forward update using the [deployment guide](../deploy/README.md). Local
  rollback/data-preservation tests passed; these server checks have not yet been
  separately reported.

Use feature branches and pull requests for subsequent work. Keep the deployment
checkout on the server under the updater's control; review and merge changes from
the development checkout.
