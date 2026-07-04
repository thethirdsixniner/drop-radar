"""
watcher.py
Polls each store's public Shopify /products.json endpoint, detects:
  - brand new products (never seen before)
  - restocked variants (a variant that was out of stock is now available)

Two-tier alert delivery:
  - VIP webhook: gets the alert immediately
  - FREE webhook: gets the SAME alert, but only after a delay
    (default 45 minutes), so free members see it later than paying members.

State is persisted to state.json:
  {
    "stores": { store_url: { product_id: {title, handle, in_stock} } },
    "pending_free": [ {"message": "...", "detected_at": "2026-07-04T12:00:00"} ]
  }
"""

from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests

from stores import STORES

STATE_FILE = "state.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (DropRadar/1.0; +https://github.com/)"}
REQUEST_TIMEOUT = 15
FREE_TIER_DELAY_MINUTES = 45  # how long free members wait behind VIP


def fetch_products(store_url: str) -> List[dict]:
    """Fetch the product catalog from a Shopify store's public JSON feed."""
    url = f"{store_url}/products.json?limit=250"
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("products", [])


def summarize(products: List[dict]) -> Dict[str, dict]:
    """Reduce full Shopify product objects to id -> {title, handle, in_stock}."""
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
    """
    Load state.json, migrating the old flat format
    ({store_url: {...}}) into the new format
    ({"stores": {...}, "pending_free": [...]}) transparently.
    """
    if not os.path.exists(STATE_FILE):
        return {"stores": {}, "pending_free": []}

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if "stores" in raw or "pending_free" in raw:
        raw.setdefault("stores", {})
        raw.setdefault("pending_free", [])
        return raw

    # Old format: the whole dict IS the stores dict
    return {"stores": raw, "pending_free": []}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def diff_store(store_name: str, store_url: str, previous: dict, current: dict) -> List[str]:
    """Returns human-readable alert messages: new drops + restocks."""
    alerts = []

    for product_id, info in current.items():
        prev_info = previous.get(product_id)

        if prev_info is None:
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
    if resp.status_code >= 300:
        print(f"Warning: Discord webhook returned {resp.status_code}: {resp.text}", file=sys.stderr)


def run(webhook_vip: str | None = None, webhook_free: str | None = None) -> int:
    state = load_state()
    stores_state = state["stores"]
    pending_free = state["pending_free"]

    new_stores_state = {}
    total_new_alerts = 0
    now = datetime.now(timezone.utc)

    # --- Step 1: check each store, send anything new instantly to VIP ---
    for store in STORES:
        name, url = store["name"], store["url"]
        print(f"Checking {name} ({url})...")

        try:
            products = fetch_products(url)
        except requests.RequestException as e:
            print(f"  -> Error fetching {name}: {e}", file=sys.stderr)
            new_stores_state[url] = stores_state.get(url, {})
            continue

        current = summarize(products)
        previous = stores_state.get(url, {})

        if not previous:
            print(f"  -> First run for {name}, recording baseline ({len(current)} products), no alerts sent.")
            new_stores_state[url] = current
            time.sleep(1)
            continue

        alerts = diff_store(name, url, previous, current)
        for alert in alerts:
            print(f"  -> {alert}")
            if webhook_vip:
                send_discord_alert(webhook_vip, alert)
                time.sleep(1)
            # Queue the same alert for free members, to be released later
            pending_free.append({"message": alert, "detected_at": now.isoformat()})
        total_new_alerts += len(alerts)

        new_stores_state[url] = current
        time.sleep(1)

    # --- Step 2: release any free-tier alerts whose delay has passed ---
    still_pending = []
    released_count = 0
    for item in pending_free:
        detected_at = datetime.fromisoformat(item["detected_at"])
        if now - detected_at >= timedelta(minutes=FREE_TIER_DELAY_MINUTES):
            print(f"  -> Releasing to FREE tier: {item['message']}")
            if webhook_free:
                send_discord_alert(webhook_free, item["message"])
                time.sleep(1)
            released_count += 1
        else:
            still_pending.append(item)

    save_state({"stores": new_stores_state, "pending_free": still_pending})
    print(
        f"\nDone. {total_new_alerts} new alert(s) sent to VIP, "
        f"{released_count} alert(s) released to FREE tier, "
        f"{len(still_pending)} still waiting."
    )
    return total_new_alerts


if __name__ == "__main__":
    vip = os.environ.get("DISCORD_WEBHOOK_VIP")
    free = os.environ.get("DISCORD_WEBHOOK_FREE")
    if not vip:
        print("Warning: DISCORD_WEBHOOK_VIP not set — VIP alerts will be console-only.")
    if not free:
        print("Warning: DISCORD_WEBHOOK_FREE not set — free alerts will be console-only.")
    run(webhook_vip=vip, webhook_free=free)