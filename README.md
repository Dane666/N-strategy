# N-strategy

A-share scanner for the "N-breakout + KDJ J oversold reversal" setup.

## Local run

```bash
conda env create -f environment.yml
conda run -n n-strategy python main.py --limit 50
conda run -n n-strategy python main.py --limit 50 --notify
```

## Signal summary

- Market regime: index above MA20, or the stock remains in a long-decline bottom region
- First leg: a >5% surge candle within 10 trading days with volume ratio > 1.5
- Pullback: 2-5 day retracement with clear volume contraction
- KDJ washout: `J < 0`, or `J < 10 and K < 20`
- Candle confirmation: a doji or hammer appears on the oversold day or the next day
- Trigger: today closes above yesterday, J turns up, and volume is above yesterday

## Feishu secret

Do not store the webhook in code.

- Local shell: set `FEISHU_WEBHOOK_URL`
- GitHub Actions: add repository secret `FEISHU_WEBHOOK_URL`

## GitHub Actions

Manual run:

1. Open `Actions`
2. Select `n-strategy-scan`
3. Click `Run workflow`

Scheduled runs use the repository secret automatically.
