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
        self,
        client,
        config,
        risk_config,
        balance_checker=None,
        adaptive_regime=None,
        risk_manager=None,
    ):
        """
        Args:
            client: OKX клиент
            config: Scalping конфигурация
            risk_config: Risk конфигурация
            balance_checker: Balance Checker модуль (опционально)
            adaptive_regime: ARM модуль (опционально)
            risk_manager: Risk Manager модуль (опционально)
        """
        self.client = client
        self.config = config
        self.risk_config = risk_config
        self.balance_checker = balance_checker
        self.adaptive_regime = adaptive_regime
        self.risk_manager = risk_manager  # 🆕 НОВОЕ: RiskManager для расчета размеров

        # Market Data WebSocket для быстрых цен
        self.market_ws = None
        self.ws_connected = False

        # Минимальные размеры ордеров - ОТКЛЮЧЕНЫ для manual_pools!
        self.min_order_value_usd = (
            0.0  # 🔥 ОТКЛЮЧЕНО: Используем ТОЛЬКО manual_pools параметры!
        )
        self.MIN_LONG_OCO = 0.0  # ОТКЛЮЧЕНО: manual_pools управляют размерами
        self.MIN_SHORT_OCO = 0.0  # ОТКЛЮЧЕНО: manual_pools управляют размерами

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
                maker_price = current_price * 0.9975  # -0.25% (увеличенная дистанция)
                maker_quantity = position_value / maker_price
            else:
                # Для SELL: цена выше рыночной для гарантированного Maker статуса
                maker_price = current_price * 1.0025  # +0.25% (увеличенная дистанция)
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

                # 3. КРИТИЧНО! Проверка займов (ОТКЛЮЧЕНО ДЛЯ ДЕМО АККАУНТА)
                base_asset = signal.symbol.split("-")[0]
                quote_asset = signal.symbol.split("-")[1]

                try:
                    # 🔥 КРИТИЧНО: Проверяем займы для ВСЕХ аккаунтов!
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

                # КРИТИЧЕСКАЯ ПРОВЕРКА БАЛАНСА - БЛОКИРУЕМ СДЕЛКУ ЕСЛИ НЕ ХВАТАЕТ ДЕНЕГ!
                balance_check = self.balance_checker.check_balance(
                    symbol=signal.symbol,
                    side=signal.side,
                    required_amount=position_size,
                    current_price=signal.price,
                    balances=balances,
                )

                if not balance_check.allowed:
                    logger.error(
                        f"🚨 {signal.symbol} {signal.side.value} "
                        f"BLOCKED: НЕДОСТАТОЧНО СРЕДСТВ! {balance_check.reason}"
                    )
                    logger.error(
                        f"💰 Доступно: ${balance_check.available_balance:.2f} {balance_check.currency}"
                    )
                    logger.error(
                        f"💰 Требуется: ${balance_check.required_balance:.2f} {balance_check.currency}"
                    )
                    logger.error(f"🚫 СДЕЛКА ЗАБЛОКИРОВАНА - НЕ БЕРЕМ ЗАЙМЫ!")
                    return None

            # 3. КРИТИЧЕСКАЯ ЗАЩИТА ОТ ЗАЙМОВ - ПРОВЕРЯЕМ БАЛАНС ПЕРЕД КАЖДОЙ СДЕЛКОЙ!
            if signal.side == OrderSide.SELL:
                base_asset = signal.symbol.split("-")[0]
                asset_balance = await self.client.get_balance(base_asset)

                if asset_balance < position_size:
                    logger.error(
                        f"🚨 {signal.symbol} SHORT BLOCKED: НЕДОСТАТОЧНО {base_asset}! "
                        f"Есть: {asset_balance:.8f}, Нужно: {position_size:.8f}"
                    )
                    logger.error(f"🚫 СДЕЛКА ЗАБЛОКИРОВАНА - НЕ БЕРЕМ ЗАЙМЫ!")
                    return None
            else:
                # Дополнительная проверка для BUY - убеждаемся что есть USDT
                quote_asset = signal.symbol.split("-")[1]
                quote_balance = await self.client.get_balance(quote_asset)
                required_quote = position_size * signal.price

                if quote_balance < required_quote:
                    logger.error(
                        f"🚨 {signal.symbol} BUY BLOCKED: НЕДОСТАТОЧНО {quote_asset}! "
                        f"Есть: {quote_balance:.2f}, Нужно: {required_quote:.2f}"
                    )
                    logger.error(f"🚫 СДЕЛКА ЗАБЛОКИРОВАНА - НЕ БЕРЕМ ЗАЙМЫ!")
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

            # 7. Определение фактического размера с учетом комиссий
            # Получаем реальные данные из ордера
            filled_sz = float(order.size) if hasattr(order, "size") else position_size
            fee = float(order.fee) if hasattr(order, "fee") else 0.0
            slippage_buffer = 0.0002  # 0.02% буфер

            # 🔧 КРИТИЧНО: Проверяем заполнение POST-ONLY ордера
            expected_size = (
                position_size
                if signal.side == OrderSide.SELL
                else position_value / signal.price
            )

            # Если заполнено менее 95% - это проблема
            if filled_sz < expected_size * 0.95:
                logger.warning(
                    f"⚠️ POST-ONLY частично заполнен: {filled_sz:.8f}/{expected_size:.8f} "
                    f"({(filled_sz/expected_size)*100:.1f}%)"
                )
                logger.warning(
                    f"   Возможные причины: недостаточная ликвидность, "
                    f"слишком близко к рынку, или быстрые изменения цены"
                )

            # Рассчитываем размер с учетом комиссий и буфера
            if signal.side == OrderSide.BUY:
                actual_position_size = filled_sz * (1 - fee - slippage_buffer)
                logger.info(
                    f"📊 BUY completed: filled={filled_sz:.8f}, fee={fee:.6f}, "
                    f"final_size={actual_position_size:.8f}"
                )
            else:
                actual_position_size = filled_sz * (1 - fee - slippage_buffer)
                logger.info(
                    f"📊 SELL completed: filled={filled_sz:.8f}, fee={fee:.6f}, "
                    f"final_size={actual_position_size:.8f}"
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

            # Проверяем займы после сделки - БЛОКИРУЕМ ПРИ ЛЮБЫХ ЗАЙМАХ!
            try:
                account_config = await self.client.get_account_config()
                if (
                    account_config.get("acctLv") == "1"
                    and account_config.get("posMode") == "long_short_mode"
                ):
                    # Демо аккаунт - проверяем займы после сделки
                    base_asset = signal.symbol.split("-")[0]
                    quote_asset = signal.symbol.split("-")[1]
                    borrowed_base = await self.client.get_borrowed_balance(base_asset)
                    borrowed_quote = await self.client.get_borrowed_balance(quote_asset)

                    if borrowed_base > 0 or borrowed_quote > 0:
                        logger.error(
                            f"🚨 ПОСЛЕ СДЕЛКИ ПОЯВИЛИСЬ ЗАЙМЫ: {base_asset}: {borrowed_base:.6f}, {quote_asset}: {borrowed_quote:.6f}"
                        )
                        logger.error(f"🚫 БОТ БУДЕТ ОСТАНОВЛЕН - НЕ ТОРГУЕМ С ЗАЙМАМИ!")
                        logger.error(
                            f"💰 Погасите займы вручную в OKX или переключитесь на SPOT режим"
                        )
                        # Закрываем позицию и останавливаем бота
                        await self.client.cancel_all_orders(signal.symbol)
                        return None
            except Exception as e:
                logger.warning(f"⚠️ Не удалось проверить займы после сделки: {e}")

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

                # 🔧 КРИТИЧНО: Используем manual_pools параметры для TP/SL!
                adjusted_tp = take_profit
                adjusted_sl = stop_loss

                # Получаем параметры из manual_pools
                try:
                    from src.config import load_config

                    full_config = load_config()
                    manual_pools = full_config.manual_pools

                    # Определяем текущий режим рынка
                    current_regime = await self._get_current_regime()

                    # Получаем параметры TP/SL из manual_pools для правильной пары
                    base_symbol = signal.symbol.split("-")[0].lower()
                    pool_key = f"{base_symbol}_pool"

                    if pool_key in manual_pools:
                        if current_regime == "TRENDING":
                            tp_percent = manual_pools[pool_key]["trending"][
                                "tp_percent"
                            ]
                            sl_percent = manual_pools[pool_key]["trending"][
                                "sl_percent"
                            ]
                        elif current_regime == "RANGING":
                            tp_percent = manual_pools[pool_key]["ranging"]["tp_percent"]
                            sl_percent = manual_pools[pool_key]["ranging"]["sl_percent"]
                        elif current_regime == "CHOPPY":
                            tp_percent = manual_pools[pool_key]["choppy"]["tp_percent"]
                            sl_percent = manual_pools[pool_key]["choppy"]["sl_percent"]
                        else:
                            tp_percent = 0.5  # Fallback
                            sl_percent = 0.35  # Fallback
                    else:
                        # Fallback для неизвестных пар
                        tp_percent = 0.5
                        sl_percent = 0.35

                    logger.info(f"🎯 Manual pools TP/SL: {tp_percent}%/{sl_percent}%")

                except Exception as e:
                    logger.error(f"❌ Ошибка получения manual_pools: {e}")
                    tp_percent = 0.5  # Fallback
                    sl_percent = 0.35  # Fallback

                # 🔧 КРИТИЧНО: Для BTC нужны большие отступы TP/SL
                if signal.symbol == "BTC-USDT":
                    tp_percent = max(tp_percent, 1.0)  # Минимум 1% для BTC TP
                    sl_percent = max(sl_percent, 0.8)  # Минимум 0.8% для BTC SL
                    logger.info(f"🎯 BTC Adjusted TP/SL: {tp_percent}%/{sl_percent}%")

                    # 🔧 КРИТИЧНО: Для BTC пересчитываем TP/SL с новыми процентами
                    if signal.side == OrderSide.BUY:  # LONG позиция
                        adjusted_tp = current_price * (1 + tp_percent / 100)
                        adjusted_sl = current_price * (1 - sl_percent / 100)
                        logger.info(
                            f"🎯 BTC Recalculated TP/SL: TP=${adjusted_tp:.2f}, SL=${adjusted_sl:.2f}"
                        )
                    else:  # SHORT позиция
                        adjusted_tp = current_price * (1 - tp_percent / 100)
                        adjusted_sl = current_price * (1 + sl_percent / 100)
                        logger.info(
                            f"🎯 BTC Recalculated TP/SL: TP=${adjusted_tp:.2f}, SL=${adjusted_sl:.2f}"
                        )

                    # Обновляем позицию с новыми TP/SL
                    position.tp_price = adjusted_tp
                    position.sl_price = adjusted_sl
                    logger.info(
                        f"✏️ Position TP/SL updated: TP=${adjusted_tp:.2f}, SL=${adjusted_sl:.2f}"
                    )
                else:
                    # Для других пар используем стандартную логику
                    if signal.side == OrderSide.BUY:  # LONG позиция
                        # SL должен быть НИЖЕ текущей цены
                        if stop_loss >= current_price:
                            adjusted_sl = current_price * (
                                1 - sl_percent / 100
                            )  # Используем manual_pools!
                            logger.warning(
                                f"⚠️ Price moved DOWN! Adjusting SL: "
                                f"${stop_loss:.2f} → ${adjusted_sl:.2f} ({sl_percent}%)"
                            )
                        # TP должен быть ВЫШЕ текущей цены
                        if take_profit <= current_price:
                            adjusted_tp = current_price * (
                                1 + tp_percent / 100
                            )  # Используем manual_pools!
                            logger.warning(
                                f"⚠️ Price moved UP! Adjusting TP: "
                                f"${take_profit:.2f} → ${adjusted_tp:.2f} ({tp_percent}%)"
                            )
                    else:  # SHORT позиция
                        # SL должен быть ВЫШЕ текущей цены
                        if stop_loss <= current_price:
                            adjusted_sl = current_price * (
                                1 + sl_percent / 100
                            )  # Используем manual_pools!
                        logger.warning(
                            f"⚠️ Price moved UP! Adjusting SL: "
                            f"${stop_loss:.2f} → ${adjusted_sl:.2f} ({sl_percent}%)"
                        )
                        # TP должен быть НИЖЕ текущей цены
                        if take_profit >= current_price:
                            adjusted_tp = current_price * (
                                1 - tp_percent / 100
                            )  # Используем manual_pools!
                            logger.warning(
                                f"⚠️ Price moved DOWN! Adjusting TP: "
                                f"${take_profit:.2f} → ${adjusted_tp:.2f} ({tp_percent}%)"
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

        Делегирует в RiskManager.

        Args:
            symbol: Торговый символ
            price: Текущая цена

        Returns:
            float: Размер позиции (0 при ошибке)
        """
        if self.risk_manager:
            return await self.risk_manager.calculate_position_size(symbol, price)
        else:
            logger.error("❌ RiskManager not initialized!")
            return 0.0

    async def _get_current_regime(self) -> str:
        """Получает текущий режим рынка от ARM"""
        try:
            if hasattr(self, "arm") and self.arm:
                regime = await self.arm.get_current_regime()
                return regime
            else:
                # Fallback: определяем по волатильности
                return "RANGING"  # По умолчанию
        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить режим рынка: {e}")
            return "RANGING"  # Fallback

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
        # Делегируем в RiskManager если доступен
        if self.risk_manager:
            take_profit, stop_loss = self.risk_manager.calculate_exit_levels(
                entry_price, side.value, atr
            )
            return stop_loss, take_profit

        # Fallback: ARM параметры или дефолтные
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
