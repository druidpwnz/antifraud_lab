# Server deployment

A systemd user timer checks for a release about every five minutes. The updater
follows the public generator image's `main` revision, selects matching full-SHA
images, validates them, applies migrations and checks service health.
GitHub does not connect to the server.

Requires Linux, Python 3.11+ (including 3.11.2), Git, Bash, Docker Compose and
noninteractive Git access. Application images contain their own Python runtime.

- [Installation, configuration and recovery](../docs/DEPLOYMENT.md)
- [Current project state](../docs/PROJECT_STATE.md)

After installation, run on the server:

```bash
systemctl --user status antifraud-update.timer
journalctl --user -u antifraud-update.service -n 60 --no-pager
systemctl --user start antifraud-update.service    # check for an update now
```

Use the updater for server changes: it manages a detached checkout and image tags.
It preserves `.env` and volumes, records successful/previous releases and supports
manual rollback. Database migrations are not reversed. Disable the timer before
pinning an older release; follow the recovery guide for the full procedure.
