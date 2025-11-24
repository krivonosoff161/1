"""
SignalValidator - Финальная валидация сигналов.

Проверяет:
- Риски (баланс, маржа, лимиты)
- Соответствие режиму
- Минимальные требования
"""

from typing import Any, Dict, Optional

from loguru import logger


class SignalValidator:
    """
    Валидатор сигналов.

    Выполняет финальную проверку сигнала перед его исполнением.
    """

    def __init__(self, risk_manager=None, balance_checker=None):
        """
        Инициализация SignalValidator.

        Args:
            risk_manager: RiskManager для проверки рисков (опционально)
            balance_checker: BalanceChecker для проверки баланса (опционально)
        """
        self.risk_manager = risk_manager
        self.balance_checker = balance_checker

        logger.info("✅ SignalValidator инициализирован")

    async def validate(
        self,
        signal: Dict[str, Any],
        market_data: Any,  # MarketData
        regime: Optional[str] = None,
        balance_profile: Optional[str] = None,
    ) -> bool:
        """
        Валидация сигнала.

        Args:
            signal: Торговый сигнал
            market_data: Рыночные данные
            regime: Режим рынка (trending, ranging, choppy)
            balance_profile: Профиль баланса (small, medium, large)

        Returns:
            True если сигнал валиден
        """
        try:
            symbol = signal.get("symbol")
            if not symbol:
                logger.warning("⚠️ SignalValidator: Сигнал не содержит symbol")
                return False

            # 1. Проверка минимальной силы сигнала
            strength = signal.get("strength", 0)
            min_strength = signal.get(
                "min_strength", 0.3
            )  # Может быть в сигнале или конфиге
            if strength < min_strength:
                logger.debug(
                    f"🔍 SignalValidator: Сигнал {symbol} не прошел проверку силы "
                    f"(strength={strength:.2f} < min={min_strength:.2f})"
                )
                return False

            # 2. Проверка наличия цены
            price = signal.get("price")
            if not price or price <= 0:
                logger.warning(
                    f"⚠️ SignalValidator: Сигнал {symbol} не содержит валидную цену"
                )
                return False

            # 3. Проверка направления
            side = signal.get("side", "").lower()
            if side not in ["buy", "sell"]:
                logger.warning(
                    f"⚠️ SignalValidator: Сигнал {symbol} имеет невалидное направление: {side}"
                )
                return False

            # 4. Проверка рисков через RiskManager
            if self.risk_manager:
                try:
                    is_risk_ok = await self._check_risks(
                        signal, regime, balance_profile
                    )
                    if not is_risk_ok:
                        logger.debug(
                            f"🔍 SignalValidator: Сигнал {symbol} не прошел проверку рисков"
                        )
                        return False
                except Exception as e:
                    logger.warning(
                        f"⚠️ SignalValidator: Ошибка проверки рисков для {symbol}: {e}"
                    )

            # 5. Проверка баланса через BalanceChecker
            if self.balance_checker:
                try:
                    is_balance_ok = await self._check_balance(signal)
                    if not is_balance_ok:
                        logger.debug(
                            f"🔍 SignalValidator: Сигнал {symbol} не прошел проверку баланса"
                        )
                        return False
                except Exception as e:
                    logger.warning(
                        f"⚠️ SignalValidator: Ошибка проверки баланса для {symbol}: {e}"
                    )

            # 6. Проверка лимитов открытых позиций
            max_open_positions = signal.get(
                "max_open_positions", 5
            )  # Может быть в конфиге
            current_positions_count = signal.get("current_positions_count", 0)
            if current_positions_count >= max_open_positions:
                logger.debug(
                    f"🔍 SignalValidator: Достигнут лимит открытых позиций "
                    f"({current_positions_count}/{max_open_positions})"
                )
                return False

            # Все проверки пройдены
            logger.debug(f"✅ SignalValidator: Сигнал {symbol} прошел валидацию")
            return True

        except Exception as e:
            logger.error(
                f"❌ SignalValidator: Ошибка валидации сигнала: {e}", exc_info=True
            )
            return False

    async def _check_risks(
        self,
        signal: Dict[str, Any],
        regime: Optional[str] = None,
        balance_profile: Optional[str] = None,
    ) -> bool:
        """
        Проверка рисков через RiskManager.

        Args:
            signal: Торговый сигнал
            regime: Режим рынка
            balance_profile: Профиль баланса

        Returns:
            True если риски допустимы
        """
        if not self.risk_manager:
            return True

        # Делегируем проверку в RiskManager
        # TODO: Реализовать после интеграции с RiskManager
        return True

    async def _check_balance(self, signal: Dict[str, Any]) -> bool:
        """
        Проверка баланса через BalanceChecker.

        Args:
            signal: Торговый сигнал

        Returns:
            True если баланс достаточен
        """
        if not self.balance_checker:
            return True

        # Делегируем проверку в BalanceChecker
        # TODO: Реализовать после интеграции с BalanceChecker
        return True
