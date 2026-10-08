#!/usr/bin/env python3
"""Build data.json for the Market Watcher desk.

Writes the snapshot only. Never regenerates index.html, app.js, or styles.css.

Fixes versus the old upload job:
- Yahoo impliedVolatility is a decimal (0.285 = 28.5%). It is scaled once.
- Unusual flow is limited to 45-75 DTE, volume >= 1.5x open interest, and
  premium >= $500k. One-day SPY prints no longer fill the panel.
- A failed source keeps that section from the previous data.json.
"""

from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data.json"
NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "market-watcher/1.0"}

def _load_wheel() -> list:
    """Alert tickers, editable by memoli in tickers.json (repo root)."""
    try:
        cfg = json.loads((ROOT / "tickers.json").read_text())
        tickers = [str(x).strip().upper() for x in cfg.get("tickers", []) if str(x).strip()]
        if tickers:
            return tickers
    except Exception as exc:  # warn() not defined yet at module load
        print(f"tickers.json unreadable, using defaults: {exc}", file=sys.stderr)
    return ["SPY", "QQQ", "IWM"]


WHEEL = _load_wheel()
SCORECARD = [
    ("^GSPC", "S&P 500", "Indices"),
    ("^IXIC", "Nasdaq Comp", "Indices"),
    ("^DJI", "Dow", "Indices"),
    ("^RUT", "Russell 2000", "Indices"),
    ("EURUSD=X", "EUR/USD", "Forex"),
    ("JPY=X", "USD/JPY", "Forex"),
    ("GBPUSD=X", "GBP/USD", "Forex"),
    ("BTC-USD", "Bitcoin", "Crypto"),
    ("ETH-USD", "Ethereum", "Crypto"),
    ("GC=F", "Gold", "Commodities"),
    ("SI=F", "Silver", "Commodities"),
    ("CL=F", "Crude oil", "Commodities"),
    ("TLT", "20Y Treasuries", "Bonds"),
]
MACRO = [
    ("CPIAUCSL", "CPI index", "yoy"),
    ("UNRATE", "Unemployment rate %", "pp"),
    ("PAYEMS", "Nonfarm payrolls (k)", "diff"),
    ("FEDFUNDS", "Fed funds rate %", "pp"),
    ("MORTGAGE30US", "30Y mortgage %", "pp"),
    ("DGS10", "10Y yield %", "pp"),
    ("DGS2", "2Y yield %", "pp"),
    ("BAMLH0A0HYM2", "HY OAS %", "pp"),
    ("GDP", "GDP", "qoq"),
    ("HOUST", "Housing starts (k)", "diff"),
    ("RSXFS", "Retail sales", "mom"),
]
COT_MARKETS = {
    "Crude oil": "CRUDE OIL, LIGHT SWEET",
    "Silver": "SILVER",
    "Gold": "GOLD",
    "British pound": "BRITISH POUND STERLING",
    "Yen": "JAPANESE YEN",
    "Euro FX": "EURO FX",
    "S&P 500 (E-mini)": "E-MINI S&P 500",
    "Nasdaq-100": "NASDAQ MINI",
}
NEWS_TERMS = (
    "fed", "fomc", "powell", "cpi", "inflation", "payroll", "jobs report",
    "unemployment", "interest rate", "rate hike", "rate cut", "treasury",
    "mortgage rate", "yield",
)


def load_previous() -> dict:
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text())
    except json.JSONDecodeError:
        return {}


def warn(section: str, exc: Exception) -> None:
    print(f"[warn] {section}: {exc}", file=sys.stderr)


def round1(value) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value), 2)


def iv_percent(raw) -> float | None:
    """Yahoo's impliedVolatility is a decimal. Scale it once."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    value = float(raw)
    if value <= 0:
        return None
    if value <= 3:
        value *= 100
    return round(value, 1)


def rsi(closes: pd.Series, period: int = 14) -> float | None:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    last_loss = loss.iloc[-1]
    if pd.isna(last_loss) or last_loss == 0:
        return 100.0 if gain.iloc[-1] and gain.iloc[-1] > 0 else None
    rs = gain.iloc[-1] / last_loss
    return round(100 - 100 / (1 + rs), 1)


def pct(new, old) -> float | None:
    if old in (None, 0) or pd.isna(old) or pd.isna(new):
        return None
    return round((float(new) / float(old) - 1) * 100, 2)


def history(symbol: str, period: str = "2y") -> pd.DataFrame:
    frame = yf.Ticker(symbol).history(period=period, auto_adjust=False)
    if frame.empty:
        raise RuntimeError(f"no prices for {symbol}")
    frame = frame.rename(columns=str.lower)
    frame.index = frame.index.tz_localize(None)
    # Yahoo sometimes returns a trailing partial bar with NaN close; it must not
    # become the "last" bar (NaN -> invalid JSON -> whole dashboard fails to load)
    return frame.dropna(subset=["close"])


def bollinger(close: pd.Series, window: int = 20, nstd: float = 2):
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return mid + nstd * std, mid, mid - nstd * std


def wheel_ticker(symbol: str) -> dict:
    frame = history(symbol, "2y")
    close = frame["close"]
    upper, mid, lower = bollinger(close)
    sma200 = close.rolling(200).mean()
    view = frame.tail(251).copy()
    view["bb_upper"] = upper
    view["bb_lower"] = lower
    view["mid"] = mid
    view["sma200"] = sma200
    entries, blocked = [], []
    tagged_prev = False
    for stamp, row in view.iterrows():
        if pd.isna(row.bb_lower) or pd.isna(row.sma200):
            tagged_prev = False
            continue
        tagged = bool(row.low <= row.bb_lower or row.close <= row.bb_lower)
        if tagged and not tagged_prev:
            point = {"x": stamp.strftime("%Y-%m-%d"), "y": round(float(row.close), 2)}
            if row.close > row.sma200:
                entries.append(point)
            else:
                blocked.append(point)
        tagged_prev = tagged
    last = view.iloc[-1]
    prev = view.iloc[-2]
    dist = (last.close / last.bb_lower - 1) * 100 if last.bb_lower else None
    return {
        "ticker": symbol,
        "dates": [stamp.strftime("%Y-%m-%d") for stamp in view.index],
        "close": [None if pd.isna(v) else round(float(v), 2) for v in view.close],
        "bb_upper": [None if pd.isna(v) else round(float(v), 2) for v in view.bb_upper],
        "bb_lower": [None if pd.isna(v) else round(float(v), 2) for v in view.bb_lower],
        "sma200": [None if pd.isna(v) else round(float(v), 2) for v in view.sma200],
        "entries": entries,
        "blocked": blocked,
        "last": {
            "close": round(float(last.close), 2),
            "chg_pct": pct(last.close, prev.close),
            "lower": round(float(last.bb_lower), 2),
            "mid": round(float(last.mid), 2),
            "sma200": round(float(last.sma200), 2),
            "bullish": bool(last.close > last.sma200),
            "dist_to_lower_pct": round(float(dist), 2),
            "last_signal": entries[-1]["x"] if entries else None,
            "n_signals_1y": len(entries),
        },
    }


def series_payload(symbol: str, tail: int = 130) -> tuple[dict, float]:
    frame = history(symbol, "1y").tail(tail)
    return {
        "dates": [stamp.strftime("%Y-%m-%d") for stamp in frame.index],
        "values": [round(float(v), 2) for v in frame.close],
    }, round(float(frame.close.iloc[-1]), 2)


def score_row(symbol: str, label: str, group: str) -> dict:
    frame = history(symbol, "2y")
    close = frame["close"]
    last = float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    window = close.tail(252)
    low, high = float(window.min()), float(window.max())
    pos = 0 if high == low else (last - low) / (high - low) * 100
    change_3m = pct(last, close.iloc[-64] if len(close) > 64 else close.iloc[0]) or 0
    trend = (25 if last > sma50 else 0) + (25 if last > sma200 else 0)
    momentum = max(0, min(25, (change_3m + 15) / 30 * 25))
    rsi_value = rsi(close) or 50
    score = round(trend + momentum + rsi_value / 100 * 25)
    return {
        "symbol": symbol,
        "label": label,
        "group": group,
        "price": round(last, 2),
        "chg_5d": pct(last, close.iloc[-6] if len(close) > 6 else close.iloc[0]),
        "chg_1m": pct(last, close.iloc[-22] if len(close) > 22 else close.iloc[0]),
        "chg_3m": round(change_3m, 2),
        "vs_50d": pct(last, sma50),
        "vs_200d": pct(last, sma200),
        "pos_52w": round(pos, 1),
        "rsi": rsi_value,
        "score": score,
    }


def fred_series(series_id: str) -> pd.Series:
    try:
        response = requests.get(
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}",
            headers=UA,
            timeout=25,
        )
        response.raise_for_status()
        frame = pd.read_csv(StringIO(response.text))
        frame.columns = ["date", "value"]
    except requests.RequestException:
        response = requests.get(f"https://fred.stlouisfed.org/data/{series_id}.txt", headers=UA, timeout=40)
        response.raise_for_status()
        lines = [line for line in response.text.splitlines() if line[:1].isdigit()]
        frame = pd.read_csv(StringIO("date value\n" + "\n".join(lines)), sep=r"\s+")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")["value"]


def macro_block() -> dict:
    out = {}
    loaded = {}
    for series_id, label, kind in MACRO:
        values = fred_series(series_id)
        loaded[series_id] = values
        last, prev = values.iloc[-1], values.iloc[-2]
        if kind == "yoy" and len(values) > 12:
            change = (last / values.iloc[-13] - 1) * 100
            change_text = f"{change:+.1f}% YoY"
        elif kind == "mom" and len(values) > 1:
            change = (last / prev - 1) * 100
            change_text = f"{change:+.1f}% MoM"
        elif kind == "qoq":
            change = last - prev
            change_text = f"{change:+.1f} QoQ"
        elif kind == "diff":
            change = last - prev
            change_text = f"{change:+.0f} MoM"
        else:
            change = last - prev
            change_text = f"{change:+.2f}pp MoM"
        out[series_id] = {
            "label": label,
            "value": f"{last:,.2f}" if kind != "diff" else f"{last:,.1f}",
            "raw": float(last),
            "change": change_text,
            "chg_raw": float(change),
            "asof": values.index[-1].strftime("%Y-%m-%d"),
        }
    if "DGS10" in loaded and "DGS2" in loaded:
        spread = float(loaded["DGS10"].iloc[-1] - loaded["DGS2"].iloc[-1])
        out["_SPREAD_10Y2Y"] = {
            "label": "10Y–2Y spread (pp)",
            "value": f"{spread:+.2f}",
            "raw": spread,
            "change": "",
            "chg_raw": None,
            "asof": loaded["DGS10"].index[-1].strftime("%Y-%m-%d"),
        }
    return out


def put_call() -> tuple[dict, str, list]:
    # The old CDN ratio CSVs stop in 2019. The daily market-statistics file is current.
    hist = []
    day = datetime.now(NY).date()
    for _ in range(16):
        day -= timedelta(days=1)
        if day.weekday() > 4:
            continue
        url = f"https://cdn.cboe.com/data/us/options/market_statistics/daily/{day.isoformat()}_daily_options"
        response = requests.get(url, headers=UA, timeout=20)
        if response.status_code != 200:
            continue
        ratios = {row["name"]: float(row["value"]) for row in response.json().get("ratios", [])}
        if "EQUITY PUT/CALL RATIO" not in ratios:
            continue
        hist.append({
            "d": day.isoformat(),
            "total": round(ratios.get("TOTAL PUT/CALL RATIO", 0), 2),
            "equity": round(ratios["EQUITY PUT/CALL RATIO"], 2),
            "index": round(ratios.get("INDEX PUT/CALL RATIO", 0), 2),
        })
        if len(hist) == 8:
            break
    if not hist:
        raise RuntimeError("no current CBOE put/call files")
    hist.sort(key=lambda row: row["d"])
    last = hist[-1]
    equity = last["equity"]
    reading = (
        f"equity put/call {equity:.2f} — fearful tape, premiums rich"
        if equity >= 0.85
        else f"equity put/call {equity:.2f} — complacent tape, premiums thin"
        if equity <= 0.65
        else f"equity put/call {equity:.2f} — neutral"
    )
    return {"as_of": last["d"], "total": last["total"], "equity": equity, "index": last["index"]}, reading, hist


def cot_block() -> tuple[dict, dict]:
    response = requests.get(
        "https://publicreporting.cftc.gov/resource/jun7-fc8e.json",
        params={"$limit": 5000, "$order": "report_date_as_yyyy_mm_dd DESC"},
        headers=UA,
        timeout=60,
    )
    response.raise_for_status()
    rows = response.json()
    current, history = {}, {}
    for label, needle in COT_MARKETS.items():
        matched = [
            row for row in rows
            if needle in row.get("contract_market_name", "").upper()
            and "MICRO" not in row.get("contract_market_name", "").upper()
        ]
        if not matched:
            continue
        matched.sort(key=lambda row: row.get("report_date_as_yyyy_mm_dd", ""), reverse=True)
        latest = matched[0]
        nets = []
        for row in matched[:52]:
            net = int(float(row.get("noncomm_positions_long_all") or 0) - float(row.get("noncomm_positions_short_all") or 0))
            nets.append({"d": (row.get("report_date_as_yyyy_mm_dd") or "")[:10], "net": net})
        latest_net = nets[0]["net"]
        rank_pool = [item["net"] for item in nets]
        pct_rank = round(sum(value <= latest_net for value in rank_pool) / len(rank_pool) * 100, 1)
        current[label] = {
            "as_of": (latest.get("report_date_as_yyyy_mm_dd") or "")[:10],
            "oi": int(float(latest.get("open_interest_all") or 0)),
            "nc_long": int(float(latest.get("noncomm_positions_long_all") or 0)),
            "nc_short": int(float(latest.get("noncomm_positions_short_all") or 0)),
            "net": latest_net,
            "pct_rank": pct_rank,
        }
        history[label] = list(reversed(nets))
    if not current:
        raise RuntimeError("no COT markets matched")
    return current, history


def stocktwits(symbol: str) -> dict:
    response = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json", headers=UA, timeout=30)
    response.raise_for_status()
    messages = response.json().get("messages", [])[:30]
    bull = bear = 0
    for msg in messages:
        sentiment = ((msg.get("entities") or {}).get("sentiment") or {}).get("basic")
        bull += sentiment == "Bullish"
        bear += sentiment == "Bearish"
    total = len(messages) or 1
    return {
        "bull": bull,
        "bear": bear,
        "total": len(messages),
        "bull_pct": round(bull / total * 100, 1),
        "bear_pct": round(bear / total * 100, 1),
    }


def aaii_block() -> dict:
    response = requests.get("https://www.aaii.com/sentimentsurvey/sent_results", headers=UA, timeout=40)
    response.raise_for_status()
    # The page embeds the latest bull/neutral/bear percentages in a small results table.
    text = response.text
    import re
    found = re.findall(r"(\d{1,2}\.\d)%", text)
    if len(found) < 3:
        raise RuntimeError("AAII percentages not found")
    bull, neutral, bear = map(float, found[:3])
    return {"bull": bull, "neutral": neutral, "bear": bear, "spread": round(bull - bear, 1)}


def option_books(symbol: str, spot: float) -> tuple[dict | None, list]:
    ticker = yf.Ticker(symbol)
    today = datetime.now(NY).date()
    wall_expiries, flow_expiries = [], []
    for raw in ticker.options:
        expiry = datetime.strptime(raw, "%Y-%m-%d").date()
        dte = (expiry - today).days
        if 40 <= dte <= 80:
            wall_expiries.append((dte, raw))
        if 45 <= dte <= 75:
            flow_expiries.append((dte, raw))
    wall = None
    if wall_expiries:
        dte, expiry = min(wall_expiries, key=lambda item: abs(item[0] - 60))
        chain = ticker.option_chain(expiry)
        puts = chain.puts[chain.puts["strike"] < spot].nlargest(3, "openInterest")
        calls = chain.calls[chain.calls["strike"] > spot].nlargest(3, "openInterest")
        wall = {
            "ticker": symbol,
            "expiry": expiry,
            "dte": dte,
            "spot": round(spot, 2),
            "supports": [{"strike": float(row.strike), "oi": int(row.openInterest or 0)} for row in puts.itertuples(index=False)],
            "resistances": [{"strike": float(row.strike), "oi": int(row.openInterest or 0)} for row in calls.itertuples(index=False)],
        }
    unusual = []
    for dte, expiry in flow_expiries:
        chain = ticker.option_chain(expiry)
        for side, frame in (("PUT", chain.puts), ("CALL", chain.calls)):
            for row in frame.itertuples(index=False):
                volume = float(row.volume or 0)
                oi = float(row.openInterest or 0)
                last = float(row.lastPrice or 0)
                premium = last * volume * 100
                if oi <= 0 or volume < 1.5 * oi or premium < 500_000:
                    continue
                unusual.append({
                    "ticker": symbol,
                    "expiry": expiry,
                    "type": side,
                    "strike": float(row.strike),
                    "volume": int(volume),
                    "oi": int(oi),
                    "premium": round(premium),
                    "iv": iv_percent(row.impliedVolatility),
                    "dte": dte,
                })
    return wall, unusual


def news_block() -> list:
    response = requests.get("https://feeds.marketwatch.com/marketwatch/topstories/", headers=UA, timeout=30)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        pub = (node.findtext("pubDate") or "").strip()
        if not title or not any(term in title.lower() for term in NEWS_TERMS):
            continue
        items.append({"pub": pub[:16], "title": title})
        if len(items) == 6:
            break
    return items


def setups(scorecard: list, chatter: dict, unusual: list) -> list:
    rows = []
    for asset in scorecard:
        if asset["score"] >= 80:
            rows.append(f"🔥 {asset['label']} strong uptrend (trend score {asset['score']}/100)")
        elif asset["score"] <= 20:
            rows.append(f"🧊 {asset['label']} strong downtrend (trend score {asset['score']}/100)")
        if asset["pos_52w"] >= 98:
            rows.append(f"📈 {asset['label']} at 52-week high")
        elif asset["pos_52w"] <= 5:
            rows.append(f"📉 {asset['label']} at 52-week low")
    for symbol, sample in chatter.items():
        if sample.get("bear_pct", 0) >= 25:
            rows.append(f"📣 StockTwits ${symbol} heavily bearish ({sample['bear_pct']}% of messages)")
        elif sample.get("bull_pct", 0) >= 60:
            rows.append(f"📣 StockTwits ${symbol} heavily bullish ({sample['bull_pct']}% of messages)")
    if unusual:
        top = max(unusual, key=lambda row: row["premium"])
        rows.append(
            f"💰 Unusual {top['type']} flow: {top['ticker']} {top['strike']:g} {top['expiry']} — ${top['premium']/1e6:.1f}M premium · {top['dte']}d"
        )
    return rows


def keep(section: str, previous: dict, builder):
    try:
        return builder()
    except Exception as exc:
        warn(section, exc)
        if section not in previous:
            raise
        return previous[section]


def _json_safe(value):
    """Recursively replace NaN/Infinity with None so json.dump emits valid JSON.

    Browsers reject raw NaN tokens (Python's json default); one NaN anywhere
    breaks the whole dashboard because boot() never runs.
    """
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def main() -> None:
    previous = load_previous()
    snapshot = dict(previous)
    snapshot["generated_at"] = datetime.now(NY).strftime("%Y-%m-%d %H:%M ET")

    tickers = {}
    for symbol in WHEEL:
        try:
            tickers[symbol] = wheel_ticker(symbol)
        except Exception as exc:
            warn(symbol, exc)
            if symbol in previous.get("tickers", {}):
                tickers[symbol] = previous["tickers"][symbol]
    if tickers:
        snapshot["tickers"] = tickers

    try:
        snapshot["vix"], snapshot["vix_last"] = series_payload("^VIX")
    except Exception as exc:
        warn("vix", exc)
    try:
        tnx, last = series_payload("^TNX")
        # Yahoo quotes the 10-year yield index in percent already.
        snapshot["tnx"], snapshot["tnx_last"] = tnx, last
    except Exception as exc:
        warn("tnx", exc)

    try:
        snapshot["putcall"], snapshot["putcall_reading"], snapshot["putcall_hist"] = put_call()
    except Exception as exc:
        warn("putcall", exc)
    try:
        snapshot["cot"], snapshot["cot_hist"] = cot_block()
    except Exception as exc:
        warn("cot", exc)
    try:
        snapshot["macro"] = macro_block()
    except Exception as exc:
        warn("macro", exc)
    try:
        snapshot["aaii"] = aaii_block()
    except Exception as exc:
        warn("aaii", exc)
    try:
        snapshot["stocktwits"] = {symbol: stocktwits(symbol) for symbol in ("SPY", "QQQ")}
    except Exception as exc:
        warn("stocktwits", exc)
    try:
        snapshot["scorecard"] = [score_row(*item) for item in SCORECARD]
    except Exception as exc:
        warn("scorecard", exc)
    try:
        snapshot["news"] = news_block()
    except Exception as exc:
        warn("news", exc)

    walls, unusual = {}, []
    for symbol in WHEEL:
        spot = snapshot.get("tickers", {}).get(symbol, {}).get("last", {}).get("close")
        if not spot:
            continue
        try:
            wall, prints = option_books(symbol, spot)
            if wall:
                walls[symbol] = wall
            unusual.extend(prints)
        except Exception as exc:
            warn(f"options {symbol}", exc)
    if walls:
        snapshot["walls"] = walls
    elif "walls" not in snapshot:
        snapshot["walls"] = {}
    unusual.sort(key=lambda row: row["premium"], reverse=True)
    snapshot["unusual"] = unusual[:12]
    snapshot["setups"] = setups(snapshot.get("scorecard", []), snapshot.get("stocktwits", {}), snapshot["unusual"])

    OUT.write_text(json.dumps(_json_safe(snapshot), indent=2) + "\n")
    print(f"wrote {OUT} at {snapshot['generated_at']}")
    print(f"unusual {len(snapshot['unusual'])} (45-75 DTE only)")


if __name__ == "__main__":
    main()
