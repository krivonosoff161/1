"""
Менеджер торговых позиций.

Ответственность:
- Мониторинг открытых позиций
- Обновление цен и PnL
- Проверка OCO статуса
- Profit Harvesting (досрочный выход)
- Закрытие по TIME_LIMIT
- Partial TP
- PHANTOM detection
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from loguru import logger

from src.models import OrderSide, OrderType, Position, PositionSide


@dataclass
class TradeResult:
    """Результат закрытия сделки"""

    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    gross_pnl: float
    commission: float
    net_pnl: float
    duration_sec: float
    reason: str
    timestamp: datetime


class PositionManager:
    """
    Менеджер позиций.

    Отвечает за мониторинг и закрытие позиций.
    """

    def __init__(self, client, config, adaptive_regime=None):
        """
        Args:
            client: OKX клиент
            config: Scalping конфигурация
            adaptive_regime: ARM модуль (опционально)
        """
        self.client = client
        self.config = config
        self.adaptive_regime = adaptive_regime

        # Параметры
        self.min_close_value_usd = 15.0

        # ✨ PROFIT HARVESTING: Теперь берем из ARM! (адаптивный под режим)
        # Default значения (если ARM не инициализирован)
        self.profit_harvesting_enabled = False
        self.quick_profit_threshold = 0.20
        self.quick_profit_time_limit = 120

        # Если ARM есть - берем параметры из текущего режима
        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            self.profit_harvesting_enabled = regime_params.ph_enabled
            self.quick_profit_threshold = regime_params.ph_threshold
            self.quick_profit_time_limit = regime_params.ph_time_limit

            logger.info(
                f"✅ PositionManager initialized | "
                f"Profit Harvesting: ADAPTIVE (from ARM)"
            )
            logger.debug(
                f"   🔍 PH параметры из ARM режима '{self.adaptive_regime.current_regime.value}':\n"
                f"      Enabled: {self.profit_harvesting_enabled}\n"
                f"      Threshold: ${self.quick_profit_threshold:.2f}\n"
                f"      Time Limit: {self.quick_profit_time_limit}s"
            )
        else:
            logger.info(
                f"✅ PositionManager initialized | "
                f"Profit Harvesting: {'ON' if self.profit_harvesting_enabled else 'OFF'} "
                f"(${self.quick_profit_threshold} in {self.quick_profit_time_limit}s)"
            )

        # Partial TP
        self.partial_tp_enabled = getattr(config, "partial_tp_enabled", False)

    async def monitor_positions(
        self, positions: Dict[str, Position], current_prices: Dict[str, float]
    ) -> List[Tuple[str, str]]:
        """
        Мониторинг всех позиций.

        Проверяет:
        1. OCO статус (TP/SL сработал?)
        2. Profit Harvesting (досрочный выход)
        3. TIME_LIMIT (макс время удержания)
        4. Partial TP (частичные выходы)

        Args:
            positions: Словарь открытых позиций
            current_prices: Текущие цены по символам

        Returns:
            List[(symbol, reason)] - список позиций для закрытия
        """
        to_close = []

        for symbol, position in list(positions.items()):
            current_price = current_prices.get(symbol)
            if not current_price:
                continue

            # Обновляем цену позиции
            position.update_price(current_price)

            # 1. Проверка OCO статуса
            # ⚠️ ВРЕМЕННО ОТКЛЮЧЕНО: Invalid Sign блокирует проверку
            # if position.algo_order_id:
            #     oco_status = await self._check_oco_status(position)
            #     if oco_status:
            #         to_close.append((symbol, oco_status))
            #         continue

            # 2. ✨ PROFIT HARVESTING (досрочный выход с микро-профитом)
            # Обновляем PH параметры из ARM (если переключился режим)
            if self.adaptive_regime:
                regime_params = self.adaptive_regime.get_current_parameters()
                self.profit_harvesting_enabled = regime_params.ph_enabled
                self.quick_profit_threshold = regime_params.ph_threshold
                self.quick_profit_time_limit = regime_params.ph_time_limit

            if self.profit_harvesting_enabled:
                should_harvest = await self._check_profit_harvesting(
                    position, current_price
                )
                if should_harvest:
                    to_close.append((symbol, "profit_harvesting"))
                    continue

            # 3. TIME_LIMIT
            max_holding = self.config.exit.max_holding_minutes
            if self.adaptive_regime:
                regime_params = self.adaptive_regime.get_current_parameters()
                max_holding = regime_params.max_holding_minutes

            time_in_position = (
                datetime.utcnow() - position.timestamp
            ).total_seconds() / 60

            if time_in_position >= max_holding:
                to_close.append((symbol, "time_limit"))
                continue

            # 4. Partial TP (если включено)
            if self.partial_tp_enabled:
                await self._check_partial_tp(symbol, position, current_price)

        return to_close

    async def _check_oco_status(self, position: Position) -> Optional[str]:
        """
        Проверка статуса OCO ордера.

        Returns:
            str: Reason если OCO сработал, None иначе
        """
        try:
            oco_status = await self.client.get_algo_order_status(position.algo_order_id)

            if oco_status.get("state") == "filled":
                actual_px = float(oco_status.get("actualPx", 0))

                # Определяем что сработало
                if abs(actual_px - position.take_profit) < abs(
                    actual_px - position.stop_loss
                ):
                    reason = "oco_take_profit"
                else:
                    reason = "oco_stop_loss"

                logger.info(
                    f"✅ OCO triggered for {position.symbol}: "
                    f"{reason} @ ${actual_px:.4f}"
                )
                return reason

        except Exception as e:
            logger.debug(f"Failed to check OCO status: {e}")

        return None

    async def _check_profit_harvesting(
        self, position: Position, current_price: float
    ) -> bool:
        """
        ✨ PROFIT HARVESTING (из Perplexity AI + ARM адаптация)

        Досрочный выход если сразу в плюс!

        НОВОЕ (18.10.2025): Адаптивные параметры из ARM:
        - TRENDING: $0.16 за 60 сек (агрессивно!)
        - RANGING: $0.20 за 120 сек (сбалансированно)
        - CHOPPY: $0.25 за 180 сек (качественно!)

        Args:
            position: Текущая позиция
            current_price: Текущая цена

        Returns:
            bool: True если нужно закрыть
        """
        time_since_open = (datetime.utcnow() - position.timestamp).total_seconds()

        # Расчет текущего PnL в USD
        if position.side == PositionSide.LONG:
            # LONG: (exit - entry) * quantity
            pnl_usd = (current_price - position.entry_price) * position.size
            price_change_pct = (
                (current_price - position.entry_price) / position.entry_price
            ) * 100
        else:
            # SHORT: (entry - exit) * quantity
            pnl_usd = (position.entry_price - current_price) * position.size
            price_change_pct = (
                (position.entry_price - current_price) / position.entry_price
            ) * 100

        # 🔍 DEBUG: Логируем КАЖДУЮ проверку
        logger.debug(
            f"🔍 PH Check: {position.symbol} {position.side.value.upper()} | "
            f"Time: {time_since_open:.1f}s/{self.quick_profit_time_limit}s | "
            f"PnL: ${pnl_usd:.4f}/${self.quick_profit_threshold:.2f} | "
            f"Price Δ: {price_change_pct:+.3f}%"
        )

        # Проверка условий Profit Harvesting
        if (
            pnl_usd >= self.quick_profit_threshold
            and time_since_open < self.quick_profit_time_limit
        ):
            logger.info(
                f"💰 PROFIT HARVESTING TRIGGERED! {position.symbol} {position.side.value.upper()}\n"
                f"   Quick profit: ${pnl_usd:.4f} (threshold: ${self.quick_profit_threshold:.2f})\n"
                f"   Time: {time_since_open:.1f}s (limit: {self.quick_profit_time_limit}s)\n"
                f"   Price change: {price_change_pct:+.3f}%\n"
                f"   Entry: ${position.entry_price:.4f} → Exit: ${current_price:.4f}"
            )
            return True

        # Логируем почему НЕ сработало (если близко)
        if time_since_open < self.quick_profit_time_limit:
            if pnl_usd > 0 and pnl_usd >= self.quick_profit_threshold * 0.5:
                logger.debug(
                    f"   ⏳ PH близко: ${pnl_usd:.4f} / ${self.quick_profit_threshold:.2f} "
                    f"({pnl_usd/self.quick_profit_threshold*100:.0f}%)"
                )

        return False

    async def _check_partial_tp(
        self, symbol: str, position: Position, current_price: float
    ):
        """
        Проверка частичного Take Profit.

        (Пока оставляем как заглушку - можно добавить позже)
        """
        # TODO: Реализовать Partial TP если включен
        pass

    async def close_position(
        self, symbol: str, position: Position, current_price: float, reason: str
    ) -> Optional[TradeResult]:
        """
        Закрыть позицию.

        Шаги:
        1. Проверка PHANTOM (баланс < expected)
        2. Проверка min_close_value ($15)
        3. Проверка баланса для SHORT
        4. Размещение MARKET ордера закрытия
        5. Расчет комиссий + NET PnL
        6. Создание TradeResult

        Args:
            symbol: Торговый символ
            position: Позиция для закрытия
            current_price: Текущая цена
            reason: Причина закрытия

        Returns:
            TradeResult или None
        """
        try:
            # 1. PHANTOM detection
            if position.side == PositionSide.LONG:
                base_currency = symbol.split("-")[0]
                actual_balance = await self.client.get_balance(base_currency)

                # 🔧 ИСПРАВЛЕНО: Более мягкая проверка + учет времени
                if (
                    actual_balance < position.size * 0.95
                ):  # 95% толерантность (было 99%)
                    time_since_open = (
                        datetime.utcnow() - position.timestamp
                    ).total_seconds()

                    # Если позиция старая (>10 мин) - скорее всего PHANTOM
                    if time_since_open > 600:  # 10 минут (было 5 мин)
                        logger.error(
                            f"❌ PHANTOM position detected: {symbol}\n"
                            f"   Expected: {position.size:.8f}, Actual: {actual_balance:.8f}\n"
                            f"   Age: {time_since_open/60:.1f} min\n"
                            f"   Removing from tracking (likely closed on exchange)"
                        )
                        return None  # НЕ закрываем - уже закрыта!
                    else:
                        # Молодая позиция - возможно комиссия или округление
                        logger.warning(
                            f"⚠️ Suspicious position size: {symbol}\n"
                            f"   Expected: {position.size:.8f}, Actual: {actual_balance:.8f}\n"
                            f"   Difference: {(1 - actual_balance/position.size)*100:.2f}%\n"
                            f"   Age: {time_since_open:.1f}s\n"
                            f"   Proceeding with close..."
                        )

            # 2. Проверка минимума
            position_value = position.size * current_price

            if position_value < self.min_close_value_usd:
                logger.debug(
                    f"⚪ Position too small to close: ${position_value:.2f} < "
                    f"${self.min_close_value_usd}"
                )
                return None

            # 3. Проверка баланса для SHORT
            if position.side == PositionSide.SHORT:
                required_usdt = position.size * current_price * 1.01
                base_balance = await self.client.get_account_balance()
                usdt_available = next(
                    (b.free for b in base_balance if b.currency == "USDT"), 0.0
                )

                if usdt_available < required_usdt:
                    logger.warning(
                        f"⚠️ Cannot close SHORT {symbol}: "
                        f"Need ${required_usdt:.2f} USDT, have ${usdt_available:.2f}"
                    )
                    return None

            # 4. Размещение ордера закрытия
            order_side = (
                OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
            )

            logger.info(
                f"🔴 CLOSING ORDER: {order_side.value.upper()} {position.size:.8f} "
                f"{symbol} @ ${current_price:.4f} | Reason: {reason}"
            )

            close_order = await self.client.place_order(
                symbol=symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=position.size,
            )

            if not close_order:
                logger.error(f"❌ Failed to close position {symbol}")
                return None

            # 5. Расчет PnL с учетом комиссий
            duration_sec = (datetime.utcnow() - position.timestamp).total_seconds()

            # Gross PnL
            gross_pnl = position.unrealized_pnl

            # Комиссии (0.1% на вход + 0.1% на выход)
            commission_rate = 0.001
            open_value = position.size * position.entry_price
            close_value = position.size * current_price
            open_commission = open_value * commission_rate
            close_commission = close_value * commission_rate
            total_commission = open_commission + close_commission

            # NET PnL
            net_pnl = gross_pnl - total_commission

            # Детальное логирование
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"💰 TRADE CLOSED: {symbol} {position.side.value.upper()}")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"   Entry: ${position.entry_price:.4f}")
            logger.info(f"   Exit: ${current_price:.4f}")
            logger.info(f"   Size: {position.size:.8f}")
            logger.info(f"   Duration: {duration_sec:.0f}s ({duration_sec/60:.1f} min)")
            logger.info(f"   Gross PnL: ${gross_pnl:.4f}")
            logger.info(f"   Commission: -${total_commission:.4f}")
            logger.info(f"   NET PnL: ${net_pnl:.4f}")
            logger.info(f"   Reason: {reason}")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # Создание TradeResult
            trade_result = TradeResult(
                symbol=symbol,
                side=position.side.value,
                entry_price=position.entry_price,
                exit_price=current_price,
                size=position.size,
                gross_pnl=gross_pnl,
                commission=total_commission,
                net_pnl=net_pnl,
                duration_sec=duration_sec,
                reason=reason,
                timestamp=datetime.utcnow(),
            )

            return trade_result

        except Exception as e:
            logger.error(f"❌ Error closing position {symbol}: {e}", exc_info=True)
            return None

    async def update_position_prices(
        self, positions: Dict[str, Position], current_prices: Dict[str, float]
    ):
        """
        Обновление цен и PnL для всех позиций.

        Args:
            positions: Словарь открытых позиций
            current_prices: Текущие цены по символам
        """
        for symbol, position in positions.items():
            current_price = current_prices.get(symbol)
            if current_price:
                position.update_price(current_price)
