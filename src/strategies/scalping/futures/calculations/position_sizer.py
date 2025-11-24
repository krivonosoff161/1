"""
PositionSizer - Расчет размера позиций.

Рассчитывает размер позиции с учетом:
- Баланса и профиля баланса
- Режима рынка
- Риска на сделку
- Левериджа
- Максимальных лимитов
"""

from typing import Any, Dict, Optional

from loguru import logger


class PositionSizer:
    """
    Калькулятор размера позиций.

    Рассчитывает оптимальный размер позиции с учетом всех факторов.
    """

    def __init__(
        self,
        margin_calculator=None,
        regime_calculator=None,
        balance_calculator=None,
        config=None,
    ):
        """
        Инициализация PositionSizer.

        Args:
            margin_calculator: MarginCalculator для расчетов маржи
            regime_calculator: RegimeCalculator для режимных параметров
            balance_calculator: BalanceCalculator для балансовых параметров
            config: Конфигурация бота
        """
        self.margin_calculator = margin_calculator
        self.regime_calculator = regime_calculator
        self.balance_calculator = balance_calculator
        self.config = config

        logger.info("✅ PositionSizer инициализирован")

    async def calculate_position_size(
        self,
        signal: Dict[str, Any],
        regime: Optional[str] = None,
        regime_params: Optional[Dict[str, Any]] = None,
        balance_profile: Optional[str] = None,
        balance: Optional[float] = None,
    ) -> Optional[float]:
        """
        Рассчитать размер позиции.

        Args:
            signal: Торговый сигнал
            regime: Режим рынка (trending, ranging, choppy)
            regime_params: Параметры режима
            balance_profile: Профиль баланса
            balance: Текущий баланс

        Returns:
            Размер позиции в монетах или None
        """
        try:
            symbol = signal.get("symbol")
            price = signal.get("price")
            leverage = signal.get("leverage", 3)  # Default leverage

            if not symbol or not price or price <= 0:
                logger.warning(
                    f"⚠️ PositionSizer: Невалидные данные сигнала для расчета размера"
                )
                return None

            if balance is None:
                logger.warning(f"⚠️ PositionSizer: Баланс не предоставлен для {symbol}")
                return None

            # 1. Базовый размер (процент от баланса)
            risk_per_trade = self._get_risk_per_trade(regime, regime_params)
            base_size_usd = balance * risk_per_trade

            # 2. Режимный множитель
            if self.regime_calculator:
                regime_multiplier = (
                    self.regime_calculator.calculate_position_size_multiplier(
                        symbol, regime, balance_profile
                    )
                )
            else:
                regime_multiplier = self._get_default_regime_multiplier(regime)

            adjusted_size_usd = base_size_usd * regime_multiplier

            # 3. Balance profile boost
            if self.balance_calculator and balance_profile:
                balance_params = self.balance_calculator.calculate_balance_parameters(
                    balance, balance_profile
                )
                size_boost = balance_params.get("position_size_boost", 1.0)
                adjusted_size_usd = adjusted_size_usd * size_boost

            # 4. Проверка максимального размера через MarginCalculator
            if self.margin_calculator:
                max_size = self.margin_calculator.calculate_max_position_size(
                    equity=balance, current_price=price, leverage=leverage
                )
                adjusted_size_usd = min(adjusted_size_usd, max_size * price)

            # 5. Конвертация в монеты
            position_size_coins = adjusted_size_usd / price

            logger.debug(
                f"✅ PositionSizer: Размер для {symbol}: "
                f"{position_size_coins:.6f} монет (${adjusted_size_usd:.2f}, "
                f"risk={risk_per_trade:.2%}, regime_mult={regime_multiplier:.2f})"
            )

            return position_size_coins

        except Exception as e:
            logger.error(
                f"❌ PositionSizer: Ошибка расчета размера для {signal.get('symbol', 'UNKNOWN')}: {e}",
                exc_info=True,
            )
            return None

    def _get_risk_per_trade(
        self,
        regime: Optional[str] = None,
        regime_params: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Получить процент риска на сделку.

        Args:
            regime: Режим рынка
            regime_params: Параметры режима

        Returns:
            Процент риска на сделку (0.01 = 1%)
        """
        # По умолчанию 1% от баланса на сделку
        default_risk = 0.01

        # Можно варьировать по режимам
        if regime_params:
            risk = regime_params.get("risk_per_trade", default_risk)
            if risk:
                return float(risk)

        if self.config and hasattr(self.config, "risk"):
            risk_config = self.config.risk
            risk = (
                getattr(risk_config, "risk_per_trade_percent", default_risk * 100) / 100
            )
            return risk

        return default_risk

    def _get_default_regime_multiplier(self, regime: Optional[str] = None) -> float:
        """
        Получить режимный множитель по умолчанию.

        Args:
            regime: Режим рынка

        Returns:
            Множитель размера позиции
        """
        multipliers = {
            "trending": 1.0,
            "ranging": 0.9,
            "choppy": 0.5,
        }

        if regime:
            return multipliers.get(regime.lower(), 1.0)

        return 1.0
