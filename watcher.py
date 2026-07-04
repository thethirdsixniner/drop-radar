"""
watcher.py
Polls each store's public Shopify /products.json endpoint, detects:
  - brand new products (never seen before)
  - restocked variants (a variant that was out of stock is now available)
Sends alerts to Discord via webhook, and persists state to state.json
so re-runs only alert on genuinely new changes.
"""

from __future__ import annotations
import json
import os
import sys
import time
from typing import Dict, List

import requests

from stores import STORES

STATE_FILE = "state.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (DropRadar/1.0; +https://github.com/)"}
REQUEST_TIMEOUT = 15


def fetch_products(store_url: str) -> List[dict]:
    """Fetch the product catalog from a Shopify store's public JSON feed."""
    url = f"{store_url}/products.json?limit=250"
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("products", [])


def summarize(products: List[dict]) -> Dict[str, dict]:
    """
    Reduce full Shopify product objects down to just what we need to
    detect changes: product id -> {title, handle, any_variant_in_stock}
    """
    summary = {}
    for p in products:
        variants = p.get("variants", [])
        in_stock = any(v.get("available") for v in variants)
        summary[str(p["id"])] = {
            "title": p.get("title", "Untitled"),
            "handle": p.get("handle", ""),
            "in_stock": in_stock,
        }
    return summary


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def diff_store(store_name: str, store_url: str, previous: dict, current: dict) -> List[str]:
    """
    Returns a list of human-readable alert messages for this store:
      - new products that weren't seen before
      - products that flipped from out-of-stock -> in-stock (restock)
    """
    alerts = []

    for product_id, info in current.items():
        prev_info = previous.get(product_id)

        if prev_info is None:
            # Never seen this product before -> brand new drop
            if info["in_stock"]:
                alerts.append(
                    f"🆕 **New drop** at {store_name}: {info['title']}\n"
                    f"{store_url}/products/{info['handle']}"
                )
            continue

        was_in_stock = prev_info.get("in_stock", False)
        now_in_stock = info["in_stock"]
        if (not was_in_stock) and now_in_stock:
            alerts.append(
                f"🔥 **Restock** at {store_name}: {info['title']}\n"
                f"{store_url}/products/{info['handle']}"
            )

    return alerts


def send_discord_alert(webhook_url: str, message: str) -> None:
    resp = requests.post(webhook_url, json={"content": message}, timeout=REQUEST_TIMEOUT)
    # Discord returns 204 on success
    if resp.status_code >= 300:
        print(f"Warning: Discord webhook returned {resp.status_code}: {resp.text}", file=sys.stderr)


def run(webhook_url: str | None = None) -> int:
    state = load_state()
    new_state = {}
    total_alerts = 0

    for store in STORES:
        name, url = store["name"], store["url"]
        print(f"Checking {name} ({url})...")

        try:
            products = fetch_products(url)
        except requests.RequestException as e:
            print(f"  -> Error fetching {name}: {e}", file=sys.stderr)
            # Keep previous state for this store so a transient network
            # error doesn't wipe our history and cause false "new" alerts
            new_state[url] = state.get(url, {})
            continue

        current = summarize(products)
        previous = state.get(url, {})

        if not previous:
            # First time seeing this store — record a baseline silently.
            # Without this, every in-stock product would look "new" and
            # flood the channel on the very first run.
            print(f"  -> First run for {name}, recording baseline ({len(current)} products), no alerts sent.")
            new_state[url] = current
            time.sleep(1)
            continue

        alerts = diff_store(name, url, previous, current)
        for alert in alerts:
            print(f"  -> {alert}")
            if webhook_url:
                send_discord_alert(webhook_url, alert)
                time.sleep(1)  # be polite to Discord's rate limits
        total_alerts += len(alerts)

        new_state[url] = current
        time.sleep(1)  # be polite between store requests

    save_state(new_state)
    print(f"\nDone. {total_alerts} alert(s) sent across {len(STORES)} store(s).")
    return total_alerts


if __name__ == "__main__":
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("Warning: DISCORD_WEBHOOK_URL not set — running in dry-run mode (console only).")
    run(webhook)
