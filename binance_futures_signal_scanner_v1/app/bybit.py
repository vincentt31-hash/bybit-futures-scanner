"""Bybit Indonesia V5 spot market-data adapter for SHP scanner.
Uses spot prices as reference data; any LONG/SHORT futures-style signal is simulated.
No order execution or account authentication.
"""
from __future__ import annotations
import requests
from .config import BASE_URL, QUOTE_COIN

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SHP-SpotScanner/1.0", "Accept": "application/json"})

_INTERVALS = {
    "15m": ("15", 15 * 60 * 1000),
    "1h": ("60", 60 * 60 * 1000),
    "15": ("15", 15 * 60 * 1000),
    "60": ("60", 60 * 60 * 1000),
    "4h": ("240", 4 * 60 * 60 * 1000),
    "1d": ("D", 24 * 60 * 60 * 1000),
}


def _get(path: str, params: dict):
    response = SESSION.get(f"{BASE_URL.rstrip('/')}{path}", params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit Indonesia API error {payload.get('retCode')}: "
            f"{payload.get('retMsg', 'Unknown error')}"
        )
    return payload.get("result", {})


def get_klines(symbol: str, interval: str, limit: int = 250):
    """Fetch Bybit Indonesia spot candles; return oldest-to-newest rows."""
    bybit_interval, duration_ms = _INTERVALS.get(interval, (interval, 60 * 1000))
    result = _get("/v5/market/kline", {
        "category": "spot",
        "symbol": symbol.upper().replace("/", "").replace(".P", ""),
        "interval": bybit_interval,
        "limit": min(max(int(limit), 1), 1000),
    })
    candles = []
    for row in reversed(result.get("list", [])):
        try:
            open_time = int(row[0])
            candles.append({
                "open_time": open_time,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time": open_time + duration_ms - 1,
            })
        except (IndexError, TypeError, ValueError):
            continue
    return candles


def _spot_symbols():
    """Fetch all available active spot instruments quoted in USDT, paging as needed."""
    instruments = []
    cursor = None
    for _ in range(20):
        params = {"category": "spot", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        result = _get("/v5/market/instruments-info", params)
        instruments.extend(result.get("list", []))
        cursor = result.get("nextPageCursor")
        if not cursor:
            break
    return {
        item.get("symbol")
        for item in instruments
        if item.get("status") == "Trading"
        and item.get("quoteCoin") == QUOTE_COIN
        and item.get("symbol", "").endswith(QUOTE_COIN)
    }


def get_active_usdc_perpetual_symbols(limit: int = 50):
    """Compatibility-named function: return top active Bybit Indonesia USDT spot pairs.
    Ranking uses 24h quote turnover (USDT), not base-coin volume.
    """
    eligible = _spot_symbols()
    if not eligible:
        raise RuntimeError("Bybit Indonesia returned no active USDT spot instruments")

    tickers = _get("/v5/market/tickers", {"category": "spot"}).get("list", [])
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
    """Compatibility-named function: current prices for active USDT spot pairs."""
    eligible = _spot_symbols()
    tickers = _get("/v5/market/tickers", {"category": "spot"}).get("list", [])
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
    """Display as .P for compatibility with existing futures-style scanner UI."""
    return f"{symbol.upper().replace('/', '').replace('.P', '')}.P"
