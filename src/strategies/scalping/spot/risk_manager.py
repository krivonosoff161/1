"""
Менеджер рисков для Spot торговли.

Ответственность:
- Расчет размера позиции (из OrderExecutor)
- Расчет уровней TP/SL (из OrderExecutor)
- Проверка балансов
- Управление manual_pools
- Интеграция с ARM для адаптивных размеров
"""

from typing import Optional, Tuple

from loguru import logger


class RiskManager:
    """
    Менеджер рисков для Spot стратегии.

    Централизует всю логику расчета рисков и размеров позиций.
    """

    def __init__(
        self,
        client,
        config,
        risk_config,
        full_config,
        adaptive_regime=None,
    ):
        """
        Args:
            client: OKX клиент
            config: Scalping конфигурация
            risk_config: Risk конфигурация
            full_config: Полный конфиг бота (для manual_pools)
            adaptive_regime: ARM модуль (опционально)
        """
        self.client = client
        self.config = config
        self.risk_config = risk_config
        self.full_config = full_config
        self.adaptive_regime = adaptive_regime

        # Минимальные размеры ордеров - ОТКЛЮЧЕНЫ для manual_pools!
        self.min_order_value_usd = (
            0.0  # 🔥 ОТКЛЮЧЕНО: Используем ТОЛЬКО manual_pools параметры!
        )

        logger.info("✅ RiskManager initialized")

    async def calculate_position_size(self, symbol: str, price: float) -> float:
        """
        Расчет размера позиции на основе риск-менеджмента.

        Использует manual_pools из конфига с учетом текущего режима рынка (ARM).

        Args:
            symbol: Торговый символ
            price: Текущая цена

        Returns:
            float: Размер позиции (0 при ошибке)
        """
        logger.info(f"🔍 CALCULATING POSITION SIZE for {symbol} @ ${price:.2f}")
        try:
            # Получаем баланс USDT
            balances = await self.client.get_account_balance()
            base_balance = next(
                (b.free for b in balances if b.currency == "USDT"),
                0.0,
            )

            logger.info(f"💰 USDT Balance: ${base_balance:.2f}")

            if base_balance <= 0:
                logger.warning(f"❌ No USDT balance for {symbol}")
                return 0.0

            # 🔥 КРИТИЧНО: Manual Pool Allocation из конфига!
            # Получаем текущий режим рынка
            current_regime = await self._get_current_regime()

            # Получаем manual_pools из конфига
            manual_pools = self.full_config.manual_pools

            if not manual_pools:
                logger.error("❌ Manual pools не найдены в конфиге!")
                return 0.0

            # Определяем размер позиции по режиму и активу из manual_pools
            quantity = 0.0

            if current_regime == "TRENDING":
                if symbol == "ETH-USDT":
                    quantity = manual_pools["eth_pool"]["trending"][
                        "quantity_per_trade"
                    ]
                    logger.info(
                        f"🎯 TRENDING ETH: {quantity} ETH (≈ ${quantity * price:.2f})"
                    )
                elif symbol == "BTC-USDT":
                    quantity = manual_pools["btc_pool"]["trending"][
                        "quantity_per_trade"
                    ]
                    logger.info(
                        f"🎯 TRENDING BTC: {quantity} BTC (≈ ${quantity * price:.2f})"
                    )
            elif current_regime == "RANGING":
                if symbol == "ETH-USDT":
                    quantity = manual_pools["eth_pool"]["ranging"]["quantity_per_trade"]
                    logger.info(
                        f"🎯 RANGING ETH: {quantity} ETH (≈ ${quantity * price:.2f})"
                    )
                elif symbol == "BTC-USDT":
                    quantity = manual_pools["btc_pool"]["ranging"]["quantity_per_trade"]
                    logger.info(
                        f"🎯 RANGING BTC: {quantity} BTC (≈ ${quantity * price:.2f})"
                    )
            elif current_regime == "CHOPPY":
                if symbol == "ETH-USDT":
                    quantity = manual_pools["eth_pool"]["choppy"]["quantity_per_trade"]
                    logger.info(
                        f"🎯 CHOPPY ETH: {quantity} ETH (≈ ${quantity * price:.2f})"
                    )
                elif symbol == "BTC-USDT":
                    quantity = manual_pools["btc_pool"]["choppy"]["quantity_per_trade"]
                    logger.info(
                        f"🎯 CHOPPY BTC: {quantity} BTC (≈ ${quantity * price:.2f})"
                    )

            if quantity <= 0:
                logger.warning(
                    f"❌ No quantity defined for {symbol} in {current_regime} mode"
                )
                return 0.0

            # Проверяем баланс актива
            if symbol == "ETH-USDT":
                eth_balance = await self.client.get_balance("ETH")
                if eth_balance < quantity:
                    logger.warning(
                        f"❌ Недостаточно ETH: {eth_balance:.6f} < {quantity:.6f}"
                    )
                    return 0.0
            elif symbol == "BTC-USDT":
                btc_balance = await self.client.get_balance("BTC")
                if btc_balance < quantity:
                    logger.warning(
                        f"❌ Недостаточно BTC: {btc_balance:.8f} < {quantity:.8f}"
                    )
                    return 0.0

            # Проверка минимума
            position_value_usd = quantity * price
            logger.info(
                f"📊 Final position size: {quantity:.6f} = "
                f"${position_value_usd:.2f} (min: ${self.min_order_value_usd})"
            )

            if position_value_usd < self.min_order_value_usd:
                # КРИТИЧНО: Проверяем баланс ПЕРЕД увеличением позиции!
                required_value = self.min_order_value_usd * 1.02
                balances_check = await self.client.get_account_balance()

                # balances_check может быть списком, словарем или объектом Balance
                usdt_balance = self._extract_usdt_balance(balances_check)

                if usdt_balance < required_value:
                    logger.error(
                        f"🚨 {symbol} НЕДОСТАТОЧНО СРЕДСТВ для увеличения позиции!"
                    )
                    logger.error(
                        f"💰 Требуется: ${required_value:.2f}, Доступно: ${usdt_balance:.2f}"
                    )
                    logger.error(f"🚫 СДЕЛКА ЗАБЛОКИРОВАНА - НЕ БЕРЕМ ЗАЙМЫ!")
                    return 0.0

                # Увеличиваем размер до минимума
                quantity = (self.min_order_value_usd * 1.02) / price
                final_value = quantity * price
                logger.info(
                    f"⬆️ {symbol} Position size increased: "
                    f"${position_value_usd:.2f} → ${final_value:.2f}"
                )

            # Округление
            rounded_size = round(quantity, 8)
            return rounded_size

        except Exception as e:
            logger.error(f"❌ Error calculating position size: {e}")
            return 0.0

    def _extract_usdt_balance(self, balances_check) -> float:
        """
        Извлекает USDT баланс из различных форматов ответа.

        Args:
            balances_check: Баланс в различных форматах

        Returns:
            float: USDT баланс
        """
        usdt_balance = 0.0

        if isinstance(balances_check, list):
            for balance in balances_check:
                if hasattr(balance, "currency") and balance.currency == "USDT":
                    # Проверяем разные атрибуты для доступного баланса
                    if hasattr(balance, "available"):
                        usdt_balance = float(balance.available)
                    elif hasattr(balance, "free"):
                        usdt_balance = float(balance.free)
                    elif hasattr(balance, "balance"):
                        usdt_balance = float(balance.balance)
                    break
                elif isinstance(balance, dict) and balance.get("currency") == "USDT":
                    usdt_balance = float(balance.get("available", 0.0))
                    break
        elif hasattr(balances_check, "get"):
            usdt_balance = balances_check.get("USDT", 0.0)
        else:
            # Это объект Balance
            if hasattr(balances_check, "USDT"):
                usdt_balance = float(balances_check.USDT)

        return usdt_balance

    async def _get_current_regime(self) -> str:
        """
        Получает текущий режим рынка от ARM.

        Returns:
            str: Режим рынка (TRENDING/RANGING/CHOPPY)
        """
        try:
            if self.adaptive_regime:
                # ARM имеет атрибут current_regime
                if hasattr(self.adaptive_regime, "current_regime"):
                    regime = self.adaptive_regime.current_regime.value
                    return regime.upper()
                # Или метод get_current_regime()
                elif hasattr(self.adaptive_regime, "get_current_regime"):
                    regime = await self.adaptive_regime.get_current_regime()
                    return regime.upper()

            # Fallback: определяем по волатильности
            return "RANGING"  # По умолчанию

        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить режим рынка: {e}")
            return "RANGING"  # Fallback

    def calculate_exit_levels(
        self, entry_price: float, side: str, atr: Optional[float] = None
    ) -> Tuple[float, float]:
        """
        Расчет уровней TP/SL на основе ATR.

        Args:
            entry_price: Цена входа
            side: Сторона сделки ("buy" или "sell")
            atr: ATR значение (опционально)

        Returns:
            Tuple[float, float]: (take_profit, stop_loss)
        """
        try:
            # Получаем параметры из конфига
            tp_multiplier = getattr(self.config, "tp_atr_multiplier", 2.0)
            sl_multiplier = getattr(self.config, "sl_atr_multiplier", 1.5)

            # Если ATR не передан - используем фиксированные проценты
            if not atr or atr <= 0:
                tp_percent = getattr(self.config, "take_profit_percent", 0.004)  # 0.4%
                sl_percent = getattr(self.config, "stop_loss_percent", 0.003)  # 0.3%

                if side.lower() == "buy":
                    take_profit = entry_price * (1 + tp_percent)
                    stop_loss = entry_price * (1 - sl_percent)
                else:  # sell
                    take_profit = entry_price * (1 - tp_percent)
                    stop_loss = entry_price * (1 + sl_percent)

                logger.debug(
                    f"📊 Exit levels (fixed %): TP=${take_profit:.4f}, SL=${stop_loss:.4f}"
                )
                return take_profit, stop_loss

            # Расчет на основе ATR
            if side.lower() == "buy":
                take_profit = entry_price + (atr * tp_multiplier)
                stop_loss = entry_price - (atr * sl_multiplier)
            else:  # sell
                take_profit = entry_price - (atr * tp_multiplier)
                stop_loss = entry_price + (atr * sl_multiplier)

            logger.debug(
                f"📊 Exit levels (ATR): TP=${take_profit:.4f}, SL=${stop_loss:.4f} "
                f"(ATR={atr:.4f})"
            )

            return take_profit, stop_loss

        except Exception as e:
            logger.error(f"❌ Error calculating exit levels: {e}")
            # Fallback: фиксированные проценты
            if side.lower() == "buy":
                return entry_price * 1.004, entry_price * 0.997
            else:
                return entry_price * 0.996, entry_price * 1.003
