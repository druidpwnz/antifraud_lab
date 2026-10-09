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
| 5 | `LATE_BET` | bet | **done** | late bet |
| 6 | `STAKE_ESCALATION` | bet | **done** | stake anomaly |
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

## 5. `LATE_BET` — done

A bet timestamped after `events.start_time`, or priced against stale odds.

**The rule.** `bets.placed_at > events.start_time`.

**Baseline is clean:** on 649,790 honest bets at 90 days this returns 0. Anything it
returns after injection is either planted or a generator bug.

**What the generator does.** `fraud.maybe_late_bets()` runs after normal betting.
At `LATE_BET_RATE` (0.01 per session) a player backs a single
selection on a match that has already kicked off but is not over — priced at the
last pre-match odds, because `move_odds` stops touching a selection once its match
starts. That staleness is exactly what a late bettor is after.

The bet lands strictly between kickoff and the final whistle
(`config.MATCH_MINUTES`). An earlier version let it land up to ten minutes after the
match ended, which broke a harder rule: settlement is timestamped from
`finished_at`, so those bets were settled *before* they were placed. The
`settled_too_early` check caught it. A deliberate post-match variant would be a
stronger pattern and is worth adding later — but then settlement has to timestamp
itself after the bet, which `settle_bets` now does.

**Labels.** `entity_type = 'bet'`, `details` carries `event_id`,
`seconds_after_kickoff` and `odds_at_placement`.

**Known gap.** A real late bettor bets *because* they already know something — a
goal has gone in. Ours picks a selection at random, so planted late bets win at
roughly the honest rate. Biasing them toward the eventual winner would add a second
detectable signal (an abnormal win rate) and make the pattern more realistic. It
needs the final score to be drawn at fixture creation instead of at settlement.

---

## 6. `STAKE_ESCALATION` — done

Weeks of small bets, then one very large one — the shape of an account takeover.

**The rule.** `stake / AVG(stake) OVER (PARTITION BY player_id ORDER BY placed_at
ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING)`.

**What the generator does.** `fraud.maybe_stake_escalation()` needs a player with a
real history (`ESCALATION_MIN_BETS`, 15 bets) *and* a balance worth emptying
(`ESCALATION_MIN_MULTIPLE`, 8x their own average stake). Only a few percent of
sessions qualify, which is why `STAKE_ESCALATION_RATE` is 0.10 — far higher than
the other patterns, for a comparable number of plants. The bet is a single, staked at
10-40x the player's running average, capped by the balance.

**Labels.** `entity_type = 'bet'`, `details` carries `average_stake`, `stake`,
`multiple_of_average` and `bets_before`.

**The point of this one.** At 14 days, 40 of the 51 planted bets are *smaller* than
the 20th biggest honest bet in the database (455.69; measured again after the
5-minute ticks — it was 17 of 26 with hourly steps). An absolute threshold ("flag stakes over
500") cannot separate them from honest high-rollers at any level. Only a per-player
comparison can - which is exactly what the window function in the stake-anomaly rule
is for:

    stake / AVG(stake) OVER (PARTITION BY player_id ORDER BY placed_at
                             ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING)

**Known gap.** A real takeover usually comes with a new device or IP. These bets come
from the player's normal session, so that second signal is not there.

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
