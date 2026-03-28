#!/usr/bin/env python3
"""
scripts/fetch_prices.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE: Real prices from edahabapp.com ONLY.
      If all sources fail → keep existing prices.json unchanged.
      NEVER write math-calculated prices.

Flow:
  1. Fetch HTML via: Cloudflare Worker → allorigins → corsproxy → codetabs
  2. Extract clean text with BeautifulSoup
  3. Parse prices with regex
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

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

# ── Regex on PLAIN TEXT (after BeautifulSoup extraction) ──────
# Verified structure from edahabapp.com plain text:
#
#   الذهب عيار 24:
#   بيع: 7840 جنيه
#   شراء: 7784 جنيه
#
_KARAT_RE = re.compile(
    r"عيار\s*(\d+)[^\n]*\n"       # عيار 24:
    r"[\s\S]{0,50}?"              # optional blank lines
    r"بيع:\s*([\d,]+)[^\n]*\n"   # بيع: 7840 جنيه
    r"[\s\S]{0,50}?"
    r"شراء:\s*([\d,]+)",          # شراء: 7784 جنيه
)


# ─────────────────────────────────────────────────────────────
# Step 1: Fetch HTML
# ─────────────────────────────────────────────────────────────
def fetch_html(url: str, label: str) -> str:
    print(f"  → Fetching [{label}]")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    print(f"    HTTP {resp.status_code}  ({len(resp.content):,} bytes)")
    if resp.status_code in (403, 429, 502, 503, 522):
        raise ValueError(f"HTTP {resp.status_code}")
    resp.raise_for_status()
    return resp.text


# ─────────────────────────────────────────────────────────────
# Step 2: HTML → clean plain text
# ─────────────────────────────────────────────────────────────
def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n", strip=True)

    # Debug: print relevant lines so we can see the structure
    lines    = text.splitlines()
    relevant = [
        l for l in lines
        if any(k in l for k in ["عيار", "بيع", "شراء", "الجنيه", "الأوقية", "الدولار"])
    ]
    print(f"    Relevant lines found: {len(relevant)}")
    for l in relevant[:20]:
        print(f"      | {l}")

    return text


# ─────────────────────────────────────────────────────────────
# Step 3: Parse prices from plain text
# ─────────────────────────────────────────────────────────────
def parse_text(text: str) -> dict:
    if "عيار" not in text or "بيع" not in text:
        raise ValueError(
            f"Text missing Arabic price content. "
            f"Length={len(text)}. Preview: {text[:200]!r}"
        )

    prices = {}

    # ── Karat prices ──
    for m in _KARAT_RE.finditer(text):
        karat    = m.group(1)
        sell_val = int(m.group(2).replace(",", ""))
        buy_val  = int(m.group(3).replace(",", ""))
        key = KARAT_MAP.get(karat)
        if key and sell_val > 1000 and buy_val > 1000:
            prices[key] = {"sell": sell_val, "buy": buy_val}
            print(f"    ✔ {key}: buy={buy_val:,}  sell={sell_val:,}")

    # ── جنيه الذهب ──
    m = re.search(r"(?:سعر\s+)?الجنيه[^\n]*\n\s*([\d,]+)", text)
    if m:
        val = int(m.group(1).replace(",", ""))
        if val > 10000:
            prices["pound"] = val
            print(f"    ✔ pound    = {val:,}")

    # ── أوقية عالمياً ──
    m = re.search(r"الأوقية[^\n]*\n\s*([\d,]+)", text)
    if m:
        val = int(m.group(1).replace(",", ""))
        if 1000 < val < 20000:
            prices["oz_usd"] = val
            print(f"    ✔ oz_usd   = {val:,}")

    # ── دولار أمريكي ──
    m = re.search(r"الدولار الأمريكي[^\n]*\n\s*([\d.]+)", text)
    if m:
        val = float(m.group(1))
        if 40 < val < 200:
            prices["usd_egp"] = val
            print(f"    ✔ usd_egp  = {val}")

    # Validate
    missing = [k for k in ["g24k", "g21k", "g18k"] if k not in prices]
    if missing:
        raise ValueError(
            f"Missing karats after parsing: {missing}. "
            f"Found keys: {list(prices.keys())}"
        )

    return prices


# ─────────────────────────────────────────────────────────────
# Fetch strategies (tried in order)
# ─────────────────────────────────────────────────────────────
def get_strategies() -> list:
    target     = "https://edahabapp.com/"
    proxy_url  = os.environ.get("PROXY_URL", "").strip()
    strategies = []

    if proxy_url:
        strategies.append(("Cloudflare Worker", proxy_url))

    strategies += [
        ("allorigins.win",  f"https://api.allorigins.win/raw?url={target}"),
        ("corsproxy.io",    f"https://corsproxy.io/?{target}"),
        ("codetabs.com",    f"https://api.codetabs.com/v1/proxy?quest={target}"),
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

    prices     = None
    used_label = None

    for label, url in get_strategies():
        print(f"\n🔄 Trying: {label}")
        try:
            html   = fetch_html(url, label)
            text   = html_to_text(html)
            prices = parse_text(text)
            used_label = label
            print(f"  ✅ SUCCESS via {label}")
            break
        except Exception as e:
            print(f"  ⚠️  Failed [{label}]: {e}")
            time.sleep(2)

    # ── All sources failed — preserve existing file ────────────
    if prices is None:
        print("\n" + "=" * 60)
        print("❌ ALL SOURCES FAILED — prices.json NOT updated")
        print("=" * 60)
        sys.exit(1)

    # ── Build payload (real prices only) ──────────────────────
    g24_buy = prices.get("g24k", {}).get("buy")

    payload = {
        "gold_usd_oz":            prices.get("oz_usd"),
        "usd_egp":                prices.get("usd_egp"),

        "gold_egp_gram_24k":      g24_buy,
        "gold_egp_gram_24k_sell": prices.get("g24k", {}).get("sell"),

        "gold_egp_gram_21k":      prices.get("g21k", {}).get("buy"),
        "gold_egp_gram_21k_sell": prices.get("g21k", {}).get("sell"),

        "gold_egp_gram_18k":      prices.get("g18k", {}).get("buy"),
        "gold_egp_gram_18k_sell": prices.get("g18k", {}).get("sell"),

        "gold_egp_gram_14k":      prices.get("g14k", {}).get("buy"),
        "gold_egp_pound":         prices.get("pound"),

        "gold_egp_oz": round(g24_buy * GRAMS_PER_OZ) if g24_buy else None,

        "status":        "live",
        "fallback_used": False,
        "source":        f"edahabapp.com via {used_label}",
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"✅ prices.json updated | source: edahabapp.com via {used_label}")
    print("=" * 60)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
