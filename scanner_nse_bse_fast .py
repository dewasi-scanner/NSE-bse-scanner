# ============================================================
# NSE + BSE SCANNER  (CACHE WALA FAST VERSION)
#
# Pehli baar: poora 1 saal ka data download -> cache files mein save
# Agli baar : sirf naye din ka data download -> cache mein jod do
#
# Filters:
#   1. RS rating >= 90
#   2. Price > Rs 10
#   3. Price > 200 DMA
#   4. 30 din ka average turnover > 7 cr
#   5. Market cap > 500 cr
#
# Chalane ka tarika:
#   python3 scanner_nse_bse_fast.py
#
# Cache dobara shuru se banana ho to ye 2 files delete kar do:
#   cache_close.pkl  aur  cache_volume.pkl
#
# Tip: market band hone ke baad (shaam ko) chalao, taaki aaj ka
# poora data mile.
# ============================================================

import io
import json
import os
import time
import requests
import pandas as pd
import yfinance as yf

# ---------- SETTINGS ----------
MIN_RS = 90
MIN_PRICE = 10
MIN_TURNOVER = 7 * 1e7      # 7 cr  (1 cr = 1e7)
MIN_MCAP = 500 * 1e7        # 500 cr
BATCH_SIZE = 100
KEEP_DAYS = 260             # cache mein kitne din ka data rakhna hai
OVERLAP_DAYS = 5            # pichle kitne din dobara download karne hain (safety)
CLOSE_FILE = "cache_close.pkl"
VOLUME_FILE = "cache_volume.pkl"
# ------------------------------

NSE_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_URL = ("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
           "?Group=&Scripcode=&industry=&segment=Equity&status=Active")
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.bseindia.com/",
}


# ---------------- STOCK LIST (NSE + BSE) ----------------

def find_col(df, options):
    cols = {str(c).strip().lower(): c for c in df.columns}
    for o in options:
        if o in cols:
            return cols[o]
    return None


def get_nse():
    try:
        r = requests.get(NSE_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        print("NSE se list nahi aayi, local EQUITY_L.csv padh raha hoon...")
        df = pd.read_csv("EQUITY_L.csv")

    df.columns = df.columns.str.strip()
    df = df[df["SERIES"].str.strip() == "EQ"]
    isin_col = find_col(df, ["isin number", "isin"])
    return pd.DataFrame({
        "ticker": df["SYMBOL"].str.strip() + ".NS",
        "isin": df[isin_col].str.strip() if isin_col else None,
    })


def get_bse():
    try:
        r = requests.get(BSE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        df = pd.DataFrame(r.json())
    except Exception:
        print("BSE se list nahi aayi, local file padh raha hoon...")
        try:
            if os.path.exists("bse_list.json"):
                df = pd.DataFrame(json.load(open("bse_list.json")))
            else:
                df = pd.read_csv("bse_list.csv")
        except Exception:
            print("bse_list.csv bhi nahi mili, BSE skip kar raha hoon.")
            return pd.DataFrame(columns=["ticker", "isin"])

    code_col = find_col(df, ["scrip_cd", "security code", "scripcode"])
    isin_col = find_col(df, ["isin_number", "isin no", "isin no.", "isin"])
    status_col = find_col(df, ["status"])
    if code_col is None:
        print("BSE file ka format samajh nahi aaya, BSE skip kar raha hoon.")
        return pd.DataFrame(columns=["ticker", "isin"])

    if status_col is not None:
        df = df[df[status_col].astype(str).str.strip().str.lower() == "active"]

    return pd.DataFrame({
        "ticker": df[code_col].astype(str).str.strip() + ".BO",
        "isin": df[isin_col].astype(str).str.strip() if isin_col else None,
    })


def get_universe():
    nse = get_nse()
    bse = get_bse()
    print("NSE stocks:", len(nse), "| BSE stocks:", len(bse))

    if bse.empty or bse["isin"].isna().all():
        return nse["ticker"].tolist()

    nse_isins = set(nse["isin"].dropna())
    bse_only = bse[~bse["isin"].isin(nse_isins)]
    print("Sirf BSE par listed:", len(bse_only))
    return nse["ticker"].tolist() + bse_only["ticker"].tolist()


# ---------------- DATA DOWNLOAD + CACHE ----------------

def fetch(tickers, **kwargs):
    """Tickers ka data batch mein download karta hai.
    kwargs mein period="1y" ya start="2026-10-01" jaisa kuch aata hai."""
    closes, volumes = [], []
    total = len(tickers)
    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        print(f"  Download: {i}/{total}")
        try:
            data = yf.download(batch, auto_adjust=True, progress=False,
                               threads=True, **kwargs)
            closes.append(data["Close"])
            volumes.append(data["Volume"])
        except Exception as e:
            print("  Batch fail hua, aage badh rahe hain:", e)
        time.sleep(1)
    if not closes:
        return pd.DataFrame(), pd.DataFrame()
    return pd.concat(closes, axis=1), pd.concat(volumes, axis=1)


def get_data(tickers):
    """Cache hai to sirf naya data laata hai, nahi hai to poora."""
    if os.path.exists(CLOSE_FILE) and os.path.exists(VOLUME_FILE):
        close = pd.read_pickle(CLOSE_FILE)
        volume = pd.read_pickle(VOLUME_FILE)
        last_date = close.index.max()
        start = (last_date - pd.Timedelta(days=OVERLAP_DAYS)).strftime("%Y-%m-%d")
        print("Cache mila. Last date:", last_date.date(), "| naya data", start, "se laa raha hoon")

        known = [t for t in tickers if t in close.columns]
        new_tickers = [t for t in tickers if t not in close.columns]

        # 1) Purane stocks: sirf naye din
        nc, nv = fetch(known, start=start)
        if not nc.empty:
            close = nc.combine_first(close)     # naya data pehle, purana backup
            volume = nv.combine_first(volume)

        # 2) Naye listed stocks: unka poora 1 saal
        if new_tickers:
            print("Naye stocks (poora data):", len(new_tickers))
            fc, fv = fetch(new_tickers, period="1y")
            if not fc.empty:
                close = close.combine_first(fc)
                volume = volume.combine_first(fv)
    else:
        print("Cache nahi mila. Poora 1 saal ka data download ho raha hai (pehli baar)...")
        close, volume = fetch(tickers, period="1y")

    close = close.sort_index().tail(KEEP_DAYS)
    volume = volume.sort_index().tail(KEEP_DAYS)

    close.to_pickle(CLOSE_FILE)
    volume.to_pickle(VOLUME_FILE)
    print("Cache save ho gaya.")

    # Sirf aaj ki list ke stocks ka data aage bhejo
    keep = [t for t in tickers if t in close.columns]
    return close[keep], volume[keep]


# ---------------- SCANNER ----------------

def main():
    tickers = get_universe()
    print("Total stocks scan honge:", len(tickers))

    close, volume = get_data(tickers)
    print("Data ki last date:", close.index.max().date())

    last_price = close.iloc[-1]
    dma200 = close.rolling(200).mean().iloc[-1]
    turnover30 = (close * volume).tail(30).mean()

    ret_6m = close.iloc[-1] / close.iloc[-126] - 1
    rs = ret_6m.rank(pct=True) * 100

    mask = (
        (rs >= MIN_RS)
        & (last_price > MIN_PRICE)
        & (last_price > dma200)
        & (turnover30 > MIN_TURNOVER)
    )
    survivors = mask[mask].index.tolist()
    print("Market cap check se pehle stocks:", len(survivors))

    rows = []
    for ticker in survivors:
        try:
            mcap = yf.Ticker(ticker).fast_info["market_cap"]
        except Exception:
            continue
        if mcap and mcap > MIN_MCAP:
            rows.append({
                "Symbol": ticker.split(".")[0],
                "Exchange": "NSE" if ticker.endswith(".NS") else "BSE",
                "Price": round(last_price[ticker], 2),
                "RS": round(rs[ticker], 1),
                "200DMA": round(dma200[ticker], 2),
                "Avg Turnover (cr)": round(turnover30[ticker] / 1e7, 2),
                "Market Cap (cr)": round(mcap / 1e7, 0),
            })

    result = pd.DataFrame(rows)
    if result.empty:
        print("Koi stock nahi mila.")
        return

    result = result.sort_values("RS", ascending=False).reset_index(drop=True)
    print(result.to_string())
    result.to_csv("scanner_result.csv", index=False)
    print("\nResult 'scanner_result.csv' mein save ho gaya.")


if __name__ == "__main__":
    main()
