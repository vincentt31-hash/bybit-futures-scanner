# Scalping strategy update

This revision changes the signal strategy to 1-minute entries with a 5-minute trend filter and a 2R main take-profit target.

- TP1: 1R partial target
- TP2: 2R main target (requested RR 1:2)
- TP3: 3R extension
- SL: tight structure/ATR-based stop
- Uses only completed candles
- Keeps the existing scanner endpoint shape and legacy TP fields for compatibility

The upload included the scanner API/strategy/data adapter and indicators, but did not include notification delivery or signal-history persistence/UI modules. Those components were therefore not edited; their integration cannot be verified from the supplied files. This scanner remains signal-only and currently uses Bybit Indonesia spot market data, not authenticated Futures execution.
