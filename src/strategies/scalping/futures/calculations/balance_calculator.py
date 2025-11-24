"""
BalanceCalculator - Расчеты по балансу.

Определяет профиль баланса и рассчитывает параметры для профиля.
"""

from typing import Optional, Tuple

from loguru import logger


class BalanceCalculator:
    """
    Калькулятор баланса.

    Определяет профиль баланса и рассчитывает boost множители.
    """

    def __init__(self, config=None):
        """
        Инициализация BalanceCalculator.

        Args:
            config: Конфигурация бота
        """
        self.config = config

        # Пороги профилей (могут быть в конфиге)
        self.small_threshold = 500.0  # До 500 USDT
        self.medium_threshold = 2000.0  # 500-2000 USDT
        # large: > 2000 USDT

        if config:
            # TODO: Загрузить пороги из конфига
            pass

        logger.info("✅ BalanceCalculator инициализирован")

    def determine_balance_profile(self, balance: float) -> str:
        """
        Определить профиль баланса.

        Args:
            balance: Текущий баланс в USDT

        Returns:
            Профиль баланса (small, medium, large)
        """
        if balance < self.small_threshold:
            profile = "small"
        elif balance < self.medium_threshold:
            profile = "medium"
        else:
            profile = "large"

        logger.debug(f"📊 BalanceCalculator: Баланс ${balance:.2f} → профиль: {profile}")

        return profile

    def calculate_balance_parameters(
        self, balance: float, profile: Optional[str] = None
    ) -> dict:
        """
        Рассчитать параметры для баланса.

        Args:
            balance: Текущий баланс
            profile: Профиль баланса (если None, определяется автоматически)

        Returns:
            Словарь с параметрами баланса
        """
        if profile is None:
            profile = self.determine_balance_profile(balance)

        # Boost множители для разных профилей
        tp_boost = self._get_tp_boost(profile)
        position_size_boost = self._get_position_size_boost(profile)

        return {
            "profile": profile,
            "balance": balance,
            "tp_boost": tp_boost,
            "position_size_boost": position_size_boost,
        }

    def _get_tp_boost(self, profile: str) -> float:
        """
        Получить boost для TP в зависимости от профиля.

        Args:
            profile: Профиль баланса

        Returns:
            Boost множитель
        """
        boosts = {
            "small": 1.0,  # Без boost
            "medium": 1.1,  # +10%
            "large": 1.2,  # +20%
        }

        return boosts.get(profile.lower(), 1.0)

    def _get_position_size_boost(self, profile: str) -> float:
        """
        Получить boost для размера позиции в зависимости от профиля.

        Args:
            profile: Профиль баланса

        Returns:
            Boost множитель
        """
        boosts = {
            "small": 1.0,  # Без boost
            "medium": 1.05,  # +5%
            "large": 1.1,  # +10%
        }

        return boosts.get(profile.lower(), 1.0)
