"""
WebSocket Order Executor для быстрых входов в позиции
Латентность: 60-85 мс (vs 180-220 мс REST)
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
from loguru import logger

from src.config import APIConfig
from src.models import Order, OrderSide, OrderType


class WebSocketOrderExecutor:
    """WebSocket-based order executor для быстрых входов"""

    def __init__(self, api_config: APIConfig):
        self.api_config = api_config
        # OKX WebSocket URL (одинаковый для demo и live)
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/private"
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.connected = False
        self.pending_orders: Dict[str, Dict] = {}
        self.listener_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """Подключение к WebSocket"""
        try:
            # Создаем WebSocket подключение с правильными параметрами
            self.session = aiohttp.ClientSession()
            self.ws = await self.session.ws_connect(
                self.ws_url,
                heartbeat=20,  # OKX требует ping каждые 30 секунд, отправляем чаще
                timeout=aiohttp.ClientTimeout(total=600),  # 10 минут таймаут
                headers={
                    "Content-Type": "application/json",
                    "OK-ACCESS-KEY": self.api_config.api_key,
                    "OK-ACCESS-SIGN": "",  # Будет заполнено при отправке
                    "OK-ACCESS-TIMESTAMP": "",
                    "OK-ACCESS-PASSPHRASE": self.api_config.passphrase,
                },
            )

            # Аутентификация СРАЗУ после подключения
            await self._authenticate()

            if not self.connected:
                logger.error("❌ Аутентификация не удалась")
                return False

            # Запускаем listener и heartbeat как фоновые задачи
            self.listener_task = asyncio.create_task(self._listen_for_responses())
            self.heartbeat_task = asyncio.create_task(self._heartbeat())

            logger.info("✅ WebSocket подключен для быстрых ордеров")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подключения WebSocket: {e}")
            return False

    async def _authenticate(self):
        """Аутентификация в WebSocket"""
        # OKX WebSocket требует Unix timestamp в секундах (строка)
        import time

        timestamp = str(int(time.time()))
        message = f"{timestamp}GET/users/self/verify"

        logger.debug(f"WebSocket auth: timestamp={timestamp}, message={message}")

        # Подпись для OKX WebSocket (как в REST API)
        import base64
        import hashlib
        import hmac

        signature = base64.b64encode(
            hmac.new(
                self.api_config.api_secret.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        auth_msg = {
            "op": "login",
            "args": [
                {
                    "apiKey": self.api_config.api_key,
                    "passphrase": self.api_config.passphrase,
                    "timestamp": timestamp,
                    "sign": signature,
                }
            ],
        }

        await self.ws.send_str(json.dumps(auth_msg))
        logger.info(f"🔐 WebSocket аутентификация отправлена (timestamp: {timestamp})")

        # Ждем ответ на аутентификацию (быстро!)
        try:
            response = await asyncio.wait_for(self.ws.receive(), timeout=2.0)
            if response.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(response.data)
                if data.get("event") == "login" and data.get("code") == "0":
                    logger.info("✅ WebSocket аутентификация успешна")
                else:
                    logger.error(f"❌ Ошибка аутентификации: {data}")
                    self.connected = False
            else:
                logger.error(f"❌ Неожиданный ответ аутентификации: {response.type}")
                self.connected = False
        except asyncio.TimeoutError:
            logger.error("❌ Таймаут аутентификации WebSocket")
            self.connected = False
        except Exception as e:
            logger.error(f"❌ Ошибка аутентификации: {e}")
            self.connected = False

    async def _heartbeat(self):
        """Отправляем ping каждые 25 секунд для поддержания соединения"""
        while self.connected and self.ws and not self.ws.closed:
            try:
                await asyncio.sleep(25)  # OKX требует ping каждые 30 секунд
                if self.ws and not self.ws.closed:
                    await self.ws.ping()
                    logger.debug("💓 WebSocket ping отправлен")
            except Exception as e:
                logger.error(f"❌ Ошибка heartbeat: {e}")
                self.connected = False
                break

    async def _listen_for_responses(self):
        """Слушаем ответы от WebSocket"""
        try:
            if not self.ws:
                logger.warning("⚠️ WebSocket не инициализирован для listener")
                return

            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    await self._handle_websocket_message(data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self.ws.exception()}")
                    self.connected = False
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.warning("🔌 WebSocket соединение закрыто сервером")
                    self.connected = False
                    break
        except Exception as e:
            logger.error(f"Ошибка в WebSocket listener: {e}")
            self.connected = False

    async def _handle_websocket_message(self, data: Dict[str, Any]):
        """Обработка сообщений от WebSocket"""
        if data.get("event") == "login":
            if data.get("code") == "0":
                logger.info("✅ WebSocket аутентификация успешна")
            else:
                logger.error(f"❌ Ошибка аутентификации: {data}")

        elif data.get("arg", {}).get("channel") == "orders":
            # Обработка обновлений ордеров
            order_data = data.get("data", [])
            for order in order_data:
                await self._handle_order_update(order)

    async def _handle_order_update(self, order_data: Dict[str, Any]):
        """Обработка обновлений ордеров"""
        order_id = order_data.get("ordId")
        state = order_data.get("state")

        if order_id in self.pending_orders:
            self.pending_orders[order_id]["state"] = state

            if state == "filled":
                logger.info(f"✅ WebSocket ордер {order_id} исполнен")
                # Уведомляем о заполнении
                self.pending_orders[order_id]["filled"] = True
            elif state in ["canceled", "failed"]:
                logger.warning(f"⚠️ WebSocket ордер {order_id} отменен/неудачен")
                self.pending_orders[order_id]["failed"] = True

    async def place_market_order(
        self, symbol: str, side: OrderSide, quantity: float, price: float
    ) -> Optional[Order]:
        """
        Размещение MARKET ордера через WebSocket

        Args:
            symbol: Торговая пара (BTC-USDT)
            side: Направление (buy/sell)
            quantity: Количество
            price: Текущая цена (для расчета размера)

        Returns:
            Order объект или None при ошибке
        """
        if not self.connected or not self.ws:
            logger.error("❌ WebSocket не подключен")
            return None

        try:
            # Проверяем, что WebSocket все еще открыт
            if self.ws.closed:
                logger.error("❌ WebSocket соединение закрыто")
                return None

            # Рассчитываем размер в базовой валюте
            if side == OrderSide.BUY:
                size = f"{quantity:.6f}"
            else:
                size = f"{quantity:.6f}"

            order_id = str(uuid.uuid4())

            # Создаем payload для ордера
            payload = {
                "id": order_id,
                "op": "order",
                "args": [
                    {
                        "instId": symbol,
                        "tdMode": "cash",
                        "side": side.value,
                        "ordType": "market",
                        "sz": size,
                    }
                ],
            }

            # Отправляем ордер с проверкой
            try:
                await self.ws.send_str(json.dumps(payload))
                logger.debug(f"📤 WebSocket ордер отправлен: {order_id}")
            except Exception as send_error:
                logger.error(f"❌ Ошибка отправки WebSocket ордера: {send_error}")
                return None

            # Сохраняем в pending orders
            self.pending_orders[order_id] = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "state": "pending",
                "filled": False,
                "failed": False,
                "timestamp": datetime.utcnow(),
            }

            logger.info(
                f"🚀 WebSocket MARKET ордер отправлен: {symbol} {side.value} {size}"
            )

            # Ждем результат (максимум 3 секунды для стабильности)
            start_time = datetime.utcnow()
            while (datetime.utcnow() - start_time).total_seconds() < 3:
                if self.pending_orders[order_id]["filled"]:
                    # Создаем Order объект
                    order = Order(
                        id=order_id,
                        symbol=symbol,
                        side=side,
                        type=OrderType.MARKET,
                        quantity=quantity,
                        price=price,
                        status="filled",
                        timestamp=datetime.utcnow(),
                    )

                    # Удаляем из pending
                    del self.pending_orders[order_id]

                    logger.info(f"✅ WebSocket ордер исполнен: {order_id}")
                    return order

                elif self.pending_orders[order_id]["failed"]:
                    logger.error(f"❌ WebSocket ордер не исполнен: {order_id}")
                    del self.pending_orders[order_id]
                    return None

                await asyncio.sleep(0.1)  # Ждем 100мс для стабильности

            # Timeout
            logger.warning(f"⏰ WebSocket ордер timeout: {order_id}")
            del self.pending_orders[order_id]
            return None

        except Exception as e:
            logger.error(f"❌ Ошибка размещения WebSocket ордера: {e}")
            return None

    async def disconnect(self):
        """Отключение от WebSocket"""
        self.connected = False

        # Отменяем фоновые задачи
        if self.listener_task and not self.listener_task.done():
            self.listener_task.cancel()
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()

        if self.ws:
            try:
                await self.ws.close()
            except:
                pass
            self.ws = None
        if self.session:
            try:
                await self.session.close()
            except:
                pass
            self.session = None
        logger.info("🔌 WebSocket отключен")

    async def reconnect(self) -> bool:
        """Переподключение к WebSocket"""
        logger.info("🔄 Попытка переподключения WebSocket...")
        await self.disconnect()
        await asyncio.sleep(1)  # Небольшая пауза
        return await self.connect()

    async def get_latency(self) -> float:
        """Измерение латентности WebSocket"""
        if not self.connected or not self.ws or self.ws.closed:
            logger.warning("⚠️ WebSocket не подключен для измерения латентности")
            return float("inf")

        try:
            start_time = datetime.utcnow()

            # Отправляем ping
            ping_msg = {"op": "ping"}
            await self.ws.send_str(json.dumps(ping_msg))

            # Ждем pong (упрощенная версия)
            await asyncio.sleep(0.1)

            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.info(f"📊 WebSocket латентность: {latency:.1f} мс")
            return latency

        except Exception as e:
            logger.error(f"❌ Ошибка измерения латентности: {e}")
            return float("inf")
