"""
Max Size Limiter для Futures торговли.

Защита от случайно больших ордеров и переполнения лимитов.
"""

from typing import Dict, Optional

from loguru import logger


class MaxSizeLimiter:
    """
    Лимитчик размера позиций для Futures.

    Защищает от:
    - Слишком больших ордеров
    - Превышения лимитов аккаунта
    - Случайных "жирных пальцев"

    Attributes:
        max_single_size_usd: Максимальный размер одной позиции в USD
        max_total_size_usd: Максимальный общий размер всех позиций в USD
        max_positions: Максимальное количество открытых позиций
        position_sizes: Словарь текущих размеров позиций
    """

    def __init__(
        self,
        max_single_size_usd: float = 1000.0,
        max_total_size_usd: float = 5000.0,
        max_positions: int = 5,
    ):
        """
        Инициализация MaxSizeLimiter.

        Args:
            max_single_size_usd: Максимальный размер одной позиции в USD
            max_total_size_usd: Максимальный общий размер позиций в USD
            max_positions: Максимальное количество позиций
        """
        self.max_single_size_usd = max_single_size_usd
        self.max_total_size_usd = max_total_size_usd
        self.max_positions = max_positions
        self.position_sizes: Dict[str, float] = {}

    def can_open_position(self, symbol: str, size_usd: float) -> tuple[bool, str]:
        """
        Проверка возможности открыть позицию.

        Args:
            symbol: Символ инструмента
            size_usd: Размер позиции в USD

        Returns:
            (allowed, reason) - можно ли открыть и почему
        """
        # 1. Проверка максимального размера одной позиции
        if size_usd > self.max_single_size_usd:
            reason = (
                f"Размер позиции {size_usd:.2f} USD превышает "
                f"лимит {self.max_single_size_usd:.2f} USD"
            )
            logger.warning(f"❌ {reason}")
            return False, reason

        # 2. Проверка текущего количества позиций
        if len(self.position_sizes) >= self.max_positions:
            reason = (
                f"Уже открыто {len(self.position_sizes)} позиций, "
                f"лимит {self.max_positions}"
            )
            logger.warning(f"❌ {reason}")
            return False, reason

        # 3. Проверка общего размера позиций
        total_size = sum(self.position_sizes.values())
        if total_size + size_usd > self.max_total_size_usd:
            reason = (
                f"Общий размер {total_size + size_usd:.2f} USD превышает "
                f"лимит {self.max_total_size_usd:.2f} USD"
            )
            logger.warning(f"❌ {reason}")
            return False, reason

        # 4. Проверка, не открыта ли уже позиция по этому символу
        if symbol in self.position_sizes:
            reason = f"Позиция {symbol} уже открыта"
            logger.warning(f"❌ {reason}")
            return False, reason

        reason = (
            f"✅ Можно открыть: {size_usd:.2f} USD "
            f"(всего {total_size:.2f} USD из {self.max_total_size_usd:.2f})"
        )
        logger.info(reason)
        return True, reason

    def add_position(self, symbol: str, size_usd: float):
        """
        Добавление позиции.

        Args:
            symbol: Символ инструмента
            size_usd: Размер позиции в USD
        """
        if symbol in self.position_sizes:
            logger.warning(f"⚠️ Позиция {symbol} уже существует, обновляю размер")

        self.position_sizes[symbol] = size_usd
        logger.info(
            f"✅ Позиция добавлена: {symbol} = {size_usd:.2f} USD "
            f"(всего {len(self.position_sizes)} позиций)"
        )

    def get_total_size(self) -> float:
        """Получение общего размера всех позиций в USD."""
        return sum(self.position_sizes.values())

    def get_position_count(self) -> int:
        """Получение количества открытых позиций."""
        return len(self.position_sizes)

    def remove_position(self, symbol: str):
        """
        Удаление позиции.

        Args:
            symbol: Символ инструмента
        """
        if symbol not in self.position_sizes:
            logger.warning(f"⚠️ Позиция {symbol} не найдена")
            return

        del self.position_sizes[symbol]
        logger.info(
            f"✅ Позиция удалена: {symbol} "
            f"(осталось {len(self.position_sizes)} позиций)"
        )

    def get_current_total_size(self) -> float:
        """
        Получение текущего общего размера позиций.

        Returns:
            Текущий общий размер в USD
        """
        return sum(self.position_sizes.values())

    def get_available_size(self) -> float:
        """
        Получение доступного размера для новых позиций.

        Returns:
            Доступный размер в USD
        """
        current_size = self.get_current_total_size()
        return max(0, self.max_total_size_usd - current_size)

    def get_utilization(self) -> float:
        """
        Получение использования лимитов в процентах.

        Returns:
            Использование в процентах (0-100)
        """
        current_size = self.get_current_total_size()
        return (
            (current_size / self.max_total_size_usd * 100)
            if self.max_total_size_usd > 0
            else 0.0
        )

    def get_statistics(self) -> Dict[str, any]:
        """
        Получение статистики лимитов.

        Returns:
            Словарь со статистикой
        """
        current_size = self.get_current_total_size()
        available = self.get_available_size()
        utilization = self.get_utilization()

        return {
            "current_positions": len(self.position_sizes),
            "max_positions": self.max_positions,
            "current_size_usd": current_size,
            "max_total_size_usd": self.max_total_size_usd,
            "max_single_size_usd": self.max_single_size_usd,
            "available_size_usd": available,
            "utilization_percent": utilization,
            "position_sizes": self.position_sizes.copy(),
        }

    def adjust_position_size(self, symbol: str, size_usd: float) -> float:
        """
        Корректировка размера позиции под лимиты.

        Args:
            symbol: Символ инструмента
            size_usd: Желаемый размер в USD

        Returns:
            Скорректированный размер в USD
        """
        # 1. Ограничение по максимальному размеру одной позиции
        if size_usd > self.max_single_size_usd:
            logger.warning(
                f"⚠️ Размер {size_usd:.2f} сокращен до "
                f"{self.max_single_size_usd:.2f} USD"
            )
            size_usd = self.max_single_size_usd

        # 2. Ограничение по доступному общему размеру
        available = self.get_available_size()
        if size_usd > available:
            logger.warning(
                f"⚠️ Размер {size_usd:.2f} сокращен до "
                f"{available:.2f} USD (доступно)"
            )
            size_usd = available

        return size_usd

    def reset(self):
        """Сброс всех лимитов."""
        self.position_sizes.clear()
        logger.info("MaxSizeLimiter сброшен")

    def __repr__(self) -> str:
        """Строковое представление лимитчика."""
        current = self.get_current_total_size()
        utilization = self.get_utilization()
        return (
            f"MaxSizeLimiter("
            f"positions={len(self.position_sizes)}/{self.max_positions}, "
            f"size={current:.2f}/{self.max_total_size_usd:.2f} USD, "
            f"utilization={utilization:.1f}%"
            f")"
        )
