import requests
from .config import BASE_URL, QUOTE_COIN

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SHP-FuturesScanner/1.0"})

_INTERVALS = {
    "15m": ("15", 15 * 60 * 1000),
    "1h": ("60", 60 * 60 * 1000),
    "15": ("15", 15 * 60 * 1000),
    "60": ("60", 60 * 60 * 1000),
}


def _get(path, params):
    response = SESSION.get(f"{BASE_URL}{path}", params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit API error {payload.get('retCode')}: {payload.get('retMsg', 'Unknown error')}"
        )
    return payload.get("result", {})


def get_klines(symbol: str, interval: str, limit: int = 250):
    """Fetch Bybit Global linear perpetual candles (native Bybit symbol)."""
    bybit_interval, duration_ms = _INTERVALS.get(interval, (interval, None))
    result = _get("/v5/market/kline", {
        "category": "linear",
        "symbol": symbol.upper().replace("/", "").replace(".P", ""),
        "interval": bybit_interval,
        "limit": limit,
    })
    candles = []
    for row in reversed(result.get("list", [])):
        open_time = int(row[0])
        candle_duration = duration_ms or 60 * 1000
        candles.append({
            "open_time": open_time,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": open_time + candle_duration - 1,
        })
    return candles


def get_active_usdc_perpetual_symbols(limit: int = 50):
    """Dynamically find active USDC LinearPerpetual instruments and rank by turnover."""
    instruments = []
    cursor = None
    for _ in range(20):
        params = {"category": "linear", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        result = _get("/v5/market/instruments-info", params)
        instruments.extend(result.get("list", []))
        cursor = result.get("nextPageCursor")
        if not cursor:
            break

    eligible = {
        item.get("symbol")
        for item in instruments
        if item.get("status") == "Trading"
        and item.get("contractType") == "LinearPerpetual"
        and item.get("quoteCoin") == QUOTE_COIN
        and item.get("symbol", "").endswith(QUOTE_COIN)
    }
    if not eligible:
        raise RuntimeError("Bybit Global returned no active USDC LinearPerpetual instruments")

    tickers = _get("/v5/market/tickers", {"category": "linear"}).get("list", [])
    ranked = []
    for ticker in tickers:
        symbol = ticker.get("symbol", "")
        if symbol not in eligible:
            continue
        try:
            turnover = float(ticker.get("turnover24h") or 0)
        except (TypeError, ValueError):
            continue
        if turnover > 0:
            ranked.append((symbol, turnover))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [symbol for symbol, _ in ranked[:max(1, int(limit))]]


def get_usdc_perpetual_prices():
    """Return current last prices for currently trading USDC LinearPerpetuals."""
    instruments = _get("/v5/market/instruments-info", {
        "category": "linear", "limit": 1000
    }).get("list", [])
    eligible = {
        item.get("symbol")
        for item in instruments
        if item.get("status") == "Trading"
        and item.get("contractType") == "LinearPerpetual"
        and item.get("quoteCoin") == QUOTE_COIN
        and item.get("symbol", "").endswith(QUOTE_COIN)
    }
    tickers = _get("/v5/market/tickers", {"category": "linear"}).get("list", [])
    prices = {}
    for ticker in tickers:
        symbol = ticker.get("symbol", "")
        if symbol not in eligible:
            continue
        try:
            price = float(ticker.get("lastPrice") or 0)
        except (TypeError, ValueError):
            continue
        if price > 0:
            prices[symbol] = price
    return prices


def tradingview_symbol(symbol: str):
    """TradingView-style display ticker, e.g. BTCUSDC.P."""
    return f"{symbol.upper().replace('/', '').replace('.P', '')}.P"
