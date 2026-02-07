"""
WebSocket Coordinator для Futures торговли.

Координирует управление WebSocket соединениями:
- Инициализация публичного и приватного WebSocket
- Обработка тикеров из публичного WebSocket
- Обработка обновлений позиций и ордеров из приватного WebSocket
- Fallback для получения цены через REST API
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from src.models import OHLCV

# ✅ Импорт Dict уже есть в typing


class WebSocketCoordinator:
    """
    Координатор WebSocket для Futures торговли.

    Управляет WebSocket соединениями и обработкой данных из них.
    """

    def __init__(
        self,
        ws_manager,
        private_ws_manager,
        scalping_config,
        active_positions_ref: Dict[str, Dict[str, Any]],
        fast_adx=None,
        position_manager=None,
        trailing_sl_coordinator=None,
        debug_logger=None,
        client=None,
        handle_ticker_callback: Optional[
            Callable[[str, float], Awaitable[None]]
        ] = None,
        update_trailing_sl_callback: Optional[
            Callable[[str, float], Awaitable[None]]
        ] = None,
        check_signals_callback: Optional[
            Callable[[str, float], Awaitable[None]]
        ] = None,
        handle_position_closed_callback: Optional[
            Callable[[str], Awaitable[None]]
        ] = None,
        update_active_positions_callback: Optional[
            Callable[[str, Dict[str, Any]], None]
        ] = None,
        update_active_orders_cache_callback: Optional[
            Callable[[str, str, Dict[str, Any]], None]
        ] = None,
        data_registry=None,  # ✅ НОВОЕ: DataRegistry для централизованного хранения данных
        position_registry=None,  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (07.02.2026): PositionRegistry для синхронизации на WS updates
        structured_logger=None,  # ✅ НОВОЕ: StructuredLogger для логирования свечей
        smart_exit_coordinator=None,  # ✅ НОВОЕ: SmartExitCoordinator для умного закрытия
        performance_tracker=None,  # ✅ НОВОЕ: PerformanceTracker для записи в CSV
        signal_generator=None,  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): SignalGenerator для проверки готовности
        orchestrator=None,  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Orchestrator для проверки готовности модулей
    ):
        """
        Инициализация WebSocketCoordinator.

        Args:
            ws_manager: Менеджер публичного WebSocket
            private_ws_manager: Менеджер приватного WebSocket
            scalping_config: Конфигурация скальпинга
            active_positions_ref: Ссылка на active_positions
            fast_adx: FastADX индикатор (опционально)
            position_manager: PositionManager для управления позициями (опционально)
            trailing_sl_coordinator: TrailingSLCoordinator для обновления TSL (опционально)
            debug_logger: DebugLogger для логирования (опционально)
            client: Futures клиент для REST API fallback (опционально)
            handle_ticker_callback: Callback для обработки тикеров (опционально)
            update_trailing_sl_callback: Callback для обновления TSL (опционально)
            check_signals_callback: Callback для проверки сигналов (опционально)
            handle_position_closed_callback: Callback для обработки закрытия позиций (опционально)
            update_active_positions_callback: Callback для обновления active_positions (опционально)
            update_active_orders_cache_callback: Callback для обновления кэша ордеров (опционально)
        """
        self.ws_manager = ws_manager
        self.private_ws_manager = private_ws_manager
        self.scalping_config = scalping_config
        self.active_positions_ref = active_positions_ref
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): FastADX должен быть per-symbol
        # Сохраняем общий fast_adx как шаблон для создания per-symbol экземпляров
        self._fast_adx_template = fast_adx
        # Словарь для хранения FastADX экземпляров по символам
        self._fast_adx_by_symbol: Dict[str, Any] = {}
        # Старый способ для обратной совместимости (deprecated)
        self.fast_adx = fast_adx
        self.position_manager = position_manager
        self.trailing_sl_coordinator = trailing_sl_coordinator
        self.debug_logger = debug_logger
        self.client = client

        # Callbacks для взаимодействия с orchestrator
        self.handle_ticker_callback = handle_ticker_callback
        self.update_trailing_sl_callback = update_trailing_sl_callback
        self.check_signals_callback = check_signals_callback
        self.handle_position_closed_callback = handle_position_closed_callback
        self.update_active_positions_callback = update_active_positions_callback
        self.update_active_orders_cache_callback = update_active_orders_cache_callback
        # ✅ НОВОЕ: DataRegistry для централизованного хранения данных
        self.data_registry = data_registry
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (07.02.2026): PositionRegistry для синхронизации на WS updates
        self.position_registry = position_registry
        # ✅ НОВОЕ: StructuredLogger для логирования свечей
        self.structured_logger = structured_logger
        # ✅ НОВОЕ: SmartExitCoordinator для умного закрытия
        self.smart_exit_coordinator = smart_exit_coordinator
        # ✅ НОВОЕ: PerformanceTracker для записи в CSV
        self.performance_tracker = performance_tracker
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): SignalGenerator для проверки готовности
        self.signal_generator = signal_generator
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Orchestrator для проверки готовности модулей
        self.orchestrator = orchestrator
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Callback для синхронизации позиций
        self.sync_positions_with_exchange = None  # Будет установлен из orchestrator
        # ✅ Дедупликация тикеров: кэш последних цен
        self.last_prices: Dict[str, float] = {}  # symbol -> price
        # Track ticker 24h volume to derive per-tick deltas (for candle volume)
        self._last_volume_ccy_24h: Dict[str, float] = {}
        self._last_volume_24h: Dict[str, float] = {}

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Отслеживание последнего timestamp для каждого символа и таймфрейма
        # Формат: "symbol_timeframe" -> timestamp последней обработанной свечи (в секундах)
        self._last_candle_timestamps: Dict[str, int] = {}

        # ✅ ИСПРАВЛЕНИЕ CPU 100% (06.01.2026): Дросселирование обработки тикеров
        # Обрабатывать каждый N-й тикер вместо каждого
        # Это снижает CPU с 100% до 40-50% без потери live данных
        self._ticker_counter: Dict[str, int] = {}  # symbol -> counter
        self._ticker_throttle: int = (
            1  # Обрабатывать каждый тикер (1/1 = 100% от исходной частоты)
        )
        # ✅ Новый lock для атомарного обновления свечей/market_data/индикаторов
        self._update_lock = asyncio.Lock()
        # ✅ Конфигурация адаптивного дросселирования по волатильности
        self._throttle_config = {
            "low": 5,  # <0.1%/мин — обрабатывать 1/5
            "medium": 2,  # 0.1-0.3%/мин — обрабатывать 1/2
            "high": 1,  # >0.3%/мин — обрабатывать все
        }
        # Кэш последних N цен для оценки волатильности
        self._volatility_cache: Dict[str, list] = {}
        # Отслеживание последнего выбранного режима дросселирования для логирования изменений
        self._last_throttle_state: Dict[str, str] = {}
        # Последний момент вывода health-логов по символу
        self._last_health_log_ts: Dict[str, float] = {}
        # Use real OHLCV from kline stream instead of ticker-derived candles.
        self._use_kline_candles = True
        # Throttle kline diagnostics to avoid log spam
        self._last_kline_log_ts: Dict[str, float] = {}
        # REST candle polling fallback (when kline WS is unavailable)
        self._rest_candle_task: Optional[asyncio.Task] = None
        self._rest_candle_poll_interval = 60.0
        self._rest_candle_rate_delay = 0.12  # <= ~8.3 req/s
        # WebSocket freshness watchdog (per-symbol)
        self._ws_watchdog_task: Optional[asyncio.Task] = None
        self._ws_watchdog_interval = 5.0
        self._ws_watchdog_max_age = 6.0
        self._ws_watchdog_stale_threshold = 2
        self._ws_watchdog_cooldown = 30.0
        self._last_ws_watchdog_trigger: Dict[str, float] = {}
        self._ws_watchdog_stale_counts: Dict[str, int] = {}
        # Последний обработанный тикер и логи форсированных обходов, чтобы избежать устаревших цен
        self._last_ticker_processed_ts: Dict[str, float] = {}
        self._last_throttle_force_log_ts: Dict[str, float] = {}
        self._ticker_force_process_threshold: float = (
            45.0  # seconds before we force processing to keep DataRegistry fresh
        )

        # Sandbox WS often does not support candle channels; use REST fallback.
        if self.client and getattr(self.client, "sandbox", False):
            self._use_kline_candles = False
        logger.info(
            f"✅ WebSocketCoordinator initialized (ticker throttle: 1/{self._ticker_throttle})"
        )

    async def auto_reconnect(self) -> bool:
        """Delegate auto-reconnect to WebSocketManager."""
        if not self.ws_manager:
            return False
        try:
            return await self.ws_manager.auto_reconnect()
        except Exception as e:
            logger.debug(f"WebSocketCoordinator auto_reconnect failed: {e}")
            return False

    async def force_reconnect(
        self,
        symbol: Optional[str] = None,
        fallback_count: Optional[int] = None,
        reason: str = "",
    ) -> bool:
        """Принудительный reconnect по сигналу деградации WS."""
        if not self.ws_manager:
            return False
        details = []
        if symbol:
            details.append(f"symbol={symbol}")
        if fallback_count is not None:
            details.append(f"fallback_count={fallback_count}")
        if reason:
            details.append(f"reason={reason}")
        detail_str = ", ".join(details)
        try:
            return await self.ws_manager.force_reconnect(reason=detail_str)
        except Exception as e:
            logger.debug(f"WebSocketCoordinator force_reconnect failed: {e}")
            return False

    async def initialize_websocket(self):
        """
        Инициализация WebSocket для получения рыночных данных.
        """
        try:
            logger.info("📡 Подключение к WebSocket...")

            # Подключение публичного WebSocket
            if await self.ws_manager.connect():
                logger.info("✅ WebSocket подключен")

                # Callback для обработки тикеров (один на все инструменты)
                async def ticker_callback(data):
                    # Извлекаем instId из данных
                    if "data" in data and len(data["data"]) > 0:
                        inst_id = data["data"][0].get("instId", "")
                        # Убираем -SWAP суффикс для получения символа
                        symbol = inst_id.replace("-SWAP", "")
                        if symbol:
                            await self.handle_ticker_data(symbol, data)

                async def kline_callback(data):
                    if "data" in data and len(data["data"]) > 0:
                        inst_id = data.get("arg", {}).get("instId", "")
                        symbol = inst_id.replace("-SWAP", "")
                        if symbol:
                            await self.handle_candle_data(symbol, data)

                # Подписка на тикеры для всех символов
                for symbol in self.scalping_config.symbols:
                    inst_id = f"{symbol}-SWAP"
                    await self.ws_manager.subscribe(
                        channel="tickers",
                        inst_id=inst_id,
                        callback=ticker_callback,  # Один callback для всех
                    )
                    if self._use_kline_candles:
                        await self.ws_manager.subscribe(
                            channel="candle1m",
                            inst_id=inst_id,
                            callback=kline_callback,
                        )
                        await self.ws_manager.subscribe(
                            channel="candle5m",
                            inst_id=inst_id,
                            callback=kline_callback,
                        )

                logger.info(
                    f"📊 Подписка на тикеры для {len(self.scalping_config.symbols)} пар"
                )
                if not self._use_kline_candles:
                    self._ensure_rest_candle_polling()
                self._ensure_ws_watchdog()
            else:
                logger.warning("⚠️ Не удалось подключиться к WebSocket")

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации WebSocket: {e}")

        # Подключение Private WebSocket для мониторинга позиций/ордеров
        if self.private_ws_manager:
            try:
                connected = await self.private_ws_manager.connect()
                if connected:
                    # Подписываемся на обновления позиций
                    await self.private_ws_manager.subscribe_positions(
                        callback=self.handle_private_ws_positions
                    )
                    # Подписываемся на обновления ордеров
                    await self.private_ws_manager.subscribe_orders(
                        callback=self.handle_private_ws_orders
                    )
                    logger.info(
                        "✅ Private WebSocket подключен и подписан на позиции/ордера"
                    )
                else:
                    logger.warning(
                        "⚠️ Не удалось подключиться к Private WebSocket (будет использоваться REST API)"
                    )
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка подключения Private WebSocket: {e} (будет использоваться REST API)"
                )

    async def handle_ticker_data(self, symbol: str, data: dict):
        logger.info(f"handle_ticker_data: {symbol}, data={str(data)[:500]}")
        now = time.time()
        # Преобразуем символ из формата OKX (например, BTC-USDT-SWAP) к внутреннему (BTC-USDT)
        if symbol.endswith("-SWAP"):
            symbol = symbol.replace("-SWAP", "")
        """
        Обработка данных тикера.

        Args:
            symbol: Торговый символ
            data: Данные тикера из WebSocket
        """
        try:
            # ✅ FIX (22.01.2026): ПРИОРИТЕТ #1 - Обновление market data (price, updated_at)
            # Это должно происходить ВСЕГДА, даже если модули не готовы или тикер дросселирован
            # Иначе price застревает на REST-значении минутами!
            if "data" in data and len(data["data"]) > 0:
                ticker = data["data"][0]
                if "last" in ticker and self.data_registry:
                    try:
                        price = float(ticker["last"])
                        volume_24h = float(ticker.get("vol24h", 0))
                        volume_ccy_24h = float(ticker.get("volCcy24h", 0))
                        high_24h = float(ticker.get("high24h", price))
                        low_24h = float(ticker.get("low24h", price))
                        open_24h = float(ticker.get("open24h", price))
                        bid_price = float(ticker.get("bidPx", price))
                        ask_price = float(ticker.get("askPx", price))

                        # Создаем объект current_tick для real-time цены
                        class CurrentTick:
                            def __init__(self, price, bid, ask, timestamp):
                                self.price = price
                                self.bid = bid
                                self.ask = ask
                                self.timestamp = timestamp

                        current_tick = CurrentTick(
                            price=price,
                            bid=bid_price,
                            ask=ask_price,
                            timestamp=time.time(),
                        )

                        # ✅ ОБНОВЛЯЕМ MARKET DATA БЕЗ ЗАДЕРЖЕК
                        await self.data_registry.update_market_data(
                            symbol,
                            {
                                "price": price,
                                "last_price": price,
                                "current_tick": current_tick,
                                "volume": volume_24h,
                                "volume_ccy": volume_ccy_24h,
                                "high_24h": high_24h,
                                "low_24h": low_24h,
                                "open_24h": open_24h,
                                "ticker": ticker,
                                "updated_at": datetime.now(),
                                "source": "WEBSOCKET",
                            },
                        )
                        now_ts = time.time()
                        self._last_ticker_processed_ts[symbol] = now_ts
                        logger.debug(
                            f"✅ WS→DataRegistry: {symbol} price=${price:.2f} source=WS ts={now_ts:.3f}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка обновления market data для {symbol}: {e}"
                        )

            # ✅ ПРОВЕРКА ГОТОВНОСТИ МОДУЛЕЙ: Блокируем только свечи/индикаторы, НЕ market data!
            modules_ready = True

            if self.signal_generator and hasattr(
                self.signal_generator, "is_initialized"
            ):
                if not self.signal_generator.is_initialized:
                    logger.debug(
                        f"⚠️ SignalGenerator еще не инициализирован, пропускаем свечи/индикаторы для {symbol}"
                    )
                    modules_ready = False

            if self.orchestrator and hasattr(self.orchestrator, "all_modules_ready"):
                if not self.orchestrator.all_modules_ready:
                    modules_ready = False

            # Если модули не готовы - market data уже обновлено, остальное пропускаем
            if not modules_ready:
                return

            # ✅ Адаптивное дросселирование: полная обработка при открытой позиции
            if symbol not in self._ticker_counter:
                self._ticker_counter[symbol] = 0

            self._ticker_counter[symbol] += 1

            # ✅ FIX (22.01.2026): Проверяем не только позиции, но и pending ордера
            # Если по символу есть открытая позиция ИЛИ pending ордер — не дросселируем
            has_open_position = symbol in self.active_positions_ref
            has_pending_order = False

            # Проверяем pending orders через order_coordinator
            if hasattr(self, "order_coordinator") and self.order_coordinator:
                try:
                    # Проверяем активные лимитные ордера
                    if hasattr(self.order_coordinator, "active_limit_orders"):
                        has_pending_order = any(
                            order_info.get("symbol") == symbol
                            for order_info in self.order_coordinator.active_limit_orders.values()
                        )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Не удалось проверить pending orders для {symbol}: {e}"
                    )

            # Если есть позиция ИЛИ pending ордер - bypass throttle
            has_open_position_or_pending = has_open_position or has_pending_order

            effective_throttle = self._ticker_throttle
            if not has_open_position_or_pending:
                # Оценка волатильности по последним ценам
                try:
                    if (
                        "data" in data
                        and len(data["data"]) > 0
                        and "last" in data["data"][0]
                    ):
                        price = float(data["data"][0]["last"])  # предварительно
                        cache = self._volatility_cache.setdefault(symbol, [])
                        cache.append((time.time(), price))
                        # Храним последние ~60 секунд данных
                        cutoff = time.time() - 60.0
                        self._volatility_cache[symbol] = [
                            p for p in cache if p[0] >= cutoff
                        ]
                        if len(self._volatility_cache[symbol]) >= 2:
                            p0 = self._volatility_cache[symbol][0][1]
                            p1 = self._volatility_cache[symbol][-1][1]
                            if p0 > 0:
                                change_pct = abs(p1 - p0) / p0 * 100.0
                                if change_pct > 0.3:
                                    effective_throttle = self._throttle_config["high"]
                                elif change_pct > 0.1:
                                    effective_throttle = self._throttle_config["medium"]
                                else:
                                    effective_throttle = self._throttle_config["low"]
                except Exception:
                    effective_throttle = self._ticker_throttle

            # Логируем смену состояния throttle (один раз на изменение)
            try:
                state = (
                    "bypass"
                    if has_open_position_or_pending
                    else (
                        "high"
                        if effective_throttle == 1
                        else ("medium" if effective_throttle == 2 else "low")
                    )
                )
                if self._last_throttle_state.get(symbol) != state:
                    self._last_throttle_state[symbol] = state
                    logger.info(
                        f"THROTTLE_STATE {symbol}: {state} (open_position={has_open_position}, pending_order={has_pending_order}, eff={effective_throttle})"
                    )
            except Exception:
                pass

            if not has_open_position_or_pending and (
                self._ticker_counter[symbol] % effective_throttle != 0
            ):
                time_since_last = now - self._last_ticker_processed_ts.get(symbol, 0)
                if time_since_last <= self._ticker_force_process_threshold:
                    # Пропускаем обработку, но логируем редко
                    if self._ticker_counter[symbol] % (effective_throttle * 10) == 0:
                        logger.debug(
                            f"⏭️ Тикер пропущен (адаптивное дросселирование {symbol} 1/{effective_throttle})"
                        )
                    return
                force_log_time = self._last_throttle_force_log_ts.get(symbol, 0)
                if now - force_log_time > self._ticker_force_process_threshold:
                    self._last_throttle_force_log_ts[symbol] = now
                    logger.warning(
                        f"⚠️ Forced ticker processing for {symbol}: "
                        f"{time_since_last:.1f}s since last processed tick (throttle 1/{effective_throttle})"
                    )

            # Извлекаем данные из ответа WebSocket
            if "data" in data and len(data["data"]) > 0:
                ticker = data["data"][0]

                if "last" in ticker:
                    price = float(ticker["last"])

                    # 🔴 BUG #1 FIX: УДАЛЕНА ДЕДУПЛИКАЦИЯ ПО ЦЕНЕ
                    # Была проблема: if price == self.last_prices.get(symbol): return
                    # Это блокировала обновления when price unchanged
                    # Но даже при одной цене нужно обновлять updated_at и проверки!

                    self.last_prices[symbol] = price

                    # ✅ АТОМАРНО: Обновляем свечи, market_data и индикаторы под одним lock
                    if self.data_registry:
                        start_ts = time.perf_counter()
                        async with self._update_lock:
                            # 1) Обновление свечей
                            if not self._use_kline_candles:
                                try:
                                    await self._update_candle_from_ticker(
                                        symbol, price, ticker
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"⚠️ Ошибка обновления свечей для {symbol}: {e}"
                                    )

                            # 2) Обновление FastADX per-symbol (market data уже обновлено в начале функции)
                            try:
                                if self._fast_adx_template:
                                    if symbol not in self._fast_adx_by_symbol:
                                        from src.strategies.scalping.futures.indicators.fast_adx import (
                                            FastADX,
                                        )

                                        period = getattr(
                                            self._fast_adx_template, "period", 9
                                        )
                                        threshold = getattr(
                                            self._fast_adx_template, "threshold", 20.0
                                        )
                                        self._fast_adx_by_symbol[symbol] = FastADX(
                                            period=period, threshold=threshold
                                        )
                                        logger.debug(
                                            f"✅ Создан FastADX экземпляр для {symbol} (period={period}, threshold={threshold})"
                                        )

                                    fast_adx_for_symbol = self._fast_adx_by_symbol[
                                        symbol
                                    ]
                                    fast_adx_for_symbol.update(
                                        high=price, low=price, close=price
                                    )

                                    if self.data_registry:
                                        try:
                                            adx_value = (
                                                fast_adx_for_symbol.get_adx_value()
                                            )
                                            plus_di = fast_adx_for_symbol.get_di_plus()
                                            minus_di = (
                                                fast_adx_for_symbol.get_di_minus()
                                            )

                                            if adx_value is None or adx_value <= 0:
                                                logger.debug(
                                                    f"ℹ️ FastADX not ready для {symbol}, пропускаем сохранение ADX (значение={adx_value})"
                                                )
                                            else:
                                                indicators_to_save = {
                                                    "adx": adx_value,
                                                    "adx_plus_di": plus_di,
                                                    "adx_minus_di": minus_di,
                                                }
                                                await self.data_registry.update_indicators(
                                                    symbol, indicators_to_save
                                                )
                                                logger.debug(
                                                    f"✅ DataRegistry: Сохранен ADX для {symbol}: ADX={adx_value:.2f}, +DI={plus_di:.2f}, -DI={minus_di:.2f}"
                                                )
                                        except Exception as e:
                                            logger.debug(
                                                f"⚠️ Ошибка сохранения ADX в DataRegistry для {symbol}: {e}"
                                            )
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ Не удалось обновить FastADX для {symbol}: {e}"
                                )
                        dur_ms = int((time.perf_counter() - start_ts) * 1000)
                        if dur_ms > 50:
                            logger.warning(
                                f"DATA_ATOMIC_UPDATE_SLOW {symbol} took {dur_ms}ms"
                            )
                        else:
                            logger.debug(f"DATA_ATOMIC_UPDATE {symbol} took {dur_ms}ms")

                        # Периодический health-лог (раз в 30 секунд на символ)
                        now = time.time()
                        last_ts = self._last_health_log_ts.get(symbol, 0)
                        if now - last_ts >= 30:
                            self._last_health_log_ts[symbol] = now
                            try:
                                md = await self.data_registry.get_market_data(symbol)
                                md_age = None
                                if md and md.get("updated_at"):
                                    md_age = (
                                        datetime.now() - md["updated_at"]
                                    ).total_seconds()
                                inds = await self.data_registry.get_indicators(
                                    symbol, check_freshness=False
                                )
                                adx_age = None
                                if inds and inds.get("updated_at"):
                                    adx_age = (
                                        datetime.now() - inds["updated_at"]
                                    ).total_seconds()
                                last_1m = await self.data_registry.get_last_candle(
                                    symbol, "1m"
                                )
                                last_5m = await self.data_registry.get_last_candle(
                                    symbol, "5m"
                                )
                                last1m_age = (
                                    (datetime.now().timestamp() - last_1m.timestamp)
                                    if last_1m
                                    else None
                                )
                                last5m_age = (
                                    (datetime.now().timestamp() - last_5m.timestamp)
                                    if last_5m
                                    else None
                                )
                                logger.info(
                                    f"DATA_HEALTH {symbol} md_age={md_age if md_age is not None else 'N/A'}s "
                                    f"adx_age={adx_age if adx_age is not None else 'N/A'}s "
                                    f"candle1m_age={last1m_age if last1m_age is not None else 'N/A'}s "
                                    f"candle5m_age={last5m_age if last5m_age is not None else 'N/A'}s"
                                )
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ DATA_HEALTH log failed for {symbol}: {e}"
                                )

                    # Логируем получение данных тикера
                    logger.info(f"💰 {symbol}: ${price:.2f}")

                    # Проверяем TP ПЕРВЫМ, затем Loss Cut, затем TSL
                    # ✅ ИСПРАВЛЕНО (TODO #1): Убрали проверку entry_price - он будет восстановлен в update_trailing_stop_loss()
                    if symbol in self.active_positions_ref:
                        # ✅ НОВОЕ: Сначала проверяем умный фильтр индикаторов (SmartExitCoordinator)
                        # Это работает в реальном времени через WebSocket
                        if self.smart_exit_coordinator:
                            try:
                                decision = (
                                    await self.smart_exit_coordinator.check_position(
                                        symbol, self.active_positions_ref[symbol]
                                    )
                                )
                                if decision and decision.get("action") == "close":
                                    # Позиция закрыта по умному фильтру, пропускаем остальные проверки
                                    return  # Выходим из функции, позиция уже закрыта
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ Ошибка SmartExitCoordinator для {symbol}: {e}"
                                )

                        # Затем проверяем TP через manage_position
                        if self.position_manager:
                            await self.position_manager.manage_position(
                                self.active_positions_ref[symbol]
                            )
                        # TSL проверяем после TP (если позиция еще открыта)
                        if symbol in self.active_positions_ref:
                            if self.update_trailing_sl_callback:
                                await self.update_trailing_sl_callback(symbol, price)
                            elif self.trailing_sl_coordinator:
                                await self.trailing_sl_coordinator.update_trailing_stop_loss(
                                    symbol, price
                                )
                    else:
                        # Генерируем сигналы только если позиции нет
                        logger.debug(f"🔍 Проверка сигналов для {symbol}...")
                        if self.check_signals_callback:
                            await self.check_signals_callback(symbol, price)
                        elif self.handle_ticker_callback:
                            await self.handle_ticker_callback(symbol, price)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки данных тикера: {e}")

    async def handle_candle_data(self, symbol: str, data: dict):
        logger.info(f"handle_candle_data вызван для {symbol}, data={str(data)[:200]}")
        # Обновляем updated_at для market_data при каждом поступлении свечи
        if self.data_registry:
            async with self.data_registry._lock:
                if symbol in self.data_registry._market_data:
                    self.data_registry._market_data[symbol][
                        "updated_at"
                    ] = datetime.now()
                    logger.info(
                        f"updated_at установлен для {symbol}: {self.data_registry._market_data[symbol]['updated_at']}"
                    )
                    logger.debug(
                        f"✅ DataRegistry: updated_at обновлен по свечам для {symbol}"
                    )
        """
        Обработка kline (OHLCV) данных от OKX.
        """
        try:
            arg = data.get("arg", {})
            channel = arg.get("channel", "")
            if not channel.startswith("candle"):
                return

            timeframe = channel.replace("candle", "")
            rows = data.get("data", [])
            if not rows:
                return

            # OKX kline format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            row = rows[0]
            if len(row) < 6:
                return

            ts_ms = int(float(row[0]))
            candle_ts = int(ts_ms / 1000)
            open_price = float(row[1])
            high_price = float(row[2])
            low_price = float(row[3])
            close_price = float(row[4])
            volume = float(row[5])
            confirm = str(row[8]) if len(row) > 8 else "0"

            last_ts = self._last_candle_timestamps.get(f"{symbol}_{timeframe}")
            if last_ts == candle_ts:
                await self.data_registry.update_last_candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                )
            else:
                new_candle = OHLCV(
                    timestamp=candle_ts,
                    symbol=symbol,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                    timeframe=timeframe,
                )
                await self.data_registry.add_candle(symbol, timeframe, new_candle)
                self._last_candle_timestamps[f"{symbol}_{timeframe}"] = candle_ts

            if (
                hasattr(self, "structured_logger")
                and self.structured_logger
                and timeframe in ["1m", "5m"]
            ):
                self.structured_logger.log_candle_new(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=candle_ts,
                    price=close_price,
                    open_price=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                )

            if confirm == "1":
                key = f"{symbol}_{timeframe}"
                now_ts = time.time()
                last_log_ts = self._last_kline_log_ts.get(key, 0.0)
                if now_ts - last_log_ts >= 60.0:
                    self._last_kline_log_ts[key] = now_ts
                    logger.info(
                        f"KLINE OK {symbol} {timeframe}: ts={candle_ts} "
                        f"O={open_price:.4f} H={high_price:.4f} "
                        f"L={low_price:.4f} C={close_price:.4f} V={volume:.4f}"
                    )
        except Exception as e:
            logger.warning(f"⚠️ Ошибка обработки kline для {symbol}: {e}")

    def _ensure_ws_watchdog(self) -> None:
        if self._ws_watchdog_task and not self._ws_watchdog_task.done():
            return
        if not self.data_registry:
            return
        try:
            sg_cfg = getattr(self.scalping_config, "signal_generator", {})
            if isinstance(sg_cfg, dict):
                if sg_cfg.get("ws_fresh_max_age") is not None:
                    self._ws_watchdog_max_age = float(sg_cfg.get("ws_fresh_max_age"))
                if sg_cfg.get("ws_watchdog_consecutive_stale") is not None:
                    self._ws_watchdog_stale_threshold = max(
                        1, int(sg_cfg.get("ws_watchdog_consecutive_stale"))
                    )
            else:
                ws_age = getattr(sg_cfg, "ws_fresh_max_age", None)
                if ws_age is not None:
                    self._ws_watchdog_max_age = float(ws_age)
                threshold_val = getattr(
                    sg_cfg,
                    "ws_watchdog_consecutive_stale",
                    self._ws_watchdog_stale_threshold,
                )
                self._ws_watchdog_stale_threshold = max(1, int(threshold_val))
        except Exception:
            pass
        self._ws_watchdog_task = asyncio.create_task(self._ws_watchdog_loop())
        logger.info("WS watchdog started")

    async def _ws_watchdog_loop(self) -> None:
        while True:
            try:
                try:
                    symbols = list(self.scalping_config.symbols)
                except Exception:
                    symbols = []

                for symbol in symbols:
                    try:
                        if not self.data_registry:
                            continue
                        if self._last_ticker_processed_ts.get(symbol) is None:
                            continue
                        is_fresh = await self.data_registry.is_ws_fresh(
                            symbol, max_age=self._ws_watchdog_max_age
                        )
                        if is_fresh:
                            if symbol in self._ws_watchdog_stale_counts:
                                self._ws_watchdog_stale_counts.pop(symbol, None)
                            continue
                        stale_count = self._ws_watchdog_stale_counts.get(symbol, 0) + 1
                        self._ws_watchdog_stale_counts[symbol] = stale_count
                        if stale_count >= 1:  # Логируем при первом stale
                            logger.debug(
                                f"WS_STALE_DETECTED {symbol}: stale_count={stale_count}/{self._ws_watchdog_stale_threshold}, "
                                f"max_age={self._ws_watchdog_max_age:.1f}s"
                            )
                        if stale_count < self._ws_watchdog_stale_threshold:
                            continue
                        now = time.time()
                        last_ts = self._last_ws_watchdog_trigger.get(symbol, 0)
                        if now - last_ts < self._ws_watchdog_cooldown:
                            continue
                        self._last_ws_watchdog_trigger[symbol] = now
                        self._ws_watchdog_stale_counts[symbol] = 0
                        logger.warning(
                            f"WS_STALE_WATCHDOG {symbol}: "
                            f"{stale_count} consecutive stale checks (max_age={self._ws_watchdog_max_age:.1f}s), forcing reconnect"
                        )
                        await self.force_reconnect(
                            symbol=symbol, reason="ws_stale_watchdog"
                        )
                    except Exception as e:
                        logger.debug(f"WS watchdog error for {symbol}: {e}")
            except Exception as e:
                logger.debug(f"WS watchdog loop error: {e}")
            await asyncio.sleep(self._ws_watchdog_interval)

    def _ensure_rest_candle_polling(self):
        if self._rest_candle_task or not self.client:
            return
        self._rest_candle_task = asyncio.create_task(self._rest_candle_poll_loop())
        logger.info("📡 REST candle polling включен (fallback)")

    async def _rest_candle_poll_loop(self):
        while True:
            try:
                await self._poll_rest_candles()
            except Exception as e:
                logger.warning(f"⚠️ REST candle polling error: {e}")
            await asyncio.sleep(self._rest_candle_poll_interval)

    async def _poll_rest_candles(self):
        """Опрос REST API для получения свечей (fallback для Sandbox)"""
        if not self.client:
            logger.warning("⚠️ REST candle polling: client is None, skipping")
            return

        logger.debug("🔄 REST candle polling: starting poll cycle")
        timeframes = ["1m", "5m"]
        updated_count = 0

        for symbol in self.scalping_config.symbols:
            for timeframe in timeframes:
                try:
                    candles = await self.client.get_candles(symbol, timeframe, limit=2)
                    if candles and len(candles) > 0:
                        candle = candles[-1]
                        last_ts = self._last_candle_timestamps.get(
                            f"{symbol}_{timeframe}"
                        )
                        if last_ts == candle.timestamp:
                            await self.data_registry.update_last_candle(
                                symbol=symbol,
                                timeframe=timeframe,
                                high=candle.high,
                                low=candle.low,
                                close=candle.close,
                                volume=candle.volume,
                            )
                            logger.debug(
                                f"✅ REST: Обновлена свеча {symbol} {timeframe}"
                            )
                        else:
                            await self.data_registry.add_candle(
                                symbol, timeframe, candle
                            )
                            self._last_candle_timestamps[
                                f"{symbol}_{timeframe}"
                            ] = candle.timestamp
                            logger.debug(
                                f"✅ REST: Добавлена новая свеча {symbol} {timeframe} (ts={candle.timestamp})"
                            )

                        updated_count += 1

                        if (
                            hasattr(self, "structured_logger")
                            and self.structured_logger
                            and timeframe in ["1m", "5m"]
                        ):
                            self.structured_logger.log_candle_new(
                                symbol=symbol,
                                timeframe=timeframe,
                                timestamp=candle.timestamp,
                                price=candle.close,
                                open_price=candle.open,
                                high=candle.high,
                                low=candle.low,
                                close=candle.close,
                                volume=candle.volume,
                            )
                    else:
                        logger.warning(f"⚠️ REST: Нет свечей для {symbol} {timeframe}")
                except Exception as e:
                    logger.warning(
                        f"⚠️ REST: Ошибка получения свечей {symbol} {timeframe}: {e}"
                    )

                await asyncio.sleep(self._rest_candle_rate_delay)

        logger.info(f"✅ REST candle polling: обновлено {updated_count} свечей")

    def _get_ticker_volume_delta(
        self, symbol: str, volume_ccy_24h: float, volume_24h: float
    ) -> float:
        """
        Estimate per-tick volume using 24h rolling volume from ticker.
        Returns 0 on first observation or if the counter resets.
        """
        if volume_ccy_24h and volume_ccy_24h > 0:
            last = self._last_volume_ccy_24h.get(symbol)
            self._last_volume_ccy_24h[symbol] = volume_ccy_24h
            if last is None or volume_ccy_24h < last:
                return 0.0
            return max(0.0, volume_ccy_24h - last)

        if volume_24h and volume_24h > 0:
            last = self._last_volume_24h.get(symbol)
            self._last_volume_24h[symbol] = volume_24h
            if last is None or volume_24h < last:
                return 0.0
            return max(0.0, volume_24h - last)

        return 0.0

    async def _update_candle_from_ticker(
        self, symbol: str, price: float, ticker: Dict[str, Any]
    ) -> None:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновить свечи для всех таймфреймов (1m, 5m, 1H, 1D) на основе тикера.

        Определяет, нужно ли обновить последнюю свечу или создать новую для каждого таймфрейма:
        - 1m: Если минута не изменилась → обновляем, если изменилась → новая свеча
        - 5m: Если 5 минут не прошло → обновляем, если прошло → новая свеча
        - 1H: Если час не прошел → обновляем, если прошел → новая свеча
        - 1D: Если день не прошел → обновляем, если прошел → новая свеча

        Args:
            symbol: Торговый символ
            price: Текущая цена из тикера
            ticker: Полные данные тикера
        """
        if not self.data_registry:
            return

        try:
            # Получаем текущее время
            current_time = datetime.now()
            current_timestamp = current_time.timestamp()

            # Derive per-tick volume delta from 24h rolling volume (quote or base).
            volume_ccy_24h = float(ticker.get("volCcy24h", 0) or 0)
            volume_24h = float(ticker.get("vol24h", 0) or 0)
            volume_delta = self._get_ticker_volume_delta(
                symbol, volume_ccy_24h, volume_24h
            )

            # ✅ КРИТИЧЕСКОЕ: Обновляем свечи для всех таймфреймов
            await self._update_candle_for_timeframe(
                symbol, "1m", price, current_timestamp, volume_delta
            )
            await self._update_candle_for_timeframe(
                symbol, "5m", price, current_timestamp, volume_delta
            )
            await self._update_candle_for_timeframe(
                symbol, "1H", price, current_timestamp, volume_delta
            )
            await self._update_candle_for_timeframe(
                symbol, "1D", price, current_timestamp, volume_delta
            )

        except Exception as e:
            logger.warning(f"⚠️ Ошибка обновления свечей из тикера для {symbol}: {e}")

    async def _update_candle_for_timeframe(
        self,
        symbol: str,
        timeframe: str,
        price: float,
        current_timestamp: float,
        volume: float,
    ) -> None:
        """
        ✅ КРИТИЧЕСКОЕ: Обновить свечу для конкретного таймфрейма.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, 1D)
            price: Текущая цена
            current_timestamp: Текущий timestamp (Unix секунды)
            volume: Объем (для накопления)
        """
        try:
            # ✅ FIX (21.01.2026): Убрана блокировка ticker-based свечей
            # Предыдущая логика создавала deadlock:
            # - Если REST polling включен → ticker свечи отключались
            # - Но REST polling мог не работать → свечи вообще не обновлялись
            # Теперь ticker-based свечи работают всегда как fallback

            # Определяем интервал таймфрейма в секундах
            timeframe_intervals = {
                "1m": 60,
                "5m": 300,
                "1H": 3600,
                "1D": 86400,
            }

            interval = timeframe_intervals.get(timeframe)
            if not interval:
                return  # Неизвестный таймфрейм, пропускаем

            # Вычисляем timestamp начала текущей свечи
            if timeframe == "1D":
                # Для дневных свечей используем начало дня (UTC)
                current_dt = datetime.utcfromtimestamp(current_timestamp)
                day_start = current_dt.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                current_candle_timestamp = int(day_start.timestamp())
            elif timeframe == "1H":
                # Для часовых свечей используем начало часа
                current_dt = datetime.utcfromtimestamp(current_timestamp)
                hour_start = current_dt.replace(minute=0, second=0, microsecond=0)
                current_candle_timestamp = int(hour_start.timestamp())
            elif timeframe == "5m":
                # Для 5-минутных свечей округляем до 5 минут
                current_candle_timestamp = int(current_timestamp // interval) * interval
            else:  # 1m
                # Для минутных свечей округляем до минуты
                current_candle_timestamp = int(current_timestamp // interval) * interval

            # Получаем последнюю свечу
            last_candle = await self.data_registry.get_last_candle(symbol, timeframe)

            # Ключ для отслеживания последнего timestamp для каждого таймфрейма
            cache_key = f"{symbol}_{timeframe}"
            last_candle_timestamp = getattr(self, "_last_candle_timestamps", {}).get(
                cache_key
            )

            if last_candle and last_candle_timestamp == current_candle_timestamp:
                # Та же свеча (еще формируется) → обновляем
                new_volume = None
                if volume is not None:
                    base_volume = (
                        last_candle.volume
                        if last_candle and last_candle.volume
                        else 0.0
                    )
                    new_volume = base_volume + max(volume, 0.0)
                await self.data_registry.update_last_candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    high=max(price, last_candle.high) if last_candle else price,
                    low=min(price, last_candle.low) if last_candle else price,
                    close=price,
                    volume=new_volume,
                )
            else:
                # Новая свеча → закрываем старую (если была) и создаем новую
                if (
                    last_candle
                    and last_candle_timestamp
                    and last_candle_timestamp < current_candle_timestamp
                ):
                    logger.debug(
                        f"📊 Переход к новой свече {timeframe} для {symbol}: "
                        f"старая={last_candle_timestamp}, новая={current_candle_timestamp}"
                    )

                # Создаем новую свечу
                new_candle = OHLCV(
                    timestamp=current_candle_timestamp,
                    symbol=symbol,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=max(volume or 0.0, 0.0),
                    timeframe=timeframe,
                )

                # Добавляем новую свечу в буфер
                await self.data_registry.add_candle(symbol, timeframe, new_candle)

                # Обновляем отслеживание последнего timestamp
                self._last_candle_timestamps[cache_key] = current_candle_timestamp

                # ✅ НОВОЕ: Логируем создание новой свечи (INFO для важных таймфреймов, DEBUG для 1m)
                if timeframe in ["5m", "1H", "1D"]:
                    logger.info(
                        f"📊 Создана новая свеча {symbol} {timeframe}: "
                        f"timestamp={current_candle_timestamp}, price={price:.2f}"
                    )
                else:
                    logger.debug(
                        f"📊 Создана новая свеча {symbol} {timeframe}: "
                        f"timestamp={current_candle_timestamp}, price={price:.2f}"
                    )

                # ✅ НОВОЕ: Логируем в StructuredLogger (только для важных таймфреймов, чтобы не перегружать)
                if (
                    timeframe in ["5m", "1H", "1D"]
                    and hasattr(self, "structured_logger")
                    and self.structured_logger
                ):
                    try:
                        # ✅ ИСПРАВЛЕНО: Используем данные из new_candle вместо получения из DataRegistry
                        self.structured_logger.log_candle_new(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=current_candle_timestamp,
                            price=price,
                            open_price=new_candle.open,  # ✅ ИСПРАВЛЕНО: переименовано в open_price
                            high=new_candle.high,
                            low=new_candle.low,
                            close=new_candle.close,
                            volume=new_candle.volume,
                        )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка логирования новой свечи в StructuredLogger: {e}"
                        )
        except Exception as e:
            logger.warning(f"⚠️ Ошибка обновления свечи {timeframe} для {symbol}: {e}")

    async def handle_private_ws_positions(self, positions_data: list):
        """
        Обработка обновлений позиций из Private WebSocket.

        Args:
            positions_data: Список позиций из WebSocket
        """
        try:
            position_closed = False  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Флаг для отслеживания закрытий

            for position_data in positions_data:
                symbol = position_data.get("instId", "").replace("-SWAP", "")
                pos_size = float(position_data.get("pos", "0"))

                if abs(pos_size) < 1e-8:
                    # Позиция закрыта - удаляем из active_positions
                    if symbol in self.active_positions_ref:
                        await self.handle_position_closed_via_ws(symbol)
                        position_closed = True  # ✅ Отмечаем, что была закрыта позиция
                    continue

                # Обновляем позицию в active_positions
                if symbol in self.active_positions_ref:
                    # Обновляем данные позиции
                    avg_px = float(position_data.get("avgPx", "0"))
                    update_data = {
                        "size": pos_size,
                        "margin": float(position_data.get("margin", "0")),
                        "avgPx": avg_px,
                        "markPx": float(position_data.get("markPx", "0")),
                        "upl": float(position_data.get("upl", "0")),
                        "uplRatio": float(position_data.get("uplRatio", "0")),
                    }
                    # ✅ НОВОЕ: Сохраняем ADL данные (если доступны)
                    # OKX API может возвращать adlRank или другие поля ADL
                    adl_rank = position_data.get("adlRank") or position_data.get("adl")
                    if adl_rank is not None:
                        try:
                            update_data["adl_rank"] = int(adl_rank)
                        except (ValueError, TypeError):
                            pass
                    # Обновляем entry_price из avgPx, если avgPx > 0
                    if avg_px > 0:
                        update_data["entry_price"] = avg_px

                    # Сохраняем entry_time и другие метаданные при обновлении
                    if "entry_time" not in self.active_positions_ref[symbol]:
                        update_data["entry_time"] = datetime.now(timezone.utc)
                        update_data["timestamp"] = datetime.now(timezone.utc)
                    # Сохраняем режим и другие метаданные, если они есть
                    saved_regime = self.active_positions_ref[symbol].get("regime")
                    saved_position_side = self.active_positions_ref[symbol].get(
                        "position_side"
                    )
                    saved_time_extended = self.active_positions_ref[symbol].get(
                        "time_extended", False
                    )
                    saved_order_type = self.active_positions_ref[symbol].get(
                        "order_type"
                    )
                    saved_post_only = self.active_positions_ref[symbol].get("post_only")

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем active_positions ЗДЕСЬ (не в except!)
                    self.active_positions_ref[symbol].update(update_data)

                    # Восстанавливаем метаданные после update
                    if saved_regime:
                        self.active_positions_ref[symbol]["regime"] = saved_regime
                    if saved_position_side:
                        self.active_positions_ref[symbol][
                            "position_side"
                        ] = saved_position_side
                    if saved_time_extended:
                        self.active_positions_ref[symbol][
                            "time_extended"
                        ] = saved_time_extended
                    if saved_order_type:
                        self.active_positions_ref[symbol][
                            "order_type"
                        ] = saved_order_type
                    if saved_post_only is not None:
                        self.active_positions_ref[symbol]["post_only"] = saved_post_only

                    # ✅ НОВОЕ: Синхронизация с PositionRegistry при WS updates
                    if hasattr(self, "position_registry") and self.position_registry:
                        try:
                            await self.position_registry.update_position(
                                symbol=symbol, position_updates=update_data
                            )
                            logger.debug(
                                f"✅ Registry синхронизирован с WS для {symbol}: upl={update_data.get('upl', 0)}"
                            )
                        except Exception as e:
                            logger.debug(
                                f"Failed to update Registry from WS for {symbol}: {e}"
                            )

                    # ✅ НОВОЕ: Логируем ADL при обновлении позиции (если доступно)
                    if "adl_rank" in update_data:
                        adl_rank = update_data["adl_rank"]
                        adl_status = (
                            "🔴 ВЫСОКИЙ"
                            if adl_rank >= 4
                            else "🟡 СРЕДНИЙ"
                            if adl_rank >= 2
                            else "🟢 НИЗКИЙ"
                        )
                        logger.debug(
                            f"📊 ADL для {symbol}: rank={adl_rank} ({adl_status}) "
                            f"(upl={position_data.get('upl', '0')} USDT)"
                        )

                        # Предупреждение при высоком ADL
                        if adl_rank >= 4:
                            logger.warning(
                                f"⚠️ ВЫСОКИЙ ADL для {symbol}: rank={adl_rank} "
                                f"(риск автоматического сокращения позиции биржей)"
                            )

                    logger.debug(
                        f"📊 Private WS: Позиция {symbol} обновлена (size={pos_size}, upl={position_data.get('upl', '0')})"
                    )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Немедленная синхронизация при закрытии позиций
            if (
                position_closed
                and hasattr(self, "sync_positions_with_exchange")
                and self.sync_positions_with_exchange
            ):
                try:
                    logger.info(
                        "🔄 Private WS: Обнаружено закрытие позиции, синхронизируем немедленно..."
                    )
                    await self.sync_positions_with_exchange(force=True)
                except Exception as e:
                    logger.error(
                        f"❌ Ошибка синхронизации позиций после закрытия через WS: {e}"
                    )

        except Exception as e:
            logger.error(f"❌ Ошибка обработки обновлений позиций из Private WS: {e}")

    async def handle_private_ws_orders(self, orders_data: list):
        """
        Обработка обновлений ордеров из Private WebSocket.

        Args:
            orders_data: Список ордеров из WebSocket
        """
        try:
            for order_data in orders_data:
                order_id = order_data.get("ordId", "")
                state = order_data.get("state", "")
                inst_id = order_data.get("instId", "")
                symbol = inst_id.replace("-SWAP", "") if inst_id else ""

                # Обновляем кэш ордеров через callback или напрямую
                if symbol:
                    order_cache_data = {
                        "order_id": order_id,
                        "state": state,
                        "inst_id": inst_id,
                        "sz": order_data.get("sz", "0"),
                        "px": order_data.get("px", "0"),
                        "side": order_data.get("side", ""),
                        "ordType": order_data.get("ordType", ""),
                        "timestamp": time.time(),
                    }

                    if self.update_active_orders_cache_callback:
                        self.update_active_orders_cache_callback(
                            symbol, order_id, order_cache_data
                        )

                    # Если ордер исполнен или отменен - логируем
                    if state in ["filled", "canceled", "partially_filled"]:
                        logger.debug(
                            f"📊 Private WS: Ордер {order_id} для {symbol} - {state}"
                        )

        except Exception as e:
            logger.error(f"❌ Ошибка обработки обновлений ордеров из Private WS: {e}")

    async def handle_position_closed_via_ws(self, symbol: str):
        """
        Обработка закрытия позиции через Private WebSocket.

        Args:
            symbol: Символ закрытой позиции
        """
        try:
            # Удаляем из active_positions
            if symbol in self.active_positions_ref:
                position = self.active_positions_ref.pop(symbol)

                # ✅ НОВОЕ: Определяем причину закрытия
                # Проверяем, была ли позиция закрыта из-за ADL
                reason = "unknown"

                # Проверяем ADL перед закрытием (если был сохранен)
                adl_rank = position.get("adl_rank")
                if adl_rank is not None and adl_rank >= 4:  # Высокий ADL (4-5 столбцов)
                    # Если позиция была закрыта биржей при высоком ADL, это может быть ADL
                    # Но мы не можем точно определить без дополнительной информации от биржи
                    # Поэтому логируем как "possible_adl" для статистики
                    reason = "possible_adl"
                    logger.warning(
                        f"⚠️ Позиция {symbol} закрыта при высоком ADL (rank={adl_rank}). "
                        f"Возможная причина: Auto-Deleveraging"
                    )

                # Получаем детали позиции для логирования
                # ✅ FIX: Приводим к float чтобы избежать TypeError
                entry_price = float(position.get("entry_price", 0) or 0)
                entry_time = position.get("entry_time")
                size = float(position.get("size", 0) or 0)
                side = position.get("position_side", "unknown")

                # Вычисляем время в позиции
                minutes_in_position = 0.0
                if isinstance(entry_time, datetime):
                    # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                    elif entry_time.tzinfo != timezone.utc:
                        entry_time = entry_time.astimezone(timezone.utc)
                    minutes_in_position = (
                        datetime.now(timezone.utc) - entry_time
                    ).total_seconds() / 60.0

                # ✅ УЛУЧШЕНО: Детальное логирование закрытия через WebSocket
                regime = position.get("regime", "unknown")
                logger.info(
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 ПОЗИЦИЯ ЗАКРЫТА ЧЕРЕЗ WEBSOCKET: {symbol} {side.upper()}\n"
                    f"   🎯 Причина: {reason}\n"
                    f"   📊 Режим рынка: {regime}\n"
                    f"   📊 Entry price: ${entry_price:.6f}\n"
                    f"   📦 Size: {size:.6f} контрактов\n"
                    f"   ⏱️  Время в позиции: {minutes_in_position:.2f} мин\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )

                # DEBUG LOGGER: Логируем закрытие через WebSocket
                if self.debug_logger:
                    # Пытаемся получить последнюю цену для расчета PnL
                    try:
                        current_price = await self.get_current_price_fallback(symbol)
                        if current_price and current_price > 0 and entry_price > 0:
                            # Рассчитываем PnL в процентах
                            # ✅ ИСПРАВЛЕНИЕ: Конвертируем в проценты (умножаем на 100)
                            if side.lower() == "long":
                                profit_pct = (
                                    (current_price - entry_price) / entry_price
                                ) * 100
                            else:
                                profit_pct = (
                                    (entry_price - current_price) / entry_price
                                ) * 100
                        else:
                            profit_pct = 0.0
                    except Exception:
                        profit_pct = 0.0

                    self.debug_logger.log_position_close(
                        symbol=symbol,
                        exit_price=current_price
                        if "current_price" in locals() and current_price
                        else 0.0,
                        pnl_usd=0.0,  # Не можем рассчитать без размера позиции
                        pnl_pct=profit_pct if "profit_pct" in locals() else 0.0,
                        time_in_position_minutes=minutes_in_position,
                        reason=f"ws_{reason}",
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Записываем закрытие позиции в CSV
                if self.performance_tracker:
                    try:
                        # Получаем данные с биржи для точного расчета
                        exit_price = 0.0
                        gross_pnl = 0.0
                        commission = 0.0
                        funding_fee = 0.0
                        size_in_coins = 0.0
                        duration_sec = minutes_in_position * 60.0

                        # Пытаемся получить последнюю цену
                        try:
                            current_price = await self.get_current_price_fallback(
                                symbol
                            )
                            if current_price and current_price > 0:
                                exit_price = current_price
                        except Exception:
                            pass

                        # Пытаемся получить данные позиции с биржи через position_manager
                        if self.position_manager and self.client:
                            try:
                                # Получаем закрытую позицию с биржи (может быть в истории)
                                positions = await self.client.get_positions(
                                    symbol=symbol
                                )
                                if positions and len(positions) > 0:
                                    # Ищем закрытую позицию (size = 0)
                                    for pos in positions:
                                        pos_size = abs(float(pos.get("pos", "0") or 0))
                                        if pos_size < 0.000001:  # Позиция закрыта
                                            # Получаем данные
                                            exit_price_raw = (
                                                pos.get("avgPx")
                                                or pos.get("last")
                                                or exit_price
                                            )
                                            if exit_price_raw:
                                                exit_price = float(exit_price_raw)

                                            # Получаем funding fee
                                            if "fundingFee" in pos:
                                                funding_fee = float(
                                                    pos.get("fundingFee", 0) or 0
                                                )
                                            elif "funding_fee" in pos:
                                                funding_fee = float(
                                                    pos.get("funding_fee", 0) or 0
                                                )

                                            # Получаем realized PnL
                                            realized_pnl = pos.get(
                                                "realizedPnl"
                                            ) or pos.get("realized_pnl")
                                            if realized_pnl:
                                                gross_pnl = float(realized_pnl)

                                            break
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ Не удалось получить данные позиции с биржи для {symbol}: {e}"
                                )

                        # Если exit_price не получен, используем текущую цену
                        if exit_price == 0.0:
                            try:
                                exit_price = await self.get_current_price_fallback(
                                    symbol
                                )
                            except Exception:
                                exit_price = entry_price  # Fallback

                        # Рассчитываем size_in_coins если нужно
                        if size > 0 and self.client:
                            try:
                                details = await self.client.get_instrument_details(
                                    symbol
                                )
                                ct_val = float(details.get("ctVal", "0.01"))
                                size_in_coins = abs(size) * ct_val
                            except Exception:
                                size_in_coins = abs(size)  # Fallback

                        # Рассчитываем gross PnL если не получен с биржи
                        if (
                            gross_pnl == 0.0
                            and entry_price > 0
                            and exit_price > 0
                            and size_in_coins > 0
                        ):
                            if side.lower() == "long":
                                gross_pnl = (exit_price - entry_price) * size_in_coins
                            else:  # short
                                gross_pnl = (entry_price - exit_price) * size_in_coins

                        # Рассчитываем комиссию (примерно, если не получена с биржи)
                        if commission == 0.0 and size_in_coins > 0:
                            trading_fee_rate = 0.0010  # 0.1% по умолчанию
                            if self.scalping_config:
                                commission_config = getattr(
                                    self.scalping_config, "commission", {}
                                )
                                if isinstance(commission_config, dict):
                                    trading_fee_rate = commission_config.get(
                                        "trading_fee_rate", 0.0010
                                    )
                                elif hasattr(commission_config, "trading_fee_rate"):
                                    trading_fee_rate = getattr(
                                        commission_config, "trading_fee_rate", 0.0010
                                    )

                            notional_entry = size_in_coins * entry_price
                            notional_exit = size_in_coins * exit_price
                            commission = (
                                notional_entry + notional_exit
                            ) * trading_fee_rate

                        # Рассчитываем net PnL
                        net_pnl = gross_pnl - commission - funding_fee

                        # Создаем TradeResult
                        from ..spot.position_manager import TradeResult

                        trade_result = TradeResult(
                            symbol=symbol,
                            side=side.lower(),
                            entry_price=entry_price,
                            exit_price=exit_price,
                            size=size_in_coins if size_in_coins > 0 else abs(size),
                            gross_pnl=gross_pnl,
                            commission=commission,
                            net_pnl=net_pnl,
                            duration_sec=duration_sec,
                            reason=f"ws_{reason}",
                            timestamp=datetime.now(timezone.utc),
                            funding_fee=funding_fee,
                        )

                        # Записываем в CSV
                        # PerformanceTracker API: record_trade()
                        self.performance_tracker.record_trade(trade_result)
                        logger.info(
                            f"✅ Закрытие позиции {symbol} через WebSocket записано в CSV"
                        )

                    except Exception as e:
                        logger.error(
                            f"❌ Ошибка записи закрытия позиции {symbol} в CSV: {e}",
                            exc_info=True,
                        )

                # Вызываем callback для обработки закрытия позиции
                if self.handle_position_closed_callback:
                    await self.handle_position_closed_callback(symbol)

        except Exception as e:
            logger.error(
                f"❌ Ошибка обработки закрытия позиции через Private WS: {e}",
                exc_info=True,
            )

    async def get_current_price_fallback(self, symbol: str) -> Optional[float]:
        """
        Получение текущей цены через REST API (fallback если WebSocket не отвечает).

        Args:
            symbol: Символ (например, BTC-USDT)

        Returns:
            Текущая цена или None если не удалось получить
        """
        try:
            # Используем прямой HTTP запрос для публичного endpoint без авторизации
            import aiohttp

            inst_id = f"{symbol}-SWAP"

            # Правильный endpoint для публичного тикера
            base_url = "https://www.okx.com"
            ticker_url = f"{base_url}/api/v5/market/ticker?instId={inst_id}"

            # Создаем временную сессию если нужно
            session = (
                self.client.session
                if self.client
                and hasattr(self.client, "session")
                and self.client.session
                and not self.client.session.closed
                else None
            )
            if not session:
                session = aiohttp.ClientSession()
                close_session = True
            else:
                close_session = False

            try:
                async with session.get(ticker_url) as ticker_resp:
                    if ticker_resp.status == 200:
                        ticker_data = await ticker_resp.json()
                        if ticker_data and ticker_data.get("code") == "0":
                            data = ticker_data.get("data", [])
                            if data and len(data) > 0:
                                last_price = data[0].get("last")
                                if last_price:
                                    return float(last_price)
                    else:
                        logger.debug(
                            f"⚠️ Не удалось получить цену для {symbol}: HTTP {ticker_resp.status}"
                        )
            finally:
                if close_session and session:
                    await session.close()

            logger.debug(f"⚠️ Не удалось получить цену для {symbol} через REST API")
            return None

        except Exception as e:
            logger.debug(f"⚠️ Ошибка получения цены для {symbol}: {e}")
            return None
