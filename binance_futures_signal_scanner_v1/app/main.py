from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import (
    WATCHLIST, DEFAULT_CAPITAL, DEFAULT_RISK_PERCENT, MAX_LEVERAGE,
    MIN_CONFIDENCE, AUTO_TOP_VOLUME, TOP_PAIR_COUNT, QUOTE_COIN,
)
from .bybit import (
    get_klines, get_active_usdc_perpetual_symbols,
    get_usdc_perpetual_prices, tradingview_symbol,
)
from .strategy import analyze

app = FastAPI(
    title="Bybit Indonesia Spot USDT Signal Scanner",
    version="0.4.0",
    description="Signal-only scanner for active Bybit Indonesia USDT spot pairs. No order execution.",
)


class ScanRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: WATCHLIST)
    auto_top_volume: bool = AUTO_TOP_VOLUME
    top_pair_count: int = Field(default=TOP_PAIR_COUNT, ge=1, le=200)
    capital_usdt: float = Field(default=DEFAULT_CAPITAL, gt=0)
    risk_percent: float = Field(default=DEFAULT_RISK_PERCENT, gt=0, le=10)
    max_leverage: float = Field(default=MAX_LEVERAGE, ge=1, le=125)
    min_confidence: int = Field(default=MIN_CONFIDENCE, ge=0, le=100)


def _normalize_symbol(symbol):
    return symbol.strip().upper().replace("/", "").replace(".P", "")


def get_active_symbols(request: ScanRequest):
    if request.auto_top_volume:
        return get_active_usdc_perpetual_symbols(request.top_pair_count)
    # Manual list is intersected with live instrument metadata to exclude spot,
    # expired contracts, non-USDC instruments, and inactive contracts.
    live = set(get_active_usdc_perpetual_symbols(10000))
    return [s for s in (_normalize_symbol(x) for x in request.symbols) if s in live]


@app.get("/")
def root():
    return {
        "name": "Bybit Indonesia Spot USDT Signal Scanner",
        "version": "0.4.0",
        "mode": "signal-only",
        "exchange_data": "Bybit Indonesia V5 spot",
        "quote_coin": QUOTE_COIN,
        "auto_top_volume": AUTO_TOP_VOLUME,
        "top_pair_count": TOP_PAIR_COUNT,
        "watchlist": WATCHLIST,
        "symbol_display_format": "Scanner display with .P suffix (e.g. BTCUSDT.P); spot-based simulation",
        "risk_model": "Fixed risk budget before fees; cross-margin account risk can differ.",
    }


@app.get("/health")
def health():
    return {"status": "ok", "exchange": "bybit-indonesia-spot", "quote_coin": QUOTE_COIN}


@app.get("/watchlist")
def watchlist():
    symbols = get_active_usdc_perpetual_symbols(TOP_PAIR_COUNT) if AUTO_TOP_VOLUME else get_active_symbols(
        ScanRequest(auto_top_volume=False)
    )
    return {
        "symbols": symbols,
        "display_symbols": [tradingview_symbol(s) for s in symbols],
        "selection": "top_24h_usdt_turnover" if AUTO_TOP_VOLUME else "manual_live_validated",
        "quote_coin": QUOTE_COIN,
    }


@app.get("/prices")
def prices():
    live_prices = get_usdc_perpetual_prices()
    return {
        "quote_coin": QUOTE_COIN,
        "prices": live_prices,
        "display_prices": {tradingview_symbol(s): p for s, p in live_prices.items()},
    }


@app.get("/scan")
def scan_default():
    return scan(ScanRequest())


def scan_one(symbol, request, latest_prices):
    try:
        h1 = get_klines(symbol, "1h", 250)
        m15 = get_klines(symbol, "15m", 250)
        result = analyze(
            symbol, h1, m15,
            capital=request.capital_usdt,
            risk_percent=request.risk_percent,
            max_leverage=request.max_leverage,
            min_confidence=request.min_confidence,
        )
        # Market ticker is fresher than candle close; include it even for NO_SIGNAL.
        if symbol in latest_prices:
            result["last_price"] = latest_prices[symbol]
        result["display_symbol"] = tradingview_symbol(symbol)
        return result
    except Exception as exc:
        return {
            "symbol": symbol,
            "display_symbol": tradingview_symbol(symbol),
            "status": "ERROR",
            "reason": str(exc),
            "last_price": latest_prices.get(symbol),
        }


@app.post("/scan")
def scan(request: ScanRequest):
    try:
        symbols = get_active_symbols(request)
        live_prices = get_usdc_perpetual_prices()
    except Exception as exc:
        return {
            "count": 0,
            "selection": "top_24h_usdt_turnover" if request.auto_top_volume else "manual_live_validated",
            "quote_coin": QUOTE_COIN,
            "error": str(exc),
            "results": [],
        }

    results_by_symbol = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(scan_one, symbol, request, live_prices): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            results_by_symbol[symbol] = future.result()

    results = [results_by_symbol[symbol] for symbol in symbols]
    return {
        "count": len(results),
        "selection": "top_24h_usdt_turnover" if request.auto_top_volume else "manual_live_validated",
        "quote_coin": QUOTE_COIN,
        "symbols": symbols,
        "display_symbols": [tradingview_symbol(s) for s in symbols],
        "prices": {s: live_prices[s] for s in symbols if s in live_prices},
        "results": results,
    }
