# Binance Futures Signal Scanner V1 — Backend MVP

This is the first backend milestone for the Android signal scanner.

## Included
- Binance USDⓈ-M public Kline data for the selected 8 symbols
- 1h trend filter and 15m breakout/volume setup
- Fixed risk budget and automatic estimated position sizing/leverage
- Entry, TP1/TP2/TP3 and SL calculation
- FastAPI endpoints
- Signal-only; **does not place orders**

## Important risk notes
- `risk_percent` is capped at 10% of the entered capital.
- The computed risk budget is a price-move estimate before fees, slippage, funding, and liquidation effects.
- Cross margin can expose account funds and depends on other open positions. This app cannot inspect the user's Binance account.
- Confidence score is a heuristic score, not a calibrated win probability.
- This MVP is not yet suitable for live trading decisions without backtesting, exchange precision/filters validation, and forward testing.

## Windows setup
1. Install Python 3.11+.
2. Extract this project.
3. Open Command Prompt in the project folder.
4. Create and activate a virtual environment:

   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   ```

5. Install dependencies:

   ```bat
   pip install -r requirements.txt
   ```

6. Start API:

   ```bat
   uvicorn app.main:app --reload
   ```

7. Open:
   - API status: http://127.0.0.1:8000/health
   - Interactive API docs: http://127.0.0.1:8000/docs
   - Default scanner: http://127.0.0.1:8000/scan

## Scan with custom settings
Use POST `/scan` with JSON:

```json
{
  "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
  "capital_usdt": 100,
  "risk_percent": 10,
  "max_leverage": 20,
  "min_confidence": 75
}
```

## Default watchlist
BTCUSDT, BNBUSDT, SOLUSDT, ETHUSDT, SUIUSDT, HBARUSDT, ADAUSDT, INJUSDT

## Next development milestones
1. Add Binance exchangeInfo precision/minQty/tickSize validation.
2. Add persistent database and signal lifecycle tracking.
3. Add backtesting with fee/slippage/funding assumptions.
4. Add Firebase push notifications.
5. Build Kotlin + Jetpack Compose Android client.
