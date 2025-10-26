"""
Micro Pivot Calculator для Futures торговли.

Рассчитывает микро-пивотные уровни для точного определения
целей (TP) на основе 15-минутного периода.
"""

from collections import deque
from typing import Deque, Dict, Optional

from loguru import logger


class MicroPivotCalculator:
    """
    Калькулятор микро-пивотов для Futures.

    Рассчитывает пивотные уровни на основе 15-минутных свечей
    для определения точных целей для TP.

    Attributes:
        timeframe: Таймфрейм для расчета пивотов
        highs: История максимальных цен
        lows: История минимальных цен
        closes: История цен закрытия
    """

    def __init__(self, timeframe: str = "15m"):
        """
        Инициализация калькулятора.

        Args:
            timeframe: Таймфрейм для расчета (по умолчанию "15m")
        """
        self.timeframe = timeframe
        self.highs: Deque[float] = deque(maxlen=20)
        self.lows: Deque[float] = deque(maxlen=20)
        self.closes: Deque[float] = deque(maxlen=20)

    def update(self, high: float, low: float, close: float) -> None:
        """
        Обновление данных свечи.

        Args:
            high: Максимальная цена свечи
            low: Минимальная цена свечи
            close: Цена закрытия свечи
        """
        if high < low:
            logger.warning(f"Некорректные данные: high={high} < low={low}")
            return

        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)

    def calculate_pivots(self) -> Dict[str, float]:
        """
        Расчет пивотных уровней.

        Standard Pivot Formula:
        - Pivot = (High + Low + Close) / 3
        - R1 = 2 * Pivot - Low
        - S1 = 2 * Pivot - High
        - R2 = Pivot + (High - Low)
        - S2 = Pivot - (High - Low)

        Returns:
            Словарь с пивотными уровнями:
            - pivot: Центральная точка
            - r1, r2: Уровни сопротивления
            - s1, s2: Уровни поддержки
            - resistance: Ближайший уровень сопротивления
            - support: Ближайший уровень поддержки
        """
        if len(self.highs) < 5 or len(self.lows) < 5 or len(self.closes) < 5:
            return {}

        # Стандартный расчет пивотов
        high = max(self.highs)
        low = min(self.lows)
        close = self.closes[-1]

        pivot = (high + low + close) / 3

        # Классические пивоты Woodie
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)

        # Camarilla пивоты для микро-уровней
        cam_r1 = close + (high - low) * 0.08333
        cam_r2 = close + (high - low) * 0.1666
        cam_s1 = close - (high - low) * 0.08333
        cam_s2 = close - (high - low) * 0.1666

        # Fibonacci пивоты
        fib_r1 = pivot + 0.382 * (high - low)
        fib_r2 = pivot + 0.618 * (high - low)
        fib_s1 = pivot - 0.382 * (high - low)
        fib_s2 = pivot - 0.618 * (high - low)

        return {
            "pivot": pivot,
            "r1": r1,
            "r2": r2,
            "s1": s1,
            "s2": s2,
            "cam_r1": cam_r1,
            "cam_r2": cam_r2,
            "cam_s1": cam_s1,
            "cam_s2": cam_s2,
            "fib_r1": fib_r1,
            "fib_r2": fib_r2,
            "fib_s1": fib_s1,
            "fib_s2": fib_s2,
            "resistance": r1,
            "support": s1,
            "high": high,
            "low": low,
            "close": close,
        }

    def get_optimal_tp(
        self, entry_price: float, side: str, max_distance_pct: float = 0.5
    ) -> float:
        """
        Получение оптимального TP на основе пивотов.

        Args:
            entry_price: Цена входа
            side: Сторона позиции ("long" или "short")
            max_distance_pct: Максимальное расстояние в процентах

        Returns:
            Оптимальная цена для TP
        """
        pivots = self.calculate_pivots()
        if not pivots:
            logger.warning("Недостаточно данных для расчета пивотов")
            return self._get_default_tp(entry_price, side, max_distance_pct)

        max_distance = entry_price * max_distance_pct

        if side == "long":
            # Для лонга берем ближайший уровень сопротивления
            r1 = pivots.get("r1", entry_price * 1.003)
            cam_r1 = pivots.get("cam_r1", entry_price * 1.001)

            # Выбираем минимальную цель (ближайшую к входу)
            target = min(r1, cam_r1)

            # Ограничиваем максимальным расстоянием
            if target - entry_price > max_distance:
                target = entry_price + max_distance

            return target

        else:  # short
            # Для шорта берем ближайший уровень поддержки
            s1 = pivots.get("s1", entry_price * 0.997)
            cam_s1 = pivots.get("cam_s1", entry_price * 0.999)

            # Выбираем максимальную цель (ближайшую к входу)
            target = max(s1, cam_s1)

            # Ограничиваем максимальным расстоянием
            if entry_price - target > max_distance:
                target = entry_price - max_distance

            return target

    def _get_default_tp(
        self, entry_price: float, side: str, max_distance_pct: float = 0.5
    ) -> float:
        """Получение дефолтного TP."""
        max_distance = entry_price * max_distance_pct

        if side == "long":
            # Консервативный TP для лонга
            return entry_price * 1.003
        else:
            # Консервативный TP для шорта
            return entry_price * 0.997

    def get_current_range(self) -> Dict[str, float]:
        """
        Получение текущего диапазона цен.

        Returns:
            Словарь с диапазоном:
            - high: Максимум
            - low: Минимум
            - range: Диапазон
            - mid: Середина диапазона
        """
        pivots = self.calculate_pivots()

        if not pivots:
            return {"high": 0.0, "low": 0.0, "range": 0.0, "mid": 0.0}

        high = pivots.get("high", 0.0)
        low = pivots.get("low", 0.0)
        range_value = high - low
        mid = (high + low) / 2

        return {
            "high": high,
            "low": low,
            "range": range_value,
            "mid": mid,
            "range_pct": (range_value / mid * 100) if mid > 0 else 0.0,
        }

    def reset(self) -> None:
        """Сброс всех данных."""
        self.highs.clear()
        self.lows.clear()
        self.closes.clear()
        logger.info("Micro Pivot Calculator сброшен")

    def __repr__(self) -> str:
        """Строковое представление калькулятора."""
        pivots = self.calculate_pivots()

        if not pivots:
            return "MicroPivotCalculator(no data)"

        range_data = self.get_current_range()

        return (
            f"MicroPivotCalculator("
            f"pivot={pivots.get('pivot', 0):.2f}, "
            f"range={range_data['range_pct']:.2f}%"
            f")"
        )
