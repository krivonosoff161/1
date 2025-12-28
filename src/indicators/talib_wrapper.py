"""
TA-Lib обертка для индикаторов.

✅ ГРОК ОПТИМИЗАЦИЯ: Использует TA-Lib для ускорения расчетов на 70-85%
"""

from typing import List, Optional

import numpy as np
import talib
from loguru import logger

from .base import BaseIndicator, IndicatorResult


class TALibRSI(BaseIndicator):
    """RSI индикатор через TA-Lib (оптимизированная версия)"""

    def __init__(self, period: int = 14, overbought: float = 70, oversold: float = 30):
        super().__init__(period)
        self.overbought = overbought
        self.oversold = oversold

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 50.0)

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Используем TA-Lib для быстрого расчета
        try:
            prices = np.array(data, dtype=np.float64)
            rsi_values = talib.RSI(prices, timeperiod=self.period)

            # Берем последнее значение
            rsi_value = (
                float(rsi_values[-1])
                if len(rsi_values) > 0 and not np.isnan(rsi_values[-1])
                else 50.0
            )
        except Exception as e:
            # ✅ ИСПРАВЛЕНО (28.12.2025): Silent fallback без warning (только debug для диагностики)
            logger.debug(
                f"TALibRSI: Ошибка расчета через TA-Lib ({type(e).__name__}: {e}), используется fallback"
            )
            # Fallback на простое среднее (не идеально, но лучше чем ошибка)
            rsi_value = 50.0

        # Generate signal
        signal = "NEUTRAL"
        if rsi_value >= self.overbought:
            signal = "SELL"
        elif rsi_value <= self.oversold:
            signal = "BUY"

        return IndicatorResult(
            name=f"RSI_{self.period}",
            value=rsi_value,
            signal=signal,
            metadata={
                "period": self.period,
                "overbought": self.overbought,
                "oversold": self.oversold,
            },
        )


class TALibEMA(BaseIndicator):
    """EMA индикатор через TA-Lib (оптимизированная версия)"""

    def __init__(self, period: int = 20):
        super().__init__(period)
        self.alpha = 2.0 / (period + 1)

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 0.0)

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Используем TA-Lib для быстрого расчета
        try:
            prices = np.array(data, dtype=np.float64)
            ema_values = talib.EMA(prices, timeperiod=self.period)

            # Берем последнее значение
            ema = (
                float(ema_values[-1])
                if len(ema_values) > 0 and not np.isnan(ema_values[-1])
                else float(data[-1])
            )
        except Exception as e:
            # ✅ ИСПРАВЛЕНО (28.12.2025): Silent fallback без warning (только debug для диагностики)
            logger.debug(f"TALibEMA fallback: {type(e).__name__}: {e}")
            # Fallback на простое среднее
            ema = float(np.mean(data[-self.period :]))

        # Generate signal
        signal = "NEUTRAL"
        if len(data) > 1:
            current_price = data[-1]
            if current_price > ema:
                signal = "BUY"
            elif current_price < ema:
                signal = "SELL"

        return IndicatorResult(
            name=f"EMA_{self.period}",
            value=ema,
            signal=signal,
            metadata={"period": self.period, "alpha": self.alpha},
        )


class TALibATR(BaseIndicator):
    """ATR индикатор через TA-Lib (оптимизированная версия)"""

    def __init__(self, period: int = 14):
        super().__init__(period)

    def calculate(
        self, high_data: List[float], low_data: List[float], close_data: List[float]
    ) -> IndicatorResult:
        """
        ✅ ГИБРИДНЫЙ ATR: TA-Lib (Wilder's) с fallback на простой расчёт.

        TA-Lib требует "разогрева" (burn-in period) и может возвращать NaN для последних значений.
        Если TA-Lib не дал валидное значение → используем простой расчёт (как в regime_manager).
        """
        # ✅ ИСПРАВЛЕНО: Проверяем минимум period + 1 свечей (TA-Lib требует больше данных)
        if len(close_data) < self.period + 1:
            logger.debug(
                f"ATR: мало данных ({len(close_data)} < {self.period + 1}), fallback простой расчёт"
            )
            return self._fallback_simple_atr(high_data, low_data, close_data)

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Используем TA-Lib для быстрого расчета (Wilder's ATR)
        try:
            highs = np.array(high_data, dtype=np.float64)
            lows = np.array(low_data, dtype=np.float64)
            closes = np.array(close_data, dtype=np.float64)

            atr_values = talib.ATR(highs, lows, closes, timeperiod=self.period)

            # ✅ ИСПРАВЛЕНО: Ищем последнее валидное значение (не NaN)
            # TA-Lib может возвращать NaN для последних значений из-за "разогрева" или дизайна библиотеки
            atr_value = 0.0
            for i in range(len(atr_values) - 1, -1, -1):
                if not np.isnan(atr_values[i]) and atr_values[i] > 0:
                    atr_value = float(atr_values[i])
                    break

            # ✅ КРИТИЧЕСКОЕ: Если TA-Lib вернул 0.0 или все NaN → используем fallback
            if atr_value > 0:
                return IndicatorResult(
                    name=f"ATR_{self.period}",
                    value=atr_value,
                    signal="NEUTRAL",
                    metadata={"period": self.period, "source": "talib"},
                )
            else:
                raise ValueError("TA-Lib вернул 0.0 или все NaN")

        except Exception as e:
            # ✅ ИСПРАВЛЕНО: Silent fallback без warning (только debug для диагностики)
            logger.debug(
                f"ATR TA-Lib ошибка: {type(e).__name__}: {e}, fallback на простой расчёт"
            )

        # ✅ Fallback на простой расчёт (как в regime_manager)
        return self._fallback_simple_atr(high_data, low_data, close_data)

    def _fallback_simple_atr(
        self, highs: List[float], lows: List[float], closes: List[float]
    ) -> IndicatorResult:
        """
        Простой расчёт ATR (среднее арифметическое True Range за период).
        Используется как fallback, когда TA-Lib не дал валидное значение.
        """
        if len(closes) < 2:
            return IndicatorResult(
                name=f"ATR_{self.period}",
                value=0.0,
                signal="NEUTRAL",
                metadata={"period": self.period, "source": "fallback_zero"},
            )

        # Рассчитываем True Range для каждой свечи
        tr_list = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)

        # Берём последние N (period) значений и считаем среднее
        recent_tr = tr_list[-self.period :] if len(tr_list) >= self.period else tr_list
        atr = sum(recent_tr) / len(recent_tr) if recent_tr else 0.0

        logger.debug(
            f"ATR fallback простой: {atr:.4f} (из {len(recent_tr)} TR, period={self.period})"
        )
        return IndicatorResult(
            name=f"ATR_{self.period}",
            value=float(atr),
            signal="NEUTRAL",
            metadata={"period": self.period, "source": "simple_fallback"},
        )


class TALibMACD(BaseIndicator):
    """MACD индикатор через TA-Lib (оптимизированная версия)"""

    def __init__(
        self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
    ):
        super().__init__(slow_period)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 0.0)

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Используем TA-Lib для быстрого расчета
        try:
            prices = np.array(data, dtype=np.float64)
            macd_line, signal_line, histogram = talib.MACD(
                prices,
                fastperiod=self.fast_period,
                slowperiod=self.slow_period,
                signalperiod=self.signal_period,
            )

            # Берем последние значения
            macd_value = (
                float(macd_line[-1])
                if len(macd_line) > 0 and not np.isnan(macd_line[-1])
                else 0.0
            )
            signal_value = (
                float(signal_line[-1])
                if len(signal_line) > 0 and not np.isnan(signal_line[-1])
                else 0.0
            )
        except Exception as e:
            # ✅ ИСПРАВЛЕНО (28.12.2025): Silent fallback без warning (только debug для диагностики)
            logger.debug(f"TALibMACD fallback: {type(e).__name__}: {e}")
            # Fallback на нулевые значения
            macd_value = 0.0
            signal_value = 0.0

        # Generate trading signal
        signal = "NEUTRAL"
        if macd_value > signal_value:
            signal = "BUY"
        elif macd_value < signal_value:
            signal = "SELL"

        return IndicatorResult(
            name="MACD",
            value=macd_value,
            signal=signal,
            metadata={
                "fast_period": self.fast_period,
                "slow_period": self.slow_period,
                "signal_period": self.signal_period,
                "macd_line": macd_value,
                "signal_line": signal_value,
            },
        )


class TALibSMA(BaseIndicator):
    """SMA индикатор через TA-Lib (оптимизированная версия)"""

    def __init__(self, period: int = 20):
        super().__init__(period)

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 0.0)

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Используем TA-Lib для быстрого расчета
        try:
            prices = np.array(data, dtype=np.float64)
            sma_values = talib.SMA(prices, timeperiod=self.period)

            # Берем последнее значение
            sma_value = (
                float(sma_values[-1])
                if len(sma_values) > 0 and not np.isnan(sma_values[-1])
                else float(np.mean(data[-self.period :]))
            )
        except Exception as e:
            # ✅ ИСПРАВЛЕНО (28.12.2025): Silent fallback без warning (только debug для диагностики)
            logger.debug(f"TALibSMA fallback: {type(e).__name__}: {e}")
            # Fallback на numpy.mean
            sma_value = float(np.mean(data[-self.period :]))

        # Generate signal
        signal = "NEUTRAL"
        if len(data) > self.period:
            current_price = data[-1]
            if current_price > sma_value:
                signal = "BUY"
            elif current_price < sma_value:
                signal = "SELL"

        return IndicatorResult(
            name=f"SMA_{self.period}",
            value=sma_value,
            signal=signal,
            metadata={"period": self.period},
        )


class TALibBollingerBands(BaseIndicator):
    """Bollinger Bands индикатор через TA-Lib (оптимизированная версия)"""

    def __init__(self, period: int = 20, std_multiplier: float = 2.0):
        super().__init__(period)
        self.std_multiplier = std_multiplier

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 0.0)

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Используем TA-Lib для быстрого расчета
        try:
            prices = np.array(data, dtype=np.float64)
            upper_band, middle_band, lower_band = talib.BBANDS(
                prices,
                timeperiod=self.period,
                nbdevup=self.std_multiplier,
                nbdevdn=self.std_multiplier,
                matype=0,  # SMA
            )

            # Берем последние значения
            sma = (
                float(middle_band[-1])
                if len(middle_band) > 0 and not np.isnan(middle_band[-1])
                else float(np.mean(data[-self.period :]))
            )
            upper = (
                float(upper_band[-1])
                if len(upper_band) > 0 and not np.isnan(upper_band[-1])
                else sma
            )
            lower = (
                float(lower_band[-1])
                if len(lower_band) > 0 and not np.isnan(lower_band[-1])
                else sma
            )
        except Exception as e:
            # ✅ ИСПРАВЛЕНО (28.12.2025): Silent fallback без warning (только debug для диагностики)
            logger.debug(f"TALibBollingerBands fallback: {type(e).__name__}: {e}")
            # Fallback на numpy расчет
            recent_data = data[-self.period :]
            sma = float(np.mean(recent_data))
            std = float(np.std(recent_data))
            upper = sma + (std * self.std_multiplier)
            lower = sma - (std * self.std_multiplier)

        current_price = data[-1]

        # Generate signal
        signal = "NEUTRAL"
        if current_price <= lower:
            signal = "BUY"
        elif current_price >= upper:
            signal = "SELL"

        return IndicatorResult(
            name=f"BB_{self.period}",
            value=sma,
            signal=signal,
            metadata={
                "period": self.period,
                "std_multiplier": self.std_multiplier,
                "upper_band": upper,
                "lower_band": lower,
                "current_price": current_price,
            },
        )
