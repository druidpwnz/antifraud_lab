# Home-server deployment

The server follows the public `antifraud-generator:main` image. Its source revision
selects one commit and all four full-SHA image tags. GitHub never connects to the
server. A systemd **user** timer runs the updater about every five minutes.

## What an update does

1. Refuse a dirty deployment checkout and acquire a lock against overlapping runs.
2. Read the published revision, fetch `origin/main`, and require that revision to
   be a commit in that history.
3. Validate that commit's Compose file with the server's existing `.env`, pull its
   images, and verify all four Python images' platform, source and build version.
   These checks finish before any service is stopped.
4. Stop the generator, rules, API and panel; check out the exact release commit in
   detached-HEAD mode; start/wait for Postgres; run migrations and the seed marker
   check. On an existing lab the seed exits without generating anything.
5. Recreate the application and monitoring containers with `--no-build --pull never`.
   Recreating monitoring loads the checked-out provisioning and Prometheus files.
6. Require healthy/running containers, the expected image IDs, API/panel/Grafana
   readiness, five UP scrape targets and four matching live build versions.
7. Atomically record the successful SHA and its predecessor. A failure keeps the
   last successful record and a pending record for recovery.

An unchanged, healthy release is left running. If the recorded version has drifted
or its checks fail, the updater attempts to repair it through the same deployment
path. It never builds images, removes volumes, edits `.env`, stashes changes or
forces a Git checkout. There is a short interruption while services are replaced.

## Install once on the home server

Requirements: Python **3.12+**, Git, Bash, systemd user services, Docker Engine and
the Compose plugin already used by the lab. The server account must be able to use
Docker and fetch this repository without an interactive password/passphrase. The
timer uses that same account; a login-session-only SSH agent may not survive logout.

First push the deployment change from the laptop and wait for **CI** and **Images**
to turn green. Run the following **on the home server**, in its existing lab
checkout. Keep its existing `.env`, ports and data. Before the first installation
the checkout is still on its normal `main` branch:

```bash
cd /absolute/path/to/antifraud_lab
git status --short                 # must be empty
git pull --ff-only
python3 --version
docker compose version
git -c core.sshCommand='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes' ls-remote origin refs/heads/main

mkdir -p "$HOME/.local/lib/antifraud" "$HOME/.config/antifraud" "$HOME/.config/systemd/user"
install -m 0755 deploy/update.sh "$HOME/.local/lib/antifraud/update.sh"
install -m 0644 deploy/update.py deploy/healthcheck.py "$HOME/.local/lib/antifraud/"
install -m 0644 deploy/antifraud-update.service deploy/antifraud-update.timer "$HOME/.config/systemd/user/"
printf 'ANTIFRAUD_REPO="%s"\n' "$PWD" > "$HOME/.config/antifraud/deploy.env"
chmod 600 "$HOME/.config/antifraud/deploy.env"
systemctl --user daemon-reload
```

The installed updater lives **outside** the checkout. It remains available when
rolling back to a release that has no `deploy/` directory. Updating these installed
scripts or units later is a manual review/install step: disable the timer, wait for
the service to finish, then repeat the copy and daemon-reload commands.

Run preflight first; it fetches/pulls and validates without changing containers,
the checkout or the release record:

```bash
ANTIFRAUD_REPO="$PWD" bash "$HOME/.local/lib/antifraud/update.sh" --check
```

Expect `PASS preflight`. If target config needs a new environment variable, fill
it in the server's `.env` and retry; never replace the server's `.env` with the demo
file. A fetch or image error also stops here without touching running services.

Then do the first deployment manually through the installed service:

```bash
systemctl --user start antifraud-update.service
journalctl --user -u antifraud-update.service -n 60 --no-pager
```

`start` waits for the oneshot to finish. Expect `DEPLOYED <full SHA>`. In Grafana
at `http://192.168.50.70:3000`, **Ops → Running build versions** should show that
SHA for API, admin, rules and generator. The panel stays on port 5000; no new
published ports are added.

Enable periodic updates and keep the user manager running after logout/reboot:

```bash
sudo loginctl enable-linger "$USER"
systemctl --user enable --now antifraud-update.timer
systemctl --user list-timers antifraud-update.timer
```

The timer first runs two minutes after the user manager starts, then five minutes
after the previous attempt finishes. Docker must already be configured to start
on boot. An unavailable network/registry causes a failed attempt and a later retry;
existing containers continue to use Docker's restart policies.

## Status and immediate checks

```bash
systemctl --user status antifraud-update.timer
journalctl --user -u antifraud-update.service -n 60 --no-pager
systemctl --user start antifraud-update.service    # check for a release now
```

The release state is in `~/.local/state/antifraud/state.json`; a failed attempt
after preflight leaves `pending.json`. Files are private to the server account.
`ANTIFRAUD_STATE_DIR` can select another state directory; `ANTIFRAUD_PROJECT`
defaults to the existing Compose project `antifraud`. State is bound to both the
checkout and project so it cannot silently be reused for another lab.

After installation, use the updater for changes instead of `git pull` or a plain
`docker compose up`: the checkout is deliberately detached, and the updater sets
`IMAGE_TAG` for every Compose command. `docker compose ps` and `logs` remain useful
for inspection. Do not change the Compose project name on the existing server.

## Roll back, then forward again

Disable the timer first so it does not immediately undo a pinned rollback:

```bash
systemctl --user disable --now antifraud-update.timer
systemctl --user is-active antifraud-update.service
```

Wait until the service is `inactive` or `failed`; let an active update finish.
From the deployment checkout, restore the recorded previous successful release:

```bash
ANTIFRAUD_REPO="$PWD" bash "$HOME/.local/lib/antifraud/update.sh" --rollback
```

After a failed attempt, this restores the last successful release from the pending
record. After a successful update, it restores its predecessor. On the first-ever
deployment there is no recorded predecessor; pass a known published full SHA
explicitly instead. For example, the first verified public release is:

```bash
ANTIFRAUD_REPO="$PWD" bash "$HOME/.local/lib/antifraud/update.sh" 4ee91662ce03c900d284fcc1f46e56f94ab6ebef
```

The same preflight and health checks apply to a rollback. `.env` and named volumes
are kept. Database migrations are **not reversed**: an older application must be
compatible with the already-applied schema. A breaking schema change needs its
own migration/backup plan; the updater never restores a database automatically.

A failed migration or health check is reported in the journal and does not advance
the successful release record. Services may be stopped or unhealthy at that point;
read the error and use the installed updater for recovery. There is no automatic
rollback over an unknown schema change.

To move forward to the latest tested release, run the service once, verify it, then
re-enable the timer:

```bash
systemctl --user start antifraud-update.service
journalctl --user -u antifraud-update.service -n 60 --no-pager
systemctl --user enable --now antifraud-update.timer
```
