"""
Fast ADX для Futures торговли.

Ускоренная версия ADX индикатора для быстрой реакции
на изменение тренда на коротких таймфреймах (1m, 5m).
"""

from collections import deque
from typing import Any, Deque, Dict

from loguru import logger


class FastADX:
    """
    Быстрый ADX индикатор для Futures.

    Использует короткий период (9 вместо 14) для быстрой реакции:
    - Быстрее определяет начало тренда
    - Подходит для скальпинга на 1m, 5m
    - Меньше ложных сигналов при боковом рынке

    Attributes:
        period: Период для расчета (обычно 9)
        threshold: Порог силы тренда (обычно 20)
        di_plus_history: История +DI
        di_minus_history: История -DI
        adx_history: История ADX
    """

    def __init__(self, period: int = 9, threshold: float = 20.0):
        """
        Инициализация Fast ADX.

        Args:
            period: Период для расчета (по умолчанию 9)
            threshold: Порог силы тренда (по умолчанию 20)
        """
        self.period = period
        self.threshold = threshold

        self.di_plus_history: Deque[float] = deque(maxlen=period)
        self.di_minus_history: Deque[float] = deque(maxlen=period)
        self.adx_history: Deque[float] = deque(maxlen=period)

        self.current_high = 0.0
        self.current_low = 0.0
        self.current_close = 0.0
        self.prev_high = 0.0
        self.prev_low = 0.0
        self.prev_close = 0.0

        logger.info(f"FastADX инициализирован: period={period}, threshold={threshold}")

    def update(self, high: float, low: float, close: float):
        """
        Обновление индикатора новыми данными свечи.

        Args:
            high: Высшая цена свечи
            low: Низшая цена свечи
            close: Цена закрытия свечи
        """
        # Сохранение предыдущих значений
        self.prev_high = self.current_high
        self.prev_low = self.current_low
        self.prev_close = self.current_close

        # Обновление текущих значений
        self.current_high = high
        self.current_low = low
        self.current_close = close

        # Расчет +DI и -DI
        if self.prev_high == 0:
            return  # Недостаточно данных

        plus_dm = max(self.current_high - self.prev_high, 0)
        minus_dm = max(self.prev_low - self.current_low, 0)

        tr = max(
            self.current_high - self.current_low,
            abs(self.current_high - self.prev_close),
            abs(self.current_low - self.prev_close),
        )

        if tr > 0:
            di_plus = 100 * (plus_dm / tr)
            di_minus = 100 * (minus_dm / tr)
        else:
            di_plus = 0.0
            di_minus = 0.0

        self.di_plus_history.append(di_plus)
        self.di_minus_history.append(di_minus)

        # Расчет ADX
        if len(self.di_plus_history) < self.period:
            return  # Недостаточно данных

        adx = self._calculate_adx()
        self.adx_history.append(adx)

    def _calculate_adx(self) -> float:
        """Расчет ADX на основе истории +DI и -DI."""
        if len(self.di_plus_history) < self.period:
            return 0.0

        # Расчет средних значений +DI и -DI
        avg_di_plus = sum(self.di_plus_history) / len(self.di_plus_history)
        avg_di_minus = sum(self.di_minus_history) / len(self.di_minus_history)

        # Расчет разности и суммы
        di_diff = abs(avg_di_plus - avg_di_minus)
        di_sum = avg_di_plus + avg_di_minus

        if di_sum > 0:
            adx = 100 * (di_diff / di_sum)
        else:
            adx = 0.0

        return adx

    def get_current_adx(self) -> float:
        """Получение текущего значения ADX."""
        if len(self.adx_history) == 0:
            return 0.0
        return self.adx_history[-1]

    def get_current_di_plus(self) -> float:
        """Получение текущего значения +DI."""
        if len(self.di_plus_history) == 0:
            return 0.0
        return self.di_plus_history[-1]

    def get_current_di_minus(self) -> float:
        """Получение текущего значения -DI."""
        if len(self.di_minus_history) == 0:
            return 0.0
        return self.di_minus_history[-1]

    def get_adx_value(self) -> float:
        """Получение значения ADX (алиас для get_current_adx)."""
        return self.get_current_adx()

    def get_di_plus(self) -> float:
        """Получение значения +DI (алиас для get_current_di_plus)."""
        return self.get_current_di_plus()

    def get_di_minus(self) -> float:
        """Получение значения -DI (алиас для get_current_di_minus)."""
        return self.get_current_di_minus()

    def is_trend_strong(self) -> bool:
        """Проверка силы тренда."""
        adx = self.get_current_adx()
        return adx > self.threshold

    def get_trend_direction(self) -> str:
        """Получение направления тренда."""
        di_plus = self.get_current_di_plus()
        di_minus = self.get_current_di_minus()

        if di_plus > di_minus:
            return "bullish"
        elif di_minus > di_plus:
            return "bearish"
        else:
            return "neutral"

    def get_trend_info(self) -> Dict[str, any]:
        """
        Получение информации о тренде.

        Returns:
            Словарь с информацией о тренде
        """
        adx = self.get_current_adx()
        di_plus = self.get_current_di_plus()
        di_minus = self.get_current_di_minus()
        direction = self.get_trend_direction()
        is_strong = self.is_trend_strong()

        return {
            "adx": adx,
            "di_plus": di_plus,
            "di_minus": di_minus,
            "direction": direction,
            "is_strong": is_strong,
            "threshold": self.threshold,
        }

    def reset(self):
        """Сброс всех данных индикатора."""
        self.di_plus_history.clear()
        self.di_minus_history.clear()
        self.adx_history.clear()
        self.current_high = 0.0
        self.current_low = 0.0
        self.current_close = 0.0
        self.prev_high = 0.0
        self.prev_low = 0.0
        self.prev_close = 0.0
        logger.info("FastADX сброшен")

    def __repr__(self) -> str:
        """Строковое представление индикатора."""
        adx = self.get_current_adx()
        direction = self.get_trend_direction()
        return (
            f"FastADX("
            f"adx={adx:.2f}, "
            f"direction={direction}, "
            f"strong={self.is_trend_strong()}"
            f")"
        )
