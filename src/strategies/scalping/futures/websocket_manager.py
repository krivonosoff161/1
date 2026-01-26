"""
Auto-Reconnect WebSocket Manager для Futures торговли.

Автоматическое переподключение при обрыве соединения,
мониторинг здоровья WebSocket и восстановление подписок.
"""

import asyncio
import json
import time
from collections import deque
from typing import Callable, Dict, Optional

import aiohttp
from loguru import logger


class FuturesWebSocketManager:
    """
    Менеджер WebSocket с авто-реконнектом для Futures.

    Автоматически переподключается при обрыве связи,
    восстанавливает подписки и мониторит здоровье соединения.
    """

    async def ensure_fresh_connection(self):
        """Проверяет свежесть соединения и heartbeat, авто-reconnect если требуется"""
        time_since_heartbeat = time.time() - self.last_heartbeat
        if not self.connected or time_since_heartbeat > self.heartbeat_interval * 2:
            logger.warning(
                f"⚠️ WebSocket stale/отключен ({time_since_heartbeat:.1f}s), авто-reconnect..."
            )
            await self._handle_disconnect()
            return False
        return True

    async def auto_reconnect(self):
        """Автоматически переподключает WebSocket если соединение неактуально"""
        if not await self.ensure_fresh_connection():
            logger.info("🔄 WebSocket auto-reconnect выполнен")
            return True
        return False

    async def force_reconnect(self, reason: str = "") -> bool:
        """Принудительный reconnect даже если heartbeat жив."""
        if not self.should_reconnect:
            self.should_reconnect = True
        self.reconnect_attempts = 0
        msg = f"Force WebSocket reconnect: {reason}" if reason else "Force WebSocket reconnect"
        logger.warning(msg)
        await self._handle_disconnect()
        return True

    def __init__(
        self,
        ws_url: str = "wss://ws.okx.com:8443/ws/v5/public",
        max_reconnect_attempts: int = 10,
        reconnect_delay: float = 5.0,
        heartbeat_interval: float = 30.0,
    ):
        """
        Инициализация WebSocket Manager.

        Args:
            ws_url: URL WebSocket
            max_reconnect_attempts: Максимум попыток переподключения
            reconnect_delay: Задержка между попытками (сек)
            heartbeat_interval: Интервал heartbeat (сек)
        """
        self.ws_url = ws_url
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[
            aiohttp.ClientSession
        ] = None  # ✅ Сохраняем сессию для закрытия
        self.connected = False
        self.subscribed_channels: Dict[str, dict] = {}
        self.callbacks: Dict[str, Callable] = {}

        self.reconnect_attempts = 0
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.heartbeat_interval = heartbeat_interval
        self.last_heartbeat = time.time()

        self.should_reconnect = True
        self.reconnect_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.listener_task: Optional[asyncio.Task] = None
        self._receive_lock = asyncio.Lock()

        logger.info(
            f"FuturesWebSocketManager инициализирован: "
            f"url={ws_url}, max_attempts={max_reconnect_attempts}"
        )

    async def connect(self) -> bool:
        """
        Подключение к WebSocket.

        Returns:
            True если подключение успешно
        """
        try:
            if self.connected and self.ws and not self.ws.closed:
                logger.debug("WebSocket уже подключен")
                return True

            # ✅ Сохраняем сессию для корректного закрытия
            if self.session and not self.session.closed:
                try:
                    await self.session.close()
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
            self.session = aiohttp.ClientSession()
            self.ws = await self.session.ws_connect(self.ws_url)
            self.connected = True
            self.reconnect_attempts = 0
            self.last_heartbeat = time.time()

            # Запускаем задачи
            if self.listener_task and not self.listener_task.done():
                self.listener_task.cancel()
            self.listener_task = asyncio.create_task(self._listen_for_data())
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            logger.info("✅ WebSocket подключен")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подключения WebSocket: {e}")
            return False

    async def disconnect(self):
        """Отключение от WebSocket."""
        self.should_reconnect = False
        self.connected = False

        # Останавливаем задачи
        if self.reconnect_task:
            self.reconnect_task.cancel()
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.listener_task:
            self.listener_task.cancel()

        if self.ws:
            try:
                await self.ws.close()
                # Ждем закрытия
                await asyncio.sleep(0.1)
            except Exception:
                pass

        # ✅ КРИТИЧЕСКОЕ: Закрываем сессию, чтобы не было "Unclosed client session"
        if self.session and not self.session.closed:
            try:
                await self.session.close()
                await asyncio.sleep(0.1)  # Даем время на корректное закрытие
                logger.debug("✅ WebSocket сессия закрыта")
            except Exception as e:
                logger.debug(f"⚠️ Ошибка при закрытии WebSocket сессии: {e}")

        logger.info("🔌 WebSocket отключен")

    async def subscribe(self, channel: str, inst_id: str, callback: Callable) -> bool:
        """
        Подписка на канал.

        Args:
            channel: Канал (tickers, trades, books, и т.д.)
            inst_id: ID инструмента (BTC-USDT-SWAP)
            callback: Callback для обработки данных

        Returns:
            True если подписка успешна
        """
        if not self.connected or not self.ws:
            logger.error("WebSocket не подключен")
            return False

        try:
            # Сохраняем callback
            key = f"{channel}:{inst_id}"
            self.callbacks[key] = callback

            # Отправляем подписку
            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": channel, "instId": inst_id}],
            }

            await self.ws.send_str(json.dumps(subscribe_msg))

            # Сохраняем информацию о подписке
            self.subscribed_channels[key] = {"channel": channel, "instId": inst_id}

            logger.info(f"📊 Подписка: {channel} - {inst_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подписки: {e}")
            return False

    async def _listen_for_data(self):
        """Слушаем данные от WebSocket."""
        while self.should_reconnect and self.connected and self.ws:
            try:
                async with self._receive_lock:
                    msg = await self.ws.receive()

                if msg.type == aiohttp.WSMsgType.TEXT:
                    # OKX может присылать ping/pong как plain text
                    if msg.data == "pong":
                        self.last_heartbeat = time.time()
                        continue
                    if msg.data == "ping":
                        try:
                            await self.ws.send_str("pong")
                        except Exception:
                            pass
                        self.last_heartbeat = time.time()
                        continue
                    data = json.loads(msg.data)
                    await self._handle_data(data)

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self.ws.exception()}")
                    await self._handle_disconnect()
                    break

                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.warning("WebSocket закрыт сервером")
                    await self._handle_disconnect()
                    break

            except Exception as e:
                logger.error(f"Ошибка в WebSocket listener: {e}")
                await self._handle_disconnect()

            await asyncio.sleep(0)

    async def _handle_data(self, data: dict):
        """Обработка данных от WebSocket."""
        try:
            # Обновляем heartbeat
            self.last_heartbeat = time.time()

            # Обрабатываем ответы
            event = data.get("event")
            if event == "subscribe":
                logger.info(f"✅ Подписка подтверждена: {data.get('arg', {})}")
                return
            elif event == "error":
                logger.error(f"WebSocket error: {data}")
                return

            # Обрабатываем данные
            arg = data.get("arg", {})
            channel = arg.get("channel")
            inst_id = arg.get("instId")

            if channel and inst_id:
                key = f"{channel}:{inst_id}"
                if key in self.callbacks:
                    await self.callbacks[key](data)

        except Exception as e:
            logger.error(f"Ошибка обработки данных: {e}")

    async def _handle_disconnect(self):
        """Обработка отключения."""
        logger.warning("🔌 WebSocket отключен")
        self.connected = False

        current_task = asyncio.current_task()
        if self.listener_task and self.listener_task is not current_task:
            if not self.listener_task.done():
                self.listener_task.cancel()

        # Закрываем текущие соединения, чтобы избежать утечек ClientSession
        await self._close_ws_session()

        if self.should_reconnect:
            await self._reconnect()

    async def _close_ws_session(self):
        """Закрывает текущие ws/session без отключения авто-reconnect."""
        if self.ws and not self.ws.closed:
            try:
                await self.ws.close()
                await asyncio.sleep(0.05)
            except Exception:
                pass
        self.ws = None

        if self.session and not self.session.closed:
            try:
                await self.session.close()
                await asyncio.sleep(0.05)
            except Exception:
                pass
        self.session = None

    async def _reconnect(self):
        """Автоматическое переподключение."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(
                f"❌ Максимум попыток переподключения достигнут "
                f"({self.max_reconnect_attempts})"
            )
            self.should_reconnect = False
            return

        self.reconnect_attempts += 1
        logger.info(
            f"🔄 Попытка переподключения {self.reconnect_attempts}/"
            f"{self.max_reconnect_attempts}..."
        )

        await asyncio.sleep(self.reconnect_delay)

        if await self.connect():
            # Восстанавливаем подписки
            await self._restore_subscriptions()

    async def _restore_subscriptions(self):
        """Восстановление подписок после переподключения."""
        if len(self.subscribed_channels) == 0:
            return

        logger.info(f"📊 Восстановление {len(self.subscribed_channels)} подписок...")

        for key, info in self.subscribed_channels.items():
            channel = info["channel"]
            inst_id = info["instId"]
            callback = self.callbacks.get(key)

            if callback:
                await self.subscribe(channel, inst_id, callback)

    async def _heartbeat_loop(self):
        """Heartbeat мониторинг."""
        while self.should_reconnect:
            await asyncio.sleep(self.heartbeat_interval)

            # Проверяем последний heartbeat
            time_since_heartbeat = time.time() - self.last_heartbeat

            if time_since_heartbeat > self.heartbeat_interval * 2:
                logger.warning(f"⚠️ Heartbeat timeout: {time_since_heartbeat:.1f}s")
                await self._handle_disconnect()
                break

    def get_status(self) -> Dict[str, any]:
        """Получение статуса WebSocket."""
        return {
            "connected": self.connected,
            "subscribed_channels": len(self.subscribed_channels),
            "reconnect_attempts": self.reconnect_attempts,
            "last_heartbeat": self.last_heartbeat,
            "time_since_heartbeat": time.time() - self.last_heartbeat,
        }

    def __repr__(self) -> str:
        """Строковое представление менеджера."""
        status = self.get_status()
        return (
            f"FuturesWebSocketManager("
            f"connected={self.connected}, "
            f"channels={status['subscribed_channels']}, "
            f"reconnect={self.reconnect_attempts}/{self.max_reconnect_attempts}"
            f")"
        )
