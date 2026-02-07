"""
Private WebSocket Manager для мониторинга позиций и ордеров в реальном времени.

Обеспечивает мгновенные обновления о состоянии позиций и ордеров без периодических REST запросов.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Callable, Dict, Optional

import aiohttp
from cachetools import TTLCache
from loguru import logger


class PrivateWebSocketManager:
    """
    Менеджер Private WebSocket для мониторинга позиций и ордеров.

    Автоматически подключается к Private WebSocket OKX,
    аутентифицируется и подписывается на каналы positions и orders.
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        passphrase: str,
        sandbox: bool = True,
    ):
        """
        Инициализация Private WebSocket Manager.

        Args:
            api_key: API ключ OKX
            secret_key: Секретный ключ OKX
            passphrase: Парольная фраза OKX
            sandbox: Использовать sandbox окружение
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.sandbox = sandbox

        # ✅ ИСПРАВЛЕНО: URL Private WebSocket зависит от окружения (sandbox/production)
        # ✅ ВЫБОР ПОРТОВ: 443 вместо 8443 для лучшей региональной доступности
        if sandbox:
            # Sandbox (demo) окружение - используем порт 443 для регионов с блокировкой 8443
            self.ws_url = "wss://wspap.okx.com:443/ws/v5/private"
        else:
            # Production окружение - используем ws.okx.com:8443
            self.ws_url = "wss://ws.okx.com:8443/ws/v5/private"

        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.connected = False
        self.authenticated = False

        # Callbacks для обработки данных
        self.position_callback: Optional[Callable] = None
        self.order_callback: Optional[Callable] = None
        self.account_callback: Optional[Callable] = None

        # Фоновые задачи
        self.listener_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None

        # Подписки
        self.subscribed_channels = set()

        # Флаг для остановки
        self.should_run = True

        # ✅ FIX: Дедупликация posId с TTL 5 минут (предотвращает двойную обработку)
        self.seen_pos: TTLCache = TTLCache(maxsize=10_000, ttl=300)

        # ✅ FIX: Счётчик reconnect с exponential backoff
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10

        logger.info(f"PrivateWebSocketManager инициализирован (sandbox={sandbox})")

    async def connect(self) -> bool:
        """
        Подключение к Private WebSocket.

        Returns:
            True если подключение успешно
        """
        try:
            if self.connected:
                logger.warning("⚠️ Private WebSocket уже подключен")
                return True

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.02.2026): Закрываем старую сессию перед созданием новой
            # БАГ #3: Утечка aiohttp sessions - старая сессия перезаписывалась без закрытия
            if self.session and not self.session.closed:
                try:
                    await self.session.close()
                    logger.debug(
                        "✅ Закрыта предыдущая Private WebSocket сессия перед переподключением"
                    )
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка при закрытии старой сессии: {e}")

            # Создаем сессию
            self.session = aiohttp.ClientSession()

            # Подключаемся к WebSocket
            self.ws = await self.session.ws_connect(
                self.ws_url,
                heartbeat=20,  # Ping каждые 20 секунд
                timeout=aiohttp.ClientTimeout(total=600),  # 10 минут таймаут
            )

            self.connected = True
            logger.info("✅ Private WebSocket подключен")

            # Аутентифицируемся
            auth_success = await self._authenticate()
            if not auth_success:
                logger.error("❌ Аутентификация не удалась")
                await self.disconnect()
                return False

            # Запускаем listener и heartbeat
            self.listener_task = asyncio.create_task(self._listen_for_data())
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            logger.info("✅ Private WebSocket готов к работе")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подключения Private WebSocket: {e}")
            await self.disconnect()
            return False

    async def _authenticate(self) -> bool:
        """
        Аутентификация в Private WebSocket.

        Returns:
            True если аутентификация успешна
        """
        try:
            # OKX требует Unix timestamp в секундах (строка)
            timestamp = str(int(time.time()))
            message = f"{timestamp}GET/users/self/verify"

            # Подпись для OKX WebSocket (как в REST API)
            signature = base64.b64encode(
                hmac.new(
                    self.secret_key.encode("utf-8"),
                    message.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")

            auth_msg = {
                "op": "login",
                "args": [
                    {
                        "apiKey": self.api_key,
                        "passphrase": self.passphrase,
                        "timestamp": timestamp,
                        "sign": signature,
                    }
                ],
            }

            await self.ws.send_str(json.dumps(auth_msg))
            logger.debug(f"🔐 Аутентификация отправлена (timestamp: {timestamp})")

            # Ждем ответ на аутентификацию
            try:
                response = await asyncio.wait_for(self.ws.receive(), timeout=5.0)
                if response.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(response.data)
                    if data.get("event") == "login" and data.get("code") == "0":
                        self.authenticated = True
                        logger.info("✅ Private WebSocket аутентификация успешна")
                        return True
                    else:
                        logger.error(f"❌ Ошибка аутентификации: {data}")
                        return False
                else:
                    logger.error(f"❌ Неожиданный ответ аутентификации: {response.type}")
                    return False
            except asyncio.TimeoutError:
                logger.error("❌ Таймаут аутентификации Private WebSocket")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка аутентификации: {e}")
            return False

    async def subscribe_positions(self, callback: Callable) -> bool:
        """
        Подписка на обновления позиций.

        Args:
            callback: Callback для обработки обновлений позиций

        Returns:
            True если подписка успешна
        """
        if not self.connected or not self.authenticated:
            logger.error("❌ Private WebSocket не подключен или не аутентифицирован")
            return False

        try:
            self.position_callback = callback

            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": "positions", "instType": "SWAP"}],
            }

            await self.ws.send_str(json.dumps(subscribe_msg))
            self.subscribed_channels.add("positions")

            logger.info("📊 Подписка на позиции отправлена")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подписки на позиции: {e}")
            return False

    async def subscribe_orders(self, callback: Callable) -> bool:
        """
        Подписка на обновления ордеров.

        Args:
            callback: Callback для обработки обновлений ордеров

        Returns:
            True если подписка успешна
        """
        if not self.connected or not self.authenticated:
            logger.error("❌ Private WebSocket не подключен или не аутентифицирован")
            return False

        try:
            self.order_callback = callback

            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": "orders", "instType": "SWAP"}],
            }

            await self.ws.send_str(json.dumps(subscribe_msg))
            self.subscribed_channels.add("orders")

            logger.info("📊 Подписка на ордера отправлена")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подписки на ордера: {e}")
            return False

    async def subscribe_account(self, callback: Callable) -> bool:
        """
        Подписка на обновления аккаунта (баланс, маржа).

        Args:
            callback: Callback для обработки обновлений аккаунта

        Returns:
            True если подписка успешна
        """
        if not self.connected or not self.authenticated:
            logger.error("❌ Private WebSocket не подключен или не аутентифицирован")
            return False

        try:
            self.account_callback = callback

            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": "account"}],
            }

            await self.ws.send_str(json.dumps(subscribe_msg))
            self.subscribed_channels.add("account")

            logger.info("📊 Подписка на аккаунт отправлена")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подписки на аккаунт: {e}")
            return False

    async def _listen_for_data(self):
        """Слушаем данные от Private WebSocket."""
        while self.should_run and self.connected and self.ws:
            try:
                async for msg in self.ws:
                    if not self.should_run:
                        break

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        await self._handle_data(data)

                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(
                            f"❌ Private WebSocket error: {self.ws.exception()}"
                        )
                        await self._handle_disconnect()
                        break

                    elif msg.type == aiohttp.WSMsgType.CLOSE:
                        logger.warning("🔌 Private WebSocket закрыт сервером")
                        await self._handle_disconnect()
                        break

            except Exception as e:
                logger.error(f"❌ Ошибка в Private WebSocket listener: {e}")
                await self._handle_disconnect()
                break

            await asyncio.sleep(1)

    async def _handle_data(self, data: dict):
        """Обработка данных от Private WebSocket."""
        try:
            # Обрабатываем события (subscribe, login, error)
            event = data.get("event")
            if event:
                if event == "subscribe":
                    arg = data.get("arg", {})
                    channel = arg.get("channel")
                    logger.info(f"✅ Подписка подтверждена: {channel}")
                    return
                elif event == "login":
                    if data.get("code") == "0":
                        logger.info("✅ Login подтвержден")
                    else:
                        logger.error(f"❌ Ошибка login: {data}")
                    return
                elif event == "error":
                    logger.error(f"❌ Private WebSocket error: {data}")
                    return

            # Обрабатываем данные каналов
            arg = data.get("arg", {})
            channel = arg.get("channel")

            if channel == "positions":
                positions_data = data.get("data", [])
                if positions_data and self.position_callback:
                    # ✅ FIX: Дедупликация по posId (биржа может слать дубли)
                    filtered_positions = []
                    for pos in positions_data:
                        pos_id = pos.get("posId")
                        if pos_id and pos_id in self.seen_pos:
                            logger.debug(f"⏭️ Пропуск дубликата позиции: {pos_id}")
                            continue
                        if pos_id:
                            self.seen_pos[pos_id] = True
                        filtered_positions.append(pos)

                    if filtered_positions:
                        await self.position_callback(filtered_positions)

            elif channel == "orders":
                orders_data = data.get("data", [])
                if orders_data and self.order_callback:
                    await self.order_callback(orders_data)

            elif channel == "account":
                account_data = data.get("data", [])
                if account_data and self.account_callback:
                    await self.account_callback(account_data)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки данных Private WebSocket: {e}")

    async def _heartbeat_loop(self):
        """Heartbeat мониторинг - отправляем ping каждые 25 секунд."""
        while self.should_run and self.connected:
            try:
                await asyncio.sleep(25)  # OKX требует ping каждые 30 секунд
                if self.ws and not self.ws.closed and self.connected:
                    await self.ws.ping()
                    logger.debug("💓 Private WebSocket ping отправлен")
            except Exception as e:
                logger.error(f"❌ Ошибка heartbeat: {e}")
                await self._handle_disconnect()
                break

    async def _handle_disconnect(self):
        """Обработка отключения."""
        logger.warning("🔌 Private WebSocket отключен")
        self.connected = False
        self.authenticated = False

        # Пытаемся переподключиться
        if self.should_run:
            # ✅ FIX: Проверка лимита переподключений
            if self._reconnect_attempts >= self._max_reconnect_attempts:
                logger.critical(
                    f"WS_MAX_RECONNECT reached ({self._max_reconnect_attempts}), stopping"
                )
                self.should_run = False
                return

            # ✅ FIX: Exponential backoff (5, 10, 20, 40... max 300 сек)
            delay = min(5 * (2**self._reconnect_attempts), 300)
            self._reconnect_attempts += 1

            logger.info(
                f"🔄 Попытка переподключения Private WebSocket "
                f"({self._reconnect_attempts}/{self._max_reconnect_attempts}, delay={delay}s)..."
            )

            # ✅ FIX: Закрываем старый сокет перед reconnect (предотвращает утечку)
            if self.ws and not self.ws.closed:
                try:
                    await self.ws.close()
                    logger.info("WS_DISCONNECT old socket closed")
                except Exception:
                    pass
                self.ws = None

            await asyncio.sleep(delay)
            if self.should_run:
                success = await self.connect()
                if success:
                    # ✅ FIX: Сброс счётчика после успешного подключения
                    self._reconnect_attempts = 0
                    # Восстанавливаем подписки
                    if self.position_callback:
                        await self.subscribe_positions(self.position_callback)
                    if self.order_callback:
                        await self.subscribe_orders(self.order_callback)
                    if self.account_callback:
                        await self.subscribe_account(self.account_callback)

    async def disconnect(self):
        """Отключение от Private WebSocket."""
        self.should_run = False
        self.connected = False
        self.authenticated = False

        # Останавливаем задачи
        if self.listener_task:
            self.listener_task.cancel()
        if self.heartbeat_task:
            self.heartbeat_task.cancel()

        # Закрываем WebSocket
        if self.ws:
            try:
                await self.ws.close()
                await asyncio.sleep(0.1)
            except Exception:
                pass

        # ✅ ИСПРАВЛЕНО: Закрываем сессию с явным ожиданием
        if self.session:
            try:
                if not self.session.closed:
                    await self.session.close()
                    # Даем время на полное закрытие сессии
                    await asyncio.sleep(0.2)
                self.session = None
                logger.debug("✅ Private WebSocket сессия закрыта")
            except Exception as e:
                logger.debug(f"⚠️ Ошибка при закрытии Private WebSocket сессии: {e}")
                self.session = None

        logger.info("🔌 Private WebSocket отключен")

    def get_status(self) -> Dict[str, any]:
        """Получение статуса Private WebSocket."""
        return {
            "connected": self.connected,
            "authenticated": self.authenticated,
            "subscribed_channels": list(self.subscribed_channels),
            "has_position_callback": self.position_callback is not None,
            "has_order_callback": self.order_callback is not None,
            "has_account_callback": self.account_callback is not None,
        }

    def __repr__(self) -> str:
        """Строковое представление менеджера."""
        status = self.get_status()
        return (
            f"PrivateWebSocketManager("
            f"connected={status['connected']}, "
            f"authenticated={status['authenticated']}, "
            f"channels={len(status['subscribed_channels'])}"
            f")"
        )
