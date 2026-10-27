from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import (
    WATCHLIST,
    DEFAULT_CAPITAL,
    DEFAULT_RISK_PERCENT,
    MAX_LEVERAGE,
    MIN_CONFIDENCE,
    AUTO_TOP_VOLUME,
    TOP_PAIR_COUNT,
)
from .bybit import get_klines, get_top_usdt_perpetual_symbols
from .strategy import analyze

app = FastAPI(
    title="USDT Futures Signal Scanner (Bybit data)",
    version="0.3.0",
    description="Signal-only scanner using Bybit linear USDT perpetual market data; no order execution.",
)


class ScanRequest(BaseModel):
    # Kept for backward compatibility with the existing Android app.
    symbols: list[str] = Field(default_factory=lambda: WATCHLIST)
    auto_top_volume: bool = AUTO_TOP_VOLUME
    top_pair_count: int = Field(default=TOP_PAIR_COUNT, ge=1, le=200)
    capital_usdt: float = Field(default=DEFAULT_CAPITAL, gt=0)
    risk_percent: float = Field(default=DEFAULT_RISK_PERCENT, gt=0, le=10)
    max_leverage: float = Field(default=MAX_LEVERAGE, ge=1, le=125)
    min_confidence: int = Field(default=MIN_CONFIDENCE, ge=0, le=100)


def get_active_symbols(request: ScanRequest):
    if request.auto_top_volume:
        return get_top_usdt_perpetual_symbols(request.top_pair_count)
    return [s.strip().upper().replace("/", "") for s in request.symbols if s.strip()]


@app.get("/")
def root():
    return {
        "name": "USDT Futures Signal Scanner (Bybit data)",
        "version": "0.3.0",
        "mode": "signal-only",
        "exchange_data": "Bybit linear USDT perpetual",
        "auto_top_volume": AUTO_TOP_VOLUME,
        "top_pair_count": TOP_PAIR_COUNT,
        "watchlist": WATCHLIST,
        "risk_model": "Fixed risk budget before fees; cross-margin account risk can differ.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/watchlist")
def watchlist():
    try:
        symbols = get_top_usdt_perpetual_symbols(TOP_PAIR_COUNT) if AUTO_TOP_VOLUME else WATCHLIST
        return {"symbols": symbols, "selection": "top_24h_turnover" if AUTO_TOP_VOLUME else "manual"}
    except Exception as exc:
        # Give caller a clear error; don't silently pretend static symbols are dynamic.
        return {"symbols": WATCHLIST, "selection": "fallback_manual", "warning": str(exc)}


@app.get("/scan")
def scan_default():
    return scan(ScanRequest())


def scan_one(symbol, request):
    try:
        h1 = get_klines(symbol, "1h", 250)
        m15 = get_klines(symbol, "15m", 250)
        return analyze(
            symbol,
            h1,
            m15,
            capital=request.capital_usdt,
            risk_percent=request.risk_percent,
            max_leverage=request.max_leverage,
            min_confidence=request.min_confidence,
        )
    except Exception as exc:
        return {"symbol": symbol, "status": "ERROR", "reason": str(exc)}


@app.post("/scan")
def scan(request: ScanRequest):
    try:
        symbols = get_active_symbols(request)
    except Exception as exc:
        return {"count": 0, "selection": "top_24h_turnover", "error": str(exc), "results": []}

    # 8 workers keep 100 candle requests for 50 pairs from running serially,
    # while avoiding an unnecessarily large burst of requests.
    results_by_symbol = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(scan_one, symbol, request): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            results_by_symbol[symbol] = future.result()

    # Preserve the ranked order from the volume list in the response.
    results = [results_by_symbol[symbol] for symbol in symbols]
    return {
        "count": len(results),
        "selection": "top_24h_turnover" if request.auto_top_volume else "manual",
        "symbols": symbols,
        "results": results,
    }
