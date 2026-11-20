# ============================================================
# EXPORT ALL  -  website ke liye saare stocks ka data file banata hai
#
# Zaroori: ye file 'scanner_nse_bse_fast.py' ke SAATH, usi folder
# (Linux files) mein honi chahiye.
#
# Chalane ka tarika:
#   python3 export_all.py
#
# Result: screener_data.json  (ye file website par upload karni hai)
# ============================================================

import json
import os
import pandas as pd
import yfinance as yf
from scanner_nse_bse_fast import get_universe, get_data

MIN_TURNOVER = 1 * 1e7        # 1 cr se kam turnover wale stocks list mein nahi
SHARES_FILE = "shares_cache.json"   # shares ki sankhya yahan save hoti hai
SECTOR_FILE = "sector_cache.json"   # sector aur industry yahan save hoti hai


def num(x, digits=1):
    """NaN ko None bana deta hai (website ko NaN samajh nahi aata)."""
    if x is None or pd.isna(x):
        return None
    return round(float(x), digits)


def main():
    tickers = get_universe()
    close, volume = get_data(tickers)

    # Khaali (missing) din ko pichle din ke price se bhar do,
    # warna 200 DMA khaali aata hai aur stock bahar ho jaata hai.
    close = close.ffill()

    last = close.iloc[-1]
    sma200 = close.rolling(200, min_periods=150).mean().iloc[-1]
    turnover = (close * volume).tail(30).mean()
    rs6 = (close.iloc[-1] / close.iloc[-126] - 1).rank(pct=True) * 100
    rs3 = (close.iloc[-1] / close.iloc[-63] - 1).rank(pct=True) * 100
    from_high = (1 - last / close.max()) * 100     # 52 hafte ke high se kitna neeche

    keep = turnover[turnover >= MIN_TURNOVER].index.tolist()
    print("Website mein jaane wale stocks:", len(keep))

    # Shares ki sankhya (market cap = price x shares). Ek baar nikalke save.
    shares = {}
    if os.path.exists(SHARES_FILE):
        shares = json.load(open(SHARES_FILE))
    missing = [t for t in keep if t not in shares]
    print("Shares nikalne hain:", len(missing), "(pehli baar slow)")
    for i, t in enumerate(missing):
        try:
            shares[t] = yf.Ticker(t).fast_info["shares"]
        except Exception:
            shares[t] = None
        if i % 200 == 0:
            print(f"  {i}/{len(missing)}")
            json.dump(shares, open(SHARES_FILE, "w"))
    json.dump(shares, open(SHARES_FILE, "w"))

    # Sector aur industry (ek baar nikalke save, pehli baar slow)
    sectors = {}
    if os.path.exists(SECTOR_FILE):
        sectors = json.load(open(SECTOR_FILE))
    missing = [t for t in keep if t not in sectors]
    print("Sector nikalne hain:", len(missing), "(pehli baar slow)")
    for i, t in enumerate(missing):
        try:
            info = yf.Ticker(t).info
            sectors[t] = [info.get("sector"), info.get("industry")]
        except Exception:
            sectors[t] = [None, None]
        if i % 200 == 0:
            print(f"  {i}/{len(missing)}")
            json.dump(sectors, open(SECTOR_FILE, "w"))
    json.dump(sectors, open(SECTOR_FILE, "w"))

    rows = []
    for t in keep:
        if pd.isna(last[t]):
            continue
        sh = shares.get(t)
        rows.append({
            "s": t.split(".")[0],
            "x": "NSE" if t.endswith(".NS") else "BSE",
            "p": num(last[t], 2),
            "m": num(last[t] * sh / 1e7, 0) if sh else None,   # market cap (cr)
            "r": num(rs6[t], 0),
            "r3": num(rs3[t], 0),
            "h": num(from_high[t], 1),
            "t": num(turnover[t] / 1e7, 1),                    # turnover (cr)
            "a": bool(last[t] > sma200[t]) if not pd.isna(sma200[t]) else False,
            "sec": sectors.get(t, [None, None])[0],
            "ind": sectors.get(t, [None, None])[1],
        })

    out = {"date": str(close.index.max().date()), "rows": rows}
    json.dump(out, open("screener_data.json", "w"))
    print("Ho gaya:", len(rows), "stocks -> screener_data.json")


if __name__ == "__main__":
    main()
