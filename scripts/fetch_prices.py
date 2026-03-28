#!/usr/bin/env python3
"""
scripts/fetch_prices.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE: Real prices from edahabapp.com ONLY.
      If scraping fails → keep existing prices.json unchanged.
      NEVER write math-calculated prices (they don't match Egypt market).

Sources tried in order:
  1. Cloudflare Worker proxy → edahabapp.com  (set PROXY_URL secret)
  2. allorigins.win proxy   → edahabapp.com
  3. corsproxy.io proxy     → edahabapp.com
  4. codetabs.com proxy     → edahabapp.com

USD/EGP and gold oz: always read from edahabapp.com page directly.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

GRAMS_PER_OZ = 31.1035
KARAT_MAP    = {"24": "g24k", "21": "g21k", "18": "g18k", "14": "g14k"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Regex tested against real edahabapp.com HTML ──────────────
# Structure:
#   الذهب عيار 24:
#   [blank line]
#   بيع: 7840 جنيه
#   شراء: 7784 جنيه
_KARAT_RE = re.compile(
    r"عيار\s*(\d+)[^\n]*\n"
    r"[\s\S]{0,30}?"
    r"بيع:\s*([\d,]+)[^\n]*\n"
    r"[\s\S]{0,30}?"
    r"شراء:\s*([\d,]+)",
)


# ─────────────────────────────────────────────────────────────
# Parse edahabapp HTML → prices dict
# ─────────────────────────────────────────────────────────────
def parse_edahab_html(html: str) -> dict:
    if "عيار" not in html or "بيع" not in html:
        raise ValueError(
            f"Page missing expected Arabic content. "
            f"Length={len(html)}. Preview: {html[:300]!r}"
        )

    prices = {}

    for m in _KARAT_RE.finditer(html):
        karat    = m.group(1)
        sell_val = int(m.group(2).replace(",", ""))
        buy_val  = int(m.group(3).replace(",", ""))
        key = KARAT_MAP.get(karat)
        if key:
            prices[key] = {"sell": sell_val, "buy": buy_val}
            print(f"    ✔ {key}: buy={buy_val:,}  sell={sell_val:,}")

    # جنيه الذهب
    m = re.search(r"الجنيه الذهب[^\n]*\n\s*([\d,]+)", html)
    if m:
        prices["pound"] = int(m.group(1).replace(",", ""))
        print(f"    ✔ pound    = {prices['pound']:,}")

    # أوقية عالمياً
    m = re.search(r"الأوقية عالمياً[^\n]*\n\s*([\d,]+)", html)
    if m:
        prices["oz_usd"] = int(m.group(1).replace(",", ""))
        print(f"    ✔ oz_usd   = {prices['oz_usd']:,}")

    # دولار أمريكي
    m = re.search(r"الدولار الأمريكي[^\n]*\n\s*([\d.]+)", html)
    if m:
        prices["usd_egp"] = float(m.group(1))
        print(f"    ✔ usd_egp  = {prices['usd_egp']}")

    # Validate we got the essential prices
    missing = [k for k in ["g24k", "g21k", "g18k"] if k not in prices]
    if missing:
        raise ValueError(f"Parsing succeeded but missing karats: {missing}. "
                         f"Found: {list(prices.keys())}")

    return prices


# ─────────────────────────────────────────────────────────────
# Fetch HTML via URL (direct or proxy)
# ─────────────────────────────────────────────────────────────
def fetch_html(url: str, label: str) -> str:
    print(f"  ↳ Fetching [{label}]: {url[:70]}")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    print(f"  ↳ HTTP {resp.status_code}  ({len(resp.text):,} bytes)")
    if resp.status_code in (403, 429, 502, 503):
        raise ValueError(f"Blocked/error: HTTP {resp.status_code}")
    resp.raise_for_status()
    return resp.text


# ─────────────────────────────────────────────────────────────
# All fetch strategies
# ─────────────────────────────────────────────────────────────
def get_strategies() -> list:
    """
    Returns list of (label, url) pairs to try in order.
    Cloudflare Worker (most reliable) goes first if PROXY_URL is set.
    """
    target = "https://edahabapp.com/"
    strategies = []

    # 1. Cloudflare Worker proxy — set PROXY_URL in GitHub Secrets
    proxy_url = os.environ.get("PROXY_URL", "").strip()
    if proxy_url:
        strategies.append(("Cloudflare Worker", proxy_url))

    # 2. Public CORS proxies (no setup needed, may or may not work)
    strategies += [
        ("allorigins.win",
         f"https://api.allorigins.win/raw?url={target}"),
        ("corsproxy.io",
         f"https://corsproxy.io/?{target}"),
        ("codetabs.com",
         f"https://api.codetabs.com/v1/proxy?quest={target}"),
    ]

    return strategies


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("⚡  edahabapp gold price scraper")
    print(f"    PROXY_URL: {'SET ✅' if os.environ.get('PROXY_URL') else 'NOT SET ⚠️'}")
    print("=" * 60)

    # ── Try every fetch strategy until one works ──────────────
    prices    = None
    used_label = None

    for label, url in get_strategies():
        print(f"\n🔄 Trying: {label}")
        try:
            html   = fetch_html(url, label)
            prices = parse_edahab_html(html)
            used_label = label
            print(f"  ✅ SUCCESS via {label}")
            break
        except Exception as e:
            print(f"  ⚠️  Failed [{label}]: {e}")
            time.sleep(2)

    # ── If ALL sources failed — preserve existing file ────────
    if prices is None:
        print("\n" + "=" * 60)
        print("❌ ALL SOURCES FAILED")
        print("   Existing data/prices.json will NOT be overwritten.")
        print("   Fix: Add PROXY_URL secret (Cloudflare Worker).")
        print("   See cloudflare-worker.js in the repo.")
        print("=" * 60)
        sys.exit(1)   # non-zero exit → GitHub Actions shows failure ✅

    # ── Build payload from REAL scraped prices only ───────────
    def karat_buy(key):  return prices.get(key, {}).get("buy")
    def karat_sell(key): return prices.get(key, {}).get("sell")

    g24_buy = karat_buy("g24k")

    payload = {
        # Global rates — read from page, not calculated
        "gold_usd_oz": prices.get("oz_usd"),
        "usd_egp":     prices.get("usd_egp"),

        # Real EGP gram prices from edahabapp.com
        "gold_egp_gram_24k":      g24_buy,
        "gold_egp_gram_24k_sell": karat_sell("g24k"),

        "gold_egp_gram_21k":      karat_buy("g21k"),
        "gold_egp_gram_21k_sell": karat_sell("g21k"),

        "gold_egp_gram_18k":      karat_buy("g18k"),
        "gold_egp_gram_18k_sell": karat_sell("g18k"),

        "gold_egp_gram_14k":      karat_buy("g14k"),
        "gold_egp_pound":         prices.get("pound"),

        # Oz in EGP — only if we have the real gram price
        "gold_egp_oz": round(g24_buy * GRAMS_PER_OZ) if g24_buy else None,

        "status":        "live",
        "fallback_used": False,
        "source":        f"edahabapp.com via {used_label}",
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }

    # ── Write to file ─────────────────────────────────────────
    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"✅ prices.json updated  |  source: edahabapp.com via {used_label}")
    print("=" * 60)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
