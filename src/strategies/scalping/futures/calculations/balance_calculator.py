"""
BalanceCalculator - Расчеты по балансу.

Определяет профиль баланса и рассчитывает параметры для профиля.
"""

from typing import Optional, Tuple  # noqa: F401

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

        # Пороги профилей — читаем из balance_profiles в конфиге
        # Fallback: micro=500, small=1500, medium=3000 (из config_futures.yaml)
        self.small_threshold = 500.0
        self.medium_threshold = 2000.0

        if config:
            try:
                scalping = getattr(config, "scalping", None)
                profiles = (
                    getattr(scalping, "balance_profiles", None) if scalping else None
                )
                if profiles:
                    # Читаем threshold каждого профиля из конфига
                    micro_cfg = getattr(profiles, "micro", None)
                    small_cfg = getattr(profiles, "small", None)
                    medium_cfg = getattr(profiles, "medium", None)  # noqa: F841
                    if micro_cfg and getattr(micro_cfg, "threshold", None):
                        self.small_threshold = float(micro_cfg.threshold)
                    if small_cfg and getattr(small_cfg, "threshold", None):
                        self.medium_threshold = float(small_cfg.threshold)
                    logger.debug(
                        f"✅ BalanceCalculator: пороги из конфига: "
                        f"micro<{self.small_threshold}$, small<{self.medium_threshold}$"
                    )
            except Exception as e:
                logger.warning(
                    f"⚠️ BalanceCalculator: не удалось загрузить пороги из конфига: {e}"
                )

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
