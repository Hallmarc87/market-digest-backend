from fastapi import FastAPI
import requests
import os

app = FastAPI()

# Your Finnhub or Polygon API key is stored in Render as an environment variable
API_KEY = os.environ.get("FINNHUB_KEY")
BASE_URL = "https://finnhub.io/api/v1"

@app.get("/get_market_snapshot")
def get_market_snapshot(tickers: str):
    """
    Get current market snapshot for one or more tickers.
    Example: /get_market_snapshot?tickers=AAPL,MSFT
    """
    results = []
    for t in tickers.split(","):
        r = requests.get(f"{BASE_URL}/quote", params={"symbol": t, "token": API_KEY}).json()
        results.append({
            "ticker": t.upper(),
            "price": r.get("c"),          # current price
            "change_pct": r.get("dp"),    # % change today
            "volume": r.get("v"),
            "range_day": f"{r.get('l')}–{r.get('h')}",
            "range_52w": "N/A",           # Finnhub free tier doesn’t give this
            "market_cap": None,           # add with premium endpoint if desired
            "beta": None,                 # not available on free tier
            "notes": []
        })
    return {"as_of": "now", "tickers": results}

@app.get("/get_fundamentals")
def get_fundamentals(tickers: str):
    """
    Placeholder for fundamentals like P/E, EPS, dividend yield.
    You can fill in with Finnhub’s /stock/metric endpoint if you have access.
    """
    return {"tickers": [
        {"ticker": t.upper(), "pe_ttm": None, "div_yield_pct": None, "eps_ttm": None, "next_earnings": None}
        for t in tickers.split(",")
    ]}

@app.get("/get_news_brief")
def get_news_brief(tickers: str, lookback_hours: int = 48):
    """
    Get recent company news headlines.
    """
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    from_date = (now - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    news_items = []
    for t in tickers.split(","):
        r = requests.get(f"{BASE_URL}/company-news", params={
            "symbol": t, "from": from_date, "to": to_date, "token": API_KEY
        }).json()
        top = [{"headline": n.get("headline"),
                "source": n.get("source"),
                "time": str(n.get("datetime")),
                "url": n.get("url")} for n in r[:3]]
        news_items.append({"ticker": t.upper(), "items": top})

    return {"news": news_items}

