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
        handle_ticker_callback: Optional[Callable[[str, float], Awaitable[None]]] = None,
        update_trailing_sl_callback: Optional[Callable[[str, float], Awaitable[None]]] = None,
        check_signals_callback: Optional[Callable[[str, float], Awaitable[None]]] = None,
        handle_position_closed_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        update_active_positions_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        update_active_orders_cache_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
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

                    # Обновляем FastADX для расчета тренда
                    try:
                        if self.fast_adx:
                            # Для тикера используем текущую цену как high/low/close
                            high = price
                            low = price
                            close = price

                            # Обновляем FastADX для расчета тренда
                            self.fast_adx.update(high=high, low=low, close=close)
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось обновить FastADX для {symbol}: {e}"
                        )

                    # Логируем получение данных тикера
                    logger.info(f"💰 {symbol}: ${price:.2f}")

                    # Проверяем TP ПЕРВЫМ, затем Loss Cut, затем TSL
                    if (
                        symbol in self.active_positions_ref
                        and "entry_price" in self.active_positions_ref.get(symbol, {})
                    ):
                        # Сначала проверяем TP через manage_position
                        if self.position_manager:
                            await self.position_manager.manage_position(
                                self.active_positions_ref[symbol]
                            )
                        # TSL проверяем после TP (если позиция еще открыта)
                        if symbol in self.active_positions_ref:
                            if self.update_trailing_sl_callback:
                                await self.update_trailing_sl_callback(symbol, price)
                            elif self.trailing_sl_coordinator:
                                await self.trailing_sl_coordinator.update_trailing_stop_loss(symbol, price)
                    else:
                        # Генерируем сигналы только если позиции нет
                        logger.debug(f"🔍 Проверка сигналов для {symbol}...")
                        if self.check_signals_callback:
                            await self.check_signals_callback(symbol, price)
                        elif self.handle_ticker_callback:
                            await self.handle_ticker_callback(symbol, price)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки данных тикера: {e}")

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
                    saved_order_type = self.active_positions_ref[symbol].get("order_type")
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
                        self.active_positions_ref[symbol]["order_type"] = saved_order_type
                    if saved_post_only is not None:
                        self.active_positions_ref[symbol]["post_only"] = saved_post_only
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
                        self.update_active_orders_cache_callback(symbol, order_id, order_cache_data)

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
                
                # Логируем закрытие
                reason = "unknown"
                
                # Получаем детали позиции для логирования
                entry_price = position.get("entry_price", 0)
                entry_time = position.get("entry_time")
                size = position.get("size", 0)
                side = position.get("position_side", "unknown")
                
                # Вычисляем время в позиции
                minutes_in_position = 0.0
                if isinstance(entry_time, datetime):
                    minutes_in_position = (datetime.now() - entry_time).total_seconds() / 60.0
                
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
                        exit_price=current_price if 'current_price' in locals() and current_price else 0.0,
                        pnl_usd=0.0,  # Не можем рассчитать без размера позиции
                        pnl_pct=profit_pct if 'profit_pct' in locals() else 0.0,
                        time_in_position_minutes=minutes_in_position,
                        reason=f"ws_{reason}"
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
                if self.client and hasattr(self.client, "session") and self.client.session and not self.client.session.closed
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

