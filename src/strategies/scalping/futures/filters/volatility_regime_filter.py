"""Фильтр волатильности рынка для Futures сигналов."""

from __future__ import annotations

from typing import Optional

from loguru import logger

from src.config import VolatilityFilterConfig
from src.models import MarketData


class VolatilityRegimeFilter:
    """Контроль диапазона и ATR для избежания экстремальных режимов рынка."""

    def __init__(self, config: VolatilityFilterConfig) -> None:
        self.config = config

    def is_signal_valid(self, symbol: str, market_data: MarketData) -> bool:
        if not self.config.enabled:
            return True

        candles = market_data.ohlcv_data
        if not candles or len(candles) < self.config.lookback_candles:
            logger.debug(
                f"⚠️ VolatilityRegimeFilter: недостаточно данных для {symbol}, допускаем сигнал"
            )
            return True

        lookback = candles[-self.config.lookback_candles :]
        closes = [c.close for c in lookback]
        highs = [c.high for c in lookback]
        lows = [c.low for c in lookback]

        last_close = closes[-1]
        if last_close == 0:
            return True

        price_range = max(highs) - min(lows)
        range_pct = (price_range / last_close) * 100

        atr = self._calculate_atr(lookback)
        atr_pct = (atr / last_close) * 100 if atr else 0.0

        if range_pct < self.config.min_range_percent:
            logger.debug(
                f"⛔ VolatilityRegimeFilter: {symbol} отклонён — диапазон {range_pct:.3f}% < {self.config.min_range_percent:.3f}%"
            )
            return False

        if range_pct > self.config.max_range_percent:
            logger.debug(
                f"⛔ VolatilityRegimeFilter: {symbol} отклонён — диапазон {range_pct:.3f}% > {self.config.max_range_percent:.3f}%"
            )
            return False

        if atr_pct < self.config.min_atr_percent:
            logger.debug(
                f"⛔ VolatilityRegimeFilter: {symbol} отклонён — ATR {atr_pct:.3f}% < {self.config.min_atr_percent:.3f}%"
            )
            return False

        if atr_pct > self.config.max_atr_percent:
            logger.debug(
                f"⛔ VolatilityRegimeFilter: {symbol} отклонён — ATR {atr_pct:.3f}% > {self.config.max_atr_percent:.3f}%"
            )
            return False

        logger.debug(
            f"✅ VolatilityRegimeFilter: {symbol} проходит (range={range_pct:.3f}%, atr={atr_pct:.3f}%)"
        )
        return True

    @staticmethod
    def _calculate_atr(candles) -> float:
        if len(candles) < 2:
            return 0.0

        trs = []
        prev_close = candles[0].close
        for candle in candles[1:]:
            high = candle.high
            low = candle.low
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            trs.append(tr)
            prev_close = candle.close

        return sum(trs) / len(trs) if trs else 0.0
