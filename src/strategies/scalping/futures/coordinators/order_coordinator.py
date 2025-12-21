"""
Order Coordinator для Futures торговли.

Управляет мониторингом и обработкой ордеров:
- Мониторинг лимитных ордеров и их отмена/замена после таймаута
- Обновление статуса ордеров в кэше
- Управление кэшем последних ордеров
"""

import time
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger


class OrderCoordinator:
    """
    Координатор управления ордерами для Futures торговли.

    Отвечает за мониторинг лимитных ордеров, обновление статуса ордеров
    в кэше и управление жизненным циклом ордеров.
    """

    def __init__(
        self,
        client,
        order_executor,
        scalping_config,
        signal_generator,
        last_orders_cache_ref: Dict[str, Dict[str, Any]],  # Ссылка на кэш ордеров
    ):
        """
        Инициализация OrderCoordinator.

        Args:
            client: Futures клиент для получения данных
            order_executor: OrderExecutor для размещения/отмены ордеров
            scalping_config: Конфигурация скальпинга
            signal_generator: SignalGenerator для получения режима рынка
            last_orders_cache_ref: Ссылка на кэш последних ордеров (из orchestrator)
        """
        self.client = client
        self.order_executor = order_executor
        self.scalping_config = scalping_config
        self.signal_generator = signal_generator
        self.last_orders_cache = last_orders_cache_ref  # Ссылка на кэш

        logger.info("✅ OrderCoordinator initialized")

    async def monitor_limit_orders(self):
        """
        Мониторинг лимитных ордеров и их отмена/замена после таймаута.

        Проверяет все активные лимитные ордера и:
        - Отменяет ордера, которые висят дольше max_wait_seconds
        - Заменяет их на рыночные ордера, если включено replace_with_market
        """
        try:
            # Получаем конфигурацию лимитных ордеров
            order_executor_config = getattr(self.scalping_config, "order_executor", {})
            limit_order_config = order_executor_config.get("limit_order", {})

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем текущий режим рынка правильно
            current_regime = None
            try:
                if self.signal_generator:
                    # Пробуем получить режим из per-symbol manager (если есть)
                    if hasattr(self.signal_generator, "regime_managers"):
                        # Для каждого символа может быть свой режим, но для order_coordinator используем глобальный
                        pass
                    # Получаем глобальный режим
                    if (
                        hasattr(self.signal_generator, "regime_manager")
                        and self.signal_generator.regime_manager
                    ):
                        regime_obj = (
                            self.signal_generator.regime_manager.get_current_regime()
                        )
                        if regime_obj:
                            current_regime = (
                                regime_obj.lower()
                                if isinstance(regime_obj, str)
                                else str(regime_obj).lower()
                            )
            except Exception as e:
                logger.debug(f"⚠️ Не удалось получить режим для OrderCoordinator: {e}")

            # Fallback на 'ranging' только если режим не найден
            if not current_regime:
                current_regime = "ranging"
                logger.debug(
                    f"⚠️ OrderCoordinator: режим не найден, используется fallback 'ranging'"
                )

            # Получаем параметры по режиму
            regime_limit_config = limit_order_config.get("by_regime", {}).get(
                current_regime, {}
            )
            max_wait = regime_limit_config.get(
                "max_wait_seconds", limit_order_config.get("max_wait_seconds", 60)
            )
            auto_cancel = limit_order_config.get("auto_cancel_enabled", True)
            replace_with_market = limit_order_config.get("replace_with_market", True)

            # Получаем активные ордера на бирже для всех символов
            for symbol in self.scalping_config.symbols:
                try:
                    active_orders = await self.client.get_active_orders(symbol)

                    for order in active_orders:
                        order_id = order.get("ordId")
                        order_type = order.get("ordType", "")
                        state = order.get("state", "")

                        # Проверяем только лимитные ордера, которые не исполнены
                        if order_type == "limit" and state in [
                            "live",
                            "partially_filled",
                        ]:
                            # ✅ НОВОЕ: Получаем side из ордера для проверки отклонения цены
                            side = order.get("side", "").lower()

                            # Получаем время создания ордера
                            c_time = order.get("cTime")
                            if c_time:
                                try:
                                    # OKX возвращает время в миллисекундах
                                    if isinstance(c_time, str):
                                        c_time = int(c_time)
                                    order_time = datetime.fromtimestamp(c_time / 1000.0)
                                    wait_time = (
                                        datetime.now() - order_time
                                    ).total_seconds()

                                    # ✅ НОВОЕ: Проверка близости цены к исполнению - НЕ отменять если близко
                                    price_drift_pct = 0.0
                                    should_cancel_early = False
                                    price_close_to_execution = False
                                    try:
                                        # Получаем текущую цену
                                        price_limits = (
                                            await self.client.get_price_limits(symbol)
                                        )
                                        if price_limits:
                                            current_price = price_limits.get(
                                                "current_price", 0
                                            )
                                            order_price = float(order.get("px", "0"))

                                            if current_price > 0 and order_price > 0:
                                                # Проверяем отклонение цены от ордера
                                                if side == "buy":
                                                    # Для BUY: если текущая цена ушла вниз > 0.1% от ордера
                                                    price_drift_pct = (
                                                        (order_price - current_price)
                                                        / order_price
                                                    ) * 100.0
                                                    # ✅ НОВОЕ: НЕ отменять если цена близка к исполнению (< 0.1%)
                                                    if abs(price_drift_pct) < 0.1:
                                                        price_close_to_execution = True
                                                    elif (
                                                        price_drift_pct > 0.1
                                                    ):  # Цена ушла вниз > 0.1%
                                                        should_cancel_early = True
                                                else:  # sell
                                                    # Для SELL: если текущая цена ушла вверх > 0.1% от ордера
                                                    price_drift_pct = (
                                                        (current_price - order_price)
                                                        / order_price
                                                    ) * 100.0
                                                    # ✅ НОВОЕ: НЕ отменять если цена близка к исполнению (< 0.1%)
                                                    if abs(price_drift_pct) < 0.1:
                                                        price_close_to_execution = True
                                                    elif (
                                                        price_drift_pct > 0.1
                                                    ):  # Цена ушла вверх > 0.1%
                                                        should_cancel_early = True
                                    except Exception as e:
                                        logger.debug(
                                            f"⚠️ Ошибка проверки отклонения цены для {symbol}: {e}"
                                        )

                                    # ✅ НОВОЕ: Быстрая отмена при отклонении цены > 0.1%
                                    if should_cancel_early:
                                        logger.info(
                                            f"💨 Быстрая отмена: цена ушла {price_drift_pct:.2f}% от ордера {order_id} "
                                            f"для {symbol} (order_price={order.get('px', 'N/A')}, current_price={price_limits.get('current_price', 'N/A') if price_limits else 'N/A'})"
                                        )
                                    elif wait_time > max_wait:
                                        logger.warning(
                                            f"⚠️ Лимитный ордер {order_id} для {symbol} висит {wait_time:.0f} сек "
                                            f"(лимит: {max_wait} сек), отменяем..."
                                        )

                                    # ✅ НОВОЕ: Проверка post_only ордеров - если цена достигла, но не исполняется, отменяем и заменяем
                                    # OKX может возвращать postOnly как строку "true"/"false" или булево значение
                                    post_only_str = str(
                                        order.get("postOnly", "false")
                                    ).lower()
                                    is_post_only = (
                                        post_only_str == "true" or post_only_str == "1"
                                    )

                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: post_only ордер может не исполниться даже при достижении цены
                                    # Если цена достигла цены ордера, но ордер не исполняется (post_only требует быть maker),
                                    # и ордер висит уже > 5 секунд - отменяем и заменяем на обычный лимитный ордер
                                    if (
                                        price_close_to_execution
                                        and is_post_only
                                        and wait_time > 5.0
                                    ):
                                        logger.warning(
                                            f"⚠️ post_only ордер {order_id} для {symbol} близок к исполнению (отклонение {abs(price_drift_pct):.3f}%), "
                                            f"но не исполняется уже {wait_time:.1f}с (post_only требует быть maker). "
                                            f"Отменяем и заменяем на обычный лимитный ордер"
                                        )
                                        # Отменяем post_only ордер
                                        if auto_cancel:
                                            cancel_result = (
                                                await self.order_executor.cancel_order(
                                                    order_id, symbol
                                                )
                                            )
                                            if cancel_result.get("success"):
                                                logger.info(
                                                    f"✅ post_only ордер {order_id} отменен"
                                                )

                                        # Заменяем на обычный лимитный ордер (без post_only)
                                        if replace_with_market:
                                            size_str = order.get("sz", "0")
                                            try:
                                                size_in_contracts = float(size_str)
                                                if size_in_contracts > 0 and side in [
                                                    "buy",
                                                    "sell",
                                                ]:
                                                    details = await self.client.get_instrument_details(
                                                        symbol
                                                    )
                                                    if details:
                                                        ct_val = float(
                                                            details.get("ctVal", 1.0)
                                                        )
                                                        if ct_val > 0:
                                                            size_in_coins = (
                                                                size_in_contracts
                                                                * ct_val
                                                            )
                                                        else:
                                                            size_in_coins = (
                                                                size_in_contracts
                                                            )

                                                        # ✅ ВАРИАНТ 4: Размещаем обычный лимитный ордер с оптимальной ценой для максимизации шанса стать maker
                                                        # Получаем актуальную цену для расчета оптимальной цены ордера
                                                        try:
                                                            price_limits_new = await self.client.get_price_limits(
                                                                symbol
                                                            )
                                                            if price_limits_new:
                                                                current_price_new = price_limits_new.get(
                                                                    "current_price", 0
                                                                )
                                                                best_bid_new = price_limits_new.get(
                                                                    "best_bid", 0
                                                                )
                                                                best_ask_new = price_limits_new.get(
                                                                    "best_ask", 0
                                                                )

                                                                # ✅ ОПТИМАЛЬНАЯ ЦЕНА: Для максимизации шанса стать maker
                                                                if side == "buy":
                                                                    # Для BUY: цена чуть выше best_ask (чтобы попасть в стакан как maker)
                                                                    # Используем минимальный offset 0.01% для гарантии попадания в стакан
                                                                    optimal_price = (
                                                                        best_ask_new
                                                                        * 1.0001
                                                                        if best_ask_new
                                                                        > 0
                                                                        else current_price_new
                                                                        * 1.0001
                                                                    )
                                                                    logger.info(
                                                                        f"💰 Оптимальная цена для BUY {symbol}: best_ask={best_ask_new:.2f} → "
                                                                        f"optimal_price={optimal_price:.2f} (+0.01% для maker)"
                                                                    )
                                                                else:  # sell
                                                                    # Для SELL: цена чуть ниже best_bid (чтобы попасть в стакан как maker)
                                                                    # Используем минимальный offset 0.01% для гарантии попадания в стакан
                                                                    optimal_price = (
                                                                        best_bid_new
                                                                        * 0.9999
                                                                        if best_bid_new
                                                                        > 0
                                                                        else current_price_new
                                                                        * 0.9999
                                                                    )
                                                                    logger.info(
                                                                        f"💰 Оптимальная цена для SELL {symbol}: best_bid={best_bid_new:.2f} → "
                                                                        f"optimal_price={optimal_price:.2f} (-0.01% для maker)"
                                                                    )
                                                            else:
                                                                # Fallback: используем цену ордера
                                                                optimal_price = (
                                                                    order_price
                                                                )
                                                                logger.warning(
                                                                    f"⚠️ Не удалось получить актуальную цену для {symbol}, используем цену ордера"
                                                                )
                                                        except Exception as e:
                                                            logger.warning(
                                                                f"⚠️ Ошибка получения актуальной цены для {symbol}: {e}, используем цену ордера"
                                                            )
                                                            optimal_price = order_price

                                                        logger.info(
                                                            f"🔄 Размещаем обычный лимитный ордер для {symbol} {side} "
                                                            f"(без post_only, оптимальная цена для maker) размер={size_in_coins:.6f}, цена={optimal_price:.2f}"
                                                        )
                                                        result = await self.order_executor._place_limit_order(
                                                            symbol=symbol,
                                                            side=side,
                                                            size=size_in_coins,
                                                            price=optimal_price,  # ✅ Используем оптимальную цену для максимизации шанса стать maker
                                                            post_only=False,  # ✅ БЕЗ post_only для гарантии исполнения
                                                            regime=current_regime,
                                                        )
                                                        if result.get("success"):
                                                            logger.info(
                                                                f"✅ Обычный лимитный ордер размещен вместо post_only ордера"
                                                            )
                                            except Exception as e:
                                                logger.error(
                                                    f"❌ Ошибка замены post_only ордера на обычный: {e}"
                                                )
                                        continue  # Пропускаем дальнейшую обработку этого ордера

                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка таймаута имеет приоритет!
                                    # Если таймаут превышен - отменяем ВСЕГДА, независимо от близости цены
                                    if wait_time > max_wait:
                                        # Таймаут превышен - отменяем ордер
                                        logger.warning(
                                            f"⚠️ Лимитный ордер {order_id} для {symbol} висит {wait_time:.0f} сек "
                                            f"(лимит: {max_wait} сек), отменяем ВСЕГДА (даже если цена близка к исполнению)"
                                        )
                                        if auto_cancel:
                                            cancel_result = (
                                                await self.order_executor.cancel_order(
                                                    order_id, symbol
                                                )
                                            )
                                            if cancel_result.get("success"):
                                                logger.info(
                                                    f"✅ Лимитный ордер {order_id} отменен по таймауту"
                                                )

                                        # ✅ НОВОЕ: Заменяем на рыночный ордер, если включено
                                        if replace_with_market:
                                            size_str = order.get("sz", "0")
                                            try:
                                                size_in_contracts = float(size_str)
                                                if size_in_contracts > 0 and side in [
                                                    "buy",
                                                    "sell",
                                                ]:
                                                    # Получаем ctVal для конвертации контрактов в монеты
                                                    size_in_coins = size_in_contracts
                                                    try:
                                                        details = await self.client.get_instrument_details(
                                                            symbol
                                                        )
                                                        if details:
                                                            ct_val = float(
                                                                details.get(
                                                                    "ctVal", 1.0
                                                                )
                                                            )
                                                            if ct_val > 0:
                                                                size_in_coins = (
                                                                    size_in_contracts
                                                                    * ct_val
                                                                )
                                                            else:
                                                                logger.warning(
                                                                    f"⚠️ ctVal для {symbol} равен 0, используем размер в контрактах как есть"
                                                                )
                                                    except Exception as e:
                                                        logger.warning(
                                                            f"⚠️ Не удалось получить ctVal для {symbol} при замене на рыночный ордер: {e}, "
                                                            f"используем размер в контрактах как есть"
                                                        )

                                                    logger.info(
                                                        f"📈 Размещаем рыночный ордер вместо зависшего лимитного (таймаут): "
                                                        f"{symbol} {side} {size_in_coins:.6f} (было {size_in_contracts:.6f} контрактов, висел {wait_time:.0f} сек)"
                                                    )
                                                    result = await self.order_executor._place_market_order(
                                                        symbol, side, size_in_coins
                                                    )
                                                    if result.get("success"):
                                                        logger.info(
                                                            f"✅ Рыночный ордер размещен вместо лимитного (таймаут): {result.get('order_id')}"
                                                        )
                                                    else:
                                                        logger.error(
                                                            f"❌ Не удалось разместить рыночный ордер вместо лимитного для {symbol}: "
                                                            f"{result.get('error', 'unknown error')}"
                                                        )
                                            except (ValueError, TypeError) as e:
                                                logger.debug(
                                                    f"Ошибка парсинга размера ордера {order_id} при замене на рыночный: {e}"
                                                )

                                        continue  # Пропускаем дальнейшую обработку

                                    # ✅ НЕ отменять если цена близка к исполнению (< 0.1%) и НЕ превышен таймаут
                                    if price_close_to_execution:
                                        logger.debug(
                                            f"⏸️ Не отменяем ордер {order_id} для {symbol} - "
                                            f"цена близка к исполнению (отклонение {abs(price_drift_pct):.3f}% < 0.1%), "
                                            f"таймаут не превышен ({wait_time:.0f}с < {max_wait}с)"
                                        )
                                        continue  # Пропускаем отмену этого ордера

                                    # Отменяем ордер если нужно (быстрая отмена)
                                    if should_cancel_early:
                                        # Отменяем ордер
                                        if auto_cancel:
                                            cancel_result = (
                                                await self.order_executor.cancel_order(
                                                    order_id, symbol
                                                )
                                            )
                                            if cancel_result.get("success"):
                                                logger.info(
                                                    f"✅ Лимитный ордер {order_id} отменен"
                                                )

                                        # Заменяем на рыночный ордер, если включено
                                        if replace_with_market:
                                            # side уже получен выше
                                            size_str = order.get("sz", "0")
                                            try:
                                                # Размер из ордера в контрактах (sz),
                                                # но _place_market_order ожидает размер в монетах
                                                size_in_contracts = float(size_str)
                                                if size_in_contracts > 0 and side in [
                                                    "buy",
                                                    "sell",
                                                ]:
                                                    # Получаем ctVal для конвертации контрактов в монеты
                                                    size_in_coins = size_in_contracts
                                                    try:
                                                        details = await self.client.get_instrument_details(
                                                            symbol
                                                        )
                                                        if details:
                                                            ct_val = float(
                                                                details.get(
                                                                    "ctVal", 1.0
                                                                )
                                                            )
                                                            if ct_val > 0:
                                                                # Конвертируем из контрактов в монеты
                                                                size_in_coins = (
                                                                    size_in_contracts
                                                                    * ct_val
                                                                )
                                                            else:
                                                                logger.warning(
                                                                    f"⚠️ ctVal для {symbol} равен 0, используем размер в контрактах как есть"
                                                                )
                                                    except Exception as e:
                                                        logger.warning(
                                                            f"⚠️ Не удалось получить ctVal для {symbol} при замене на рыночный ордер: {e}, "
                                                            f"используем размер в контрактах как есть"
                                                        )

                                                    logger.info(
                                                        f"📈 Размещаем рыночный ордер вместо зависшего лимитного: "
                                                        f"{symbol} {side} {size_in_coins:.6f} (было {size_in_contracts:.6f} контрактов)"
                                                    )
                                                    result = await self.order_executor._place_market_order(
                                                        symbol, side, size_in_coins
                                                    )
                                                    if result.get("success"):
                                                        logger.info(
                                                            f"✅ Рыночный ордер размещен вместо лимитного: {result.get('order_id')}"
                                                        )
                                                        logger.info(
                                                            f"📊 Замена ордера: {symbol} {side} {size_in_coins:.6f} монет "
                                                            f"(было {size_in_contracts:.6f} контрактов, лимит висел {wait_time:.0f} сек, "
                                                            f"лимит ордера: {order_id})"
                                                        )
                                                    else:
                                                        logger.error(
                                                            f"❌ Не удалось разместить рыночный ордер вместо лимитного для {symbol}: "
                                                            f"{result.get('error', 'unknown error')}"
                                                        )
                                                        logger.error(
                                                            f"📊 Детали: side={side}, size={size_in_coins:.6f}, "
                                                            f"лимит висел {wait_time:.0f} сек, причина отмены: timeout, "
                                                            f"лимит ордера: {order_id}"
                                                        )
                                            except (ValueError, TypeError) as e:
                                                logger.debug(
                                                    f"Ошибка парсинга размера ордера {order_id}: {e}"
                                                )

                                except (ValueError, TypeError, OSError) as e:
                                    logger.debug(
                                        f"Ошибка парсинга времени ордера {order_id}: {e}"
                                    )
                                    continue

                except Exception as e:
                    logger.debug(f"Ошибка проверки ордеров для {symbol}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Ошибка мониторинга лимитных ордеров: {e}")

    async def update_orders_cache_status(self, normalize_symbol_callback):
        """
        Обновляет статус ордеров в кэше.

        Проверяет статус последних ордеров и обновляет кэш,
        определяя, были ли ордера исполнены или отменены.

        Args:
            normalize_symbol_callback: Функция для нормализации символа
                (например, orchestrator._normalize_symbol)
        """
        try:
            current_time = time.time()

            # Проверяем только ордера, которые были размещены недавно (менее 5 минут назад)
            symbols_to_check = []
            for normalized_symbol_key, order_info in self.last_orders_cache.items():
                order_time = order_info.get("timestamp", 0)
                order_status = order_info.get("status", "unknown")
                # Проверяем только pending ордера, которые старше 10 секунд
                if order_status == "pending" and (current_time - order_time) > 10:
                    # Находим оригинальный символ для API запросов
                    symbol = None
                    for config_symbol in self.scalping_config.symbols:
                        if (
                            normalize_symbol_callback(config_symbol)
                            == normalized_symbol_key
                        ):
                            symbol = config_symbol
                            break
                    if symbol:
                        symbols_to_check.append((symbol, normalized_symbol_key))

            # Проверяем статус ордеров (не чаще раза в 30 секунд на символ)
            for symbol, normalized_symbol_key in symbols_to_check:
                try:
                    # Проверяем активные ордера
                    active_orders = await self.client.get_active_orders(symbol)
                    inst_id = f"{symbol}-SWAP"

                    order_info = self.last_orders_cache.get(normalized_symbol_key, {})
                    order_id = order_info.get("order_id")

                    if order_id:
                        # Ищем наш ордер среди активных
                        found = False
                        for order in active_orders:
                            if (
                                order.get("ordId") == str(order_id)
                                and order.get("instId") == inst_id
                            ):
                                # Ордер все еще активен
                                order_state = order.get("state", "").lower()
                                if order_state in ["filled", "partially_filled"]:
                                    self.last_orders_cache[normalized_symbol_key][
                                        "status"
                                    ] = "filled"
                                    logger.debug(
                                        f"✅ Ордер {order_id} для {symbol} исполнен"
                                    )
                                elif order_state in ["cancelled", "canceled"]:
                                    self.last_orders_cache[normalized_symbol_key][
                                        "status"
                                    ] = "cancelled"
                                    logger.debug(
                                        f"⚠️ Ордер {order_id} для {symbol} отменен"
                                    )
                                found = True
                                break

                        # Если ордера нет среди активных - возможно исполнен
                        if not found:
                            # Проверяем позиции - возможно ордер исполнился
                            all_positions = await self.client.get_positions()
                            for pos in all_positions:
                                if (
                                    pos.get("instId") == inst_id
                                    and abs(float(pos.get("pos", "0"))) > 0.000001
                                ):
                                    # Есть позиция - возможно ордер исполнился
                                    self.last_orders_cache[normalized_symbol_key][
                                        "status"
                                    ] = "filled"
                                    logger.debug(
                                        f"✅ Ордер {order_id} для {symbol} вероятно исполнен (есть позиция)"
                                    )
                                    break
                            else:
                                # Нет активного ордера и нет позиции - возможно отменен
                                self.last_orders_cache[normalized_symbol_key][
                                    "status"
                                ] = "cancelled"
                                logger.debug(
                                    f"⚠️ Ордер {order_id} для {symbol} вероятно отменен (нет в активных)"
                                )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка обновления статуса ордера для {symbol}: {e}"
                    )
        except Exception as e:
            logger.debug(f"⚠️ Ошибка обновления кэша ордеров: {e}")

    def clear_orders_cache(self):
        """Очищает кэш последних ордеров."""
        self.last_orders_cache.clear()
        logger.debug("✅ last_orders_cache очищен")

    def get_order_status(self, normalized_symbol: str) -> Optional[str]:
        """
        Получает статус последнего ордера для символа.

        Args:
            normalized_symbol: Нормализованный символ

        Returns:
            Статус ордера или None, если ордера нет в кэше
        """
        order_info = self.last_orders_cache.get(normalized_symbol)
        if order_info:
            return order_info.get("status")
        return None

    def update_order_in_cache(
        self,
        normalized_symbol: str,
        order_id: str,
        status: str = "pending",
        timestamp: Optional[float] = None,
    ):
        """
        Обновляет информацию об ордере в кэше.

        Args:
            normalized_symbol: Нормализованный символ
            order_id: ID ордера
            status: Статус ордера (pending, filled, cancelled, closed)
            timestamp: Временная метка (если None, используется текущее время)
        """
        if timestamp is None:
            timestamp = time.time()

        self.last_orders_cache[normalized_symbol] = {
            "order_id": order_id,
            "status": status,
            "timestamp": timestamp,
        }

    def mark_order_as_closed(self, normalized_symbol: str):
        """
        Помечает ордер как закрытый в кэше.

        Args:
            normalized_symbol: Нормализованный символ
        """
        if normalized_symbol in self.last_orders_cache:
            self.last_orders_cache[normalized_symbol]["status"] = "closed"
