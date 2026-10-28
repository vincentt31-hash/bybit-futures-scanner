"""Public Lighter REST market-data adapter. No order execution or account auth."""
from __future__ import annotations
import time
import requests
from .config import BASE_URL

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SHP-FuturesScanner-Lighter/1.0", "Accept": "application/json"})

def _get(path: str, params: dict | None = None):
    response = SESSION.get(f"{BASE_URL}{path}", params=params or {}, timeout=25)
    response.raise_for_status()
    payload = response.json()
    # Lighter public REST uses a body code field; API errors can still have HTTP 200.
    code = payload.get("code")
    if code not in (None, 200, "200"):
        raise RuntimeError(f"Lighter API error code={code}: {payload.get('message', payload.get('msg', 'unknown'))}")
    return payload

def _list_from(payload, *keys):
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    # Some responses nest their result object.
    result = payload.get("result")
    if isinstance(result, dict):
        for key in keys:
            value = result.get(key)
            if isinstance(value, list):
                return value
    return []

def _market_id(item):
    value = item.get("market_id", item.get("marketId", item.get("id")))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _market_name(item):
    return str(item.get("symbol") or item.get("ticker") or item.get("name") or item.get("market_name") or "").strip()

def get_markets():
    """Load Lighter market metadata. Lighter's listed markets are perpetuals;
    request the market list without the unsupported `filter=perp` parameter.
    """
    payload = _get("/orderBooks")
    markets = _list_from(payload, "order_books", "orderBooks", "list")
    if not markets:
        # tolerate alternate response key names, but do not add query filters
        markets = _list_from(payload, "order_book_details", "orderBookDetails")
    normalized = []
    for item in markets:
        if not isinstance(item, dict):
            continue
        mid = _market_id(item)
        name = _market_name(item)
        if mid is None or not name:
            continue
        status = str(item.get("status") or item.get("market_status") or "active").lower()
        if status in {"inactive", "closed", "delisted", "disabled"}:
            continue
        normalized.append({
            "market_id": mid,
            "symbol": name,
            "status": status,
            "raw": item,
        })
    by_id = {}
    for item in normalized:
        by_id.setdefault(item["market_id"], item)
    return list(by_id.values())

def _ticker_data():
    payload = _get("/exchangeStats")
    # Stats response is often an object keyed by market id or an array.
    stats = payload.get("stats", payload.get("exchange_stats", payload.get("result", payload)))
    if isinstance(stats, list):
        return {str(x.get("market_id", x.get("marketId", x.get("id", "")))): x for x in stats if isinstance(x, dict)}
    if isinstance(stats, dict):
        if isinstance(stats.get("markets"), list):
            return {str(x.get("market_id", x.get("marketId", x.get("id", "")))): x for x in stats["markets"] if isinstance(x, dict)}
        return stats
    return {}

def _number(item, *keys):
    for key in keys:
        try:
            value = float(item.get(key))
            if value > 0:
                return value
        except (TypeError, ValueError, AttributeError):
            pass
    return 0.0

def get_active_markets(limit: int = 50):
    markets = get_markets()
    if not markets:
        raise RuntimeError("Lighter returned no perpetual markets from orderBookDetails/orderBooks")
    stats = _ticker_data()
    ranked = []
    for market in markets:
        item = market["raw"]
        stat = stats.get(str(market["market_id"]), {}) if isinstance(stats, dict) else {}
        # Metadata may contain 24h volume. If not, retain market order as fallback.
        volume = _number(stat, "volume_24h", "volume24h", "quote_volume_24h", "turnover24h")
        if not volume:
            volume = _number(item, "volume_24h", "volume24h", "quote_volume_24h", "turnover24h")
        ranked.append((market, volume))
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return [m for m, _ in ranked[:max(1, int(limit))]]

def _resolve_market(symbol: str):
    normalized = str(symbol).strip().upper().replace("/", "").replace(".P", "")
    markets = get_markets()
    for market in markets:
        native = market["symbol"].upper().replace("/", "").replace("-PERP", "").replace("PERP", "")
        if native == normalized or market["symbol"].upper() == str(symbol).strip().upper():
            return market
        if str(market["market_id"]) == normalized:
            return market
    raise ValueError(f"Lighter market not found: {symbol}")

def get_klines(symbol: str, interval: str, limit: int = 250):
    market = _resolve_market(symbol)
    resolution_map = {
        "15m": "15m", "15": "15m", "1h": "1h", "60": "1h",
        "4h": "4h", "1d": "1d",
    }
    resolution = resolution_map.get(interval, interval)
    end = int(time.time())
    # API caps at 500 bars per request. A slightly generous time range is harmless;
    # count_back is retained for implementations that honor it.
    seconds = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(resolution, 60)
    start = end - seconds * (min(int(limit), 500) + 3)
    payload = _get("/candles", {
        "market_id": market["market_id"],
        "resolution": resolution,
        "start_timestamp": start,
        "end_timestamp": end,
        "count_back": min(int(limit), 500),
    })
    rows = _list_from(payload, "candles", "data", "list")
    candles = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            # Lighter candle `t` is milliseconds; parameters are Unix seconds.
            stamp = int(row.get("t", row.get("timestamp", row.get("start_timestamp", 0))))
            if stamp < 10_000_000_000:
                stamp *= 1000
            o = float(row.get("o", row.get("open")))
            h = float(row.get("h", row.get("high")))
            l = float(row.get("l", row.get("low")))
            c = float(row.get("c", row.get("close")))
            v = float(row.get("v", row.get("volume", 0)) or 0)
            candles.append({
                "open_time": stamp, "open": o, "high": h, "low": l,
                "close": c, "volume": v, "close_time": stamp + seconds * 1000 - 1,
            })
        except (TypeError, ValueError):
            continue
    candles.sort(key=lambda c: c["open_time"])
    return candles[-int(limit):]

def get_prices():
    markets = get_markets()
    stats = _ticker_data()
    prices = {}
    for market in markets:
        item = market["raw"]
        stat = stats.get(str(market["market_id"]), {}) if isinstance(stats, dict) else {}
        price = _number(stat, "last_trade_price", "last_price", "lastPrice", "mark_price", "markPrice")
        if not price:
            price = _number(item, "last_trade_price", "last_price", "lastPrice", "mark_price", "markPrice")
        if price:
            prices[market["symbol"]] = price
    return prices

def display_symbol(symbol: str):
    clean = str(symbol).strip().upper().replace("/", "").replace(".P", "")
    if clean.endswith("PERP"):
        clean = clean[:-4]
    return f"{clean}.P"
