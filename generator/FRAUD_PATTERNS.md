# Fraud Patterns

What the injector plants, what it labels, and which rule is supposed to catch it.
One section per pattern. Keep this file updated as patterns are added — it is the
map between `generator/fraud.py`, `db/tests/`, and `rules/`.

## The ground rule

Every planted thing writes a row to `fraud_labels`:

| column | meaning |
|---|---|
| `entity_type` / `entity_id` | what was tampered with (`settlement`, `bet`, `transaction`, `player`, `session`) |
| `pattern_code` | which pattern, from the table below |
| `cluster_id` | ties several rows to one incident (multi-accounting, matched betting) |
| `details` | jsonb: what the correct value was, and any knobs used |
| `injected_at` | simulated time, not wall clock |

**Nothing in `rules/` may ever read `fraud_labels`.** The rules must find the fraud
from the same data an analyst would have. The table exists only to score them
afterwards — precision, recall, F1 per rule.

Files in `db/tests/` *may* join to it, for one purpose: telling "planted on purpose"
apart from "broken by accident".

## Status

| # | `pattern_code` | Entity | Status | Rule that should catch it |
|---|---|---|---|---|
| 1 | `SETTLEMENT_ERROR` | settlement | **done** | settlement mismatch |
| 2 | `MULTI_ACCOUNT` | player | planned | linked accounts |
| 3 | `PASSTHROUGH` | transaction | planned | turnover ratio |
| 4 | `CARD_TESTING` | transaction | planned | deposit velocity |
| 5 | `LATE_BET` | bet | planned | late bet |
| 6 | `STAKE_ESCALATION` | bet | planned | stake anomaly |
| 7 | `MATCHED_BETTING` | bet | planned | opposing bets |
| 8 | `BONUS_ABUSE` | player | blocked | bonus abuse |

---

## 1. `SETTLEMENT_ERROR` — done

The bridge between this project and day-to-day work on payout accuracy.

**What the generator does.** In `fraud.break_settlement()`, at
`SETTLEMENT_ERROR_RATE` (default 0.0005, about 1 in 2000 settlements), one of two
things happens instead of the correct payout:

- `wrong_amount` — a **won** bet is paid 5–40% too much or too little.
- `lost_bet_paid` — a **losing** bet is paid 50–100% of what a win would have been.

**Labels.** `entity_type = 'settlement'`, `details` carries `variant`,
`correct_payout`, and the offset or share used.

**The rule.** `ABS(payout - stake * total_odds) > 0.01`.

**Known blind spot, on purpose.** That rule is usually written with
`WHERE result = 'won'`, which makes `lost_bet_paid` invisible to it at any
threshold. Losing bets outnumber winners roughly 2:1, so about two thirds of what
is planted here cannot be found by the obvious version of the rule. Recall of ~0.33
on this pattern is the rule's fault, not the data's.

---

## 2. `MULTI_ACCOUNT` — planned

3–6 accounts belonging to one person, registered within a few days, sharing a
`device_id` or a payment `fingerprint`, betting similarly.

**Honest noise it has to compete with:** the household sharing already in the
generator — at 90 days, 156 shared devices out of 9,594, four of them with three
players. Every one of those is a false positive waiting to happen.

**Needs first:** `cluster_id` on every member, so the whole ring scores as one
incident rather than N separate ones.

**Open question:** with one device per player today, the device graph is
unrealistically clean. Several devices per player would make this pattern — and the
rule — much closer to real life. Parked.

---

## 3. `PASSTHROUGH` — planned

Large deposit, almost no betting, withdrawal within the hour, often to a different
payment method. Money laundering shaped.

**The rule.** Turnover ratio: withdrawals ÷ stakes per player per day, flagged below
0.1 with deposits above a floor.

**Needs first:** more than one payment method per player, otherwise "withdrew to a
different method" cannot be expressed.

---

## 4. `CARD_TESTING` — planned

Many small deposits from different card fingerprints, one IP, high rejection rate —
someone checking which stolen cards still work.

**The rule.** Deposit velocity: deposits per player per rolling hour, using a
`RANGE BETWEEN INTERVAL '1 hour' PRECEDING` window.

**Fits the schema already:** rejection rate is modelled (8% of honest deposits), and
the generator can create extra payment methods for the tester.

---

## 5. `LATE_BET` — planned

A bet timestamped after `events.start_time`, or priced against stale odds.

**The rule.** `bets.placed_at > events.start_time`.

**Baseline is clean:** on 649,790 honest bets at 90 days this returns 0. Anything it
returns after injection is either planted or a generator bug.

**Watch out:** the generator structurally prevents late bets (`load_open_selections`
only offers matches starting after the current hour), so the injector has to write
these deliberately, bypassing that path.

---

## 6. `STAKE_ESCALATION` — planned

Weeks of small bets, then one very large one — the shape of an account takeover.

**The rule.** `stake / AVG(stake) OVER (PARTITION BY player_id ORDER BY placed_at
ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING)`.

**Honest noise it has to compete with:** high-rollers stake log-normally, so large
bets happen legitimately all the time. This is the pattern where the threshold
actually has to be earned from the data.

---

## 7. `MATCHED_BETTING` — planned

Linked accounts backing opposite selections on the same market within minutes, to
clear a bonus or move money between accounts at near-zero risk.

**The rule.** Self-join `bet_selections` on market where selections differ, players
are in the same link cluster, and `placed_at` is within 10 minutes.

**Depends on `MULTI_ACCOUNT`** — the accounts have to be linked before betting
opposite sides means anything.

---

## 8. `BONUS_ABUSE` — blocked

Deposit exactly the bonus minimum, wager the requirement on near-certain low-odds
markets, withdraw.

**Blocked on:** the `bonuses` table exists but nothing writes to it. The generator
needs to grant welcome bonuses and track `wagered_amount` before this can be planted
or detected.

---

## Config knobs

All in `config.py`:

```
INJECT_FRAUD              master switch - False gives a clean dataset for comparison
SETTLEMENT_ERROR_RATE     share of settlements planted as wrong
SETTLEMENT_ERROR_OFFSET   how far off a wrong_amount payout is
```

Rate matters more than it looks. Too rare and precision/recall are computed from a
handful of rows and mean nothing. Too common and the dataset stops looking like a
real back office, where fraud is a small fraction of a percent.
