"""
ParameterAdapter - Объединение и приоритизация параметров.

Объединяет параметры из разных источников и применяет приоритизацию:
1. Per-symbol параметры
2. Per-regime параметры
3. Balance profile boost
4. Глобальные параметры
"""

from typing import Any, Dict, Optional

from loguru import logger


class ParameterAdapter:
    """
    Адаптер параметров.

    Объединяет параметры из разных источников с правильной приоритизацией.
    """

    def __init__(
        self,
        regime_calculator=None,
        balance_calculator=None,
        config=None,
    ):
        """
        Инициализация ParameterAdapter.

        Args:
            regime_calculator: RegimeCalculator для режимных параметров
            balance_calculator: BalanceCalculator для балансовых параметров
            config: Конфигурация бота
        """
        self.regime_calculator = regime_calculator
        self.balance_calculator = balance_calculator
        self.config = config

        logger.info("✅ ParameterAdapter инициализирован")

    def get_adaptive_parameters(
        self,
        symbol: str,
        regime: Optional[str] = None,
        balance_profile: Optional[str] = None,
        parameter_type: str = "tp",  # tp, sl, position_size, etc.
    ) -> Dict[str, Any]:
        """
        Получить адаптивные параметры с учетом всех приоритетов.

        Args:
            symbol: Торговый символ
            regime: Режим рынка
            balance_profile: Профиль баланса
            parameter_type: Тип параметра (tp, sl, position_size)

        Returns:
            Словарь с адаптивными параметрами
        """
        parameters = {}

        if parameter_type == "tp":
            if self.regime_calculator:
                tp_percent = self.regime_calculator.calculate_tp_percent(
                    symbol, regime, balance_profile
                )
                parameters["tp_percent"] = tp_percent

        elif parameter_type == "sl":
            if self.regime_calculator:
                sl_percent = self.regime_calculator.calculate_sl_percent(
                    symbol, regime, balance_profile
                )
                parameters["sl_percent"] = sl_percent

        elif parameter_type == "position_size":
            if self.regime_calculator:
                multiplier = self.regime_calculator.calculate_position_size_multiplier(
                    symbol, regime, balance_profile
                )
                parameters["position_multiplier"] = multiplier

        # Добавляем balance profile boost
        if balance_profile and self.balance_calculator:
            balance_params = self.balance_calculator.calculate_balance_parameters(
                balance=0, profile=balance_profile
            )
            parameters["balance_boost"] = balance_params

        return parameters

    def apply_all_multipliers(
        self,
        base_value: float,
        symbol: str,
        regime: Optional[str] = None,
        balance_profile: Optional[str] = None,
    ) -> float:
        """
        Применить все множители к базовому значению.

        Args:
            base_value: Базовое значение
            symbol: Торговый символ
            regime: Режим рынка
            balance_profile: Профиль баланса

        Returns:
            Значение после применения всех множителей
        """
        value = base_value

        # Режимный множитель
        if self.regime_calculator:
            regime_mult = self.regime_calculator.calculate_position_size_multiplier(
                symbol, regime, balance_profile
            )
            value = value * regime_mult

        # Balance profile boost
        if balance_profile and self.balance_calculator:
            balance_params = self.balance_calculator.calculate_balance_parameters(
                balance=0, profile=balance_profile
            )
            size_boost = balance_params.get("position_size_boost", 1.0)
            value = value * size_boost

        return value
