# 2026-11-18: sector_mom (trial #4) - FAIL

- **Hypothesis**: stocks in sectors that have recently outperformed keep outperforming (industry momentum).
- **Source**: Moskowitz & Grinblatt (1999), J. Finance 54(4), 1249-1290 (citation checked by search). Disputed by Grundy & Martin
  (2001) and Lewellen (2002). Note: the backlog row originally said "stock relative to its sector"; the paper is about
  the sector's own momentum, so that is what was tested (sector mean trailing return, tiny own-return tie-break).
- **Grid** (fixed before any result): lookback 126 / 252, skip 21; top 10, buffer 10, bear exit, monthly.
- **Setup**: liquid top-100, INR 5,000, real costs, walk-forward, OOS 2021-01-01 to 2026-11-17.

| gate | result |
|---|---|
| no_lookahead | pass |
| beats index and basket | FAIL: 8.2% vs 12.9% vs 16.3% |
| beats index in most years | FAIL: 3 of 6 (need 4) |
| beats random picks | pass: 8.2% vs 4.0% |
| robust across grid | FAIL: 12.3% (126) and 9.4% (252), both below the index |
| deflated Sharpe | FAIL: 0.60 after 4 counted trials |
| charges < 3% | FAIL: 4.0% (72 trades) |
| not a duplicate | pass: correlation 0.79 with default momentum |

| account | candidate CAGR | index | basket | max DD | charges %/yr | years beating index |
|---|---|---|---|---|---|---|
| 5,000 | 8.2% | 12.9% | 16.3% | -21% | 4.0 | 3/6 |
| 25,000 | 15.9% | 12.9% | 16.3% | -33% | 1.7 | 4/6 |
| 100,000 | 17.1% | 12.9% | 16.3% | -35% | 1.0 | 4/6 |

## What happened
Merit at 100,000 is "yes" (every grid point beats the index there), but the margin over the survivorship-flattered basket
is under one point and the drawdown is about -35%, because ten stocks from the one or two hottest sectors is a
concentrated bet. At INR 5,000 costs and whole shares cut the return roughly in half. Together with `high_52w`
(16.5% at 100,000) this is a second lead that only exists with more capital; neither survives the INR 5,000 gate.
