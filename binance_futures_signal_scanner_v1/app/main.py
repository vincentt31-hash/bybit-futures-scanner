from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import (
    WATCHLIST, DEFAULT_CAPITAL, DEFAULT_RISK_PERCENT, MAX_LEVERAGE,
    MIN_CONFIDENCE, AUTO_TOP_VOLUME, TOP_PAIR_COUNT,
)
from .lighter import get_klines, get_active_markets, get_prices, display_symbol
from .strategy import analyze

app = FastAPI(
    title="SHP Lighter Futures Signal Scanner",
    version="1.0.0",
    description="Signal-only scanner using Lighter public market data. No order execution.",
)

class ScanRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: WATCHLIST)
    auto_top_volume: bool = AUTO_TOP_VOLUME
    top_pair_count: int = Field(default=TOP_PAIR_COUNT, ge=1, le=200)
    capital_usdt: float = Field(default=DEFAULT_CAPITAL, gt=0)
    risk_percent: float = Field(default=DEFAULT_RISK_PERCENT, gt=0, le=10)
    max_leverage: float = Field(default=MAX_LEVERAGE, ge=1, le=125)
    min_confidence: int = Field(default=MIN_CONFIDENCE, ge=0, le=100)

def _normalize(symbol):
    return str(symbol).strip().upper().replace("/", "").replace(".P", "")

def _market_lookup():
    return {_normalize(m["symbol"]): m for m in get_active_markets(10000)}

def get_selected_markets(request: ScanRequest):
    live = _market_lookup()
    if request.auto_top_volume:
        return get_active_markets(request.top_pair_count)
    selected = []
    for requested in request.symbols:
        key = _normalize(requested)
        market = live.get(key)
        if market is None:
            # Users may submit numeric Lighter market ids.
            market = next((m for m in live.values() if str(m["market_id"]) == key), None)
        if market and market not in selected:
            selected.append(market)
    return selected

@app.get("/")
def root():
    return {
        "name": "SHP Lighter Futures Signal Scanner",
        "version": "1.0.0",
        "mode": "signal-only",
        "exchange_data": "Lighter public REST market data",
        "market_identifier": "Lighter market_id",
        "auto_top_volume": AUTO_TOP_VOLUME,
        "top_pair_count": TOP_PAIR_COUNT,
        "watchlist": WATCHLIST,
        "symbol_display_format": "Exchange market symbol with .P display suffix",
        "risk_model": "Fixed risk budget estimate; excludes fees, slippage, funding and liquidation effects.",
    }

@app.get("/health")
def health():
    return {"status": "ok", "exchange": "lighter", "market_data": "public"}

@app.get("/watchlist")
def watchlist():
    markets = get_active_markets(TOP_PAIR_COUNT) if AUTO_TOP_VOLUME else get_selected_markets(ScanRequest(auto_top_volume=False))
    return {
        "symbols": [m["symbol"] for m in markets],
        "display_symbols": [display_symbol(m["symbol"]) for m in markets],
        "market_ids": {m["symbol"]: m["market_id"] for m in markets},
        "selection": "top_volume_if_available_else_market_order" if AUTO_TOP_VOLUME else "manual_live_validated",
        "exchange": "lighter",
    }

@app.get("/prices")
def prices():
    live_prices = get_prices()
    return {
        "exchange": "lighter",
        "prices": live_prices,
        "display_prices": {display_symbol(s): p for s, p in live_prices.items()},
    }

@app.get("/scan")
def scan_default():
    return scan(ScanRequest())

def scan_one(market, request, latest_prices):
    symbol = market["symbol"]
    market_id = market["market_id"]
    # Strategy continues to use its string symbol field; exchange market ID is
    # returned too so the client can resolve the actual Lighter market.
    strategy_symbol = symbol
    try:
        h1 = get_klines(str(market_id), "1h", 250)
        m15 = get_klines(str(market_id), "15m", 250)
        result = analyze(
            strategy_symbol, h1, m15,
            capital=request.capital_usdt,
            risk_percent=request.risk_percent,
            max_leverage=request.max_leverage,
            min_confidence=request.min_confidence,
        )
        result["market_id"] = market_id
        result["display_symbol"] = display_symbol(symbol)
        if symbol in latest_prices:
            result["last_price"] = latest_prices[symbol]
        return result
    except Exception as exc:
        return {
            "symbol": symbol,
            "market_id": market_id,
            "display_symbol": display_symbol(symbol),
            "status": "ERROR",
            "reason": str(exc),
            "last_price": latest_prices.get(symbol),
        }

@app.post("/scan")
def scan(request: ScanRequest):
    try:
        markets = get_selected_markets(request)
        live_prices = get_prices()
    except Exception as exc:
        return {
            "count": 0,
            "selection": "top_volume" if request.auto_top_volume else "manual_live_validated",
            "exchange": "lighter",
            "error": str(exc),
            "results": [],
        }
    results_by_id = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(scan_one, market, request, live_prices): market["market_id"]
            for market in markets
        }
        for future in as_completed(futures):
            market_id = futures[future]
            results_by_id[market_id] = future.result()
    results = [results_by_id[m["market_id"]] for m in markets]
    symbols = [m["symbol"] for m in markets]
    return {
        "count": len(results),
        "selection": "top_volume" if request.auto_top_volume else "manual_live_validated",
        "exchange": "lighter",
        "symbols": symbols,
        "display_symbols": [display_symbol(s) for s in symbols],
        "market_ids": {m["symbol"]: m["market_id"] for m in markets},
        "prices": {s: live_prices[s] for s in symbols if s in live_prices},
        "results": results,
    }
