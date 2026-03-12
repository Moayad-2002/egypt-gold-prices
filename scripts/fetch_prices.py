#!/usr/bin/env python3
"""
scripts/fetch_prices.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
المصدر الأساسي:  dahabmasr.com (أسعار السوق المصري الحقيقية)
المصدر الثانوي: yfinance      (للدولار والسعر الدولي)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json, os, re
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

# ─────────────────────────────────────────
# 1. Yahoo Finance — الدولار والسعر الدولي
# ─────────────────────────────────────────
def get_yahoo_price(ticker: str) -> float:
    t = yf.Ticker(ticker)
    price = t.fast_info.last_price
    if not price:
        raise ValueError(f"فشل جلب: {ticker}")
    return float(price)

# ─────────────────────────────────────────
# 2. dahabmasr.com — السعر المحلي المصري
# ─────────────────────────────────────────
def scrape_dahabmasr() -> dict:
    url = "https://dahabmasr.com/gold-price-today-ar"
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "lxml")

    prices = {}
    rows = soup.find_all("tr")

    karat_map = {
        "24": "g24k",
        "21": "g21k",
        "18": "g18k",
        "14": "g14k",
    }

    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        text = row.get_text(" ", strip=True)

        for k, key in karat_map.items():
            if f"{k}K" in text or f"عيار {k}" in text:
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

# ─────────────────────────────────────────
# 3. Fallback — حساب رياضي لو فشل الـ Scraping
# ─────────────────────────────────────────
def calculate_fallback(gold_usd: float, usd_egp: float) -> dict:
    g24 = (gold_usd * usd_egp) / GRAMS_PER_OZ
    return {
        "g24k": {"buy": round(g24), "sell": round(g24 * 0.99)},
        "g21k": {"buy": round(g24 * 21/24), "sell": round(g24 * 21/24 * 0.99)},
        "g18k": {"buy": round(g24 * 18/24), "sell": round(g24 * 18/24 * 0.99)},
        "g14k": {"buy": round(g24 * 14/24), "sell": round(g24 * 14/24 * 0.99)},
        "pound": round(g24 * 21/24 * 8),
    }

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print("⚡ جلب الأسعار...")

    try:
        gold_usd = get_yahoo_price("XAUUSD=X")
        usd_egp  = get_yahoo_price("USDEGP=X")
        print(f"  ✅ Yahoo: ذهب=${gold_usd:,.2f} | دولار={usd_egp:.2f} ج.م")
    except Exception as e:
        print(f"  ⚠️  Yahoo فشل: {e} — سيُستخدم Fallback")
        gold_usd, usd_egp = 5182, 52.5

    local_prices = {}
    try:
        local_prices = scrape_dahabmasr()
        if local_prices.get("g24k"):
            print(f"  ✅ dahabmasr: عيار 24 = {local_prices['g24k']['buy']:,} ج.م")
        else:
            raise ValueError("لم يُعثر على أسعار في الصفحة")
    except Exception as e:
        print(f"  ⚠️  dahabmasr فشل: {e} — سيُستخدم الحساب الرياضي")
        local_prices = calculate_fallback(gold_usd, usd_egp)

    fb = calculate_fallback(gold_usd, usd_egp)

    def get(key, subkey="buy"):
        if key in local_prices and isinstance(local_prices[key], dict):
            return local_prices[key][subkey]
        if key in local_prices and isinstance(local_prices[key], (int, float)):
            return local_prices[key]
        return fb.get(key, {}).get(subkey) if isinstance(fb.get(key), dict) else fb.get(key)

    payload = {
        "gold_usd_oz":          round(gold_usd, 2),
        "usd_egp":              round(usd_egp, 2),
        "gold_egp_gram_24k":    get("g24k", "buy"),
        "gold_egp_gram_24k_sell": get("g24k", "sell"),
        "gold_egp_gram_21k":    get("g21k", "buy"),
        "gold_egp_gram_21k_sell": get("g21k", "sell"),
        "gold_egp_gram_18k":    get("g18k", "buy"),
        "gold_egp_gram_18k_sell": get("g18k", "sell"),
        "gold_egp_gram_14k":    get("g14k", "buy"),
        "gold_egp_pound":       get("pound"),
        "gold_egp_oz":          round((get("g24k", "buy") or 8500) * GRAMS_PER_OZ),
        "source":               "dahabmasr.com + Yahoo Finance",
        "timestamp":            datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n  ✅ تم الحفظ بنجاح في data/prices.json")

if __name__ == "__main__":
    main()
