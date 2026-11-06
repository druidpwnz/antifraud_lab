# Prometheus

Scrapes generator, API, rules, admin and Prometheus itself every 15 seconds.
Open http://localhost:9090 to inspect targets and run PromQL queries.

[prometheus.yml](prometheus.yml) defines the targets. Python metrics listeners
use port 9100 inside Docker networks; these ports are not published to the host.
The admin listener exposes build identity only.

For a development configuration change:

```bash
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose restart prometheus
```

Managed deployments reload monitoring through the updater.
[Grafana](../grafana/README.md) displays metrics and evaluates alert rules.
