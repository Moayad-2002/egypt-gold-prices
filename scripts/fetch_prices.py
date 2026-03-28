#!/usr/bin/env python3
"""
scripts/fetch_prices.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Local EGP prices:
  1. Cloudflare Worker proxy → edahabapp.com   (set PROXY_URL secret)
  2. Public proxy fallbacks  → edahabapp.com
  3. dahabmasr.com           (direct — may also be blocked)
  4. Math calculation from USD rates

USD/EGP rate:
  1. edahabapp.com (via proxy, parsed from page)
  2. open.er-api.com (free, no key, supports EGP) ✅ confirmed working

Gold USD/oz:
  1. edahabapp.com (via proxy, parsed from page)
  2. Yahoo Finance yf.download
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import requests
import yfinance as yf
from bs4 import BeautifulSoup

GRAMS_PER_OZ = 31.1035
KARAT_MAP    = {"24": "g24k", "21": "g21k", "18": "g18k", "14": "g14k"}

# Regex tested against real edahabapp.com HTML structure:
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Public proxy services that typically work on GitHub Actions
# Used as fallback when PROXY_URL secret is not set
PUBLIC_PROXIES = [
    "https://api.allorigins.win/raw?url=https://edahabapp.com/",
    "https://corsproxy.io/?https://edahabapp.com/",
    "https://api.codetabs.com/v1/proxy?quest=https://edahabapp.com/",
]


# ─────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────

def with_retry(fn, attempts: int = 3, delay: int = 4):
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            print(f"    ↳ attempt {i+1}/{attempts} failed: {e}")
            if i < attempts - 1:
                time.sleep(delay)
    raise last_err


def safe_int(s: str) -> int:
    return int(s.replace(",", "").strip())


def safe_float(s: str) -> float:
    return float(s.replace(",", "").strip())


# ─────────────────────────────────────────────────────────────
# HTML parser — shared by all edahabapp fetch methods
# ─────────────────────────────────────────────────────────────

def parse_edahab_html(html: str) -> dict:
    """Parse prices from edahabapp.com HTML. Raises if content looks wrong."""
    if "عيار" not in html:
        raise ValueError(
            f"Unexpected content — 'عيار' not found. "
            f"Length={len(html)}. Preview: {html[:200]}"
        )

    prices = {}

    for m in _KARAT_RE.finditer(html):
        karat, sell_s, buy_s = m.group(1), m.group(2), m.group(3)
        key = KARAT_MAP.get(karat)
        if key:
            prices[key] = {"sell": safe_int(sell_s), "buy": safe_int(buy_s)}
            print(f"    ✔ {key}: buy={prices[key]['buy']:,}  sell={prices[key]['sell']:,}")

    m = re.search(r"الجنيه الذهب[^\n]*\n\s*([\d,]+)", html)
    if m:
        prices["pound"] = safe_int(m.group(1))
        print(f"    ✔ pound  = {prices['pound']:,}")

    m = re.search(r"الأوقية عالمياً[^\n]*\n\s*([\d,]+)", html)
    if m:
        prices["oz_usd"] = safe_int(m.group(1))
        print(f"    ✔ oz_usd = {prices['oz_usd']:,}")

    m = re.search(r"الدولار الأمريكي[^\n]*\n\s*([\d.]+)", html)
    if m:
        prices["usd_egp"] = safe_float(m.group(1))
        print(f"    ✔ usd_egp = {prices['usd_egp']}")

    return prices


# ─────────────────────────────────────────────────────────────
# Fetch method A — Cloudflare Worker proxy (most reliable)
# Set PROXY_URL as a GitHub Actions secret pointing to your worker
# ─────────────────────────────────────────────────────────────

def fetch_via_cloudflare_worker() -> dict:
    proxy_url = os.environ.get("PROXY_URL", "").strip()
    if not proxy_url:
        raise ValueError("PROXY_URL secret not set — skipping Cloudflare Worker")

    print(f"  ↳ Fetching via Cloudflare Worker: {proxy_url}")
    resp = requests.get(proxy_url, headers=HEADERS, timeout=15)
    print(f"  ↳ HTTP {resp.status_code} ({len(resp.text):,} bytes)")

    if resp.status_code in (403, 429, 502, 503):
        raise ValueError(f"Worker returned HTTP {resp.status_code}")
    resp.raise_for_status()

    return parse_edahab_html(resp.text)


# ─────────────────────────────────────────────────────────────
# Fetch method B — Public CORS proxies (no setup needed)
# ─────────────────────────────────────────────────────────────

def fetch_via_public_proxy() -> dict:
    last_err = None
    for proxy_url in PUBLIC_PROXIES:
        try:
            print(f"  ↳ Trying proxy: {proxy_url[:55]}...")
            resp = requests.get(proxy_url, timeout=15)
            print(f"  ↳ HTTP {resp.status_code} ({len(resp.text):,} bytes)")
            if resp.status_code not in (200, 201):
                raise ValueError(f"HTTP {resp.status_code}")
            prices = parse_edahab_html(resp.text)
            print(f"  ✅ Proxy worked: {proxy_url[:55]}")
            return prices
        except Exception as e:
            print(f"  ⚠️  Proxy failed: {e}")
            last_err = e
            time.sleep(2)
    raise ValueError(f"All public proxies failed. Last error: {last_err}")


# ─────────────────────────────────────────────────────────────
# Fetch method C — dahabmasr.com (direct)
# ─────────────────────────────────────────────────────────────

def scrape_dahabmasr() -> dict:
    url = "https://dahabmasr.com/gold-price-today-ar"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    print(f"  ↳ HTTP {resp.status_code} — dahabmasr.com ({len(resp.text):,} bytes)")

    if resp.status_code in (403, 429, 503):
        raise ValueError(f"Blocked: HTTP {resp.status_code}")
    resp.raise_for_status()

    soup   = BeautifulSoup(resp.text, "lxml")
    prices = {}

    for row in soup.find_all("tr"):
        text = row.get_text(" ", strip=True)
        if not text:
            continue
        for karat, key in KARAT_MAP.items():
            if f"{karat}K" in text or f"عيار {karat}" in text:
                nums = [
                    float(n.replace(",", ""))
                    for n in re.findall(r"[\d,]+\.?\d*", text)
                    if float(n.replace(",", "")) > 1000
                ]
                if nums:
                    prices[key] = {"buy": max(nums), "sell": min(nums)}
                    print(f"    ✔ {key}: buy={max(nums):,.0f}  sell={min(nums):,.0f}")
        if "جنيه" in text and "ذهب" in text:
            nums = [
                float(n.replace(",", ""))
                for n in re.findall(r"[\d,]+\.?\d*", text)
                if float(n.replace(",", "")) > 10000
            ]
            if nums:
                prices["pound"] = max(nums)

    return prices


# ─────────────────────────────────────────────────────────────
# USD/EGP — open.er-api.com (confirmed working on GitHub Actions)
# ─────────────────────────────────────────────────────────────

def get_usd_egp_openapi() -> float:
    resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise ValueError(f"open.er-api error: {data.get('error-type')}")
    rate = data["rates"].get("EGP")
    if not rate:
        raise ValueError("EGP not in open.er-api response")
    return float(rate)


# ─────────────────────────────────────────────────────────────
# Gold USD/oz — Yahoo Finance
# ─────────────────────────────────────────────────────────────

def get_gold_usd_yahoo() -> float:
    df = yf.download("XAUUSD=X", period="1d", interval="5m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError("Empty dataframe from Yahoo for XAUUSD=X")
    return float(df["Close"].iloc[-1])


def get_usd_egp_yahoo() -> float:
    df = yf.download("USDEGP=X", period="1d", interval="5m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError("Empty dataframe from Yahoo for USDEGP=X")
    return float(df["Close"].iloc[-1])


# ─────────────────────────────────────────────────────────────
# Math fallback
# ─────────────────────────────────────────────────────────────

def calculate_fallback(gold_usd: float, usd_egp: float) -> dict:
    g24 = (gold_usd * usd_egp) / GRAMS_PER_OZ
    return {
        "g24k": {"buy": round(g24),           "sell": round(g24 * 0.992)},
        "g21k": {"buy": round(g24 * 21 / 24), "sell": round(g24 * 21 / 24 * 0.992)},
        "g18k": {"buy": round(g24 * 18 / 24), "sell": round(g24 * 18 / 24 * 0.992)},
        "g14k": {"buy": round(g24 * 14 / 24), "sell": round(g24 * 14 / 24 * 0.992)},
        "pound": round(g24 * 21 / 24 * 8),
    }


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("⚡  Gold price update started")
    print(f"    PROXY_URL set: {'YES' if os.environ.get('PROXY_URL') else 'NO — add as GitHub secret'}")
    print("=" * 60)

    fallback_used = False
    source_parts  = []

    # ── Step 1: USD/EGP ────────────────────────────────────
    print("\n📌 Step 1: USD/EGP rate")
    usd_egp = None

    try:
        usd_egp = with_retry(get_usd_egp_openapi)
        source_parts.append("open.er-api.com")
        print(f"  ✅ USD/EGP = {usd_egp:.2f}  (open.er-api.com)")
    except Exception as e:
        print(f"  ⚠️  open.er-api failed: {e}")
        try:
            usd_egp = with_retry(get_usd_egp_yahoo)
            source_parts.append("Yahoo FX")
            print(f"  ✅ USD/EGP = {usd_egp:.2f}  (Yahoo Finance)")
        except Exception as e2:
            print(f"  ⚠️  Yahoo FX failed: {e2}")
            usd_egp = 52.75
            fallback_used = True
            print(f"  ⚠️  Hardcoded USD/EGP = {usd_egp}")

    # ── Step 2: Gold USD/oz ─────────────────────────────────
    print("\n📌 Step 2: Gold USD/oz")
    gold_usd = None

    try:
        gold_usd = with_retry(get_gold_usd_yahoo)
        source_parts.append("Yahoo Gold")
        print(f"  ✅ Gold = {gold_usd:,.2f} USD/oz  (Yahoo Finance)")
    except Exception as e:
        print(f"  ⚠️  Yahoo Gold failed: {e}")
        gold_usd = 4493          # last known value — updated 2026-03-28
        fallback_used = True
        print(f"  ⚠️  Hardcoded Gold = {gold_usd} USD/oz")

    # ── Step 3: Local EGP prices ────────────────────────────
    print("\n📌 Step 3: Local EGP gold prices")
    local_prices = {}
    prices_ok = False

    # Method A — Cloudflare Worker (most reliable)
    if not prices_ok:
        try:
            local_prices = with_retry(fetch_via_cloudflare_worker, attempts=2)
            if local_prices.get("g24k", {}).get("buy"):
                source_parts.append("edahabapp.com (CF Worker)")
                prices_ok = True
                print("  ✅ Cloudflare Worker → edahabapp OK")
        except Exception as e:
            print(f"  ⚠️  Cloudflare Worker failed: {e}")

    # Method B — Public proxy services
    if not prices_ok:
        try:
            local_prices = with_retry(fetch_via_public_proxy, attempts=1)
            if local_prices.get("g24k", {}).get("buy"):
                source_parts.append("edahabapp.com (proxy)")
                prices_ok = True
                print("  ✅ Public proxy → edahabapp OK")
        except Exception as e:
            print(f"  ⚠️  Public proxies failed: {e}")

    # Method C — dahabmasr.com direct
    if not prices_ok:
        try:
            local_prices = with_retry(scrape_dahabmasr, attempts=2)
            if local_prices.get("g24k", {}).get("buy"):
                source_parts.append("dahabmasr.com")
                prices_ok = True
                print("  ✅ dahabmasr OK")
        except Exception as e:
            print(f"  ⚠️  dahabmasr failed: {e}")

    # Method D — Math fallback
    if not prices_ok:
        print("  ⚠️  All scraping sources failed — using math calculation")
        local_prices = calculate_fallback(gold_usd, usd_egp)
        source_parts.append("Fallback Calculation")
        fallback_used = True

    # Override USD/EGP and gold_usd with live values from page if available
    if local_prices.get("usd_egp"):
        usd_egp = local_prices["usd_egp"]
        print(f"  ↳ USD/EGP overridden from page: {usd_egp}")
    if local_prices.get("oz_usd"):
        gold_usd = local_prices["oz_usd"]
        print(f"  ↳ Gold USD/oz overridden from page: {gold_usd}")

    # ── Build payload ───────────────────────────────────────
    fallback_prices = calculate_fallback(gold_usd, usd_egp)

    def get_price(key: str, subkey: str = "buy"):
        val = local_prices.get(key)
        if isinstance(val, dict):
            return val.get(subkey)
        val = fallback_prices.get(key)
        if isinstance(val, dict):
            return val.get(subkey)
        return None

    source_label = " + ".join(source_parts) if source_parts else "Fallback Calculation"
    status       = "fallback" if fallback_used else "live"

    payload = {
        "gold_usd_oz":            round(gold_usd, 2),
        "usd_egp":                round(usd_egp, 2),

        "gold_egp_gram_24k":      get_price("g24k", "buy"),
        "gold_egp_gram_24k_sell": get_price("g24k", "sell"),

        "gold_egp_gram_21k":      get_price("g21k", "buy"),
        "gold_egp_gram_21k_sell": get_price("g21k", "sell"),

        "gold_egp_gram_18k":      get_price("g18k", "buy"),
        "gold_egp_gram_18k_sell": get_price("g18k", "sell"),

        "gold_egp_gram_14k":      get_price("g14k", "buy"),
        "gold_egp_pound":         get_price("pound"),

        "gold_egp_oz": round(
            (get_price("g24k", "buy") or 7829) * GRAMS_PER_OZ
        ),

        "status":        status,
        "fallback_used": fallback_used,
        "source":        source_label,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"✅ Done  |  status={status}")
    print(f"   source: {source_label}")
    print("=" * 60)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
