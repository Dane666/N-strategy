# N-strategy

A-share scanner for the "bottom doji + contraction pullback N-breakout" setup.

## Local run

```bash
conda env create -f environment.yml
conda run -n n-strategy python main.py --limit 50
conda run -n n-strategy python main.py --limit 50 --notify
```

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
