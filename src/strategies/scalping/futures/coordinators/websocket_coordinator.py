"""
WebSocket Coordinator для Futures торговли.

Координирует управление WebSocket соединениями:
- Инициализация публичного и приватного WebSocket
- Обработка тикеров из публичного WebSocket
- Обработка обновлений позиций и ордеров из приватного WebSocket
- Fallback для получения цены через REST API
"""

import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from src.models import OHLCV


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
        structured_logger=None,  # ✅ НОВОЕ: StructuredLogger для логирования свечей
        smart_exit_coordinator=None,  # ✅ НОВОЕ: SmartExitCoordinator для умного закрытия
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
        # ✅ НОВОЕ: StructuredLogger для логирования свечей
        self.structured_logger = structured_logger
        # ✅ НОВОЕ: SmartExitCoordinator для умного закрытия
        self.smart_exit_coordinator = smart_exit_coordinator

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Отслеживание последнего timestamp для каждого символа и таймфрейма
        # Формат: "symbol_timeframe" -> timestamp последней обработанной свечи (в секундах)
        self._last_candle_timestamps: Dict[str, int] = {}

        logger.info("✅ WebSocketCoordinator initialized")

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

                # Подписка на тикеры для всех символов
                for symbol in self.scalping_config.symbols:
                    inst_id = f"{symbol}-SWAP"
                    await self.ws_manager.subscribe(
                        channel="tickers",
                        inst_id=inst_id,
                        callback=ticker_callback,  # Один callback для всех
                    )

                logger.info(
                    f"📊 Подписка на тикеры для {len(self.scalping_config.symbols)} пар"
                )
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
        """
        Обработка данных тикера.

        Args:
            symbol: Торговый символ
            data: Данные тикера из WebSocket
        """
        try:
            # Извлекаем данные из ответа WebSocket
            if "data" in data and len(data["data"]) > 0:
                ticker = data["data"][0]

                if "last" in ticker:
                    price = float(ticker["last"])

                    # ✅ НОВОЕ: Обновляем свечи в DataRegistry (инкрементально)
                    if self.data_registry:
                        try:
                            await self._update_candle_from_ticker(symbol, price, ticker)
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Ошибка обновления свечей для {symbol}: {e}"
                            )

                    # ✅ НОВОЕ: Обновляем DataRegistry с рыночными данными
                    if self.data_registry:
                        try:
                            # Извлекаем дополнительные данные из тикера
                            volume_24h = float(ticker.get("vol24h", 0))
                            volume_ccy_24h = float(ticker.get("volCcy24h", 0))
                            high_24h = float(ticker.get("high24h", price))
                            low_24h = float(ticker.get("low24h", price))
                            open_24h = float(ticker.get("open24h", price))

                            # Обновляем market data в DataRegistry
                            await self.data_registry.update_market_data(
                                symbol,
                                {
                                    "price": price,
                                    "last_price": price,
                                    "volume": volume_24h,
                                    "volume_ccy": volume_ccy_24h,
                                    "high_24h": high_24h,
                                    "low_24h": low_24h,
                                    "open_24h": open_24h,
                                    "ticker": ticker,
                                    "updated_at": datetime.now(),
                                },
                            )
                            logger.debug(
                                f"✅ DataRegistry: Обновлены market data для {symbol} (price=${price:.2f})"
                            )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Ошибка обновления DataRegistry для {symbol}: {e}"
                            )

                    # Обновляем FastADX для расчета тренда
                    try:
                        if self.fast_adx:
                            # Для тикера используем текущую цену как high/low/close
                            high = price
                            low = price
                            close = price

                            # Обновляем FastADX для расчета тренда
                            self.fast_adx.update(high=high, low=low, close=close)

                            # ✅ НОВОЕ: Сохраняем ADX в DataRegistry после обновления
                            if self.data_registry:
                                try:
                                    adx_value = self.fast_adx.get_adx_value()
                                    # Также получаем +DI и -DI
                                    plus_di = self.fast_adx.get_di_plus()
                                    minus_di = self.fast_adx.get_di_minus()

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

                    # Логируем получение данных тикера
                    logger.info(f"💰 {symbol}: ${price:.2f}")

                    # Проверяем TP ПЕРВЫМ, затем Loss Cut, затем TSL
                    # ✅ ИСПРАВЛЕНО (TODO #1): Убрали проверку entry_price - он будет восстановлен в update_trailing_stop_loss()
                    if symbol in self.active_positions_ref:
                        # ✅ НОВОЕ: Сначала проверяем умный фильтр индикаторов (SmartExitCoordinator)
                        # Это работает в реальном времени через WebSocket
                        if self.smart_exit_coordinator:
                            try:
                                decision = await self.smart_exit_coordinator.check_position(
                                    symbol, self.active_positions_ref[symbol]
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

            # Определяем объем из тикера (если доступен)
            volume_24h = float(ticker.get("vol24h", 0))
            volume_ccy_24h = float(ticker.get("volCcy24h", 0))
            # Используем volume_ccy_24h для более точного расчета объема в USDT

            # ✅ КРИТИЧЕСКОЕ: Обновляем свечи для всех таймфреймов
            await self._update_candle_for_timeframe(
                symbol, "1m", price, current_timestamp, volume_ccy_24h
            )
            await self._update_candle_for_timeframe(
                symbol, "5m", price, current_timestamp, volume_ccy_24h
            )
            await self._update_candle_for_timeframe(
                symbol, "1H", price, current_timestamp, volume_ccy_24h
            )
            await self._update_candle_for_timeframe(
                symbol, "1D", price, current_timestamp, volume_ccy_24h
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
                await self.data_registry.update_last_candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    high=max(price, last_candle.high) if last_candle else price,
                    low=min(price, last_candle.low) if last_candle else price,
                    close=price,
                    # volume будет обновляться накоплением (можно улучшить)
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
                    volume=0.0,  # Объем будет накапливаться
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
            for position_data in positions_data:
                symbol = position_data.get("instId", "").replace("-SWAP", "")
                pos_size = float(position_data.get("pos", "0"))

                if abs(pos_size) < 1e-8:
                    # Позиция закрыта - удаляем из active_positions
                    if symbol in self.active_positions_ref:
                        await self.handle_position_closed_via_ws(symbol)
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
                        update_data["entry_time"] = datetime.now()
                        update_data["timestamp"] = datetime.now()
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
                else:
                    # Новая позиция - добавляем
                    logger.info(
                        f"📊 Private WS: Обнаружена новая позиция {symbol} (size={pos_size})"
                    )
                    # Позиция будет обработана при следующей синхронизации

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
                entry_price = position.get("entry_price", 0)
                entry_time = position.get("entry_time")
                size = position.get("size", 0)
                side = position.get("position_side", "unknown")

                # Вычисляем время в позиции
                minutes_in_position = 0.0
                if isinstance(entry_time, datetime):
                    minutes_in_position = (
                        datetime.now() - entry_time
                    ).total_seconds() / 60.0

                # Логируем закрытие через WebSocket
                logger.info(
                    f"📊 Private WS: Позиция {symbol} закрыта (причина: {reason}, "
                    f"side={side}, size={size}, entry={entry_price}, time={minutes_in_position:.2f} мин)"
                )

                # DEBUG LOGGER: Логируем закрытие через WebSocket
                if self.debug_logger:
                    # Пытаемся получить последнюю цену для расчета PnL
                    try:
                        current_price = await self.get_current_price_fallback(symbol)
                        if current_price and current_price > 0 and entry_price > 0:
                            # Рассчитываем PnL
                            if side.lower() == "long":
                                profit_pct = (current_price - entry_price) / entry_price
                            else:
                                profit_pct = (entry_price - current_price) / entry_price
                        else:
                            profit_pct = 0.0
                    except:
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

                # Вызываем callback для обработки закрытия позиции
                if self.handle_position_closed_callback:
                    await self.handle_position_closed_callback(symbol)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки закрытия позиции через Private WS: {e}")

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
