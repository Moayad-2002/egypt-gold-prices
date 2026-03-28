#!/usr/bin/env python3
"""
scripts/fetch_prices.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
المصدر الأساسي:  edahabapp.com
المصدر الثانوي: dahabmasr.com
المصدر الاحتياطي: Yahoo Finance + frankfurter.app
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
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
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
# Yahoo Finance — yf.download (more reliable than fast_info on CI)
# ──────────────────────────────────────────
def get_yahoo_price(ticker: str) -> float:
    df = yf.download(ticker, period="1d", interval="1m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"Empty dataframe for {ticker}")
    return float(df["Close"].iloc[-1])


# ──────────────────────────────────────────
# frankfurter.app — USD/EGP fallback (works on GitHub Actions)
# ──────────────────────────────────────────
def get_usd_egp_frankfurter() -> float:
    url = "https://api.frankfurter.app/latest?base=USD&symbols=EGP"
    r = requests.get(url, timeout=10, headers=HEADERS)
    r.raise_for_status()
    rate = r.json().get("rates", {}).get("EGP")
    if not rate:
        raise ValueError("No EGP rate in frankfurter response")
    return float(rate)


# ──────────────────────────────────────────
# ① edahabapp.com — Primary source
# ──────────────────────────────────────────
def scrape_edahab() -> dict:
    url = "https://edahabapp.com/"
    response = requests.get(url, headers=HEADERS, timeout=15)
    print(f"  ↳ HTTP {response.status_code} from {url}")
    if response.status_code in (403, 429, 503):
        raise ValueError(f"Blocked by server: HTTP {response.status_code}")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    full_text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

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

        for karat, key in karat_map.items():
            if f"عيار {karat}" in line:
                current_karat = key
                break

        if current_karat and "بيع" in line and "شراء" not in line:
            val = extract_number(line)
            if val:
                prices.setdefault(current_karat, {})["sell"] = val

        if current_karat and "شراء" in line:
            val = extract_number(line)
            if val:
                prices.setdefault(current_karat, {})["buy"] = val
                current_karat = None

        if "الجنيه الذهب" in line or ("جنيه" in line and "ذهب" in line and "عيار" not in line):
            val = extract_number(line) or (extract_number(lines[i + 1]) if i + 1 < len(lines) else None)
            if val and val > 10000:
                prices["pound"] = val

        if "الأوقية" in line or ("عالمياً" in line and "دولار" in line):
            val = extract_number(line) or (extract_number(lines[i + 1]) if i + 1 < len(lines) else None)
            if val and 1000 < val < 20000:
                prices["oz_usd"] = val

        if "الدولار الأمريكي" in line or "الدولار" in line:
            val = extract_number(line) or (extract_number(lines[i + 1]) if i + 1 < len(lines) else None)
            if val and 40 < val < 200:
                prices["usd_egp"] = val

        i += 1

    return prices


# ──────────────────────────────────────────
# ② dahabmasr.com — Secondary source
# ──────────────────────────────────────────
def scrape_dahabmasr() -> dict:
    url = "https://dahabmasr.com/gold-price-today-ar"
    response = requests.get(url, headers=HEADERS, timeout=15)
    print(f"  ↳ HTTP {response.status_code} from {url}")
    if response.status_code in (403, 429, 503):
        raise ValueError(f"Blocked by server: HTTP {response.status_code}")
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

        if "عالمية" in text or "دولار" in text:
            nums = re.findall(r"[\d,]+\.?\d*", text)
            nums = [float(n.replace(",", "")) for n in nums if 4000 < float(n.replace(",", "")) < 10000]
            if nums:
                prices["oz_usd"] = nums[0]

    return prices


# ──────────────────────────────────────────
# ③ Fallback — math from Yahoo prices
# ──────────────────────────────────────────
def calculate_fallback(gold_usd: float, usd_egp: float) -> dict:
    g24 = (gold_usd * usd_egp) / GRAMS_PER_OZ
    return {
        "g24k": {"buy": round(g24), "sell": round(g24 * 0.99)},
        "g21k": {"buy": round(g24 * 21 / 24), "sell": round(g24 * 21 / 24 * 0.99)},
        "g18k": {"buy": round(g24 * 18 / 24), "sell": round(g24 * 18 / 24 * 0.99)},
        "g14k": {"buy": round(g24 * 14 / 24), "sell": round(g24 * 14 / 24 * 0.99)},
        "pound": round(g24 * 21 / 24 * 8),
    }


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────
def main():
    print("⚡ Starting price update...")

    fallback_used = False
    source_parts = []

    # ── Gold price (Yahoo) ──
    gold_usd = None
    try:
        gold_usd = with_retry(lambda: get_yahoo_price("XAUUSD=X"))
        source_parts.append("Yahoo Finance (Gold)")
        print(f"✅ Yahoo Gold OK | {gold_usd:,.2f} USD/oz")
    except Exception as e:
        print(f"⚠️ Yahoo Gold failed: {e}")
        gold_usd = 3300
        fallback_used = True

    # ── USD/EGP — Yahoo first, frankfurter as backup ──
    usd_egp = None
    try:
        usd_egp = with_retry(lambda: get_yahoo_price("USDEGP=X"))
        source_parts.append("Yahoo Finance (FX)")
        print(f"✅ Yahoo FX OK | USD/EGP: {usd_egp:.2f}")
    except Exception as e:
        print(f"⚠️ Yahoo FX failed: {e} — trying frankfurter.app...")
        try:
            usd_egp = with_retry(get_usd_egp_frankfurter)
            source_parts.append("frankfurter.app (FX)")
            print(f"✅ Frankfurter OK | USD/EGP: {usd_egp:.2f}")
        except Exception as e2:
            print(f"⚠️ Frankfurter failed: {e2}")
            usd_egp = 52.5
            fallback_used = True

    # ── Local gold prices — edahabapp first, dahabmasr as backup ──
    local_prices = {}
    try:
        local_prices = with_retry(scrape_edahab)
        has_prices = (
            local_prices.get("g24k", {}).get("buy")
            and local_prices.get("g21k", {}).get("buy")
        )
        if has_prices:
            source_parts.append("edahabapp.com")
            print(f"✅ eDahab OK | 24K: {local_prices['g24k']['buy']:,} | 21K: {local_prices['g21k']['buy']:,}")
            if local_prices.get("usd_egp"):
                usd_egp = local_prices["usd_egp"]
                print(f"   ↳ USD/EGP from edahabapp: {usd_egp}")
        else:
            raise ValueError("Not enough prices found on edahabapp.com")
    except Exception as e:
        print(f"⚠️ eDahab failed: {e} — trying dahabmasr.com...")
        try:
            local_prices = with_retry(scrape_dahabmasr)
            if local_prices.get("g24k"):
                source_parts.append("dahabmasr.com")
                print(f"✅ DahabMasr OK | 24K: {local_prices['g24k']['buy']:,}")
            else:
                raise ValueError("Not enough prices found on dahabmasr.com")
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
            (get_price("g24k", "buy") or 8500) * GRAMS_PER_OZ
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
