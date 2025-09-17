from fastapi import FastAPI, HTTPException
import requests
import os
from datetime import datetime, timedelta

app = FastAPI()

API_KEY = os.environ.get("FINNHUB_KEY")
if not API_KEY:
    raise RuntimeError("Missing FINNHUB_KEY environment variable")

BASE_URL = "https://finnhub.io/api/v1"
HTTP_TIMEOUT = 10  # seconds


def http_get(path: str, params: dict):
    """Helper to call Finnhub with basic error handling."""
    try:
        params = {**params, "token": API_KEY}
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        # Bubble up a readable error for logs; return {} to keep service running
        print(f"Finnhub HTTP error on {path}: {e} | Body: {getattr(e.response,'text', '')}")
        return {}
    except Exception as e:
        print(f"Finnhub request error on {path}: {e}")
        return {}


def normalize_div_yield(raw):
    """
    Finnhub's 'dividendYieldIndicatedAnnual' can appear as fraction (0.012) or percent (1.2).
    Heuristic: if 0 < raw < 1, treat as fraction and convert to percent; else pass-through.
    """
    if raw is None:
        return None
    try:
        val = float(raw)
    except Exception:
        return None
    if 0 < val < 1:
        return round(val * 100.0, 4)
    return round(val, 4)


def get_metrics(symbol: str):
    """
    Fetch key metrics from /stock/metric.
    """
    data = http_get("/stock/metric", {"symbol": symbol, "metric": "all"})
    metric = (data or {}).get("metric", {}) or {}

    pe = metric.get("peBasicExclExtraTTM")
    if pe is None:
        pe = metric.get("peTTM")

    eps = metric.get("epsInclExtraItemsTTM")
    if eps is None:
        eps = metric.get("epsTTM")
    if eps is None:
        eps = metric.get("epsNormalizedAnnual")

    div_yield_pct = normalize_div_yield(metric.get("dividendYieldIndicatedAnnual"))

    return {
        "pe_ttm": float(pe) if isinstance(pe, (int, float, str)) and str(pe).replace('.', '', 1).lstrip('-').isdigit() else None,
        "eps_ttm": float(eps) if isinstance(eps, (int, float, str)) and str(eps).replace('.', '', 1).lstrip('-').isdigit() else None,
        "div_yield_pct": div_yield_pct
    }


def get_next_earnings(symbol: str):
    """
    Look ahead up to 365 days using /calendar/earnings and return the next earnings date (ISO).
    """
    today = datetime.utcnow().date()
    to_date = (today + timedelta(days=365)).isoformat()
    payload = http_get("/calendar/earnings", {"from": today.isoformat(), "to": to_date}) or {}
    cal = payload.get("earningsCalendar") or []

    future = [row for row in cal if (row.get("symbol") == symbol and row.get("date"))]
    future_dates = []
    for row in future:
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d").date()
            if d >= today:
                future_dates.append(d)
        except Exception:
            continue

    if not future_dates:
        return None
    return min(future_dates).isoformat()


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "market-digest-backend",
        "time": datetime.utcnow().isoformat()
    }


@app.get("/get_market_snapshot")
def get_market_snapshot(tickers: str, interval: str = "1d"):
    """
    Current snapshot for comma-separated tickers.
    Example: /get_market_snapshot?tickers=AAPL,MSFT
    """
    if not tickers:
        raise HTTPException(status_code=400, detail="Provide ?tickers=COMMA,SEP,SYMBOLS")

    results = []
    for t in tickers.split(","):
        sym = t.strip().upper()
        if not sym:
            continue
        q = http_get("/quote", {"symbol": sym}) or {}
        results.append({
            "ticker": sym,
            "price": q.get("c"),
            "change_pct": q.get("dp"),
            "volume": q.get("v"),
            "range_day": f"{q.get('l')}–{q.get('h')}" if q.get("l") is not None and q.get("h") is not None else None,
            "range_52w": None,     # You can populate via /stock/metric 52w high/low if you want later
            "market_cap": None,    # Available in metrics (e.g., 'marketCapitalization')
            "beta": None,          # Available in metrics (e.g., 'beta')
            "notes": []
        })
    return {"as_of": datetime.utcnow().isoformat(), "tickers": results}


@app.get("/get_fundamentals")
def get_fundamentals(tickers: str):
    """
    Real fundamentals using /stock/metric + next earnings from /calendar/earnings.
    Example: /get_fundamentals?tickers=AAPL,MSFT
    """
    if not tickers:
        raise HTTPException(status_code=400, detail="Provide ?tickers=COMMA,SEP,SYMBOLS")

    out = []
    for t in tickers.split(","):
        sym = t.strip().upper()
        if not sym:
            continue

        metrics = get_metrics(sym)
        next_earn = get_next_earnings(sym)

        out.append({
            "ticker": sym,
            "pe_ttm": metrics["pe_ttm"],
            "div_yield_pct": metrics["div_yield_pct"],
            "eps_ttm": metrics["eps_ttm"],
            "next_earnings": next_earn
        })

    return {"tickers": out}


@app.get("/get_news_brief")
def get_news_brief(tickers: str, lookback_hours: int = 48):
    """
    Recent headlines for comma-separated tickers.
    Example: /get_news_brief?tickers=AAPL,MSFT&lookback_hours=72
    """
    if not tickers:
        raise HTTPException(status_code=400, detail="Provide ?tickers=COMMA,SEP,SYMBOLS")

    now = datetime.utcnow()
    from_date = (now - timedelta(hours=max(1, min(lookback_hours, 24*7)))).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    news_items = []
    for t in tickers.split(","):
        sym = t.strip().upper()
        if not sym:
            continue
        r = http_get("/company-news", {"symbol": sym, "from": from_date, "to": to_date}) or []
        # Take top 3 headlines
        top = [{
            "headline": n.get("headline"),
            "source": n.get("source"),
            "time": str(n.get("datetime")),
            "url": n.get("url")
        } for n in (r or [])[:3]]
        news_items.append({"ticker": sym, "items": top})

    return {"news": news_items}
