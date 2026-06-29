import warnings, json
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
from datetime import date, datetime, timedelta

FUNDS = {
    "CGDV": {"name": "Capital Group Dividend Value ETF", "category": "Large Value"},
    "CGGR": {"name": "Capital Group Growth ETF",         "category": "Large Growth"},
    "CGUS": {"name": "Capital Group Core Equity ETF",    "category": "Large Blend"},
    "CGMM": {"name": "Cap Group Core Municipal Market",  "category": "Muni Bond"},
}

PEER_GROUPS = {
    "Large Value":  ["VTV",  "IVE",  "DVY",  "VYM",  "SCHD", "RPV",  "IWD"],
    "Large Growth": ["VUG",  "IVW",  "SPYG", "QQQ",  "MGK",  "IWF"],
    "Large Blend":  ["SPY",  "IVV",  "VOO",  "VV",   "SCHX", "VTI"],
    "Muni Bond":    ["MUB",  "VTEB", "TFI",  "CMF",  "HYMB"],
}


def download_prices():
    tickers = list(set(
        list(FUNDS.keys()) +
        [t for peers in PEER_GROUPS.values() for t in peers]
    ))
    raw = yf.download(tickers, period="6y", auto_adjust=True,
                      progress=False, threads=True)
    return raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw


def calc_1d(s):
    s = s.dropna()
    if len(s) < 2:
        return None
    return round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2)


def calc_return(s, start, annualize=False, years=1):
    s = s.dropna()
    if s.empty:
        return None
    subset = s[s.index >= pd.Timestamp(start)]
    if subset.empty:
        return None
    sp, ep = subset.iloc[0], s.iloc[-1]
    if sp == 0 or pd.isna(sp):
        return None
    raw = ep / sp - 1
    if annualize and years > 1:
        actual_years = (s.index[-1] - subset.index[0]).days / 365.25
        if actual_years < 0.5:
            return None
        raw = (1 + raw) ** (1 / actual_years) - 1
    return round(raw * 100, 2)


def peer_rank(ticker, category, ret_map):
    peers = PEER_GROUPS.get(category, [])
    universe = {t: ret_map[t] for t in ([ticker] + peers) if ret_map.get(t) is not None}
    if ticker not in universe:
        return None, None
    ranked = sorted(universe, key=lambda t: universe[t], reverse=True)
    return ranked.index(ticker) + 1, len(ranked)


def build_payload():
    prices = download_prices()
    today = date.today()

    PERIODS = [
        ("1D",  None,                              False, 1),
        ("1M",  today - timedelta(days=30),        False, 1),
        ("YTD", date(today.year, 1, 1),            False, 1),
        ("1Y",  today - timedelta(days=365),       False, 1),
        ("3Y",  today - timedelta(days=365 * 3),   False, 3),
        ("5Y",  today - timedelta(days=365 * 5),   False, 5),
    ]

    all_returns = {p[0]: {} for p in PERIODS}
    for ticker in prices.columns:
        s = prices[ticker]
        for pname, start, ann, yrs in PERIODS:
            ret = calc_1d(s) if pname == "1D" else calc_return(s, start, ann, yrs)
            if ret is not None:
                all_returns[pname][ticker] = ret

    funds_out = []
    for ticker, info in FUNDS.items():
        periods_out = []
        for pname, *_ in PERIODS:
            ret = all_returns[pname].get(ticker)
            rank, total = peer_rank(ticker, info["category"], all_returns[pname])
            periods_out.append({"period": pname, "return": ret,
                                 "rank": rank, "total": total})
        funds_out.append({
            "ticker":   ticker,
            "name":     info["name"],
            "category": info["category"],
            "periods":  periods_out,
        })

    return {
        "funds":   funds_out,
        "updated": datetime.now().strftime("%b %d, %Y  %I:%M %p"),
    }


if __name__ == "__main__":
    print("Fetching price data...")
    payload = build_payload()
    with open("data.json", "w") as f:
        json.dump(payload, f)
    print(f"Done — updated: {payload['updated']}")
