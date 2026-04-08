---
name: n-strategy-project
description: Use when working in the N-strategy project to keep the environment, market index, Tencent K-line source, and SQLite cache conventions consistent with the project's bottom-doji plus N-breakout scanner.
---

# N-strategy Project

## When to use

Use this skill whenever the task touches strategy logic, data fetching, environment setup, or scan execution in `/Users/admin/Documents/codeHub/N-strategy`.

## Fixed project conventions

- Conda environment name: `n-strategy`
- Market index for regime filter: `000001` (上证指数)
- K-line source: Tencent `web.ifzq.gtimg.cn/appstock/app/fqkline/get`
- Stock list source priority: Tencent realtime API first, Eastmoney fallback
- Local cache: SQLite file [n_strategy.db](/Users/admin/Documents/codeHub/N-strategy/n_strategy.db)
- Feishu webhook source: environment variable `FEISHU_WEBHOOK_URL` or GitHub Actions secret with the same name

## Working rules

- Reuse [config.py](/Users/admin/Documents/codeHub/N-strategy/config.py) for thresholds instead of hardcoding new constants.
- Reuse [data_fetcher.py](/Users/admin/Documents/codeHub/N-strategy/data_fetcher.py) for all OHLCV access so cache behavior stays consistent.
- Keep strategy detection in [strategy.py](/Users/admin/Documents/codeHub/N-strategy/strategy.py).
- Use [main.py](/Users/admin/Documents/codeHub/N-strategy/main.py) as the scan entrypoint.

## Strategy checklist

1. Gate everything behind the market filter: index above MA20 or index daily gain above 1%.
2. Search for a bottom doji 5 to 15 trading days before today.
3. Require a next-day volume surge candle after the doji.
4. Require a 2 to 5 day pullback with no new low and clear volume contraction.
5. Trigger only on a close above the first surge high with same-day volume expansion.

## Command patterns

- Syntax check: `python -m compileall .`
- Small scan: `python main.py --limit 50`
- Full scan: `python main.py`
- Notify run: `python main.py --limit 100 --notify`
