# Cursor Report — Testing & Next Fixes (06.01.2026)

## What We Ran
- Backtest (mock data) via `python tests/test_backtest_simple.py --test simple`
- Adaptive params integration via `python test_adaptive_integration.py`

## Results
- Backtest: 914 trades, Win Rate 23.1%, Profit Factor 1.05, Total PnL 0.6499 (mock candles)
- Adaptive params test: ✅ passed — adaptive TP/SL scale correctly with balance

## Diagnosis
- Signal quality still poor: too many weak/false signals in ranging/choppy regimes.
- Filters in code need tightening beyond current config thresholds.

## Planned Code Fixes (apply in `src/strategies/scalping/futures/signal_generator.py`)
1) Require multi-indicator confirmation in `_detect_impulse_signals()`:
   ```python
   score = 0
   if macd_crossover:  # MACD line crosses signal
       score += 3
   if rsi_overbought or rsi_oversold:
       score += 2
   if bb_breakout:
       score += 1
   if ema_crossover:
       score += 1

   if score < 4:
       continue  # need at least two confirmations
   ```

2) Add volume filter inside `_detect_impulse_signals()`:
   ```python
   vol_cur = candles[-1].volume
   vol_sma20 = sum(c.volume for c in candles[-20:]) / 20
   if vol_cur < vol_sma20 * 1.1:
       continue  # block low-volume noise
   ```

3) (Optional) Raise ADX gate before adding impulse signals:
   ```python
   if adx_value is None or adx_value < adx_min_required:
       continue
   # adx_min_required: trending 20, ranging 30, choppy 40
   ```

## Context Files
- Backtest engine: `tests/backtesting/backtest_engine.py`
- Simple runner: `tests/test_backtest_simple.py`
- Adaptive params test: `test_adaptive_integration.py`
- Final report: `docs/ФИНАЛЬНЫЙ_ОТЧЕТ_ПРОБЛЕМЫ_И_РЕШЕНИЯ.md`

## Next Steps
- Implement the three code changes above.
- Re-run backtest and record metrics.
