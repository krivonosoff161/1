"""
Funding Rate Monitor для Futures торговли.

Отслеживает фандинг-сборы (funding rate) для избежания
неблагоприятных входов перед выплатой фандинга.
"""

from collections import deque
from typing import Deque, Dict

from loguru import logger


class FundingRateMonitor:
    """
    Мониторинг фандинга для Futures.

    Анализирует funding rate:
    - Положительный funding → продавцы платят покупателям
    - Отрицательный funding → покупатели платят продавцам
    - Предупреждает перед неблагоприятным входом

    Attributes:
        max_funding_rate: Максимальный допустимый funding
        current_funding: Текущий funding rate
        funding_history: История funding rates
    """

    def __init__(self, max_funding_rate: float = 0.0009):
        """
        Инициализация мониторинга фандинга.

        Args:
            max_funding_rate: Максимальный допустимый funding в %
        """
        self.max_funding_rate = self._normalize_rate(max_funding_rate)
        self.current_funding = 0.0
        self.funding_history: Deque[float] = deque(maxlen=24)  # 24 часа

    def update(self, funding_rate: float):
        """
        Обновление данных о фандинге.

        Args:
            funding_rate: Текущий funding rate
        """
        normalized = self._normalize_rate(funding_rate)
        self.current_funding = normalized
        self.funding_history.append(normalized)
        logger.debug(f"Funding rate обновлен: {normalized:.4%}")

    def get_current_funding(self) -> float:
        """Получение текущего funding rate."""
        return self.current_funding

    def get_avg_funding(self, periods: int = 8) -> float:
        """
        Получение среднего funding за N периодов.

        Args:
            periods: Количество периодов

        Returns:
            Средний funding
        """
        if len(self.funding_history) == 0:
            return 0.0

        if len(self.funding_history) < periods:
            periods = len(self.funding_history)

        recent = list(self.funding_history)[-periods:]
        return sum(recent) / len(recent)

    def is_funding_favorable(self, side: str) -> bool:
        """
        Проверка, благоприятен ли фандинг для входа.

        Args:
            side: Сторона позиции ("long" или "short")

        Returns:
            True если фандинг благоприятен
        """
        # Если funding слишком высокий по модулю
        if abs(self.current_funding) > self.max_funding_rate:
            # ✅ ИСПРАВЛЕНО: Нормализуем side перед сравнением
            side_normalized = side.lower() if isinstance(side, str) else "long"
            if side_normalized == "long" and self.current_funding > 0:
                # Для лонга при положительном funding - неблагоприятно
                logger.warning(f"Высокий funding для лонга: {self.current_funding:.4%}")
                return False
            elif side_normalized == "short" and self.current_funding < 0:
                # Для шорта при отрицательном funding - неблагоприятно
                logger.warning(f"Высокий funding для шорта: {self.current_funding:.4%}")
                return False

        return True

    @staticmethod
    def _normalize_rate(rate: float) -> float:
        try:
            value = float(rate)
        except (TypeError, ValueError):
            return 0.0
        if value > 1 or value < -1:
            value /= 100.0
        return value

    def get_funding_trend(self) -> str:
        """
        Получение тренда фандинга.

        Returns:
            "increasing" - растет
            "decreasing" - падает
            "sideways" - боковой
        """
        if len(self.funding_history) < 3:
            return "unknown"

        recent = list(self.funding_history)[-3:]

        # Анализ тренда
        if all(recent[i] < recent[i + 1] for i in range(len(recent) - 1)):
            return "increasing"
        elif all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
            return "decreasing"
        else:
            return "sideways"

    def get_payment_amount(
        self, side: str, position_size: float, price: float
    ) -> float:
        """
        Получение суммы фандингового платежа.

        Args:
            side: Сторона позиции
            position_size: Размер позиции
            price: Цена актива

        Returns:
            Сумма фандинга (положительная = получение, отрицательная = выплата)
        """
        notional = position_size * price
        funding_amount = notional * self.current_funding

        # ✅ ИСПРАВЛЕНО: Нормализуем side перед сравнением
        side_normalized = side.lower() if isinstance(side, str) else "long"
        if side_normalized == "long":
            # Позитивный funding = получение, отрицательный = выплата
            return funding_amount
        else:
            # Для шорта наоборот
            return -funding_amount

    def get_funding_info(self, side: str) -> Dict[str, any]:
        """
        Получение информации о фандинге для позиции.

        Args:
            side: Сторона позиции

        Returns:
            Словарь с информацией о фандинге
        """
        is_favorable = self.is_funding_favorable(side)
        trend = self.get_funding_trend()
        payment_direction = (
            "in"
            if (side == "long" and self.current_funding > 0)
            or (side == "short" and self.current_funding < 0)
            else "out"
        )

        return {
            "current_funding": self.current_funding,
            "avg_funding": self.get_avg_funding(),
            "trend": trend,
            "is_favorable": is_favorable,
            "payment_direction": payment_direction,
            "recommendation": "enter" if is_favorable else "avoid",
        }

    def reset(self):
        """Сброс всех данных."""
        self.funding_history.clear()
        self.current_funding = 0.0
        logger.info("FundingRateMonitor сброшен")

    def __repr__(self) -> str:
        """Строковое представление мониторинга."""
        trend = self.get_funding_trend()
        return (
            f"FundingRateMonitor("
            f"current={self.current_funding:.4%}, "
            f"avg={self.get_avg_funding():.4%}, "
            f"trend={trend}"
            f")"
        )
