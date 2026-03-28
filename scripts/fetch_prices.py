#!/usr/bin/env python3
"""
scripts/fetch_prices.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gold:    edahabapp.com → dahabmasr.com → math fallback
USD/EGP: edahabapp.com → open.er-api.com → hardcoded
Gold/oz: edahabapp.com → yf.download    → hardcoded
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
}


# ──────────────────────────────────────────
# Retry wrapper
# ──────────────────────────────────────────
def with_retry(fn, attempts=3, delay=3):
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            print(f"  ↳ Attempt {i+1}/{attempts} failed: {e}")
            if i < attempts - 1:
                time.sleep(delay)
    raise last_err


# ──────────────────────────────────────────
# USD/EGP — open.er-api.com (free, no key, supports EGP)
# ──────────────────────────────────────────
def get_usd_egp_openapi() -> float:
    url = "https://open.er-api.com/v6/latest/USD"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("result") != "success":
        raise ValueError(f"open.er-api error: {data}")
    rate = data["rates"].get("EGP")
    if not rate:
        raise ValueError("EGP not found in open.er-api response")
    return float(rate)


# ──────────────────────────────────────────
# Gold USD/oz — Yahoo Finance
# ──────────────────────────────────────────
def get_gold_usd_yahoo() -> float:
    df = yf.download("XAUUSD=X", period="1d", interval="5m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError("Empty dataframe from Yahoo for XAUUSD=X")
    return float(df["Close"].iloc[-1])


# ──────────────────────────────────────────
# ① edahabapp.com — Primary scraper
# ──────────────────────────────────────────
def scrape_edahab() -> dict:
    url = "https://edahabapp.com/"
    response = requests.get(url, headers=HEADERS, timeout=15)
    print(f"  ↳ HTTP {response.status_code} from {url}")
    if response.status_code in (403, 429, 503):
        raise ValueError(f"Blocked: HTTP {response.status_code}")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    full_text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    # Debug: print relevant lines so we can see what the scraper sees
    relevant = [l for l in lines if any(
        k in l for k in ["عيار", "بيع", "شراء", "جنيه", "دولار", "أوقية", "الذهب"]
    )]
    print(f"  ↳ Found {len(relevant)} relevant lines on edahabapp:")
    for l in relevant[:30]:
        print(f"     | {repr(l)}")

    prices = {}

    def extract_number(text: str):
        nums = re.findall(r"[\d,]+", text)
        for n in nums:
            val = float(n.replace(",", ""))
            if val > 100:
                return val
        return None

    karat_map = {"24": "g24k", "21": "g21k", "18": "g18k", "14": "g14k"}

    i = 0
    current_karat = None

    while i < len(lines):
        line = lines[i]

        # Detect karat — handles "عيار 24:" and "الذهب عيار 24:"
        for karat, key in karat_map.items():
            if f"عيار {karat}" in line:
                current_karat = key
                break

        # بيع line → sell price
        if current_karat and "بيع" in line and "شراء" not in line:
            val = extract_number(line)
            if val:
                prices.setdefault(current_karat, {})["sell"] = val
                print(f"  ↳ Parsed {current_karat} sell = {val}")

        # شراء line → buy price
        if current_karat and "شراء" in line:
            val = extract_number(line)
            if val:
                prices.setdefault(current_karat, {})["buy"] = val
                print(f"  ↳ Parsed {current_karat} buy  = {val}")
                current_karat = None

        # جنيه الذهب
        if "الجنيه الذهب" in line or (
            "جنيه" in line and "ذهب" in line and "عيار" not in line
        ):
            val = extract_number(line)
            if not val and i + 1 < len(lines):
                val = extract_number(lines[i + 1])
            if val and val > 10000:
                prices["pound"] = val
                print(f"  ↳ Parsed pound = {val}")

        # أوقية عالمية
        if "الأوقية" in line or "عالمياً" in line:
            val = extract_number(line)
            if not val and i + 1 < len(lines):
                val = extract_number(lines[i + 1])
            if val and 1000 < val < 20000:
                prices["oz_usd"] = val
                print(f"  ↳ Parsed oz_usd = {val}")

        # سعر الدولار
        if "الدولار الأمريكي" in line:
            val = extract_number(line)
            if not val and i + 1 < len(lines):
                val = extract_number(lines[i + 1])
            if val and 40 < val < 200:
                prices["usd_egp"] = val
                print(f"  ↳ Parsed usd_egp = {val}")

        i += 1

    return prices


# ──────────────────────────────────────────
# ② dahabmasr.com — Secondary scraper
# ──────────────────────────────────────────
def scrape_dahabmasr() -> dict:
    url = "https://dahabmasr.com/gold-price-today-ar"
    response = requests.get(url, headers=HEADERS, timeout=15)
    print(f"  ↳ HTTP {response.status_code} from {url}")
    if response.status_code in (403, 429, 503):
        raise ValueError(f"Blocked: HTTP {response.status_code}")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    rows = soup.find_all("tr")
    prices = {}
    karat_map = {"24": "g24k", "21": "g21k", "18": "g18k", "14": "g14k"}

    for row in rows:
        text = row.get_text(" ", strip=True)
        if not text:
            continue
        for karat, key in karat_map.items():
            if f"{karat}K" in text or f"عيار {karat}" in text:
                nums = re.findall(r"[\d,]+\.?\d*", text)
                nums = [float(n.replace(",", "")) for n in nums if float(n.replace(",", "")) > 1000]
                if nums:
                    prices[key] = {"buy": max(nums), "sell": min(nums)}
        if "جنيه" in text and "ذهب" in text:
            nums = re.findall(r"[\d,]+\.?\d*", text)
            nums = [float(n.replace(",", "")) for n in nums if float(n.replace(",", "")) > 10000]
            if nums:
                prices["pound"] = max(nums)

    return prices


# ──────────────────────────────────────────
# ③ Math fallback
# ──────────────────────────────────────────
def calculate_fallback(gold_usd: float, usd_egp: float) -> dict:
    g24 = (gold_usd * usd_egp) / GRAMS_PER_OZ
    return {
        "g24k": {"buy": round(g24), "sell": round(g24 * 0.992)},
        "g21k": {"buy": round(g24 * 21 / 24), "sell": round(g24 * 21 / 24 * 0.992)},
        "g18k": {"buy": round(g24 * 18 / 24), "sell": round(g24 * 18 / 24 * 0.992)},
        "g14k": {"buy": round(g24 * 14 / 24), "sell": round(g24 * 14 / 24 * 0.992)},
        "pound": round(g24 * 21 / 24 * 8),
    }


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────
def main():
    print("⚡ Starting price update...")

    fallback_used = False
    source_parts = []

    # ── Step 1: Get USD/EGP ──────────────────
    usd_egp = None

    # Try edahabapp first (scraped later, but try open.er-api now for USD/EGP)
    try:
        usd_egp = with_retry(get_usd_egp_openapi)
        source_parts.append("open.er-api.com (FX)")
        print(f"✅ open.er-api OK | USD/EGP: {usd_egp:.2f}")
    except Exception as e:
        print(f"⚠️ open.er-api failed: {e}")
        try:
            usd_egp_yahoo = with_retry(lambda: yf.download(
                "USDEGP=X", period="1d", interval="5m",
                progress=False, auto_adjust=True
            ))
            if usd_egp_yahoo is not None and not usd_egp_yahoo.empty:
                usd_egp = float(usd_egp_yahoo["Close"].iloc[-1])
                source_parts.append("Yahoo Finance (FX)")
                print(f"✅ Yahoo FX OK | USD/EGP: {usd_egp:.2f}")
            else:
                raise ValueError("Empty Yahoo FX dataframe")
        except Exception as e2:
            print(f"⚠️ Yahoo FX failed: {e2} — using hardcoded 52.75")
            usd_egp = 52.75
            fallback_used = True

    # ── Step 2: Get Gold USD/oz ──────────────
    gold_usd = None
    try:
        gold_usd = with_retry(get_gold_usd_yahoo)
        source_parts.append("Yahoo Finance (Gold)")
        print(f"✅ Yahoo Gold OK | {gold_usd:,.2f} USD/oz")
    except Exception as e:
        print(f"⚠️ Yahoo Gold failed: {e} — using hardcoded 4493")
        gold_usd = 4493  # current approximate value from edahabapp screenshot
        fallback_used = True

    # ── Step 3: Get local EGP gold prices ───
    local_prices = {}
    try:
        local_prices = with_retry(scrape_edahab)
        has_prices = (
            local_prices.get("g24k", {}).get("buy")
            and local_prices.get("g21k", {}).get("buy")
        )
        if has_prices:
            source_parts.append("edahabapp.com")
            print(f"✅ eDahab OK | 24K buy: {local_prices['g24k']['buy']:,} | 21K buy: {local_prices['g21k']['buy']:,}")
            # Override USD/EGP with local value if available (more accurate)
            if local_prices.get("usd_egp"):
                usd_egp = local_prices["usd_egp"]
                print(f"   ↳ USD/EGP overridden from edahabapp: {usd_egp}")
            # Override gold_usd with oz price from page if available
            if local_prices.get("oz_usd"):
                gold_usd = local_prices["oz_usd"]
                print(f"   ↳ Gold USD/oz overridden from edahabapp: {gold_usd}")
        else:
            raise ValueError(f"Incomplete prices from edahabapp: {list(local_prices.keys())}")
    except Exception as e:
        print(f"⚠️ eDahab failed: {e} — trying dahabmasr.com...")
        try:
            local_prices = with_retry(scrape_dahabmasr)
            if local_prices.get("g24k"):
                source_parts.append("dahabmasr.com")
                print(f"✅ DahabMasr OK | 24K buy: {local_prices['g24k']['buy']:,}")
            else:
                raise ValueError(f"Incomplete prices from dahabmasr: {list(local_prices.keys())}")
        except Exception as e2:
            print(f"⚠️ DahabMasr failed: {e2} — using math fallback")
            local_prices = calculate_fallback(gold_usd, usd_egp)
            source_parts.append("Fallback Calculation")
            fallback_used = True

    fallback_prices = calculate_fallback(gold_usd, usd_egp)

    def get_price(key: str, subkey: str = "buy"):
        val = local_prices.get(key)
        if val:
            return val.get(subkey) if isinstance(val, dict) else val
        val = fallback_prices.get(key)
        if val:
            return val.get(subkey) if isinstance(val, dict) else val
        return None

    status = "fallback" if fallback_used else "live"
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

    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\n✅ data/prices.json updated successfully")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
