import requests
from .config import BASE_URL

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SignalScanner/1.0"})

_INTERVALS = {
    "15m": ("15", 15 * 60 * 1000),
    "1h": ("60", 60 * 60 * 1000),
    "15": ("15", 15 * 60 * 1000),
    "60": ("60", 60 * 60 * 1000),
}


def get_klines(symbol: str, interval: str, limit: int = 250):
    """Fetch Bybit USDT linear perpetual candles, normalized for the strategy."""
    bybit_interval, duration_ms = _INTERVALS.get(interval, (interval, None))
    response = SESSION.get(
        f"{BASE_URL}/v5/market/kline",
        params={
            "category": "linear",
            "symbol": symbol.upper(),
            "interval": bybit_interval,
            "limit": limit,
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit API error {payload.get('retCode')}: {payload.get('retMsg', 'Unknown error')}"
        )

    raw = payload.get("result", {}).get("list", [])
    candles = []
    for row in reversed(raw):  # Bybit returns newest first; strategy expects oldest first.
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


def get_top_usdt_perpetual_symbols(limit: int = 50):
    """
    Return top linear USDT perpetual symbols ranked by 24h turnover.
    Instruments are checked for Trading + LinearPerpetual status first.
    """
    instruments = []
    cursor = None
    # Bybit instrument list is paginated; collect all currently listed instruments.
    for _ in range(20):
        params = {"category": "linear", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        response = SESSION.get(
            f"{BASE_URL}/v5/market/instruments-info",
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(
                f"Bybit instruments API error {payload.get('retCode')}: {payload.get('retMsg', 'Unknown error')}"
            )
        result = payload.get("result", {})
        instruments.extend(result.get("list", []))
        cursor = result.get("nextPageCursor")
        if not cursor:
            break

    eligible = {
        item.get("symbol")
        for item in instruments
        if item.get("status") == "Trading"
        and item.get("contractType") == "LinearPerpetual"
        and item.get("quoteCoin") == "USDT"
        and item.get("symbol", "").endswith("USDT")
    }
    if not eligible:
        raise RuntimeError("Bybit returned no active USDT linear perpetual instruments")

    response = SESSION.get(
        f"{BASE_URL}/v5/market/tickers",
        params={"category": "linear"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit tickers API error {payload.get('retCode')}: {payload.get('retMsg', 'Unknown error')}"
        )

    ranked = []
    for ticker in payload.get("result", {}).get("list", []):
        symbol = ticker.get("symbol", "")
        if symbol not in eligible:
            continue
        try:
            turnover = float(ticker.get("turnover24h", 0))
        except (TypeError, ValueError):
            continue
        if turnover > 0:
            ranked.append((symbol, turnover))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return [symbol for symbol, _ in ranked[:max(1, limit)]]
