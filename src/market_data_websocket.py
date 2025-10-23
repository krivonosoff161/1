"""
Public WebSocket для получения рыночных данных (БЕЗ аутентификации)
"""

import asyncio
import json
from typing import Callable, Optional

import aiohttp
from loguru import logger


class MarketDataWebSocket:
    """Public WebSocket для получения цен и рыночных данных"""

    def __init__(self):
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.connected = False
        self.price_callbacks: dict = {}  # symbol -> callback

    async def connect(self) -> bool:
        """Подключение к Public WebSocket (БЕЗ аутентификации)"""
        try:
            session = aiohttp.ClientSession()
            self.ws = await session.ws_connect(self.ws_url)
            self.connected = True

            # Запускаем listener
            asyncio.create_task(self._listen_for_data())

            logger.info("✅ Public WebSocket подключен (цены в реальном времени)")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подключения Public WebSocket: {e}")
            return False

    async def subscribe_ticker(self, symbol: str, callback: Callable):
        """Подписка на цены символа"""
        if not self.connected or not self.ws:
            logger.error("WebSocket не подключен")
            return False

        try:
            # Сохраняем callback
            self.price_callbacks[symbol] = callback

            # Подписываемся на тикер
            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": "tickers", "instId": symbol}],
            }

            await self.ws.send_str(json.dumps(subscribe_msg))
            logger.info(f"📊 Подписка на {symbol} активирована")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подписки на {symbol}: {e}")
            return False

    async def _listen_for_data(self):
        """Слушаем данные от WebSocket"""
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    await self._handle_ticker_data(data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self.ws.exception()}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.warning("WebSocket закрыт сервером")
                    break
        except Exception as e:
            logger.error(f"Ошибка в WebSocket listener: {e}")
        finally:
            self.connected = False

    async def _handle_ticker_data(self, data: dict):
        """Обработка данных тикера"""
        if data.get("arg", {}).get("channel") == "tickers":
            ticker_data = data.get("data", [])
            for ticker in ticker_data:
                symbol = ticker.get("instId")
                if symbol in self.price_callbacks:
                    # Вызываем callback с ценой
                    price = float(ticker.get("last", 0))
                    await self.price_callbacks[symbol](price, ticker)

    async def disconnect(self):
        """Отключение от WebSocket"""
        self.connected = False
        if self.ws:
            await self.ws.close()
        logger.info("🔌 Public WebSocket отключен")
