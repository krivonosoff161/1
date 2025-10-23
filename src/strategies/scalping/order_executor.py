"""
Исполнитель торговых ордеров.

Ответственность:
- Расчет размера позиции
- Размещение entry ордеров (MARKET)
- Размещение OCO ордеров (TP + SL)
- Обработка ошибок OKX
- Retry логика
"""

from datetime import datetime
from typing import Optional, Tuple

from loguru import logger

from src.models import (Order, OrderSide, OrderType, Position, PositionSide,
                        Signal)
from src.websocket_order_executor import WebSocketOrderExecutor


class OrderExecutor:
    """
    Исполнитель торговых ордеров.

    Отвечает за размещение ордеров на бирже и создание Position объектов.
    """

    def __init__(
        self, client, config, risk_config, balance_checker=None, adaptive_regime=None
    ):
        """
        Args:
            client: OKX клиент
            config: Scalping конфигурация
            risk_config: Risk конфигурация
            balance_checker: Balance Checker модуль (опционально)
            adaptive_regime: ARM модуль (опционально)
        """
        self.client = client
        self.config = config
        self.risk_config = risk_config
        self.balance_checker = balance_checker
        self.adaptive_regime = adaptive_regime

        # Market Data WebSocket для быстрых цен
        self.market_ws = None
        self.ws_connected = False

        # Минимальные размеры ордеров
        self.min_order_value_usd = (
            60.0  # 🔥 СНИЖЕНО: $35 → $60 (баланс для частых сделок!)
        )
        self.MIN_LONG_OCO = 60.0  # Для LONG OCO (синхронизировано!)
        self.MIN_SHORT_OCO = 60.0  # Для SHORT OCO (синхронизировано!)

    async def initialize_websocket(self):
        """Инициализация Market Data WebSocket для быстрых цен"""
        try:
            from src.market_data_websocket import MarketDataWebSocket

            self.market_ws = MarketDataWebSocket()
            self.ws_connected = await self.market_ws.connect()

            if self.ws_connected:
                logger.info("✅ Market Data WebSocket подключен для быстрых цен")

                # Подписываемся на цены торговых символов
                # Получаем символы из основного конфига
                from src.config import load_config

                main_config = load_config()
                for symbol in main_config.trading.symbols:
                    await self.market_ws.subscribe_ticker(symbol, self._on_price_update)
            else:
                logger.warning("⚠️ Market Data WebSocket не подключен, используем REST")

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации Market WebSocket: {e}")
            self.ws_connected = False

    async def _on_price_update(self, price: float, ticker_data: dict):
        """Обработка обновления цены через WebSocket"""
        symbol = ticker_data.get("instId")
        logger.debug(f"📊 {symbol}: {price} (WebSocket)")

        # Здесь можно добавить логику быстрого анализа
        # Например, проверка на быстрые сигналы

    async def cleanup_websocket(self):
        """Очистка WebSocket соединения"""
        if self.market_ws:
            await self.market_ws.disconnect()
            self.ws_connected = False
            logger.info("🔌 Market Data WebSocket отключен")

    async def _try_maker_order(
        self,
        signal,
        position_value: float,
        position_size: float,
        take_profit: float,
        stop_loss: float,
    ) -> Optional[Order]:
        """
        Попытка размещения POST-ONLY (Maker) ордера для экономии комиссий

        Args:
            signal: Торговый сигнал
            position_value: Размер позиции в USDT (для BUY)
            position_size: Размер позиции в монетах (для SELL)
            take_profit: Цена Take Profit
            stop_loss: Цена Stop Loss

        Returns:
            Order или None если POST-ONLY не сработал
        """
        try:
            # Получаем актуальную цену для POST-ONLY
            current_price = await self.client.get_current_price(signal.symbol)

            # Рассчитываем цену для POST-ONLY (более консервативно для Maker комиссий)
            if signal.side == OrderSide.BUY:
                # Для BUY: цена ниже рыночной для гарантированного Maker статуса
                maker_price = current_price * 0.9995  # -0.05% (безопасная дистанция)
                maker_quantity = position_value / maker_price
            else:
                # Для SELL: цена выше рыночной для гарантированного Maker статуса
                maker_price = current_price * 1.0005  # +0.05% (безопасная дистанция)
                maker_quantity = position_size

            logger.info(f"🎯 POST-ONLY attempt: {signal.symbol} {signal.side.value}")
            logger.info(f"   Market: ${current_price:.4f} → Maker: ${maker_price:.4f}")
            logger.info(f"   Quantity: {maker_quantity:.8f}")

            # Размещаем POST-ONLY ордер
            order = await self.client.place_order(
                symbol=signal.symbol,
                side=signal.side,
                order_type=OrderType.LIMIT,
                quantity=maker_quantity,
                price=maker_price,
                post_only=True,  # Ключевой параметр для Maker
            )

            if order:
                logger.info(f"✅ POST-ONLY успешен: {order.id} (Maker fee: 0.08%)")
                return order
            else:
                logger.warning("⚠️ POST-ONLY не сработал, fallback на MARKET")
                return None

        except Exception as e:
            logger.warning(f"⚠️ POST-ONLY error: {e}, fallback на MARKET")
            return None

        logger.info("✅ OrderExecutor initialized")

    async def execute_signal(self, signal: Signal, market_data) -> Optional[Position]:
        """
        Исполнить торговый сигнал.

        Шаги:
        1. Рассчитать position_size
        2. Проверить баланс через Balance Checker
        3. Проверить займы (КРИТИЧНО!)
        4. Разместить entry ордер (MARKET)
        5. Получить фактический баланс (для LONG)
        6. Рассчитать TP/SL
        7. Разместить OCO ордер
        8. Создать Position объект

        Args:
            signal: Торговый сигнал
            market_data: Рыночные данные для расчета ATR

        Returns:
            Position или None при ошибке
        """
        try:
            # 1. Расчет размера позиции
            position_size = await self._calculate_position_size(
                signal.symbol, signal.price
            )

            if position_size <= 0:
                logger.warning(f"❌ Invalid position size for {signal.symbol}")
                return None

            # 2. Balance Checker - проверка баланса
            if self.balance_checker:
                balances = await self.client.get_account_balance()

                # 3. КРИТИЧНО! Проверка займов
                base_asset = signal.symbol.split("-")[0]
                quote_asset = signal.symbol.split("-")[1]

                try:
                    borrowed_base = await self.client.get_borrowed_balance(base_asset)
                    borrowed_quote = await self.client.get_borrowed_balance(quote_asset)

                    if borrowed_base > 0 or borrowed_quote > 0:
                        logger.error(
                            f"⛔ {signal.symbol} {signal.side.value} BLOCKED: "
                            f"BORROWED FUNDS DETECTED! "
                            f"{base_asset}: {borrowed_base:.6f} | "
                            f"{quote_asset}: {borrowed_quote:.6f}"
                        )
                        logger.error(
                            "🚨 TRADING SUSPENDED! Repay loans and switch to SPOT mode!"
                        )
                        return None
                except Exception as e:
                    logger.error(f"❌ Failed to check borrowed balance: {e}")
                    logger.error(
                        "⛔ Trade blocked due to borrowed balance check failure"
                    )
                    return None

                # Проверка баланса через Balance Checker
                balance_check = self.balance_checker.check_balance(
                    symbol=signal.symbol,
                    side=signal.side,
                    required_amount=position_size,
                    current_price=signal.price,
                    balances=balances,
                )

                if not balance_check.allowed:
                    logger.warning(
                        f"⛔ {signal.symbol} {signal.side.value} "
                        f"BLOCKED by Balance Checker: {balance_check.reason}"
                    )
                    return None

            # 3. Дополнительная защита SHORT без актива
            if signal.side == OrderSide.SELL:
                base_asset = signal.symbol.split("-")[0]
                asset_balance = await self.client.get_balance(base_asset)

                if asset_balance < position_size:
                    logger.error(
                        f"🚨 {signal.symbol} SHORT BLOCKED: No {base_asset} on balance! "
                        f"Have: {asset_balance:.8f}, Need: {position_size:.8f}"
                    )
                    return None

            # 4. Рассчитать TP/SL
            # Используем ATR из signal.indicators (уже рассчитан в SignalGenerator)
            atr = signal.indicators.get("ATR")
            if not atr:
                logger.warning(f"❌ No ATR in signal indicators for {signal.symbol}")
                logger.debug(
                    f"   Available indicators: {list(signal.indicators.keys())}"
                )
                return None

            stop_loss, take_profit = self._calculate_exit_levels(
                signal.price, signal.side, atr
            )

            # 5. Проверка минимума для OCO
            min_position_value = (
                self.MIN_LONG_OCO
                if signal.side == OrderSide.BUY
                else self.MIN_SHORT_OCO
            )
            position_value = position_size * signal.price

            if position_value < min_position_value:
                required_value = min_position_value * 1.05
                old_size = position_size
                position_size = round(required_value / signal.price, 8)
                new_value = position_size * signal.price

                logger.info(
                    f"⬆️ Position size increased for OCO: "
                    f"{old_size:.6f} → {position_size:.6f} "
                    f"(${position_value:.2f} → ${new_value:.2f})"
                )
                position_value = new_value

            # 6. Размещение entry ордера (WebSocket или REST)
            order = None

            # Попытка WebSocket (быстрый вход)
            if False:  # WebSocket торговля отключена, используем только REST
                try:
                    # Проверяем, что WebSocket все еще подключен
                    if not self.ws_executor.connected or self.ws_executor.ws.closed:
                        logger.warning(
                            "⚠️ WebSocket disconnected, attempting reconnection..."
                        )
                        # Попытка переподключения
                        if await self.ws_executor.reconnect():
                            logger.info(
                                "✅ WebSocket переподключен, продолжаем с WebSocket"
                            )
                        else:
                            logger.warning(
                                "⚠️ WebSocket переподключение не удалось, falling back to REST"
                            )
                            order = None  # Переходим к REST

                    # Если WebSocket подключен, пробуем разместить ордер
                    if self.ws_executor.connected and not self.ws_executor.ws.closed:
                        logger.info(
                            f"🚀 WebSocket entry attempt: {signal.symbol} {signal.side.value}"
                        )

                        if signal.side == OrderSide.BUY:
                            # Для BUY передаем сумму в USDT
                            order = await self.ws_executor.place_market_order(
                                symbol=signal.symbol,
                                side=signal.side,
                                quantity=position_value,  # Сумма в USDT
                                price=signal.price,
                            )
                        else:
                            # Для SELL передаем количество монет
                            order = await self.ws_executor.place_market_order(
                                symbol=signal.symbol,
                                side=signal.side,
                                quantity=position_size,  # Количество монет
                                price=signal.price,
                            )

                        if order:
                            logger.info(f"✅ WebSocket entry successful: {order.id}")
                        else:
                            logger.warning(
                                "⚠️ WebSocket entry failed, falling back to REST"
                            )
                            order = None

                except Exception as e:
                    logger.error(f"❌ WebSocket entry error: {e}")
                    logger.info("🔄 Falling back to REST API")

            # Fallback на REST API с Maker-First Strategy
            if not order:
                # Попытка POST-ONLY (Maker) для экономии комиссий
                order = await self._try_maker_order(
                    signal, position_value, position_size, take_profit, stop_loss
                )

                # Если POST-ONLY не сработал - используем MARKET
                if not order:
                    if signal.side == OrderSide.BUY:
                        logger.info(
                            f"📤 REST MARKET LONG order: BUY ${position_value:.2f} USDT "
                            f"{signal.symbol} @ ${signal.price:.2f}"
                        )
                        logger.info(
                            f"   📊 TP/SL: TP=${take_profit:.2f}, SL=${stop_loss:.2f}"
                        )

                        # REST MARKET ордер (0.1% комиссия)
                        order = await self.client.place_order(
                            symbol=signal.symbol,
                            side=signal.side,
                            order_type=OrderType.MARKET,
                            quantity=position_value,  # Сумма в USDT
                        )
                    else:
                        logger.info(
                            f"📤 REST MARKET SHORT order: SELL {position_size} "
                            f"{signal.symbol} @ ${signal.price:.2f}"
                        )
                        logger.info(
                            f"   📊 TP/SL: TP=${take_profit:.2f}, SL=${stop_loss:.2f}"
                        )

                        # REST MARKET ордер (0.1% комиссия)
                        order = await self.client.place_order(
                            symbol=signal.symbol,
                            side=signal.side,
                            order_type=OrderType.MARKET,
                            quantity=position_size,  # Количество монет
                        )

            if not order:
                logger.error(f"❌ Order placement FAILED: {signal.symbol}")
                return None

            # 7. Определение фактического размера
            if signal.side == OrderSide.BUY:
                actual_position_size = position_value / signal.price
                logger.info(
                    f"📊 BUY completed: position size {actual_position_size:.8f} "
                    f"(${position_value:.2f} @ ${signal.price:.2f})"
                )
            else:
                actual_position_size = position_size
                logger.info(
                    f"📊 SELL completed: position size {actual_position_size:.8f}"
                )

            # 8. Создание Position объекта
            position = Position(
                id=order.id,
                symbol=signal.symbol,
                side=PositionSide.LONG
                if signal.side == OrderSide.BUY
                else PositionSide.SHORT,
                entry_price=signal.price,
                current_price=signal.price,
                size=actual_position_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                timestamp=datetime.utcnow(),
            )

            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(
                f"✅ POSITION OPENED: {signal.symbol} {position.side.value.upper()}"
            )
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"   Order ID: {order.id}")
            logger.info(f"   Side: {signal.side.value.upper()}")
            logger.info(
                f"   Size: {actual_position_size:.8f} {signal.symbol.split('-')[0]}"
            )
            logger.info(f"   Entry: ${signal.price:.2f}")
            logger.info(f"   Take Profit: ${take_profit:.2f}")
            logger.info(f"   Stop Loss: ${stop_loss:.2f}")
            rr_ratio = abs(take_profit - signal.price) / abs(signal.price - stop_loss)
            logger.info(f"   Risk/Reward: 1:{rr_ratio:.2f}")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # 9. Размещение OCO ордера
            # 🔥 КРИТИЧНЫЙ ФИКС #2: Обработка ошибок OCO!
            try:
                close_side = (
                    OrderSide.SELL if signal.side == OrderSide.BUY else OrderSide.BUY
                )

                # 🔥 НОВЫЙ ФИКС: Проверяем актуальную цену перед OCO
                # (защита от проскальзывания между MARKET и OCO)
                current_price = await self.client.get_current_price(signal.symbol)
                logger.debug(
                    f"   💹 Price check: Entry=${signal.price:.2f}, "
                    f"Current=${current_price:.2f}"
                )

                # Корректируем TP/SL если цена сильно ушла
                adjusted_tp = take_profit
                adjusted_sl = stop_loss

                if signal.side == OrderSide.BUY:  # LONG позиция
                    # SL должен быть НИЖЕ текущей цены
                    if stop_loss >= current_price:
                        adjusted_sl = current_price * 0.995  # -0.5% от текущей
                        logger.warning(
                            f"⚠️ Price moved DOWN! Adjusting SL: "
                            f"${stop_loss:.2f} → ${adjusted_sl:.2f}"
                        )
                    # TP должен быть ВЫШЕ текущей цены
                    if take_profit <= current_price:
                        adjusted_tp = current_price * 1.005  # +0.5% от текущей
                        logger.warning(
                            f"⚠️ Price moved UP! Adjusting TP: "
                            f"${take_profit:.2f} → ${adjusted_tp:.2f}"
                        )
                else:  # SHORT позиция
                    # SL должен быть ВЫШЕ текущей цены
                    if stop_loss <= current_price:
                        adjusted_sl = current_price * 1.005  # +0.5% от текущей
                        logger.warning(
                            f"⚠️ Price moved UP! Adjusting SL: "
                            f"${stop_loss:.2f} → ${adjusted_sl:.2f}"
                        )
                    # TP должен быть НИЖЕ текущей цены
                    if take_profit >= current_price:
                        adjusted_tp = current_price * 0.995  # -0.5% от текущей
                        logger.warning(
                            f"⚠️ Price moved DOWN! Adjusting TP: "
                            f"${take_profit:.2f} → ${adjusted_tp:.2f}"
                        )

                # Обновляем в Position если скорректировали
                if adjusted_tp != take_profit or adjusted_sl != stop_loss:
                    position.take_profit = adjusted_tp
                    position.stop_loss = adjusted_sl
                    logger.info(
                        f"✏️ Position TP/SL updated: TP=${adjusted_tp:.2f}, "
                        f"SL=${adjusted_sl:.2f}"
                    )

                oco_order_id = await self.client.place_oco_order(
                    symbol=signal.symbol,
                    side=close_side,
                    quantity=actual_position_size,
                    tp_trigger_price=adjusted_tp,
                    sl_trigger_price=adjusted_sl,
                )

                if oco_order_id:
                    position.algo_order_id = oco_order_id
                    logger.info(
                        f"✅ OCO order placed: ID={oco_order_id} | "
                        f"TP @ ${take_profit:.2f}, SL @ ${stop_loss:.2f}"
                    )
                else:
                    logger.warning(
                        f"⚠️ OCO order returned None for {signal.symbol} - "
                        f"position without automatic TP/SL protection!"
                    )

            except Exception as e:
                logger.error(
                    f"❌ OCO FAILED for {signal.symbol}:\n"
                    f"   Error: {e}\n"
                    f"   TP: ${take_profit:.4f}, SL: ${stop_loss:.4f}\n"
                    f"   Quantity: {actual_position_size:.8f}\n"
                    f"   Side: {close_side.value}\n"
                    f"   ⚠️ Position will be managed by TIME_LIMIT only!"
                )
                # Продолжаем БЕЗ OCO (позиция будет закрыта по TIME_LIMIT)

            return position

        except Exception as e:
            logger.error(
                f"❌ Error executing signal {signal.symbol}: {e}", exc_info=True
            )
            return None

    async def _calculate_position_size(self, symbol: str, price: float) -> float:
        """
        Расчет размера позиции на основе риск-менеджмента.

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

            # Расчет risk amount (1% от баланса)
            risk_amount = base_balance * (self.risk_config.risk_per_trade_percent / 100)
            logger.info(
                f"🎯 Risk amount: ${risk_amount:.2f} "
                f"({self.risk_config.risk_per_trade_percent}%)"
            )

            # Получаем ATR для расчета stop distance

            # Предполагаем что market_data уже есть в кэше
            # TODO: передавать market_data или использовать кэш
            # Упрощенный расчет (будет улучшен)
            atr_value = price * 0.01  # 1% от цены как fallback

            # ARM параметры SL
            sl_multiplier = self.config.exit.stop_loss_atr_multiplier
            if self.adaptive_regime:
                regime_params = self.adaptive_regime.get_current_parameters()
                sl_multiplier = regime_params.sl_atr_multiplier

            stop_distance = atr_value * sl_multiplier

            # Position size = risk / stop_distance
            position_size = risk_amount / stop_distance

            # Лимит максимального размера
            max_position_value = base_balance * (
                self.risk_config.max_position_size_percent / 100
            )
            max_position_size = max_position_value / price

            final_position_size = min(position_size, max_position_size)

            # ARM - корректировка размера
            if self.adaptive_regime:
                regime_params = self.adaptive_regime.get_current_parameters()
                multiplier = regime_params.position_size_multiplier
                final_position_size *= multiplier
                logger.debug(
                    f"🧠 ARM: {self.adaptive_regime.current_regime.value.upper()} "
                    f"→ size multiplier {multiplier}x"
                )

            # Проверка минимума
            position_value_usd = final_position_size * price
            logger.info(
                f"📊 Final position size: {final_position_size:.6f} = "
                f"${position_value_usd:.2f} (min: ${self.min_order_value_usd})"
            )

            if position_value_usd < self.min_order_value_usd:
                final_position_size = (self.min_order_value_usd * 1.02) / price
                final_value = final_position_size * price
                logger.info(
                    f"⬆️ {symbol} Position size increased: "
                    f"${position_value_usd:.2f} → ${final_value:.2f}"
                )

                # Повторная проверка баланса после увеличения
                if self.balance_checker:
                    balances_check = await self.client.get_account_balance()
                    balance_result = self.balance_checker._check_usdt_balance(
                        symbol, final_position_size, price, balances_check
                    )

                    if not balance_result.allowed:
                        logger.error(
                            f"⛔ {symbol}: Insufficient balance after increase! "
                            f"{balance_result.reason}"
                        )
                        return 0.0

            # Округление
            rounded_size = round(final_position_size, 8)
            return rounded_size

        except Exception as e:
            logger.error(f"❌ Error calculating position size: {e}")
            return 0.0

    def _calculate_exit_levels(
        self, entry_price: float, side: OrderSide, atr: float
    ) -> Tuple[float, float]:
        """
        Расчет уровней TP/SL на основе ATR.

        Args:
            entry_price: Цена входа
            side: Направление позиции
            atr: ATR value

        Returns:
            (stop_loss, take_profit)
        """
        # ARM параметры или дефолтные
        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            sl_multiplier = regime_params.sl_atr_multiplier
            tp_multiplier = regime_params.tp_atr_multiplier
        else:
            sl_multiplier = self.config.exit.stop_loss_atr_multiplier
            tp_multiplier = self.config.exit.take_profit_atr_multiplier

        stop_distance = atr * sl_multiplier
        profit_distance = atr * tp_multiplier

        if side == OrderSide.BUY:
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + profit_distance
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - profit_distance

        return stop_loss, take_profit

    async def _get_atr(self, symbol: str, market_data) -> Optional[float]:
        """Получить ATR из индикаторов"""
        try:
            from src.indicators import IndicatorManager

            indicators_mgr = IndicatorManager()
            # Временный способ - нужно улучшить
            # TODO: получать из переданных данных
            indicators = indicators_mgr.calculate_all(market_data)
            atr_result = indicators.get("ATR")
            return atr_result.value if atr_result else None
        except Exception as e:
            logger.error(f"❌ Failed to get ATR: {e}")
            return None
