# GOLDM_REVISED — stopped trades that first held floating profit

## Scope

- Candidate: REVISED stop multiplier 1.75, target multiplier 2.5
- Full suite: 2020-01-01 through 2026-08-19
- Analysis clock: closed broker M1 bars
- Population: 640 final STOP outcomes
- Focus population: 478 STOPs that first reached at least +0.25R
- This is diagnosis, not a filter or runtime change

## Five distinct path types

| Archetype | Count | Share | Mean MFE | Mean target | Median peak→SL | Momentum reversal detected |
|---|---:|---:|---:|---:|---:|---:|
| Shallow profit fade | 96 | 20.1% | 0.37R | 3.34R | 12.5 min | 85.4% |
| Medium profit fade | 149 | 31.2% | 0.73R | 3.31R | 26 min | 91.9% |
| 1R+ round trip | 141 | 29.5% | 1.41R | 3.78R | 43 min | 95.0% |
| Deep runner fade | 49 | 10.3% | 2.93R | 5.90R | 67 min | 98.0% |
| Near-target reversal | 43 | 9.0% | 2.75R | 3.10R | 88 min | 97.7% |

These types should not share one trailing or exit response. The shallow group
is an early false start, while deep-runner and near-target cases held a valid
move for much longer before relinquishing it.

## Typical timeline

Across all 478 profitable fades:

| Event after entry/peak | Median time |
|---|---:|
| Entry → MFE peak | 20 min |
| Peak → M1 bearish micro-break | 3 min |
| Peak → three-bar momentum reversal | 3 min |
| Peak → first intrabar return to entry | 6 min |
| Peak → first close below entry | 7 min |
| Peak → two-close acceptance below entry | 14.5 min |
| Peak → final SL | 30 min |

Detection and remaining lead time:

| Post-peak evidence | Detected | Detection median | Median lead before SL |
|---|---:|---:|---:|
| M1 micro-break | 451 / 478 | 3 min | 30 min |
| M1 momentum reversal | 443 / 478 | 3 min | 29 min |
| Two-close acceptance below entry | 434 / 478 | 14.5 min | 14 min |
| Return to entry | 467 / 478 | 6 min | 20 min |

There is generally enough time to react before the original SL. The problem is
not that invalidation appears only at the stop; it often appears much earlier.

## Target distance and first obstacle

| Population | Mean target R | Mean first-obstacle R | Target/obstacle ratio |
|---|---:|---:|---:|
| Final targets | 2.57R | 1.16R | 2.15× |
| All stops | 3.54R | 1.54R | 2.26× |
| Stops after floating profit | **3.70R** | **1.60R** | **2.27×** |

Every one of the 478 profitable fades had its scaled target beyond the first
obstacle. Price actually reached/passed the first obstacle in 170 cases. All 43
near-target reversals and 37 of 49 deep-runner fades first reached their
obstacle.

This is the strongest real variable in the analysis: profitable fades were
asked to travel materially farther than winners. It does not mean every trade
should be capped at the obstacle, but it explains why fixed no-management
runners surrender large floating gains.

## Post-entry invalidation is informative but not sufficient alone

Among the 478 profitable STOPs:

- 438 show both M1 micro-break and momentum reversal after peak;
- 419 show micro-break, momentum reversal, and two-close acceptance below
  entry.

Control group: 310 eventual winners that first reached +0.5R:

- 139 returned intrabar to entry;
- 120 closed below entry;
- 226 showed a bearish micro-break;
- 221 showed momentum reversal;
- 90 showed two-close acceptance below entry;
- 89 showed micro-break + momentum + acceptance and still recovered to TP.

Therefore a single micro-break, momentum reversal, breakeven touch, or even the
three-signal combination cannot automatically close every position. Doing so
would close roughly 29% of the +0.5R winner control group. This matches the
causal trailing experiment, where fixed trailing reduced expectancy and USD
profit.

## Time-of-day observations

Profitable fades occur in every session; there is no clean bad-session filter.

| Session | Count | Share | Mean MFE | Median peak→SL |
|---|---:|---:|---:|---:|
| Asia | 147 | 30.8% | 1.23R | 33 min |
| London | 146 | 30.5% | 1.16R | 30 min |
| London–NY overlap | 113 | 23.6% | 1.20R | 23 min |
| New York late | 72 | 15.1% | 1.64R | 52 min |

Notable hours in server time:

- 04:00: 31 profitable fades from 35 stops (88.6%), median 39 min peak→SL;
- 21:00: 19/22 (86.4%), mean MFE 1.85R, median 93 min peak→SL;
- 02:00: 24/28 (85.7%), but only 22.2% overall win rate;
- 11:00: 34/42 (81.0%), median 62 min peak→SL;
- 16:00–19:00 contains 15 of the 43 near-target reversals.

Hours describe liquidity/reversal timing, but winners also occur in those
hours. They should guide management timing research, not entry exclusion.

## Other observed variables

- RANGE supplies 384 profitable fades and MOMENTUM 94, but their mean MFE is
  nearly identical (1.26R versus 1.28R).
- BULL_ENGULFING is 71.3% of fades because it is also the dominant setup; its
  final win rate is 33.6%, similar to morning-star at 33.0%.
- Retest count is not a simple defect: win rate rises from 31.8% at zero retest
  to 37.8% at two, while profitable-fade frequency also rises.
- H1 trend, H1 efficiency, and M5 ATR expansion are almost identical between
  winner and STOP groups. They do not explain the round trip alone.
- Psychological `$10` is the first obstacle for 272 profitable fades (56.9%).

## Research conclusion

There are two main mechanisms, not one:

1. **Fast failed continuation:** shallow/medium fades peak quickly and show
   micro-break/momentum within about three minutes. These may benefit from a
   stateful invalidation response, but winner false positives are substantial.
2. **Valid move with overextended objective:** 1R+, deep-runner, and near-target
   trades hold profit for tens of minutes, often reach the first obstacle, then
   reverse because the scaled target remains much farther away.

The next valid experiment is not a universal trailing stop. It should replay a
state machine that conditions management on current achieved R, first-obstacle
touch, persistence of acceptance, and time since peak. No change is applied to
REVISED from this analysis.
