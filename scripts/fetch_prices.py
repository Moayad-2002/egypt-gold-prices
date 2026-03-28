#!/usr/bin/env python3
"""
scripts/fetch_prices.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tier 1  — edahabapp.com   (local EGP prices, USD/EGP, oz price)
Tier 2  — dahabmasr.com   (local EGP prices fallback)
Tier 3  — open.er-api.com (USD/EGP fallback — free, no key, supports EGP)
Tier 4  — Yahoo Finance   (gold USD/oz fallback)
Tier 5  — math calculation (last resort)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

KARAT_MAP = {"24": "g24k", "21": "g21k", "18": "g18k", "14": "g14k"}


# ──────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────

def with_retry(fn, attempts: int = 3, delay: int = 4):
    """Run fn up to `attempts` times, sleeping `delay` seconds between tries."""
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


# ──────────────────────────────────────────────────────────────
# Tier 1 — edahabapp.com
#
# Verified HTML structure (static, no JS rendering):
#
#   الذهب عيار 24:
#   [blank line]
#   بيع: 7840 جنيه
#   شراء: 7784 جنيه
#   ...
#   سعر الجنيه الذهب:
#   54880 جنيه
#   سعر الأوقية عالمياً:
#   4493 دولار
#   الدولار الأمريكي:
#   52.75 جنيه
# ──────────────────────────────────────────────────────────────

# Flexible regex — handles blank lines between karat header and prices
_KARAT_RE = re.compile(
    r"عيار\s*(\d+)[^\n]*\n"      # عيار 24:
    r"[\s\S]{0,30}?"              # skip optional blank lines (max 30 chars)
    r"بيع:\s*([\d,]+)[^\n]*\n"   # بيع: 7840 جنيه
    r"[\s\S]{0,30}?"
    r"شراء:\s*([\d,]+)",          # شراء: 7784 جنيه
)


def scrape_edahab() -> dict:
    url = "https://edahabapp.com/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    print(f"  ↳ HTTP {resp.status_code} — edahabapp.com ({len(resp.text):,} bytes)")

    if resp.status_code in (403, 429, 503):
        raise ValueError(f"Blocked by server: HTTP {resp.status_code}")
    resp.raise_for_status()

    html = resp.text

    if "عيار" not in html:
        raise ValueError(
            f"Unexpected page content — 'عيار' not found. "
            f"First 300 chars: {html[:300]}"
        )

    prices = {}

    # ── عيار prices ──
    for m in _KARAT_RE.finditer(html):
        karat, sell_s, buy_s = m.group(1), m.group(2), m.group(3)
        key = KARAT_MAP.get(karat)
        if key:
            prices[key] = {"sell": safe_int(sell_s), "buy": safe_int(buy_s)}
            print(f"  ↳ {key}: buy={prices[key]['buy']:,}  sell={prices[key]['sell']:,}")

    # ── جنيه الذهب ──
    m = re.search(r"الجنيه الذهب[^\n]*\n\s*([\d,]+)", html)
    if m:
        prices["pound"] = safe_int(m.group(1))
        print(f"  ↳ pound = {prices['pound']:,}")

    # ── أوقية عالمياً ──
    m = re.search(r"الأوقية عالمياً[^\n]*\n\s*([\d,]+)", html)
    if m:
        prices["oz_usd"] = safe_int(m.group(1))
        print(f"  ↳ oz_usd = {prices['oz_usd']:,}")

    # ── دولار أمريكي ──
    m = re.search(r"الدولار الأمريكي[^\n]*\n\s*([\d.]+)", html)
    if m:
        prices["usd_egp"] = safe_float(m.group(1))
        print(f"  ↳ usd_egp = {prices['usd_egp']}")

    return prices


# ──────────────────────────────────────────────────────────────
# Tier 2 — dahabmasr.com
# ──────────────────────────────────────────────────────────────

def scrape_dahabmasr() -> dict:
    url = "https://dahabmasr.com/gold-price-today-ar"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    print(f"  ↳ HTTP {resp.status_code} — dahabmasr.com ({len(resp.text):,} bytes)")

    if resp.status_code in (403, 429, 503):
        raise ValueError(f"Blocked by server: HTTP {resp.status_code}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
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
                    print(f"  ↳ {key}: buy={max(nums):,.0f}  sell={min(nums):,.0f}")

        if "جنيه" in text and "ذهب" in text:
            nums = [
                float(n.replace(",", ""))
                for n in re.findall(r"[\d,]+\.?\d*", text)
                if float(n.replace(",", "")) > 10000
            ]
            if nums:
                prices["pound"] = max(nums)

    return prices


# ──────────────────────────────────────────────────────────────
# Tier 3 — open.er-api.com  (USD/EGP — free, no API key needed)
# ──────────────────────────────────────────────────────────────

def get_usd_egp_openapi() -> float:
    url = "https://open.er-api.com/v6/latest/USD"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise ValueError(f"open.er-api error: {data.get('error-type', 'unknown')}")
    rate = data["rates"].get("EGP")
    if not rate:
        raise ValueError("EGP not found in open.er-api response")
    print(f"  ↳ open.er-api USD/EGP = {rate}")
    return float(rate)


# ──────────────────────────────────────────────────────────────
# Tier 4 — Yahoo Finance  (gold USD/oz)
# ──────────────────────────────────────────────────────────────

def get_gold_usd_yahoo() -> float:
    df = yf.download("XAUUSD=X", period="1d", interval="5m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError("Empty dataframe from Yahoo for XAUUSD=X")
    val = float(df["Close"].iloc[-1])
    print(f"  ↳ Yahoo gold = {val:,.2f} USD/oz")
    return val


def get_usd_egp_yahoo() -> float:
    df = yf.download("USDEGP=X", period="1d", interval="5m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError("Empty dataframe from Yahoo for USDEGP=X")
    val = float(df["Close"].iloc[-1])
    print(f"  ↳ Yahoo USD/EGP = {val:.2f}")
    return val


# ──────────────────────────────────────────────────────────────
# Tier 5 — Math fallback
# ──────────────────────────────────────────────────────────────

def calculate_fallback(gold_usd: float, usd_egp: float) -> dict:
    g24 = (gold_usd * usd_egp) / GRAMS_PER_OZ
    return {
        "g24k": {"buy": round(g24),           "sell": round(g24 * 0.992)},
        "g21k": {"buy": round(g24 * 21 / 24), "sell": round(g24 * 21 / 24 * 0.992)},
        "g18k": {"buy": round(g24 * 18 / 24), "sell": round(g24 * 18 / 24 * 0.992)},
        "g14k": {"buy": round(g24 * 14 / 24), "sell": round(g24 * 14 / 24 * 0.992)},
        "pound": round(g24 * 21 / 24 * 8),
    }


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("⚡ Gold price update started")
    print("=" * 55)

    fallback_used = False
    source_parts  = []

    # ── USD/EGP ─────────────────────────────────────────────
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
            usd_egp = 52.75          # last known value
            fallback_used = True
            print(f"  ⚠️  Using hardcoded USD/EGP = {usd_egp}")

    # ── Gold USD/oz ──────────────────────────────────────────
    print("\n📌 Step 2: Gold USD/oz")
    gold_usd = None

    try:
        gold_usd = with_retry(get_gold_usd_yahoo)
        source_parts.append("Yahoo Gold")
        print(f"  ✅ Gold = {gold_usd:,.2f} USD/oz  (Yahoo Finance)")
    except Exception as e:
        print(f"  ⚠️  Yahoo gold failed: {e}")
        gold_usd = 4493              # last known value from edahabapp
        fallback_used = True
        print(f"  ⚠️  Using hardcoded gold = {gold_usd} USD/oz")

    # ── Local EGP prices ─────────────────────────────────────
    print("\n📌 Step 3: Local EGP gold prices")
    local_prices = {}

    # — Try edahabapp —
    try:
        local_prices = with_retry(scrape_edahab)
        has_24 = isinstance(local_prices.get("g24k"), dict) and local_prices["g24k"].get("buy")
        has_21 = isinstance(local_prices.get("g21k"), dict) and local_prices["g21k"].get("buy")

        if not (has_24 and has_21):
            raise ValueError(
                f"Incomplete data from edahabapp. Keys found: {list(local_prices.keys())}"
            )

        source_parts.append("edahabapp.com")
        print(f"  ✅ edahabapp OK")

        # Override with live local values when available
        if local_prices.get("usd_egp"):
            usd_egp = local_prices["usd_egp"]
            print(f"  ↳ USD/EGP overridden from page: {usd_egp}")
        if local_prices.get("oz_usd"):
            gold_usd = local_prices["oz_usd"]
            print(f"  ↳ Gold USD/oz overridden from page: {gold_usd}")

    except Exception as e:
        print(f"  ⚠️  edahabapp failed: {e}")

        # — Try dahabmasr —
        try:
            local_prices = with_retry(scrape_dahabmasr)
            has_24 = isinstance(local_prices.get("g24k"), dict) and local_prices["g24k"].get("buy")

            if not has_24:
                raise ValueError(
                    f"Incomplete data from dahabmasr. Keys found: {list(local_prices.keys())}"
                )

            source_parts.append("dahabmasr.com")
            print(f"  ✅ dahabmasr OK")

        except Exception as e2:
            print(f"  ⚠️  dahabmasr failed: {e2}")
            print("  ⚠️  Using math fallback for all EGP prices")
            local_prices = calculate_fallback(gold_usd, usd_egp)
            source_parts.append("Fallback Calculation")
            fallback_used = True

    # ── Build payload ─────────────────────────────────────────
    fallback_prices = calculate_fallback(gold_usd, usd_egp)

    def get_price(key: str, subkey: str = "buy"):
        val = local_prices.get(key)
        if isinstance(val, dict):
            return val.get(subkey)
        if isinstance(val, (int, float)) and subkey == "buy":
            return val
        val = fallback_prices.get(key)
        if isinstance(val, dict):
            return val.get(subkey)
        return None

    status       = "fallback" if fallback_used else "live"
    source_label = " + ".join(source_parts) if source_parts else "Fallback Calculation"

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

    # ── Write output ──────────────────────────────────────────
    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 55)
    print(f"✅ Done  |  status={status}  |  source={source_label}")
    print("=" * 55)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
