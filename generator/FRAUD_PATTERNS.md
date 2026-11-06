# Implemented fraud patterns

Injection lives in `fraud.py`; rates and thresholds live in `config.py`.
Every planted case writes ground truth to `fraud_labels`. Detection rules inspect
ordinary business tables and are evaluated against labels afterwards.

| Pattern | Planted behavior | Detection rule |
|---|---|---|
| `SETTLEMENT_ERROR` | Wrong payout on a winning bet, or a losing bet paid out | `SETTLEMENT_MISMATCH` |
| `LATE_BET` | Single bet placed after kickoff, before the match ends, at stale pre-match odds | `LATE_BET` |
| `STAKE_ESCALATION` | Large stake after an established history of smaller bets | `STAKE_ANOMALY` |

## Settlement error

Winning payouts are shifted by 5–40%; paid losing bets receive 50–100% of a
winning payout. Labels identify the settlement and record the variant and correct
payout. Detection must compare payout with the expected amount for the actual
result; checking only won bets misses the paid-loss variant.

## Late bet

`maybe_late_bets()` places a bet strictly between kickoff and the final whistle.
Labels record the bet, event, delay after kickoff and placement odds. Honest bets
must stay before kickoff. The planted selection is random, so the current pattern
does not model a bettor choosing after seeing a goal.

## Stake escalation

`maybe_stake_escalation()` needs at least 15 previous bets and enough available
balance. It stakes 10–40 times the player's running average, capped by balance.
Labels record the average, amount, multiple and prior bet count.

Detection compares with the previous 50 bets and requires at least 15. Honest
high rollers are deliberate noise; an absolute stake threshold is insufficient.
The injected bet uses the normal session, without a new device/IP takeover signal.

## Controls and evaluation

`INJECT_FRAUD` switches injection off for a clean comparison dataset.
`SETTLEMENT_ERROR_RATE`, `LATE_BET_RATE` and `STAKE_ESCALATION_RATE` control frequency.
Run [rules and scoring](../rules/README.md) and [data checks](../db/tests/README.md)
after changes. Rate changes alter sample size and the usefulness of recall scores.

Unimplemented scenarios and prerequisites live in
[project state](../docs/PROJECT_STATE.md#future-candidates-not-an-agreed-implementation-order).
