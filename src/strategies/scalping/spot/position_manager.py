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

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.models import OrderSide, OrderType, Position, PositionSide

from .batch_order_manager import BatchOrderManager


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

        # Batch Order Manager для группировки обновлений TP/SL
        self.batch_manager = BatchOrderManager(client)

        # Параметры
        self.min_close_value_usd = 15.0

        # ✨ PROFIT HARVESTING: Теперь берем из ARM! (адаптивный под режим)
        # Default значения (если ARM не инициализирован)
        self.profit_harvesting_enabled = False
        self.quick_profit_threshold = 0.20
        self.quick_profit_time_limit = 120

        # Если ARM есть - берем параметры из текущего режима
        if self.adaptive_regime:
            # Получаем параметры текущего режима (без balance_manager для инициализации)
            regime_params = self.adaptive_regime.get_current_parameters()
            if regime_params:
                self.profit_harvesting_enabled = regime_params.ph_enabled
                self.quick_profit_threshold = regime_params.ph_threshold
                self.quick_profit_time_limit = regime_params.ph_time_limit

            logger.info(
                "✅ PositionManager initialized | "
                "Profit Harvesting: ADAPTIVE (from ARM)"
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

            # 1. 🔥 ОТКЛЮЧЕНО: Проверка OCO через /trade/fills API (БАГ!)
            # Проблема: Находит СТАРЫЕ fills из истории → закрывает позиции через 7 сек
            # Решение: Полагаемся на OCO на бирже + PH + max_holding
            # if position.algo_order_id:
            #     fills_result = await self._check_fills_closure(position)
            #     ...

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

            # 3. ⏰ MAX HOLDING (страховка от зависших позиций)
            if self.adaptive_regime:
                max_holding = (
                    self.adaptive_regime.get_current_parameters().max_holding_minutes
                )
                time_since_open = (
                    datetime.utcnow() - position.timestamp
                ).total_seconds() / 60

                if time_since_open >= max_holding:
                    logger.warning(
                        f"⏰ MAX HOLDING EXCEEDED: {symbol} "
                        f"{position.side.value.upper()} | "
                        f"Time: {time_since_open:.1f} min / "
                        f"{max_holding} min | "
                        f"PnL: ${position.unrealized_pnl:.4f} | "
                        f"Closing at market..."
                    )
                    to_close.append((symbol, "max_holding_exceeded"))
                    continue

            # 4. Partial TP (если включено)
            if self.partial_tp_enabled:
                await self._check_partial_tp(symbol, position, current_price)

        return to_close

    async def _check_fills_closure(
        self, position: Position
    ) -> Optional[Tuple[str, float]]:
        """
        🔥 НОВЫЙ МЕТОД (18.10.2025): Проверка закрытия через /trade/fills API!

        САМЫЙ НАДЕЖНЫЙ способ отследить OCO закрытия (обход Invalid Sign).

        Логика:
        1. Получаем последние fills для символа
        2. Ищем fill с algoId == position.algo_order_id
        3. Определяем TP/SL по execType

        Returns:
            Optional[Tuple[str, float]]: (reason, exit_price) если закрыта, None иначе
        """
        try:
            if not position.algo_order_id:
                return None

            # Получаем последние fills за последние 5 минут
            fills = await self.client.get_recent_fills(symbol=position.symbol, limit=50)

            if not fills:
                return None

            # Ищем ЗАКРЫВАЮЩИЙ fill
            # 🔥 ИСПРАВЛЕНО (19.10.2025): algoId НЕТ в fills! Ищем по времени + стороне + execType

            position_open_ts = int(position.timestamp.timestamp() * 1000)

            for fill in fills:
                fill_ts = int(fill.get("ts", 0))
                fill_side = fill.get("side", "")
                fill_px = float(fill.get("fillPx", 0))
                exec_type = fill.get("execType", "")

                # Fill ПОСЛЕ открытия позиции?
                if fill_ts <= position_open_ts:
                    continue

                # Fill - это ЗАКРЫТИЕ нашей позиции?
                if position.side == PositionSide.LONG:
                    is_closing = fill_side == "sell"
                else:
                    is_closing = fill_side == "buy"

                if not is_closing:
                    continue

                # ✅ Это закрывающий fill!
                logger.debug(
                    f"🔍 Found closing fill for {position.symbol}: "
                    f"execType={exec_type}, fillPx={fill_px}, side={fill_side}, "
                    f"time_diff={(fill_ts - position_open_ts)/1000:.1f}s"
                )

                # Определяем причину по execType
                if exec_type == "T":
                    reason = "oco_take_profit"
                elif exec_type == "S":
                    reason = "oco_stop_loss"
                elif exec_type == "M":
                    reason = "manual_close"  # Закрыто вручную или ботом
                else:
                    # Fallback: по цене
                    if position.side == PositionSide.LONG:
                        reason = (
                            "oco_take_profit"
                            if fill_px >= position.take_profit * 0.999
                            else "oco_stop_loss"
                        )
                    else:
                        reason = (
                            "oco_take_profit"
                            if fill_px <= position.take_profit * 1.001
                            else "oco_stop_loss"
                        )

                logger.info(
                    f"💰 OCO ЗАКРЫТ НА БИРЖЕ: {position.symbol} | "
                    f"Reason: {reason} | Price: ${fill_px:.2f} | "
                    f"ExecType: {exec_type}"
                )

                return (reason, fill_px)

            return None

        except Exception as e:
            logger.debug(f"Fills closure check failed: {e}")
            return None

    async def _check_balance_closure(self, position: Position) -> bool:
        """
        ⚠️ DEPRECATED (18.10.2025): Используем _check_fills_closure() вместо этого!

        Проверка закрытия позиции через баланс (обход Invalid Sign!).

        Логика:
        - LONG: проверяем баланс BTC/ETH (если = 0 → закрыта биржей)
        - SHORT: не проверяем (нужен USDT, всегда есть)

        Returns:
            bool: True если позиция закрыта биржей
        """
        try:
            # Только для LONG (SHORT всегда имеет USDT баланс)
            if position.side != PositionSide.LONG:
                return False

            base_currency = position.symbol.split("-")[0]
            actual_balance = await self.client.get_balance(base_currency)

            # Если баланс < 1% от ожидаемого → позиция закрыта биржей
            if actual_balance < position.size * 0.01:
                logger.info(
                    f"🔍 Balance Check: {position.symbol} LONG закрыта биржей | "
                    f"Expected: {position.size:.8f}, Actual: {actual_balance:.8f}"
                )
                return True

            return False

        except Exception as e:
            logger.debug(f"Balance closure check failed: {e}")
            return False

    async def _check_oco_status(self, position: Position) -> Optional[str]:
        """
        Проверка статуса OCO ордера.

        КРИТИЧНО (18.10.2025): Правильное определение TP/SL для PnL!

        Returns:
            str: Reason если OCO сработал, None иначе
        """
        try:
            oco_status = await self.client.get_algo_order_status(position.algo_order_id)

            if not oco_status:
                return None

            state = oco_status.get("state")

            # 🔍 DEBUG: Логируем ЧТО получили от биржи
            logger.debug(
                f"🔍 OCO Status {position.symbol}: "
                f"state={state}, "
                f"actualSide={oco_status.get('actualSide')}, "
                f"actualPx={oco_status.get('actualPx')}"
            )

            if state == "filled":
                actual_side = oco_status.get("actualSide", "")
                actual_px = float(oco_status.get("actualPx", 0))

                # Определяем что сработало ПО actualSide (надежнее!)
                if actual_side == "tp":
                    reason = "oco_take_profit"
                elif actual_side == "sl":
                    reason = "oco_stop_loss"
                else:
                    # Fallback: по цене
                    if abs(actual_px - position.take_profit) < abs(
                        actual_px - position.stop_loss
                    ):
                        reason = "oco_take_profit"
                    else:
                        reason = "oco_stop_loss"

                logger.info(
                    f"💰 OCO FILLED: {position.symbol} | "
                    f"Reason: {reason} | "
                    f"Price: ${actual_px:.4f} | "
                    f"TP: ${position.take_profit:.4f} | "
                    f"SL: ${position.stop_loss:.4f}"
                )

                # Обновляем цену позиции на РЕАЛЬНУЮ цену закрытия от биржи!
                position.update_price(actual_px)

                return reason

        except Exception as e:
            logger.error(f"❌ Error checking OCO status {position.symbol}: {e}")

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

            # 4. Отменяем OCO ордер перед закрытием позиции
            if hasattr(position, "algo_order_id") and position.algo_order_id:
                try:
                    logger.info(
                        f"🔄 Cancelling OCO order {position.algo_order_id} before closing position"
                    )
                    await self.client.cancel_algo_order(position.algo_order_id, symbol)
                    logger.info(f"✅ OCO order {position.algo_order_id} cancelled")
                except Exception as e:
                    logger.warning(
                        f"⚠️ Failed to cancel OCO order {position.algo_order_id}: {e}"
                    )
                    # Продолжаем закрытие позиции даже если OCO не отменился

            # 5. Размещение ордера закрытия
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

            # 6. Расчет PnL с учетом комиссий
            duration_sec = (datetime.utcnow() - position.timestamp).total_seconds()

            # Gross PnL
            gross_pnl = position.unrealized_pnl

            # Комиссии OKX (адаптивные под тип ордера)
            # Определяем тип entry ордера по цене исполнения
            price_diff_pct = (
                abs(current_price - position.entry_price) / position.entry_price
            )

            if price_diff_pct < 0.001:  # < 0.1% разница = POST-ONLY (Maker)
                open_commission_rate = 0.0008  # POST-ONLY entry (MAKER)
                logger.debug(f"💰 Entry: POST-ONLY (Maker) - 0.08% комиссия")
            else:
                open_commission_rate = 0.001  # MARKET entry (TAKER)
                logger.debug(f"💰 Entry: MARKET (Taker) - 0.10% комиссия")

            close_commission_rate = 0.001  # MARKET exit (TAKER)
            open_value = position.size * position.entry_price
            close_value = position.size * current_price
            open_commission = open_value * open_commission_rate
            close_commission = close_value * close_commission_rate
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

    async def batch_update_tp_sl(
        self,
        symbol: str,
        tp_ord_id: str,
        sl_ord_id: str,
        new_tp_price: float,
        new_sl_price: float,
        new_tp_trigger: Optional[float] = None,
        new_sl_trigger: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Batch обновление TP/SL ордеров

        Args:
            symbol: Торговая пара
            tp_ord_id: ID Take Profit ордера
            sl_ord_id: ID Stop Loss ордера
            new_tp_price: Новая цена TP
            new_sl_price: Новая цена SL
            new_tp_trigger: Новый trigger для TP (опционально)
            new_sl_trigger: Новый trigger для SL (опционально)
        """
        try:
            logger.info(f"🔄 Batch updating TP/SL for {symbol}")
            logger.info(f"   TP: ${new_tp_price:.4f} (trigger: {new_tp_trigger})")
            logger.info(f"   SL: ${new_sl_price:.4f} (trigger: {new_sl_trigger})")

            # Используем Batch Order Manager
            result = await self.batch_manager.update_tp_sl_batch(
                inst_id=symbol,
                tp_ord_id=tp_ord_id,
                sl_ord_id=sl_ord_id,
                new_tp_price=f"{new_tp_price:.8f}",
                new_sl_price=f"{new_sl_price:.8f}",
                new_tp_trigger=f"{new_tp_trigger:.8f}" if new_tp_trigger else None,
                new_sl_trigger=f"{new_sl_trigger:.8f}" if new_sl_trigger else None,
            )

            if result.get("code") == "0":
                logger.info(f"✅ Batch TP/SL update successful for {symbol}")
            else:
                logger.error(
                    f"❌ Batch TP/SL update failed: {result.get('msg', 'Unknown error')}"
                )

            return result

        except Exception as e:
            logger.error(f"❌ Batch TP/SL update error: {e}")
            return {"code": "1", "msg": str(e), "data": []}

    async def flush_pending_updates(self) -> Dict[str, Any]:
        """Принудительный flush всех накопленных batch обновлений"""
        try:
            logger.info("🔄 Flushing pending batch updates...")
            result = await self.batch_manager.force_flush()

            if result.get("code") == "0":
                logger.info("✅ Batch updates flushed successfully")
            else:
                logger.error(
                    f"❌ Batch flush failed: {result.get('msg', 'Unknown error')}"
                )

            return result

        except Exception as e:
            logger.error(f"❌ Batch flush error: {e}")
            return {"code": "1", "msg": str(e), "data": []}

    def get_batch_stats(self) -> Dict[str, Any]:
        """Получить статистику batch операций"""
        return self.batch_manager.get_stats()
