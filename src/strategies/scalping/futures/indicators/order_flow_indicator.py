"""
Order Flow Indicator для Futures торговли.

Анализирует соотношение bid/ask объемов для определения направления
силы покупателей и продавцов на рынке.
"""

from collections import deque
from typing import Deque, Dict, Optional

from loguru import logger


class OrderFlowIndicator:
    """
    Индикатор потока ордеров для Futures.

    Анализирует соотношение bid/ask объемов для определения:
    - Силы покупателей (delta > 0)
    - Силы продавцов (delta < 0)
    - Нейтрального рынка (delta ≈ 0)

    Attributes:
        window: Размер окна для анализа
        long_threshold: Порог для благоприятности лонга
        short_threshold: Порог для благоприятности шорта
        bid_volumes: История bid объемов
        ask_volumes: История ask объемов
        deltas: История delta значений
    """

    def __init__(
        self,
        window: int = 100,
        long_threshold: float = 0.1,
        short_threshold: float = -0.1,
    ):
        """
        Инициализация индикатора.

        Args:
            window: Размер окна для анализа (по умолчанию 100)
            long_threshold: Порог для благоприятности лонга (по умолчанию 0.1)
            short_threshold: Порог для благоприятности шорта (по умолчанию -0.1)
        """
        self.window = window
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold
        self.bid_volumes: Deque[float] = deque(maxlen=window)
        self.ask_volumes: Deque[float] = deque(maxlen=window)
        self.deltas: Deque[float] = deque(maxlen=window)

    def update(self, bid_volume: float, ask_volume: float) -> None:
        """
        Обновление данных о bid/ask объемах.

        Args:
            bid_volume: Объем на стороне бида (покупатели)
            ask_volume: Объем на стороне аска (продавцы)
        """
        if bid_volume < 0 or ask_volume < 0:
            logger.warning(f"Отрицательные объемы: bid={bid_volume}, ask={ask_volume}")
            return

        self.bid_volumes.append(bid_volume)
        self.ask_volumes.append(ask_volume)

        # Расчет delta всегда
        delta = self._calculate_delta(bid_volume, ask_volume)
        self.deltas.append(delta)

    def _calculate_delta(self, bid_volume: float, ask_volume: float) -> float:
        """
        Расчет delta (разность между bid и ask объемами).

        Formula: delta = (bid_volume - ask_volume) / (bid_volume + ask_volume)

        Returns:
            Delta в диапазоне [-1, 1]:
            - 1.0 = все покупатели
            - -1.0 = все продавцы
            - 0.0 = равновесие
        """
        total_volume = bid_volume + ask_volume
        if total_volume == 0:
            return 0.0

        return (bid_volume - ask_volume) / total_volume

    def get_delta(self) -> float:
        """
        Получение текущего delta.

        Returns:
            Текущее значение delta
        """
        if len(self.deltas) == 0:
            return 0.0

        return self.deltas[-1]

    def get_avg_delta(self, periods: int = 10) -> float:
        """
        Получение среднего delta за N периодов.

        Args:
            periods: Количество периодов для расчета

        Returns:
            Среднее delta за N периодов
        """
        if len(self.deltas) == 0:
            return 0.0

        if len(self.deltas) < periods:
            periods = len(self.deltas)

        recent_deltas = list(self.deltas)[-periods:]
        return sum(recent_deltas) / len(recent_deltas)

    def get_delta_trend(self) -> str:
        """
        Определение тренда delta.

        Returns:
            "long" если delta растет (сила покупателей)
            "short" если delta падает (сила продавцов)
            "neutral" если delta стабильна
        """
        if len(self.deltas) < 5:
            return "neutral"

        recent_deltas = list(self.deltas)[-5:]

        # Анализ тренда
        increasing = all(
            recent_deltas[i] < recent_deltas[i + 1]
            for i in range(len(recent_deltas) - 1)
        )
        decreasing = all(
            recent_deltas[i] > recent_deltas[i + 1]
            for i in range(len(recent_deltas) - 1)
        )

        if increasing:
            return "long"  # Сила покупателей растет
        elif decreasing:
            return "short"  # Сила продавцов растет
        else:
            return "neutral"

    def is_long_favorable(self, threshold: Optional[float] = None) -> bool:
        """
        Проверка, благоприятен ли вход в лонг.

        Args:
            threshold: Минимальный порог delta для лонга (если None, используется self.long_threshold)

        Returns:
            True если delta > threshold (больше покупателей)
        """
        delta = self.get_delta()
        threshold = threshold if threshold is not None else self.long_threshold
        return delta > threshold

    def is_short_favorable(self, threshold: Optional[float] = None) -> bool:
        """
        Проверка, благоприятен ли вход в шорт.

        Args:
            threshold: Максимальный порог delta для шорта (если None, используется self.short_threshold)

        Returns:
            True если delta < threshold (больше продавцов)
        """
        delta = self.get_delta()
        threshold = threshold if threshold is not None else self.short_threshold
        return delta < threshold

    def get_market_pressure(self) -> Dict[str, float]:
        """
        Получение данных о рыночном давлении.

        Returns:
            Словарь с данными о:
            - current_delta: Текущий delta
            - avg_delta: Средний delta
            - trend: Тренд delta
            - strength: Сила давления (0-100%)
        """
        current_delta = self.get_delta()
        avg_delta = self.get_avg_delta()
        trend = self.get_delta_trend()

        # Расчет силы давления (0-100%)
        strength = abs(avg_delta) * 100

        return {
            "current_delta": current_delta,
            "avg_delta": avg_delta,
            "trend": trend,
            "strength": strength,
            "favor_long": current_delta > self.long_threshold,
            "favor_short": current_delta < self.short_threshold,
        }

    def reset(self) -> None:
        """Сброс всех данных индикатора."""
        self.bid_volumes.clear()
        self.ask_volumes.clear()
        self.deltas.clear()
        logger.info("Order Flow Indicator сброшен")

    def __repr__(self) -> str:
        """Строковое представление индикатора."""
        delta = self.get_delta()
        trend = self.get_delta_trend()
        pressure = self.get_market_pressure()

        return (
            f"OrderFlowIndicator("
            f"delta={delta:.4f}, "
            f"trend={trend}, "
            f"strength={pressure['strength']:.1f}%"
            f")"
        )
