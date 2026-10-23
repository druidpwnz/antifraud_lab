# Dashboards

Loaded by Grafana from this folder (`../provisioning/dashboards/dashboards.yml`) into
the **Antifraud Lab** folder, re-read every 30 seconds.

| File | Dashboard | Datasource | Time |
|---|---|---|---|
| `ops.json` | **Ops** — services up, the generator's lag, the rules runner, API traffic and latency | Prometheus | real |
| `fraud.json` | **Fraud** — detections per hour by rule, the players with most alerts, the latest alerts | Postgres | simulated |
| `scoring.json` | **Scoring** — precision and recall per rule, caught / missed / false alarms | Postgres (`rule_scores` view) | — |
| `money.json` | **Money** — deposits vs withdrawals, staked vs paid out, house margin, one currency at a time | Postgres | simulated |

The Fraud dashboard links player and bet numbers to the admin panel; its **Admin
panel** box at the top says where that is (default `http://localhost:5000` — change
it if `PANEL_PORT` is different).

## Changing one

Provisioned dashboards cannot be saved from the UI. Edit in the UI, then
**Export → Export as JSON** (not "for sharing externally"), save over the file here,
commit. A change that is only in the UI is gone at the next restart.

## How they are drawn

- Each rule has one colour everywhere: `SETTLEMENT_MISMATCH` blue, `LATE_BET` orange,
  `STAKE_ANOMALY` green. The colours were checked for colour-blind separation on
  Grafana's dark background.
- Green / orange / red only mean status (UP/DOWN, lag, errors), always next to the
  value as text — never "series number 4".
- One y-axis per panel. Two measures of different size get two panels.
- Simulated-time dashboards plot when things happened (`placed_at`, `window_start`),
  never `created_at`.
