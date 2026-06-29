import warnings, os
warnings.filterwarnings("ignore")

from flask import Flask, jsonify, render_template_string
import yfinance as yf
import pandas as pd
from datetime import date, datetime, timedelta

app = Flask(__name__)

# 15-minute in-memory cache — prevents re-downloading on every page hit
_cache = {"payload": None, "expires": None}

# ── Funds ──────────────────────────────────────────────────────────────────
FUNDS = {
    "CGDV": {"name": "Capital Group Dividend Value ETF", "category": "Large Value"},
    "CGGR": {"name": "Capital Group Growth ETF",         "category": "Large Growth"},
    "CGUS": {"name": "Capital Group Core Equity ETF",    "category": "Large Blend"},
    "CGMM": {"name": "Cap Group Core Municipal Market",  "category": "Muni Bond"},
}

# Free peer groups pulled from Yahoo Finance — used to compute rankings
PEER_GROUPS = {
    "Large Value":  ["VTV",  "IVE",  "DVY",  "VYM",  "SCHD", "RPV",  "IWD"],
    "Large Growth": ["VUG",  "IVW",  "SPYG", "QQQ",  "MGK",  "IWF"],
    "Large Blend":  ["SPY",  "IVV",  "VOO",  "VV",   "SCHX", "VTI"],
    "Muni Bond":    ["MUB",  "VTEB", "TFI",  "CMF",  "HYMB"],
}


# ── Helpers ─────────────────────────────────────────────────────────────────

def download_prices() -> pd.DataFrame:
    """Batch-download 6 years of adjusted close prices for all tickers."""
    tickers = list(set(
        list(FUNDS.keys()) +
        [t for peers in PEER_GROUPS.values() for t in peers]
    ))
    raw = yf.download(tickers, period="6y", auto_adjust=True,
                      progress=False, threads=True)
    return raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw


def calc_1d(s: pd.Series):
    s = s.dropna()
    if len(s) < 2:
        return None
    return round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2)


def calc_return(s: pd.Series, start, annualize=False, years=1):
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
        raw = (1 + raw) ** (1 / years) - 1
    return round(raw * 100, 2)


def peer_rank(ticker: str, category: str, ret_map: dict):
    """Return (rank, total) for ticker vs its peer group. 1 = top performer."""
    peers = PEER_GROUPS.get(category, [])
    universe = {t: ret_map[t] for t in ([ticker] + peers) if ret_map.get(t) is not None}
    if ticker not in universe:
        return None, None
    ranked = sorted(universe, key=lambda t: universe[t], reverse=True)
    return ranked.index(ticker) + 1, len(ranked)


# ── API ──────────────────────────────────────────────────────────────────────

def build_payload():
    prices = download_prices()
    today = date.today()

    PERIODS = [
        ("1D",  None,                              False, 1),
        ("1M",  today - timedelta(days=30),        False, 1),
        ("YTD", date(today.year, 1, 1),            False, 1),
        ("1Y",  today - timedelta(days=365),       False, 1),
        ("3Y",  today - timedelta(days=365 * 3),   True,  3),
        ("5Y",  today - timedelta(days=365 * 5),   True,  5),
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


@app.route("/api/data")
def api_data():
    now = datetime.now()
    if _cache["payload"] and _cache["expires"] and now < _cache["expires"]:
        return jsonify(_cache["payload"])
    try:
        payload = build_payload()
        _cache["payload"] = payload
        _cache["expires"] = now + timedelta(seconds=900)
        return jsonify(payload)
    except Exception as e:
        if _cache["payload"]:
            return jsonify(_cache["payload"])
        return jsonify({"error": str(e)}), 500


# ── HTML ─────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fund Performance Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: linear-gradient(135deg, #0d0d1a 0%, #111827 55%, #0f172a 100%);
  min-height: 100vh;
  color: #e2e8f0;
  padding: 1.5rem;
}

/* ─ Header ─ */
.header {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1.5rem;
}
.header h1 {
  font-size: 1.35rem; font-weight: 800; letter-spacing: 0.4px;
  background: linear-gradient(90deg, #60a5fa, #a78bfa);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.header-right { display: flex; align-items: center; gap: 0.75rem; }
.updated { font-size: 0.76rem; color: #475569; }
.refresh-btn {
  background: rgba(96,165,250,0.12); border: 1px solid rgba(96,165,250,0.3);
  color: #60a5fa; padding: 0.4rem 1rem; border-radius: 8px;
  cursor: pointer; font-size: 0.82rem; font-weight: 600; transition: background 0.18s;
}
.refresh-btn:hover:not(:disabled) { background: rgba(96,165,250,0.22); }
.refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ─ Grid ─ */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
  gap: 1.2rem;
}

/* ─ Card ─ */
.card {
  background: rgba(255,255,255,0.05);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 18px; overflow: hidden;
  transition: border-color 0.2s, transform 0.15s;
}
.card:hover { border-color: rgba(96,165,250,0.25); transform: translateY(-1px); }

.card-header {
  padding: 1.2rem 1.4rem 1rem;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem;
}
.ticker { font-size: 1.6rem; font-weight: 800; color: #f8fafc; letter-spacing: 1px; }
.fund-name { font-size: 0.76rem; color: #64748b; margin-top: 3px; }
.category-pill {
  font-size: 0.66rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 0.28rem 0.6rem; border-radius: 99px; white-space: nowrap; margin-top: 3px;
  background: rgba(167,139,250,0.12); border: 1px solid rgba(167,139,250,0.28); color: #a78bfa;
}

/* ─ Table ─ */
.tbl { width: 100%; border-collapse: collapse; }
.tbl thead th {
  font-size: 0.66rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
  color: #334155; padding: 0.55rem 1.4rem;
  border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left;
}
.tbl thead th.r { text-align: right; }
.tbl tbody td {
  padding: 0.6rem 1.4rem; font-size: 0.88rem;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.tbl tbody tr:last-child td { border-bottom: none; }
.tbl tbody tr:hover td { background: rgba(255,255,255,0.025); }

.period { font-weight: 600; color: #94a3b8; }
.ret { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
.pos { color: #4ade80; }
.neg { color: #f87171; }
.nil { color: #334155; }

.rank-cell { text-align: right; }
.rank-wrap { display: inline-flex; align-items: center; gap: 6px; }
.rank-val { font-variant-numeric: tabular-nums; color: #94a3b8; font-size: 0.82rem; }
.badge {
  font-size: 0.63rem; font-weight: 700; padding: 0.16rem 0.4rem; border-radius: 99px;
}
.b-top { background: rgba(74,222,128,0.15); color: #4ade80; }
.b-mid { background: rgba(251,191,36,0.15);  color: #fbbf24; }
.b-bot { background: rgba(248,113,113,0.15); color: #f87171; }

/* ─ Skeleton ─ */
@keyframes shimmer {
  from { background-position: -200% 0; }
  to   { background-position:  200% 0; }
}
.sk {
  display: inline-block; border-radius: 4px;
  background: linear-gradient(90deg,
    rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.04) 75%);
  background-size: 200% 100%; animation: shimmer 1.4s infinite;
}
.err { grid-column:1/-1; text-align:center; padding:3rem; color:#f87171; font-size:0.9rem; }
</style>
</head>
<body>

<div class="header">
  <h1>Fund Performance Dashboard</h1>
  <div class="header-right">
    <span class="updated" id="upd">—</span>
    <button class="refresh-btn" id="rbtn" onclick="load()">&#8635; Refresh</button>
  </div>
</div>

<div class="grid" id="grid"></div>

<script>
const PERIODS = ["1D","1M","YTD","1Y","3Y","5Y"];

function skeleton() {
  const rows = PERIODS.map(() => `<tr>
    <td><span class="sk" style="width:26px;height:.82em"></span></td>
    <td class="ret"><span class="sk" style="width:60px;height:.82em"></span></td>
    <td class="rank-cell"><span class="sk" style="width:48px;height:.82em"></span></td>
  </tr>`).join("");
  return `<div class="card">
    <div class="card-header">
      <div>
        <div class="sk" style="width:78px;height:1.4em;margin-bottom:6px;border-radius:6px"></div>
        <div class="sk" style="width:195px;height:.72em"></div>
      </div>
      <div class="sk" style="width:70px;height:1.1em;border-radius:99px;margin-top:4px"></div>
    </div>
    <table class="tbl">
      <thead><tr><th>Period</th><th class="r">Return</th><th class="r">Peer Rank</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function fmt(val) {
  if (val == null) return {t:"—", c:"nil"};
  return {t:(val>=0?"+":"")+val.toFixed(2)+"%", c:val>=0?"pos":"neg"};
}

function badge(rank, total) {
  if (!rank || !total) return "";
  const pct = rank / total;
  const cls = pct <= 0.33 ? "b-top" : pct <= 0.66 ? "b-mid" : "b-bot";
  return `<span class="badge ${cls}">${Math.round(pct*100)}th pct</span>`;
}

function card(f) {
  const rows = f.periods.map(p => {
    const r = fmt(p.return);
    const rankHtml = p.rank != null
      ? `<div class="rank-wrap">
           <span class="rank-val">${p.rank}&thinsp;/&thinsp;${p.total}</span>
           ${badge(p.rank, p.total)}
         </div>`
      : `<span style="color:#334155">—</span>`;
    return `<tr>
      <td><span class="period">${p.period}</span></td>
      <td class="ret ${r.c}">${r.t}</td>
      <td class="rank-cell">${rankHtml}</td>
    </tr>`;
  }).join("");

  return `<div class="card">
    <div class="card-header">
      <div>
        <div class="ticker">${f.ticker}</div>
        <div class="fund-name">${f.name}</div>
      </div>
      <div class="category-pill">${f.category}</div>
    </div>
    <table class="tbl">
      <thead><tr><th>Period</th><th class="r">Return</th><th class="r">Peer Rank</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

async function load() {
  const btn  = document.getElementById("rbtn");
  const grid = document.getElementById("grid");
  btn.disabled = true;
  btn.textContent = "Loading…";
  grid.innerHTML = Array.from({length:4}, skeleton).join("");
  try {
    const res  = await fetch("/api/data");
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    grid.innerHTML = data.funds.map(card).join("");
    document.getElementById("upd").textContent = "Updated " + data.updated;
  } catch(e) {
    grid.innerHTML = `<div class="err">Failed to load data: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "↻ Refresh";
  }
}

setInterval(load, 15 * 60 * 1000); // auto-refresh every 15 minutes
load();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
