# Drop Radar

Free, automated restock & new-drop alerts for independent streetwear/sneaker Shopify stores — delivered straight to Discord.

## Why

Big retailers (Nike, Target, Pokémon Center) already have huge free monitoring communities. Boutique/independent stores like Kith, Undefeated, Asphaltgold, or Sneaker Politics don't — there are thousands of them and nobody bothers to watch each one closely. Drop Radar fills that gap.

## How it works

1. Every 15 minutes, GitHub Actions runs `watcher.py` for free (no server needed).
2. It fetches each store's public `products.json` feed — a standard, publicly documented Shopify feature, not scraping.
3. It compares the current catalog against the last saved snapshot (`state.json`).
4. If a product is brand new, or a sold-out variant flips back to available, it posts an alert to a Discord webhook.
5. The new snapshot is committed back to the repo so the next run only alerts on genuinely new changes.

## Setup

### 1. Fork/clone this repo

### 2. Create a Discord webhook
- In your Discord server: Server Settings → Integrations → Webhooks → New Webhook
- Copy the webhook URL

### 3. Add it as a GitHub secret
- Repo → Settings → Secrets and variables → Actions → New repository secret
- Name: `DISCORD_WEBHOOK_URL`
- Value: paste your webhook URL

### 4. Enable the workflow
- Go to the **Actions** tab on your repo → enable workflows if prompted
- It'll now run automatically every 15 minutes

### 5. Add/remove stores
Edit `stores.py` — any Shopify store works, just add its root URL.

## Monetization model

- **Free public Discord**: alerts delayed by ~30-60 minutes (edit the workflow schedule or add a delay), or limited to a subset of stores
- **Paid private Discord role**: instant alerts across all stores — collect payment manually via PayPal.me and grant the role yourself at small scale

## Local testing

```bash
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="your-webhook-url"   # optional, omit for dry-run
python watcher.py
```

## Notes

- First run on a new store always baselines silently (no alerts) so you don't get flooded with "new" alerts for the entire existing catalog.
- Respect each store's terms of service and reasonable request rates — this polls once per 15 minutes per store, which is well within normal browsing-level traffic.
