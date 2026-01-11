"""
Fast ADX для Futures торговли.

Ускоренная версия ADX индикатора для быстрой реакции
на изменение тренда на коротких таймфреймах (1m, 5m).
"""

from collections import deque
from typing import Any, Deque, Dict, Optional

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
        """Инициализация Fast ADX."""
        self.period = period
        self.threshold = threshold

        self.di_plus_history: Deque[float] = deque(maxlen=period)
        self.di_minus_history: Deque[float] = deque(maxlen=period)
        self.adx_history: Deque[float] = deque(maxlen=period)
        self.tr_history: Deque[float] = deque(maxlen=period)
        self.plus_dm_history: Deque[float] = deque(maxlen=period)
        self.minus_dm_history: Deque[float] = deque(maxlen=period)
        self.dx_history: Deque[float] = deque(maxlen=period)

        self.current_high = 0.0
        self.current_low = 0.0
        self.current_close = 0.0
        self.prev_high = 0.0
        self.prev_low = 0.0
        self.prev_close = 0.0

        self._smoothed_tr: Optional[float] = None
        self._smoothed_plus_dm: Optional[float] = None
        self._smoothed_minus_dm: Optional[float] = None
        self._smoothed_adx: Optional[float] = None

        logger.info(f"FastADX инициализирован: period={period}, threshold={threshold}")

    def reset(self):
        """🔴 BUG #2 FIX: Reset состояния ADX перед новым расчетом.

        Необходимо для предотвращения накопления состояния между
        несколькими вызовами detect_regime().
        """
        self.di_plus_history.clear()
        self.di_minus_history.clear()
        self.adx_history.clear()
        self.tr_history.clear()
        self.plus_dm_history.clear()
        self.minus_dm_history.clear()
        self.dx_history.clear()

        self.current_high = 0.0
        self.current_low = 0.0
        self.current_close = 0.0
        self.prev_high = 0.0
        self.prev_low = 0.0
        self.prev_close = 0.0

        self._smoothed_tr: Optional[float] = None
        self._smoothed_plus_dm: Optional[float] = None
        self._smoothed_minus_dm: Optional[float] = None
        self._smoothed_adx: Optional[float] = None

        logger.debug("FastADX reset: состояние очищено")

    def update(self, high: float, low: float, close: float):
        """Обновление индикатора новыми данными свечи."""
        if self.prev_high == 0 and self.prev_low == 0:
            self.prev_high = high
            self.prev_low = low
            self.prev_close = close
            self.current_high = high
            self.current_low = low
            self.current_close = close
            return

        self.prev_high = self.current_high
        self.prev_low = self.current_low
        self.prev_close = self.current_close

        self.current_high = high
        self.current_low = low
        self.current_close = close

        up_move = high - self.prev_high
        down_move = self.prev_low - low

        plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0

        tr = max(
            self.current_high - self.current_low,
            abs(self.current_high - self.prev_close),
            abs(self.current_low - self.prev_close),
        )

        self.tr_history.append(tr)
        self.plus_dm_history.append(plus_dm)
        self.minus_dm_history.append(minus_dm)

        if len(self.tr_history) < self.period:
            return

        if self._smoothed_tr is None:
            self._smoothed_tr = sum(self.tr_history)
            self._smoothed_plus_dm = sum(self.plus_dm_history)
            self._smoothed_minus_dm = sum(self.minus_dm_history)
        else:
            self._smoothed_tr = (
                self._smoothed_tr - (self._smoothed_tr / self.period) + tr
            )
            self._smoothed_plus_dm = (
                self._smoothed_plus_dm
                - (self._smoothed_plus_dm / self.period)
                + plus_dm
            )
            self._smoothed_minus_dm = (
                self._smoothed_minus_dm
                - (self._smoothed_minus_dm / self.period)
                + minus_dm
            )

        if not self._smoothed_tr or self._smoothed_tr == 0:
            return

        di_plus = 100 * (self._smoothed_plus_dm / self._smoothed_tr)
        di_minus = 100 * (self._smoothed_minus_dm / self._smoothed_tr)

        self.di_plus_history.append(di_plus)
        self.di_minus_history.append(di_minus)

        di_sum = di_plus + di_minus
        if di_sum == 0:
            return

        dx = 100 * abs(di_plus - di_minus) / di_sum
        self.dx_history.append(dx)

        if self._smoothed_adx is None:
            if len(self.dx_history) >= self.period:
                self._smoothed_adx = sum(self.dx_history) / len(self.dx_history)
                self.adx_history.append(self._smoothed_adx)
        else:
            self._smoothed_adx = (
                (self._smoothed_adx * (self.period - 1)) + dx
            ) / self.period
            self.adx_history.append(self._smoothed_adx)

    def _calculate_adx(self) -> float:
        """Расчет ADX на основе истории +DI и -DI."""
        if len(self.adx_history) == 0:
            return 0.0
        return self.adx_history[-1]

    def get_current_adx(self) -> float:
        """Получение текущего значения ADX."""
        return self._calculate_adx()

    def get_adx(self, symbol: Optional[str] = None) -> Optional[Dict[str, float]]:
        """
        ✅ НОВОЕ (08.01.2026): Получить ADX данные в формате словаря

        Args:
            symbol: Торговый символ (игнорируется, для совместимости с интерфейсом)

        Returns:
            {'adx': float, 'plus_di': float, 'minus_di': float} или None
        """
        if len(self.adx_history) == 0:
            return None

        di_plus = self.di_plus_history[-1] if len(self.di_plus_history) > 0 else 0.0
        di_minus = self.di_minus_history[-1] if len(self.di_minus_history) > 0 else 0.0
        adx_value = self._calculate_adx()

        return {
            "adx": adx_value,
            "plus_di": di_plus,
            "minus_di": di_minus,
        }

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
        """Получение значения ADX (алиас)."""
        return self.get_current_adx()

    def get_di_plus(self) -> float:
        """Получение значения +DI (алиас)."""
        return self.get_current_di_plus()

    def get_di_minus(self) -> float:
        """Получение значения -DI (алиас)."""
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

    def get_trend_info(self) -> Dict[str, Any]:
        """Получение информации о тренде."""
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
