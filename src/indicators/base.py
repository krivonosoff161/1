"""
Technical indicators for trading strategies
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class IndicatorResult:
    """Result container for indicator calculations"""

    name: str
    value: float
    signal: Optional[str] = None  # 'BUY', 'SELL', 'NEUTRAL'
    timestamp: Optional[str] = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseIndicator(ABC):
    """Base class for all technical indicators"""

    def __init__(self, period: int = 14):
        self.period = period
        self.name = self.__class__.__name__

    @abstractmethod
    def calculate(self, data: List[float]) -> IndicatorResult:
        """Calculate indicator value"""
        pass

    def validate_data(self, data: List[float]) -> bool:
        """Validate input data"""
        return len(data) >= self.period


class SimpleMovingAverage(BaseIndicator):
    """Simple Moving Average indicator"""

    def __init__(self, period: int = 20):
        super().__init__(period)

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 0.0)

        # Расчёт SMA: среднее арифметическое последних N значений
        # SMA = (P1 + P2 + ... + PN) / N
        sma_value = np.mean(data[-self.period :])

        # Генерация торгового сигнала на основе положения цены относительно SMA
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


class ExponentialMovingAverage(BaseIndicator):
    """Exponential Moving Average indicator"""

    def __init__(self, period: int = 20):
        super().__init__(period)
        self.alpha = 2.0 / (period + 1)

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 0.0)

        # Расчёт EMA: экспоненциальная скользящая средняя
        # EMA(t) = Price(t) * α + EMA(t-1) * (1 - α)
        # где α = 2 / (period + 1) - сглаживающий коэффициент
        ema = data[0]  # Инициализация первым значением
        for price in data[1:]:
            ema = (price * self.alpha) + (ema * (1 - self.alpha))

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


class RSI(BaseIndicator):
    """Relative Strength Index indicator"""

    def __init__(self, period: int = 14, overbought: float = 70, oversold: float = 30):
        super().__init__(period)
        self.overbought = overbought
        self.oversold = oversold

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 50.0)

        # Расчёт RSI (Relative Strength Index)
        # Шаг 1: Вычисляем изменения цены
        prices = np.array(data)
        deltas = np.diff(prices)  # Разница между соседними ценами

        # Шаг 2: Разделяем на прибыльные и убыточные движения
        gains = np.where(deltas > 0, deltas, 0)  # Только положительные изменения
        losses = np.where(deltas < 0, -deltas, 0)  # Только отрицательные (по модулю)

        # Шаг 3: Вычисляем средние значения за период
        # ✅ ИСПРАВЛЕНО: Используем экспоненциальное сглаживание Wilder вместо простого среднего
        # Стандарт RSI использует формулу Wilder: EMA = (prev_EMA * (period - 1) + current) / period
        if len(gains) >= self.period:
            # Первое значение - простое среднее за период
            avg_gain = np.mean(gains[-self.period :])
            avg_loss = np.mean(losses[-self.period :])
            
            # Если есть больше данных, применяем экспоненциальное сглаживание
            if len(gains) > self.period:
                # Для каждого нового значения применяем формулу Wilder
                for i in range(self.period, len(gains)):
                    avg_gain = (avg_gain * (self.period - 1) + gains[i]) / self.period
                    avg_loss = (avg_loss * (self.period - 1) + losses[i]) / self.period
        else:
            avg_gain = 0
            avg_loss = 0

        # Шаг 4: Вычисляем RSI по формуле
        # RSI = 100 - (100 / (1 + RS)), где RS = средний прирост / средний убыток
        if avg_loss == 0:
            rsi_value = 100.0  # Все движения вверх
        else:
            rs = avg_gain / avg_loss  # Relative Strength
            rsi_value = 100.0 - (100.0 / (1.0 + rs))

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


class ATR(BaseIndicator):
    """Average True Range indicator"""

    def __init__(self, period: int = 14):
        super().__init__(period)

    def calculate(
        self, high_data: List[float], low_data: List[float], close_data: List[float]
    ) -> IndicatorResult:
        if (
            len(high_data) < self.period
            or len(low_data) < self.period
            or len(close_data) < self.period
        ):
            return IndicatorResult(self.name, 0.0)

        # Расчёт ATR (Average True Range) - мера волатильности
        # True Range = max из трёх значений:
        #   1. High - Low (диапазон текущего бара)
        #   2. |High - Close_prev| (гэп вверх от предыдущего закрытия)
        #   3. |Low - Close_prev| (гэп вниз от предыдущего закрытия)
        true_ranges = []
        for i in range(1, len(close_data)):
            high_low = high_data[i] - low_data[i]
            high_close = abs(high_data[i] - close_data[i - 1])
            low_close = abs(low_data[i] - close_data[i - 1])
            true_range = max(high_low, high_close, low_close)
            true_ranges.append(true_range)

        # ATR = экспоненциальное среднее значение True Range за период
        # ✅ ИСПРАВЛЕНО: Используем экспоненциальное сглаживание Wilder вместо простого среднего
        # Стандарт ATR использует формулу Wilder: EMA = (prev_EMA * (period - 1) + current) / period
        if len(true_ranges) >= self.period:
            # Первое значение - простое среднее за период
            atr_value = np.mean(true_ranges[-self.period :])
            
            # Если есть больше данных, применяем экспоненциальное сглаживание
            if len(true_ranges) > self.period:
                # Для каждого нового значения применяем формулу Wilder
                for i in range(self.period, len(true_ranges)):
                    atr_value = (atr_value * (self.period - 1) + true_ranges[i]) / self.period
        else:
            atr_value = 0

        return IndicatorResult(
            name=f"ATR_{self.period}",
            value=atr_value,
            signal="NEUTRAL",
            metadata={"period": self.period},
        )


class BollingerBands(BaseIndicator):
    """Bollinger Bands indicator"""

    def __init__(self, period: int = 20, std_multiplier: float = 2.0):
        super().__init__(period)
        self.std_multiplier = std_multiplier

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 0.0)

        # Расчёт Bollinger Bands - полосы волатильности
        recent_data = data[-self.period :]

        # Средняя линия = SMA (Simple Moving Average)
        sma = np.mean(recent_data)

        # Стандартное отклонение - мера волатильности
        std = np.std(recent_data)

        # Верхняя полоса = SMA + (n * σ), где n - мультипликатор, σ - std
        upper_band = sma + (std * self.std_multiplier)

        # Нижняя полоса = SMA - (n * σ)
        lower_band = sma - (std * self.std_multiplier)

        current_price = data[-1]

        # Generate signal
        signal = "NEUTRAL"
        if current_price <= lower_band:
            signal = "BUY"
        elif current_price >= upper_band:
            signal = "SELL"

        return IndicatorResult(
            name=f"BB_{self.period}",
            value=sma,
            signal=signal,
            metadata={
                "period": self.period,
                "std_multiplier": self.std_multiplier,
                "upper_band": upper_band,
                "lower_band": lower_band,
                "current_price": current_price,
            },
        )


class MACD(BaseIndicator):
    """MACD indicator"""

    def __init__(
        self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
    ):
        super().__init__(slow_period)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        # ✅ ИСПРАВЛЕНО: Сохраняем историю MACD для правильного расчета signal line
        self.macd_history: List[float] = []

    def calculate(self, data: List[float]) -> IndicatorResult:
        if not self.validate_data(data):
            return IndicatorResult(self.name, 0.0)

        # Calculate EMAs
        ema_fast = self._calculate_ema(data, self.fast_period)
        ema_slow = self._calculate_ema(data, self.slow_period)

        # Calculate MACD line
        macd_line = ema_fast - ema_slow

        # ✅ ИСПРАВЛЕНО: Сохраняем историю MACD для правильного расчета signal line
        self.macd_history.append(macd_line)
        # Ограничиваем размер истории (нужно только для signal_period)
        if len(self.macd_history) > self.signal_period * 2:
            self.macd_history = self.macd_history[-self.signal_period * 2:]

        # ✅ ИСПРАВЛЕНО: Signal line - это EMA от истории MACD
        if len(self.macd_history) >= self.signal_period:
            # Используем последние signal_period значений для расчета EMA
            signal_value = self._calculate_ema(
                self.macd_history[-self.signal_period:], self.signal_period
            )
        else:
            # Если недостаточно данных, используем текущий MACD
            signal_value = macd_line

        # Generate trading signal
        signal = "NEUTRAL"
        if macd_line > signal_value:
            signal = "BUY"
        elif macd_line < signal_value:
            signal = "SELL"

        return IndicatorResult(
            name="MACD",
            value=macd_line,
            signal=signal,
            metadata={
                "fast_period": self.fast_period,
                "slow_period": self.slow_period,
                "signal_period": self.signal_period,
                "macd_line": macd_line,
                "signal_line": signal_value,
            },
        )

    def _calculate_ema(self, data: List[float], period: int) -> float:
        """
        Вспомогательный метод для расчёта EMA.

        Вычисляет экспоненциальную скользящую среднюю с заданным периодом.

        Args:
            data: Список цен
            period: Период для расчёта EMA

        Returns:
            float: Значение EMA
        """
        alpha = 2.0 / (period + 1)  # Сглаживающий коэффициент
        ema = data[0]
        for price in data[1:]:
            ema = (price * alpha) + (ema * (1 - alpha))
        return ema


class VolumeIndicator(BaseIndicator):
    """Volume-based indicator"""

    def __init__(self, period: int = 20, threshold_multiplier: float = 1.5):
        super().__init__(period)
        self.threshold_multiplier = threshold_multiplier

    def calculate(self, volume_data: List[float]) -> IndicatorResult:
        if not self.validate_data(volume_data):
            return IndicatorResult(self.name, 0.0)

        recent_volumes = volume_data[-self.period :]
        avg_volume = np.mean(recent_volumes)
        current_volume = volume_data[-1]

        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        # Generate signal
        signal = "NEUTRAL"
        if volume_ratio >= self.threshold_multiplier:
            signal = "BUY"  # High volume could indicate strong move

        return IndicatorResult(
            name=f"VOLUME_{self.period}",
            value=volume_ratio,
            signal=signal,
            metadata={
                "period": self.period,
                "threshold_multiplier": self.threshold_multiplier,
                "avg_volume": avg_volume,
                "current_volume": current_volume,
            },
        )


class IndicatorManager:
    """Manages multiple technical indicators"""

    def __init__(self):
        self.indicators = {}

    def add_indicator(self, name: str, indicator: BaseIndicator):
        """Add an indicator to the manager"""
        self.indicators[name] = indicator

    def calculate_all(self, market_data) -> dict:
        """Calculate all indicators for given market data"""
        results = {}

        closes = market_data.get_closes()
        highs = market_data.get_highs()
        lows = market_data.get_lows()
        volumes = market_data.get_volumes()

        for name, indicator in self.indicators.items():
            try:
                if isinstance(indicator, ATR):
                    result = indicator.calculate(highs, lows, closes)
                elif isinstance(indicator, VolumeIndicator):
                    result = indicator.calculate(volumes)
                else:
                    result = indicator.calculate(closes)

                results[name] = result
            except Exception as e:
                # Log error and continue
                results[name] = IndicatorResult(name, 0.0, "ERROR")

        return results

    def get_signals(self, market_data) -> List[str]:
        """Get all trading signals from indicators"""
        results = self.calculate_all(market_data)
        signals = []

        for name, result in results.items():
            if result.signal in ["BUY", "SELL"]:
                signals.append(f"{name}: {result.signal}")

        return signals
