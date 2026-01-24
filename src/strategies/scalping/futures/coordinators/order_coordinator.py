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
    def __init__(
        self,
        client,
        order_executor,
        scalping_config,
        signal_generator,
        last_orders_cache_ref: Dict[str, Dict[str, Any]],  # Ссылка на кэш ордеров
        structured_logger=None,
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
        self.structured_logger = structured_logger
        self._last_amend_ts: Dict[str, float] = {}

        # --- Получаем конфиги ДО использования ---
        order_executor_config = getattr(self.scalping_config, "order_executor", {})
        limit_order_config = order_executor_config.get("limit_order", {})

        # --- Логгирование rate limit отмен/замен ---
        # Храним историю отмен/замен по символу: {symbol: [timestamp, ...]}
        self._cancel_replace_history: Dict[str, list] = {}
        self._rate_limit_window_sec: int = 300  # 5 минут
        self._rate_limit_threshold: int = 5  # Порог отмен/замен за окно
        # Статистика причин неисполнения лимитных ордеров
        self._limit_cancel_reasons: Dict[str, int] = {}  # reason -> count
        # Лимит на количество market-замен подряд по символу
        self._market_replace_limit: int = int(
            limit_order_config.get("market_replace_limit", 2)
        )
        self._market_replace_counters: Dict[str, int] = {}  # symbol -> count
        # Блокировка повторных входов после неудачной market-замены
        self._reentry_blocked_until: Dict[str, float] = {}  # symbol -> timestamp
        self._reentry_block_minutes: float = float(
            limit_order_config.get("reentry_block_minutes", 2.0)
        )
        # 🔴 BUG #8 FIX: Drift threshold из конфига (по умолчанию 0.1%)
        self.drift_cancel_threshold_pct: float = float(
            limit_order_config.get("drift_cancel_pct", 0.1)
        )

        logger.info("✅ OrderCoordinator initialized")

    async def monitor_limit_orders(self):
        now_ts = time.time()
        # Очищаем устаревшие записи из истории отмен/замен
        for symbol, ts_list in list(self._cancel_replace_history.items()):
            self._cancel_replace_history[symbol] = [
                ts for ts in ts_list if now_ts - ts < self._rate_limit_window_sec
            ]

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

            def _log_cancel_reason(
                reason: str,
                symbol: str,
                order: Dict[str, Any],
                side: str,
                price_limits: Optional[Dict[str, Any]],
                wait_time: Optional[float],
                price_drift_pct: Optional[float],
                is_post_only: bool,
                extra: Optional[Dict[str, Any]] = None,
            ) -> None:
                order_id = order.get("ordId") or order.get("clOrdId") or "unknown"
                order_price = None
                try:
                    order_price = float(order.get("px", "0") or 0)
                except (TypeError, ValueError):
                    order_price = None
                current_price = (
                    price_limits.get("current_price") if price_limits else None
                )
                best_bid = price_limits.get("best_bid") if price_limits else None
                best_ask = price_limits.get("best_ask") if price_limits else None

                logger.info(
                    f"🧾 Отмена лимитного ордера {symbol} {side} | id={order_id} | "
                    f"reason={reason} | order_px={order_price} | "
                    f"current={current_price} | bid={best_bid} | ask={best_ask} | "
                    f"wait={wait_time:.1f}s | drift={price_drift_pct:.2f}% | "
                    f"post_only={is_post_only}"
                )
                # Статистика причин отмены лимитных ордеров
                self._limit_cancel_reasons[reason] = (
                    self._limit_cancel_reasons.get(reason, 0) + 1
                )
                logger.debug(f"LIMIT_CANCEL_SUMMARY: {self._limit_cancel_reasons}")

                if self.structured_logger:
                    try:
                        self.structured_logger.log_order_cancel(
                            symbol=symbol,
                            order_id=order_id,
                            side=side,
                            reason=reason,
                            order_price=order_price,
                            current_price=current_price,
                            best_bid=best_bid,
                            best_ask=best_ask,
                            wait_time_sec=wait_time,
                            drift_pct=price_drift_pct,
                            post_only=is_post_only,
                            extra=extra or {},
                        )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось записать structured cancel log для {symbol}: {e}"
                        )

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
            now = time.time()
            for symbol in self.scalping_config.symbols:
                # Проверка блокировки повторного входа
                blocked_until = self._reentry_blocked_until.get(symbol, 0)
                if now < blocked_until:
                    logger.warning(
                        f"⏳ Вход по {symbol} заблокирован до {datetime.fromtimestamp(blocked_until).strftime('%H:%M:%S')}"
                    )
                    continue
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
                                    did_amend = False
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
                                                    # Для BUY: если текущая цена ушла вниз > drift_cancel_threshold_pct
                                                    price_drift_pct = (
                                                        (order_price - current_price)
                                                        / order_price
                                                    ) * 100.0
                                                    # ✅ НОВОЕ: НЕ отменять если цена близка к исполнению (< threshold)
                                                    if (
                                                        abs(price_drift_pct)
                                                        < self.drift_cancel_threshold_pct
                                                    ):
                                                        price_close_to_execution = True
                                                    elif (
                                                        price_drift_pct
                                                        > self.drift_cancel_threshold_pct
                                                    ):  # Цена ушла вниз > threshold
                                                        should_cancel_early = True
                                                else:  # sell
                                                    # Для SELL: если текущая цена ушла вверх > drift_cancel_threshold_pct
                                                    price_drift_pct = (
                                                        (current_price - order_price)
                                                        / order_price
                                                    ) * 100.0
                                                    # ✅ НОВОЕ: НЕ отменять если цена близка к исполнению (< threshold)
                                                    if (
                                                        abs(price_drift_pct)
                                                        < self.drift_cancel_threshold_pct
                                                    ):
                                                        price_close_to_execution = True
                                                    elif (
                                                        price_drift_pct
                                                        > self.drift_cancel_threshold_pct
                                                    ):  # Цена ушла вверх > threshold
                                                        should_cancel_early = True
                                    except Exception as e:
                                        logger.debug(
                                            f"⚠️ Ошибка проверки отклонения цены для {symbol}: {e}"
                                        )

                                    # ✅ ИСПРАВЛЕНО: Определяем is_post_only ПЕРЕД использованием
                                    # OKX может возвращать postOnly как строку "true"/"false" или булево значение
                                    post_only_str = str(
                                        order.get("postOnly", "false")
                                    ).lower()
                                    is_post_only = (
                                        post_only_str == "true" or post_only_str == "1"
                                    )

                                    # ✅ FIX (22.01.2026): УМНАЯ ПЕРЕОЦЕНКА вместо тупой отмены по таймауту
                                    # Идея: Если ордер висит > max_wait, НЕ отменяем автоматически
                                    # Вместо этого ПЕРЕОЦЕНИВАЕМ сигнал:
                                    # - Фильтры всё ещё PASSED? → ОСТАВИТЬ ордер
                                    # - Рынок развернулся? → ОТМЕНИТЬ
                                    if wait_time > max_wait:
                                        # Проверяем актуальность сигнала ПЕРЕД отменой
                                        signal_still_valid = (
                                            await self._revalidate_signal(
                                                symbol, side, order_price
                                            )
                                        )

                                        if signal_still_valid:
                                            logger.info(
                                                f"✅ Лимитный ордер {order_id} для {symbol} висит {wait_time:.0f} сек, "
                                                f"НО сигнал всё ещё актуален → ОСТАВЛЯЕМ ордер"
                                            )
                                            continue  # НЕ отменяем, оставляем висеть!

                                        # Сигнал устарел или развернулся - отменяем
                                        logger.warning(
                                            f"⚠️ Лимитный ордер {order_id} для {symbol} висит {wait_time:.0f} сек "
                                            f"(лимит: {max_wait} сек), сигнал УСТАРЕЛ → отменяем"
                                        )

                                        # --- Логгирование rate limit отмен/замен ---
                                        hist = self._cancel_replace_history.setdefault(
                                            symbol, []
                                        )
                                        hist.append(now_ts)
                                        recent_cnt = len(hist)
                                        if recent_cnt > self._rate_limit_threshold:
                                            logger.warning(
                                                f"⏳ [RATE_LIMIT_LOG] За {self._rate_limit_window_sec//60} мин по {symbol} отмен/замен: {recent_cnt} (порог: {self._rate_limit_threshold}). Возможна проблема с исполнением!"
                                            )

                                        _log_cancel_reason(
                                            reason="timeout",
                                            symbol=symbol,
                                            order=order,
                                            side=side,
                                            price_limits=price_limits,
                                            wait_time=wait_time,
                                            price_drift_pct=price_drift_pct,
                                            is_post_only=is_post_only,
                                            extra={
                                                "max_wait": max_wait,
                                                "auto_cancel": auto_cancel,
                                                "replace_with_market": replace_with_market,
                                                "rate_limit_cnt": recent_cnt,
                                                "rate_limit_window_min": self._rate_limit_window_sec
                                                // 60,
                                            },
                                        )

                                        # ✅ ИСПРАВЛЕНИЕ #3: POST_ONLY ордера заменяются на market при timeout
                                        if is_post_only:
                                            logger.warning(
                                                f"⚠️ Post-only ордер {order_id} для {symbol} висит {wait_time:.0f} сек, "
                                                f"заменяем на market..."
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

                                        # ✅ ИСПРАВЛЕНИЕ #3: Заменяем на market ордер (для post_only и обычных limit)

                                        if replace_with_market:
                                            # Проверка лимита market-замен подряд
                                            cnt = self._market_replace_counters.get(
                                                symbol, 0
                                            )
                                            if cnt >= self._market_replace_limit:
                                                logger.warning(
                                                    f"⛔ Превышен лимит market-замен подряд для {symbol}: {cnt} (максимум {self._market_replace_limit}), market-замена не выполняется"
                                                )
                                                continue
                                            size_str = order.get("sz", "0")
                                            filled_str = order.get("accFillSz", "0")
                                            try:
                                                size_in_contracts = float(size_str)
                                                filled_in_contracts = float(filled_str)
                                                remaining_contracts = max(
                                                    size_in_contracts
                                                    - filled_in_contracts,
                                                    0,
                                                )
                                                if remaining_contracts <= 0:
                                                    logger.warning(
                                                        f"⚠️ Остаток для market-замены лимитного ордера {order_id} по {symbol} равен 0 (total={size_in_contracts}, filled={filled_in_contracts}), market-замена не требуется."
                                                    )
                                                    continue
                                                # Получаем ctVal для конвертации контрактов в монеты
                                                size_in_coins = remaining_contracts
                                                try:
                                                    details = await self.client.get_instrument_details(
                                                        symbol
                                                    )
                                                    if details:
                                                        ct_val = float(
                                                            details.get("ctVal", 1.0)
                                                        )
                                                        if ct_val > 0:
                                                            size_in_coins = (
                                                                remaining_contracts
                                                                * ct_val
                                                            )
                                                except Exception as e:
                                                    logger.warning(
                                                        f"⚠️ Не удалось получить ctVal для {symbol}: {e}"
                                                    )

                                                logger.info(
                                                    f"📈 Размещаем market ордер вместо зависшего лимитного (таймаут): {symbol} {side} {size_in_coins:.6f} (остаток {remaining_contracts:.6f} контрактов из {size_in_contracts:.6f}, исполнено {filled_in_contracts:.6f}, висел {wait_time:.0f} сек)"
                                                )
                                                result = await self.order_executor._place_market_order(
                                                    symbol, side, size_in_coins
                                                )
                                                if result.get("success"):
                                                    logger.info(
                                                        f"✅ Market ордер размещен вместо лимитного (таймаут): {result.get('order_id')}"
                                                    )
                                                    # Сбросить счётчик market-замен подряд
                                                    self._market_replace_counters[
                                                        symbol
                                                    ] = 0
                                                    # Сразу после market-замены инициируем sync позиций для актуализации реестра
                                                    if (
                                                        hasattr(
                                                            self.order_executor,
                                                            "position_manager",
                                                        )
                                                        and self.order_executor.position_manager
                                                    ):
                                                        try:
                                                            await self.order_executor.position_manager.sync_positions_with_exchange(
                                                                force=True
                                                            )
                                                            logger.info(
                                                                f"✅ Реестр позиций синхронизирован после market-замены для {symbol}"
                                                            )
                                                        except Exception as e:
                                                            logger.warning(
                                                                f"⚠️ Не удалось синхронизировать позиции после market-замены для {symbol}: {e}"
                                                            )
                                                else:
                                                    logger.error(
                                                        f"❌ Не удалось разместить market ордер для {symbol}: {result.get('error', 'unknown error')}"
                                                    )
                                                    # Увеличить счётчик market-замен подряд
                                                    self._market_replace_counters[
                                                        symbol
                                                    ] = (cnt + 1)
                                                    # Блокируем повторные входы по символу на N минут
                                                    block_until = (
                                                        time.time()
                                                        + self._reentry_block_minutes
                                                        * 60
                                                    )
                                                    self._reentry_blocked_until[
                                                        symbol
                                                    ] = block_until
                                                    logger.warning(
                                                        f"⏳ Вход по {symbol} заблокирован на {self._reentry_block_minutes} мин после неудачной market-замены"
                                                    )
                                            except (ValueError, TypeError) as e:
                                                logger.debug(
                                                    f"Ошибка парсинга размера/остатка ордера {order_id} при замене на market: {e}"
                                                )

                                        continue  # Пропускаем дальнейшую обработку

                                    # ✅ НОВОЕ: Быстрая отмена при отклонении цены > 0.1% (только если timeout еще не наступил)
                                    if should_cancel_early:
                                        logger.info(
                                            f"💨 Быстрая отмена: цена ушла {price_drift_pct:.2f}% от ордера {order_id} "
                                            f"для {symbol} (order_price={order.get('px', 'N/A')}, "
                                            f"current_price={price_limits.get('current_price', 'N/A') if price_limits else 'N/A'})"
                                        )
                                        _log_cancel_reason(
                                            reason="drift_cancel",
                                            symbol=symbol,
                                            order=order,
                                            side=side,
                                            price_limits=price_limits,
                                            wait_time=wait_time,
                                            price_drift_pct=price_drift_pct,
                                            is_post_only=is_post_only,
                                            extra={
                                                "drift_threshold": self.drift_cancel_threshold_pct,
                                                "auto_cancel": auto_cancel,
                                            },
                                        )

                                    # 🔄 Авто-репрайс: если отклонение >= 0.2% и таймаут не превышен
                                    try:
                                        if (
                                            not price_close_to_execution
                                            and price_drift_pct >= 0.2
                                            and wait_time <= max_wait
                                        ):
                                            now_ts = time.time()
                                            last_ts = self._last_amend_ts.get(
                                                order_id, 0
                                            )
                                            if now_ts - last_ts >= 2.0:
                                                current_price = (
                                                    price_limits.get("current_price", 0)
                                                    if price_limits
                                                    else 0
                                                )
                                                best_bid = (
                                                    price_limits.get("best_bid", 0)
                                                    if price_limits
                                                    else 0
                                                )
                                                best_ask = (
                                                    price_limits.get("best_ask", 0)
                                                    if price_limits
                                                    else 0
                                                )
                                                max_buy_price = (
                                                    price_limits.get("max_buy_price", 0)
                                                    if price_limits
                                                    else 0
                                                )
                                                min_sell_price = (
                                                    price_limits.get(
                                                        "min_sell_price", 0
                                                    )
                                                    if price_limits
                                                    else 0
                                                )

                                                new_price = None
                                                if is_post_only:
                                                    # Репрайс для maker: BUY к bid, SELL к ask с минимальным смещением
                                                    if side == "buy":
                                                        base = (
                                                            best_bid
                                                            if best_bid
                                                            else current_price
                                                        )
                                                        new_price = (
                                                            base * 0.9999
                                                            if base > 0
                                                            else float(
                                                                order.get("px", "0")
                                                                or 0
                                                            )
                                                        )
                                                        if max_buy_price:
                                                            new_price = min(
                                                                new_price,
                                                                max_buy_price * 0.999,
                                                            )
                                                    else:
                                                        base = (
                                                            best_ask
                                                            if best_ask
                                                            else current_price
                                                        )
                                                        new_price = (
                                                            base * 1.0001
                                                            if base > 0
                                                            else float(
                                                                order.get("px", "0")
                                                                or 0
                                                            )
                                                        )
                                                        if min_sell_price:
                                                            new_price = max(
                                                                new_price,
                                                                min_sell_price * 1.001,
                                                            )
                                                else:
                                                    # Репрайс для быстрого исполнения: расчет оптимальной лимитной цены
                                                    try:
                                                        calc_price = await self.order_executor._calculate_limit_price(
                                                            symbol=symbol,
                                                            side=side,
                                                            signal_price=None,
                                                            base_price=current_price,
                                                            regime=current_regime,
                                                        )
                                                        new_price = calc_price
                                                    except Exception as e:
                                                        logger.debug(
                                                            f"⚠️ Ошибка расчета новой цены для репрайса {symbol}: {e}"
                                                        )
                                                        new_price = None

                                                if new_price and new_price > 0:
                                                    amend_res = await self.order_executor.amend_order_price(
                                                        symbol,
                                                        order_id,
                                                        float(new_price),
                                                    )
                                                    if amend_res.get("success"):
                                                        did_amend = True
                                                        self._last_amend_ts[
                                                            order_id
                                                        ] = now_ts
                                                        logger.info(
                                                            f"✅ Авто-репрайс {symbol} {side}: {order.get('px', 'N/A')} → {float(new_price):.6f} (дрейф {price_drift_pct:.2f}%)"
                                                        )
                                                    else:
                                                        logger.warning(
                                                            f"⚠️ Авто-репрайс не выполнен для {order_id}: {amend_res.get('error')}"
                                                        )
                                    except Exception as e:
                                        logger.debug(
                                            f"⚠️ Ошибка авто-репрайса для {symbol}: {e}"
                                        )

                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: post_only ордер может не исполниться даже при достижении цены
                                    # (is_post_only уже определен выше)
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
                                        _log_cancel_reason(
                                            reason="post_only_stuck",
                                            symbol=symbol,
                                            order=order,
                                            side=side,
                                            price_limits=price_limits,
                                            wait_time=wait_time,
                                            price_drift_pct=price_drift_pct,
                                            is_post_only=is_post_only,
                                            extra={"auto_cancel": auto_cancel},
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

                                    # ✅ FIX (22.01.2026): УМНАЯ ПЕРЕОЦЕНКА вместо тупой отмены по таймауту
                                    # Проверяем актуальность сигнала ПЕРЕД отменой
                                    if wait_time > max_wait:
                                        # Проверяем актуальность сигнала ПЕРЕД отменой
                                        signal_still_valid = (
                                            await self._revalidate_signal(
                                                symbol, side, order_price
                                            )
                                        )

                                        if signal_still_valid:
                                            logger.info(
                                                f"✅ Лимитный ордер {order_id} для {symbol} висит {wait_time:.0f} сек, "
                                                f"НО сигнал всё ещё актуален → ОСТАВЛЯЕМ ордер"
                                            )
                                            continue  # НЕ отменяем, оставляем висеть!

                                        # Сигнал устарел - отменяем
                                        logger.warning(
                                            f"⚠️ Лимитный ордер {order_id} для {symbol} висит {wait_time:.0f} сек "
                                            f"(лимит: {max_wait} сек), сигнал УСТАРЕЛ → отменяем"
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

                                    # Отменяем ордер если нужно (быстрая отмена), пропускаем если уже сделали репрайс
                                    if should_cancel_early and not did_amend:
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

    async def _revalidate_signal(
        self, symbol: str, side: str, order_price: float
    ) -> bool:
        """
        ✅ FIX (22.01.2026): УМНАЯ ПЕРЕОЦЕНКА сигнала перед отменой ордера.

        Вместо тупой отмены по таймауту проверяем:
        1. Есть ли сигнал в нужном направлении (buy/sell)
        2. Фильтры всё ещё PASSED
        3. Цена движется в нужную сторону (или стоит)

        Args:
            symbol: Символ (BTC-USDT)
            side: Направление ордера (buy/sell)
            order_price: Цена ордера

        Returns:
            True если сигнал всё ещё актуален (НЕ отменять ордер)
            False если сигнал устарел (ОТМЕНИТЬ ордер)
        """
        try:
            # 1. Генерируем сигналы заново
            if not self.signal_generator:
                logger.warning(
                    f"⚠️ SignalGenerator недоступен для {symbol}, не можем переоценить сигнал → отменяем"
                )
                return False

            signals = await self.signal_generator.generate_signals()
            if not signals:
                logger.debug(f"⚠️ Нет сигналов для {symbol} → сигнал устарел")
                return False

            # 2. Ищем сигнал в нужном направлении для символа
            matching_signals = [
                s
                for s in signals
                if s.get("symbol") == symbol and s.get("side") == side
            ]

            if not matching_signals:
                logger.info(
                    f"⚠️ Нет {side} сигнала для {symbol} → сигнал развернулся, отменяем ордер"
                )
                return False

            # 3. Берём лучший сигнал (первый, они отсортированы по strength)
            best_signal = matching_signals[0]
            signal_strength = best_signal.get("strength", 0)
            filters_passed = best_signal.get("filters_passed", [])

            logger.info(
                f"✅ Сигнал {side} для {symbol} всё ещё актуален! "
                f"strength={signal_strength:.2f}, filters={len(filters_passed)}"
            )

            # 4. Проверяем что фильтры PASSED (хотя бы 3 фильтра)
            if len(filters_passed) < 3:
                logger.warning(
                    f"⚠️ Сигнал для {symbol} слабый (filters={len(filters_passed)} < 3) → отменяем"
                )
                return False

            # 5. Проверяем strength (хотя бы 0.5)
            if signal_strength < 0.5:
                logger.warning(
                    f"⚠️ Сигнал для {symbol} слабый (strength={signal_strength} < 0.5) → отменяем"
                )
                return False

            # 6. Опционально: проверяем направление движения цены
            # Если рынок развернулся ПРОТИВ ордера - отменяем
            try:
                signal_price = best_signal.get("price", 0)
                if signal_price > 0 and order_price > 0:
                    if side == "sell":
                        # Для SELL: если цена ушла ВВЕРХ > 0.5% от ордера → рынок развернулся
                        if signal_price > order_price * 1.005:
                            logger.warning(
                                f"⚠️ Рынок развернулся ВВЕРХ для {symbol} SELL "
                                f"(signal={signal_price:.2f} > order={order_price:.2f}) → отменяем"
                            )
                            return False
                    else:  # buy
                        # Для BUY: если цена ушла ВНИЗ > 0.5% от ордера → рынок развернулся
                        if signal_price < order_price * 0.995:
                            logger.warning(
                                f"⚠️ Рынок развернулся ВНИЗ для {symbol} BUY "
                                f"(signal={signal_price:.2f} < order={order_price:.2f}) → отменяем"
                            )
                            return False
            except Exception as e:
                logger.debug(f"⚠️ Не удалось проверить направление цены: {e}")

            # ✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - сигнал актуален!
            logger.info(
                f"✅ Сигнал для {symbol} {side} @ {order_price:.2f} АКТУАЛЕН "
                f"(strength={signal_strength:.2f}, filters={filters_passed}) → ОСТАВЛЯЕМ ордер"
            )
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка переоценки сигнала для {symbol}: {e}")
            # При ошибке безопаснее отменить
            return False
