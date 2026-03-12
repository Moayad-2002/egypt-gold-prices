#!/usr/bin/env python3
"""
scripts/fetch_prices.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
المصدر الأساسي:  dahabmasr.com
المصدر الثانوي: Yahoo Finance
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import re
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


def get_yahoo_price(ticker: str) -> float:
    ticker_obj = yf.Ticker(ticker)
    price = ticker_obj.fast_info.last_price
    if not price:
        raise ValueError(f"فشل جلب السعر من Yahoo: {ticker}")
    return float(price)


def scrape_dahabmasr() -> dict:
    url = "https://dahabmasr.com/gold-price-today-ar"
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    rows = soup.find_all("tr")

    prices = {}
    karat_map = {
        "24": "g24k",
        "21": "g21k",
        "18": "g18k",
        "14": "g14k",
    }

    for row in rows:
        text = row.get_text(" ", strip=True)
        if not text:
            continue

        for karat, key in karat_map.items():
            if f"{karat}K" in text or f"عيار {karat}" in text:
                nums = re.findall(r"[\d,]+\.?\d*", text)
                nums = [float(n.replace(",", "")) for n in nums if float(n.replace(",", "")) > 1000]
                if nums:
                    prices[key] = {
                        "buy": max(nums),
                        "sell": min(nums),
                    }

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


def calculate_fallback(gold_usd: float, usd_egp: float) -> dict:
    g24 = (gold_usd * usd_egp) / GRAMS_PER_OZ

    return {
        "g24k": {"buy": round(g24), "sell": round(g24 * 0.99)},
        "g21k": {"buy": round(g24 * 21 / 24), "sell": round(g24 * 21 / 24 * 0.99)},
        "g18k": {"buy": round(g24 * 18 / 24), "sell": round(g24 * 18 / 24 * 0.99)},
        "g14k": {"buy": round(g24 * 14 / 24), "sell": round(g24 * 14 / 24 * 0.99)},
        "pound": round(g24 * 21 / 24 * 8),
    }


def main():
    print("⚡ بدء تحديث الأسعار...")

    fallback_used = False
    source_parts = []

    try:
        gold_usd = get_yahoo_price("XAUUSD=X")
        usd_egp = get_yahoo_price("USDEGP=X")
        source_parts.append("Yahoo Finance")
        print(f"✅ Yahoo OK | Gold USD/Oz: {gold_usd:,.2f} | USD/EGP: {usd_egp:.2f}")
    except Exception as e:
        print(f"⚠️ فشل Yahoo: {e}")
        gold_usd = 5182
        usd_egp = 52.5
        fallback_used = True

    local_prices = {}
    try:
        local_prices = scrape_dahabmasr()
        if local_prices.get("g24k"):
            source_parts.append("dahabmasr.com")
            print(f"✅ DahabMasr OK | 24K Buy: {local_prices['g24k']['buy']:,}")
        else:
            raise ValueError("لم يتم العثور على أسعار كافية في الصفحة")
    except Exception as e:
        print(f"⚠️ فشل DahabMasr: {e}")
        local_prices = calculate_fallback(gold_usd, usd_egp)
        fallback_used = True

    fallback_prices = calculate_fallback(gold_usd, usd_egp)

    def get_price(key: str, subkey: str = "buy"):
        if key in local_prices:
            if isinstance(local_prices[key], dict):
                return local_prices[key].get(subkey)
            return local_prices[key]

        if key in fallback_prices:
            if isinstance(fallback_prices[key], dict):
                return fallback_prices[key].get(subkey)
            return fallback_prices[key]

        return None

    status = "fallback" if fallback_used else "live"
    source_label = " + ".join(source_parts) if source_parts else "Fallback Calculation"

    payload = {
        "gold_usd_oz": round(gold_usd, 2),
        "usd_egp": round(usd_egp, 2),

        "gold_egp_gram_24k": get_price("g24k", "buy"),
        "gold_egp_gram_24k_sell": get_price("g24k", "sell"),

        "gold_egp_gram_21k": get_price("g21k", "buy"),
        "gold_egp_gram_21k_sell": get_price("g21k", "sell"),

        "gold_egp_gram_18k": get_price("g18k", "buy"),
        "gold_egp_gram_18k_sell": get_price("g18k", "sell"),

        "gold_egp_gram_14k": get_price("g14k", "buy"),
        "gold_egp_pound": get_price("pound"),

        "gold_egp_oz": round((get_price("g24k", "buy") or 8500) * GRAMS_PER_OZ),

        "status": status,
        "fallback_used": fallback_used,
        "source": source_label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    print("✅ تم تحديث data/prices.json بنجاح")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
