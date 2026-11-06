# Grafana

Four provisioned dashboards and nine alert rules for service health, fraud,
detection quality and money flows. Open http://localhost:3000 and find the
**Antifraud Lab** dashboard folder.

| Path | Purpose |
|---|---|
| [dashboards/](dashboards/README.md) | Ops, Fraud, Scoring and Money dashboards |
| `provisioning/datasources/` | Prometheus and restricted PostgreSQL connections |
| `provisioning/alerting/` | Alert rules managed as code |

Dashboard definitions live in Git. Export UI edits back to their JSON files;
UI-only edits are not the source of truth. The Fraud dashboard's **Admin panel**
variable must point to the browser-accessible panel URL.

Ops uses wall-clock time; business dashboards use simulated event time.
The Ops build-version table identifies the running commit for each Python service.
Notification routing, including Telegram, is future work; current alerts are
available in Grafana.
