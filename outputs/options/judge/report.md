# DSRD Short-Strangle — Judge Report

**Verdict: FAIL** (judged window 2023-01-01 → 2026-08-18, stop none, earnings filter ON, capital ₹500,000)

## Criteria

- `cagr_beats_fd_7pct`: FAIL (value 0.0271, threshold 0.07)
- `sharpe_beats_nifty`: FAIL (value -0.5753, threshold 0.21969561150552744)
- `max_drawdown_below_30pct`: PASS (value 0.0988, threshold 0.3)
- `covid_2020_equity_floor_above_60pct`: PASS (value 0.9661, threshold 0.6)
- `monthly_excess_tstat_above_2`: FAIL (value -1.0890, threshold 2.0)

## Judged stats

- breach_rate: 0.2778
- cagr: 0.0271
- equity_floor_fraction: 0.9470
- max_drawdown: 0.0988
- mean_monthly_return: 0.0024
- median_margin: 112560.0000
- n_months: 43
- n_trades: 36
- profit_factor: 1.3733
- sharpe: -0.5753
- sortino: -0.6595
- t_stat_excess: -1.0890
- total_return: 0.1004
- win_rate: 0.7778

## Per-year returns (judged)

- 2023: -2.4%
- 2024: +6.1%
- 2025: +0.0%
- 2026: +6.3%

## Variant: earnings filter OFF

- total_return: 0.1004
- sharpe: -0.5753
- max_drawdown: 0.0988
- n_trades: 36
- win_rate: 0.7778

## Symbol attribution (judged, net P&L)

Best:
- WIPRO: ₹11,783
- ZEEL: ₹11,383
- ADANIPORTS: ₹10,839
- GAIL: ₹10,278
- AARTIIND: ₹9,439
- TATAPOWER: ₹9,214
- NBCC: ₹9,049
- CUB: ₹8,773
- TATASTEEL: ₹8,633
- SAMMAANCAP: ₹7,840

Worst:
- IEX: ₹-58,441
- CHAMBLFERT: ₹-14,979
- NMDC: ₹-10,169
- ASHOKLEY: ₹-8,905
- YESBANK: ₹-6,329
- PETRONET: ₹-6,289
- IDEA: ₹-2,930
- CANBK: ₹-952
- COALINDIA: ₹1,419
- INDUSTOWER: ₹3,115

## Finding #0 — capital feasibility

- median trade margin: ₹112,560
- ₹1L supports a single strangle: False
