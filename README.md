# Antifraud Lab

A self-hosted fraud-detection lab with synthetic betting and payment traffic.
Generate realistic activity, investigate players through an API and admin panel,
and measure how well detection rules find deliberately planted fraud.

Built to practise **Python services, REST API design and CI/CD**.

## What it includes

- Reproducible historical data and a live generator with five-minute ticks.
- Three fraud patterns: late bets, settlement errors and stake escalation.
- FastAPI API with API-key authentication, cursor pagination and idempotent risk checks.
- Flask, Jinja and HTMX investigation panel that reads through the API.
- Incremental detection rules scored against known fraud labels.
- Prometheus metrics, four Grafana dashboards and nine alert rules.
- GitHub Actions checks, tested images in GHCR and automatic server updates.

```text
Generator → PostgreSQL ← Detection rules
                 ↑
Browser → Admin → API

Prometheus → Grafana ← PostgreSQL (read-only)
```

## Quick start

Requires Docker Engine and the Docker Compose plugin.

```bash
git clone https://github.com/druidpwnz/antifraud_lab.git
cd antifraud_lab
cp .env.example .env
docker compose up -d --build
```

Demo credentials are public. Change passwords, keys and the session secret in
`.env` before sharing access. For an existing installation, see
[credential changes](docs/DEVELOPMENT.md#configuration-and-data).

| Service | Address | Demo access |
|---|---|---|
| Admin panel | http://localhost:5000 | `admin` / `demo-admin-password-change-me` |
| API docs | http://localhost:8000/docs | API key: `demo-full-key-change-me` |
| Grafana | http://localhost:3000 | `admin` / `demo-grafana-admin-password-change-me` |
| Prometheus | http://localhost:9090 | No login |

The first start seeds 14 days of history, then catches up to the current time.
Catch-up can take several minutes or longer and initially produces many alerts.
Ports can be changed in `.env`; PostgreSQL stays internal to Docker.

```bash
docker compose ps
docker compose logs -f generator
docker compose down                 # stop services and keep stored data
```

## Components and guides

| Component | Guide |
|---|---|
| [Generator](generator/) | Historical data, live simulation and planted fraud |
| [Database](db/) | Schema, migrations and data checks |
| [API](api/) | Endpoints, authentication and Postman collection |
| [Admin panel](admin/) | Player, bet and event investigation |
| [Detection rules](rules/) | Incremental detection and precision/recall scoring |
| [Grafana](grafana/) / [Prometheus](prometheus/) | Dashboards, alerts and metrics |
| [CI](ci/) | Automated checks and image publishing |
| [Deployment](deploy/) | Server updater, status checks and rollback |

For local work, see [development and testing](docs/DEVELOPMENT.md).
Server releases follow **main → CI → GHCR → server timer → health checks**;
the server uses published images and keeps its database between releases.

AI coding tools: start with [AGENTS.md](AGENTS.md). Current project state and future
work are maintained in [PROJECT_STATE.md](docs/PROJECT_STATE.md).
