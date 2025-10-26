"""
OKX Exchange API client with corrected signature
"""
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiohttp
from asyncio_throttle import Throttler
from loguru import logger
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

from src.config import APIConfig
from src.models import (OHLCV, Balance, Order, OrderSide, OrderStatus,
                        OrderType, Position, PositionSide, Tick, Trade)


class OKXClient:
    """OKX Exchange API client with corrected signature"""

    def __init__(self, config: APIConfig):
        self.config = config
        self.api_key = config.api_key
        self.api_secret = config.api_secret
        self.passphrase = config.passphrase
        self.sandbox = config.sandbox

        # API endpoints - OKX использует один URL для всех режимов
        # НО для sandbox нужен специальный заголовок x-simulated-trading
        self.base_url = "https://www.okx.com"
        self.session: Optional[aiohttp.ClientSession] = None

        # 🔥 КРИТИЧНО: Rate limiting для предотвращения бана API ключей
        self.throttler = Throttler(rate_limit=10, period=1)  # 10 запросов в секунду

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()

    async def connect(self):
        """Initialize HTTP session"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        logger.info("OKX client connected")

    async def disconnect(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None
        logger.info("OKX client disconnected")

    async def get_websocket_latency(self) -> float:
        """Получение латентности WebSocket (для сравнения с REST)"""
        try:
            from src.websocket_order_executor import WebSocketOrderExecutor

            ws_executor = WebSocketOrderExecutor(self.config)
            if await ws_executor.connect():
                latency = await ws_executor.get_latency()
                await ws_executor.disconnect()
                return latency
            return float("inf")
        except Exception as e:
            logger.error(f"Ошибка измерения WebSocket латентности: {e}")
            return float("inf")

    async def batch_amend_orders(
        self, orders_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Batch amend orders - обновление до 20 ордеров за один API call

        Args:
            orders_data: Список данных для обновления ордеров
            [
                {
                    "instId": "BTC-USDT",
                    "ordId": "123456789",
                    "newSz": "0.001",
                    "newPx": "50000.0"
                },
                ...
            ]

        Returns:
            Результат batch операции
        """
        if not orders_data:
            return {"code": "0", "msg": "No orders to amend", "data": []}

        if len(orders_data) > 20:
            logger.warning(
                f"⚠️ Batch amend: {len(orders_data)} orders > 20 limit, splitting..."
            )
            # Разбиваем на части по 20
            results = []
            for i in range(0, len(orders_data), 20):
                batch = orders_data[i : i + 20]
                result = await self._batch_amend_single(batch)
                results.append(result)
            return {"code": "0", "msg": "Batch completed", "data": results}

        return await self._batch_amend_single(orders_data)

    async def _batch_amend_single(
        self, orders_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Выполнение batch amend для одной группы ордеров (≤20)"""
        try:
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            request_path = "/api/v5/trade/amend-batch-orders"  # ✅ С /api/v5 в подписи!

            # 🔧 КРИТИЧНО: Инициализируем body!
            body = ""  # ← инициализируем пустой строкой

            # Логируем параметры для отладки
            logger.debug(f"Batch amend request: {request_path}")
            logger.debug(f"Orders data: {orders_data}")

            # Проверяем формат данных для batch amend
            # OKX batch amend принимает массив ордеров напрямую
            if not isinstance(orders_data, list):
                orders_data = [orders_data]

            # 🔥 КРИТИЧНО: OKX batch amend НЕ требует обертку "data"!
            # Формируем payload для batch amend
            payload = []
            for order_data in orders_data:
                amend_data = {
                    "instId": order_data.get("instId"),
                    "ordId": order_data.get("ordId"),
                    "reqId": order_data.get("reqId", ""),
                }

                # Добавляем новые цены если они есть
                if "newTpTriggerPx" in order_data:
                    amend_data["newTpTriggerPx"] = order_data["newTpTriggerPx"]
                if "newTpOrdPx" in order_data:
                    amend_data["newTpOrdPx"] = order_data["newTpOrdPx"]
                if "newSlTriggerPx" in order_data:
                    amend_data["newSlTriggerPx"] = order_data["newSlTriggerPx"]
                if "newSlOrdPx" in order_data:
                    amend_data["newSlOrdPx"] = order_data["newSlOrdPx"]

                payload.append(amend_data)

            body = json.dumps(payload, separators=(",", ":"))

            # Логируем body после создания
            logger.debug(f"Body: {body}")
            logger.debug(f"Body length: {len(body)}")

            # ✅ ИСПРАВЛЕНО: Используем правильный путь для подписи
            signature = self._generate_signature(timestamp, "POST", request_path, body)

            headers = {
                "OK-ACCESS-KEY": self.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
            }

            # ✅ ИСПРАВЛЕНО: Добавляем sandbox заголовок СРАЗУ
            if self.sandbox:
                headers["x-simulated-trading"] = "1"

            # ✅ ИСПРАВЛЕНО: Используем полный URL для запроса
            url = f"{self.base_url}{request_path}"

            async with self.session.post(url, headers=headers, data=body) as response:
                result = await response.json()

                if result.get("code") == "0":
                    logger.info(f"✅ Batch amend successful: {len(orders_data)} orders")
                else:
                    logger.error(
                        f"❌ Batch amend failed: {result.get('msg', 'Unknown error')}"
                    )

                return result

        except Exception as e:
            logger.error(f"❌ Batch amend error: {e}")
            return {"code": "1", "msg": str(e), "data": []}

    def _generate_signature(
        self, timestamp: str, method: str, request_path: str, body: str = ""
    ) -> str:
        """
        Generate signature for OKX API authentication.
        Format: timestamp + method.upper() + request_path + body (БЕЗ пробелов)
        """
        # Собираем сообщение БЕЗ пробела, метод в UPPERCASE
        message = f"{timestamp}{method.upper()}{request_path}{body}"

        # Детальное логирование для отладки
        logger.debug("Signature components:")
        logger.debug(f"  Timestamp: {timestamp}")
        logger.debug(f"  Method: {method.upper()}")
        logger.debug(f"  Path: {request_path}")
        logger.debug(f"  Body: '{body}'")
        logger.debug(f"  Full message: '{message}'")
        logger.debug(f"  Secret (first 10): {self.api_secret[:10]}...")

        # ✅ ПРАВИЛЬНО: OKX Secret Key это обычная строка (не base64!)
        secret_bytes = self.api_secret.encode("utf-8")

        # HMAC-SHA256 + Base64
        message_bytes = message.encode("utf-8")
        sign = hmac.new(secret_bytes, message_bytes, hashlib.sha256).digest()
        signature = base64.b64encode(sign).decode("utf-8")

        logger.debug(f"Generated signature: {signature}")
        return signature

    def _get_headers(
        self, method: str, request_path: str, body: str = ""
    ) -> Dict[str, str]:
        """Get headers for API request"""
        # OKX requires timestamp in ISO 8601 format with milliseconds
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        signature = self._generate_signature(timestamp, method, request_path, body)

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

        # ВАЖНО: Добавляем заголовок для демо-счета
        if self.sandbox:
            headers["x-simulated-trading"] = "1"

        return headers

    def _is_private_endpoint(self, endpoint: str) -> bool:
        """Проверяет, является ли эндпоинт приватным (требует аутентификации)"""
        private_endpoints = [
            "/account/",
            "/trade/",
            "/asset/",
            "/users/",
            "/subaccount/",
            "/broker/",
            "/margin/",
            "/futures/",
            "/swap/",
            "/option/",
            "/system/status",  # Этот тоже может быть приватным
        ]
        return any(endpoint.startswith(ep) for ep in private_endpoints)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, Exception)),
        reraise=True,
    )
    async def _make_request(
        self, method: str, endpoint: str, params: Dict = None, data: Dict = None
    ) -> Dict:
        """Make HTTP request to OKX API"""
        if not self.session:
            await self.connect()

        # ✅ ПРАВИЛЬНО ДЛЯ OKX: Полный путь С /api/v5 для подписи!
        full_path = f"/api/v5{endpoint}"

        # ✅ Для GET с параметрами добавляем query string в подпись!
        if params and method.upper() == "GET":
            # ✅ OKX требует instType ПЕРВЫМ для trade endpoints!
            if "instType" in params:
                query_parts = [f"instType={params['instType']}"]
                for k, v in sorted(params.items()):
                    if k != "instType":
                        query_parts.append(f"{k}={v}")
                query_string = "&".join(query_parts)
            else:
                query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
            full_path = f"/api/v5{endpoint}?{query_string}"

        # URL для запроса - добавляем /api/v5 только если endpoint его не содержит
        if endpoint.startswith("/api/v5"):
            url = f"{self.base_url}{endpoint}"
        else:
            url = f"{self.base_url}/api/v5{endpoint}"

        body = json.dumps(data) if data else ""
        # For GET requests, body should be empty
        if method.upper() == "GET":
            body = ""

        # ✅ Передаём полный путь с query string в подпись
        headers = self._get_headers(method, full_path, body)

        # КРИТИЧНО: Добавляем sandbox заголовок для ВСЕХ запросов
        if self.sandbox:
            headers["x-simulated-trading"] = "1"

        # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ ДЛЯ ОТЛАДКИ
        logger.debug(f"🔍 API REQUEST DEBUG:")
        logger.debug(f"   Method: {method}")
        logger.debug(f"   Endpoint: {endpoint}")
        logger.debug(f"   Full Path (for signature): {full_path}")
        logger.debug(f"   URL: {url}")
        logger.debug(f"   Body: {body}")
        logger.debug(f"   Params: {params}")
        logger.debug(f"   API Key (first 10): {self.api_key[:10]}...")
        logger.debug(f"   Headers: {headers}")

        try:
            # 🔥 КРИТИЧНО: Rate limiting для предотвращения бана API ключей
            async with self.throttler:
                async with self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    data=body,
                ) as response:
                    response_text = await response.text()
                    logger.debug(f"🔍 RAW RESPONSE: {response_text}")

                    try:
                        result = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ JSON DECODE ERROR: {e}")
                        logger.error(f"   Response text: {response_text}")
                        raise Exception(f"Invalid JSON response: {e}")

                    logger.debug(f"🔍 PARSED RESPONSE: {result}")

                    if result.get("code") != "0":
                        logger.error(f"❌ OKX API ERROR:")
                        logger.error(f"   Code: {result.get('code')}")
                        logger.error(f"   Message: {result.get('msg')}")
                        logger.error(f"   Data: {result.get('data')}")
                        logger.error(f"   Full response: {result}")
                        raise Exception(
                            f"API Error: {result.get('msg', 'Unknown error')}"
                        )

                    logger.debug(f"✅ API SUCCESS: {result}")
                    return result

        except Exception as e:
            logger.error(f"❌ REQUEST FAILED:")
            logger.error(f"   Error: {e}")
            logger.error(f"   Method: {method}")
            logger.error(f"   Endpoint: {endpoint}")
            logger.error(f"   URL: {url}")
            logger.error(f"   Full Path: {full_path}")
            logger.error(f"   Body: {body}")
            if params:
                logger.error(f"   Params: {params}")
            if data:
                logger.error(f"   Data: {data}")
            logger.error(f"   Headers: {headers}")
            raise

    async def health_check(self) -> bool:
        """Check if API connection is healthy"""
        try:
            result = await self._make_request("GET", "/system/status")
            return result.get("code") == "0"
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    # Market Data Methods
    async def get_ticker(self, symbol: str) -> Dict:
        """Get ticker information for symbol"""
        params = {"instId": symbol}
        result = await self._make_request("GET", "/market/ticker", params=params)
        return result["data"][0] if result["data"] else {}

    async def get_current_price(self, symbol: str) -> float:
        """
        Get current market price for symbol.

        Args:
            symbol: Trading pair (e.g. "BTC-USDT")

        Returns:
            float: Current last price
        """
        ticker = await self.get_ticker(symbol)
        return float(ticker.get("last", 0))

    async def get_orderbook(self, symbol: str, depth: int = 20) -> Dict:
        """Get order book for symbol"""
        params = {"instId": symbol, "sz": str(depth)}
        result = await self._make_request("GET", "/market/books", params=params)
        return result["data"][0] if result["data"] else {}

    async def get_klines(
        self, symbol: str, timeframe: str = "1m", limit: int = 100
    ) -> List[OHLCV]:
        """Get kline/candlestick data"""
        params = {
            "instId": symbol,
            "bar": timeframe,
            "limit": str(limit),
        }
        result = await self._make_request("GET", "/market/candles", params=params)

        # OKX возвращает свечи в обратном порядке (новые первыми), нужно развернуть
        candles = [
            OHLCV(
                symbol=symbol,
                timestamp=int(candle[0]),
                open=float(candle[1]),
                high=float(candle[2]),
                low=float(candle[3]),
                close=float(candle[4]),
                volume=float(candle[5]),
            )
            for candle in result["data"]
        ]

        # Разворачиваем список, чтобы старые свечи были первыми
        return list(reversed(candles))

    async def get_candles(
        self, symbol: str, timeframe: str = "1m", limit: int = 100
    ) -> List[OHLCV]:
        """
        Get candlestick data (alias for get_klines for compatibility).

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USDT")
            timeframe: Candle timeframe (e.g., "1m", "5m", "1H", "1D")
            limit: Number of candles to retrieve (default: 100, max: 300)

        Returns:
            List of OHLCV candles
        """
        return await self.get_klines(symbol, timeframe, limit)

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Trade]:
        """Get recent trades"""
        params = {"instId": symbol, "limit": str(limit)}
        result = await self._make_request("GET", "/market/trades", params=params)

        return [
            Trade(
                id=str(trade["tradeId"]),
                symbol=trade["instId"],
                side=OrderSide.BUY if trade["side"] == "buy" else OrderSide.SELL,
                price=float(trade["px"]),
                quantity=float(trade["sz"]),
                timestamp=int(trade["ts"]),
            )
            for trade in result["data"]
        ]

    # Account Methods
    async def get_account_balance(self) -> List[Balance]:
        """Get account balance"""
        result = await self._make_request("GET", "/account/balance")

        balances = []
        for account in result["data"]:
            for detail in account.get("details", []):
                # Проверяем наличие баланса (доступного или замороженного)
                available = float(detail.get("availBal", 0))
                frozen = float(detail.get("frozenBal", 0))

                if available > 0 or frozen > 0:
                    balances.append(
                        Balance(
                            currency=detail["ccy"],
                            free=available,  # ✅ free вместо available
                            used=frozen,  # ✅ used вместо frozen
                            total=available + frozen,
                        )
                    )

        return balances

    async def get_balance(self, currency: str) -> float:
        """
        Get available balance for specific currency.

        Args:
            currency: Currency code (e.g., "BTC", "ETH", "USDT")

        Returns:
            Available balance amount
        """
        try:
            result = await self._make_request("GET", "/account/balance")

            for account in result["data"]:
                for detail in account.get("details", []):
                    if detail["ccy"] == currency:
                        return float(detail.get("availBal", 0))

            return 0.0
        except Exception as e:
            logger.error(f"Error getting balance for {currency}: {e}")
            return 0.0

    async def get_account_config(self) -> Dict[str, Any]:
        """
        Get account configuration to check trading mode (SPOT vs MARGIN).

        Returns account level:
        - '1' = Simple mode (SPOT only) ✅
        - '2' = Single-currency margin ❌
        - '3' = Multi-currency margin ❌
        - '4' = Portfolio margin ❌
        """
        try:
            result = await self._make_request("GET", "/account/config")
            if result.get("data"):
                return result["data"][0]
            return {}
        except Exception as e:
            logger.error(f"Error getting account config: {e}")
            return {}

    async def set_trading_mode(self, mode: str = "spot") -> bool:
        """
        Установить режим торговли на SPOT.

        Args:
            mode: "spot" для SPOT режима

        Returns:
            True если успешно установлен
        """
        try:
            # 🔧 КРИТИЧНО: Для sandbox НЕ МОЖЕМ изменить режим торговли!
            # Sandbox всегда в SPOT режиме
            if self.sandbox:
                logger.info("🔧 Sandbox режим - SPOT по умолчанию")
                return True

            # Устанавливаем режим торговли (только для live)
            data = {
                "acctLv": "1",  # Simple mode (SPOT only)
                "posMode": "net_mode" if mode == "spot" else "long_short_mode",
            }

            result = await self._make_request(
                "POST", "/account/set-position-mode", data=data
            )

            if result.get("code") == "0":
                logger.info(f"✅ Trading mode set to {mode.upper()}")
                return True
            else:
                logger.error(f"❌ Failed to set trading mode: {result.get('msg')}")
                return False

        except Exception as e:
            logger.error(f"Error setting trading mode: {e}")
            return False

    async def get_borrowed_balance(self, currency: str) -> float:
        """
        Get borrowed (margin) balance for a specific currency.

        Args:
            currency: Currency code (e.g., "SOL", "BTC", "USDT")

        Returns:
            Borrowed amount (0.0 if no borrowing or SPOT mode)
        """
        try:
            result = await self._make_request(
                "GET", "/account/balance", params={"ccy": currency}
            )

            if result.get("data"):
                for account in result["data"]:
                    for detail in account.get("details", []):
                        if detail.get("ccy") == currency:
                            # 'liab' = actual borrowed amount (liability)
                            # На SPOT режиме должно быть "0" или ""
                            borrowed_str = detail.get("liab", "0")
                            borrowed = float(borrowed_str) if borrowed_str else 0.0

                            if borrowed > 0:
                                logger.warning(
                                    f"⚠️ BORROWED DETECTED: {borrowed:.6f} {currency}"
                                )
                            return borrowed
            return 0.0
        except Exception as e:
            logger.error(f"Error getting borrowed balance for {currency}: {e}")
            return 0.0

    async def get_positions(self) -> List[Position]:
        """Get current positions"""
        result = await self._make_request("GET", "/account/positions")

        positions = []
        for pos in result["data"]:
            # Игнорируем нулевые позиции
            if float(pos.get("pos", 0)) != 0:
                # Определяем направление позиции (long/short)
                position_side = (
                    PositionSide.LONG
                    if pos["posSide"] == "long"
                    else PositionSide.SHORT
                )

                positions.append(
                    Position(
                        symbol=pos["instId"],
                        side=position_side,
                        size=float(pos["pos"]),
                        entry_price=float(pos.get("avgPx", 0)),
                        mark_price=float(pos.get("markPx", 0)),
                        pnl=float(pos.get("upl", 0)),
                    )
                )

        return positions

    # Trading Methods
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        post_only: bool = False,
    ) -> Order:
        """
        Place a new order (simple SPOT trading).

        Args:
            symbol: Trading pair (e.g., "BTC-USDT")
            side: BUY or SELL
            order_type: MARKET or LIMIT
            quantity: Order size
            price: Limit price (only for LIMIT orders)

        Returns:
            Order object

        Note:
            TP/SL управляются ботом через активный мониторинг (_update_position_prices).
            OKX SPOT не поддерживает автоматические TP/SL в одном запросе.
        """
        data = {
            "instId": symbol,
            "tdMode": "cash",  # SPOT mode
            "side": "buy" if side == OrderSide.BUY else "sell",
            "ordType": "limit" if order_type == OrderType.LIMIT else "market",
            "sz": str(quantity),
            "autoBorrow": "false",  # 🔥 КРИТИЧНО: Запрещаем займы!
        }

        # 🔧 КРИТИЧНО: Для sandbox нужен специальный режим!
        if self.sandbox:
            data["tdMode"] = "cash"  # SPOT для sandbox

        # Добавляем POST-ONLY если указан
        if post_only and order_type == OrderType.LIMIT:
            data["postOnly"] = "true"

        # 🔥 КРИТИЧНО! tgtCcy для BUY MARKET ордеров - ИСПРАВЛЕНО!
        # Для SPOT торговли ВСЕГДА используем base_ccy (количество монет)
        # НЕ используем quote_ccy - это может вызвать займы!
        if order_type == OrderType.MARKET and side == OrderSide.BUY:
            # ВСЕГДА используем base_ccy для SPOT торговли
            data["tgtCcy"] = "base_ccy"
            logger.info(f"🔧 BUY MARKET: tgtCcy=base_ccy (quantity={quantity})")

        if price is not None:
            data["px"] = str(price)

        result = await self._make_request("POST", "/trade/order", data=data)

        logger.info(f"Order response: {result}")

        if not result.get("data") or len(result["data"]) == 0:
            raise Exception(f"Invalid order response: {result}")

        order_data = result["data"][0]
        logger.info(f"Order data: {order_data}")

        # OKX возвращает минимальный ответ, используем исходные данные
        return Order(
            id=order_data["ordId"],
            symbol=symbol,  # Используем исходный symbol из запроса
            side=side,  # Используем исходный side из запроса
            type=order_type,  # Используем исходный order_type из запроса
            amount=quantity,  # amount в модели, quantity в параметре
            price=price if price else 0.0,  # Используем исходный price из запроса
            status=OrderStatus.PENDING,
            timestamp=datetime.utcnow(),  # datetime объект, не timestamp
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order"""
        data = {
            "instId": symbol,
            "ordId": order_id,
        }

        try:
            await self._make_request("POST", "/trade/cancel-order", data=data)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return False

    async def get_order(self, symbol: str, order_id: str) -> Optional[Order]:
        """Get order details"""
        params = {"instId": symbol, "ordId": order_id}
        result = await self._make_request("GET", "/trade/order", params=params)

        if not result["data"]:
            return None

        order_data = result["data"][0]
        return Order(
            id=order_data["ordId"],
            symbol=order_data["instId"],
            side=OrderSide.BUY if order_data["side"] == "buy" else OrderSide.SELL,
            type=OrderType.LIMIT
            if order_data["ordType"] == "limit"
            else OrderType.MARKET,
            quantity=float(order_data["sz"]),
            price=float(order_data.get("px", 0)),
            status=self._convert_status(order_data["state"]),
            timestamp=int(order_data["cTime"]),
        )

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders"""
        params = {
            "instType": "SPOT",  # ✅ Обязательный параметр для OKX!
        }
        if symbol:
            params["instId"] = symbol

        # ✅ OKX требует instType ПЕРВЫМ в query string!
        # Переупорядочиваем для правильной сортировки
        ordered_params = {"instType": params["instType"]}
        if "instId" in params:
            ordered_params["instId"] = params["instId"]

        result = await self._make_request(
            "GET", "/trade/orders-pending", params=ordered_params
        )

        orders = []
        for order_data in result["data"]:
            orders.append(
                Order(
                    id=order_data["ordId"],
                    symbol=order_data["instId"],
                    side=OrderSide.BUY
                    if order_data["side"] == "buy"
                    else OrderSide.SELL,
                    type=OrderType.LIMIT
                    if order_data["ordType"] == "limit"
                    else OrderType.MARKET,
                    amount=float(order_data["sz"]),  # amount, не quantity
                    price=float(order_data.get("px", 0)),
                    status=self._convert_status(order_data["state"]),
                    timestamp=datetime.utcnow(),  # datetime, не int
                )
            )

        return orders

    async def place_algo_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        trigger_price: float,
        order_type: str = "conditional",
    ) -> Optional[str]:
        """
        Выставить ALGO order (TP/SL) для SPOT.

        Args:
            symbol: Торговая пара
            side: BUY или SELL
            quantity: Размер
            trigger_price: Цена триггера (TP или SL)
            order_type: "conditional" для TP/SL

        Returns:
            algo order ID или None
        """
        # Форматируем trigger price с фиксированными 6 знаками после запятой
        # Это важно для корректной обработки биржей!
        formatted_trigger = f"{trigger_price:.6f}"

        data = {
            "instId": symbol,
            "tdMode": "cash",  # SPOT
            "side": "buy" if side == OrderSide.BUY else "sell",
            "ordType": order_type,
            "sz": str(quantity),
            "autoBorrow": "false",  # 🔥 КРИТИЧНО: Запрещаем займы!
            # "reduceOnly": "true",  # ❌ УБРАНО: Не поддерживается в SPOT режиме
            # Примечание: tgtCcy НЕ поддерживается для algo orders!
            "tpTriggerPx": formatted_trigger,  # Для TP
            "tpOrdPx": "-1",  # Market при триггере
        }

        # 🔧 КРИТИЧНО: Для sandbox нужен специальный режим!
        if self.sandbox:
            data["tdMode"] = "cash"  # SPOT для sandbox

        try:
            result = await self._make_request("POST", "/trade/order-algo", data=data)

            if result.get("code") == "0" and result.get("data"):
                algo_id = result["data"][0].get("algoId")
                logger.info(f"✅ Algo order placed: {algo_id} @ ${trigger_price}")
                return algo_id
            else:
                logger.error(f"❌ Algo order failed: {result.get('msg')}")
                return None
        except Exception as e:
            logger.error(f"Error placing algo order: {e}")
            return None

    async def place_stop_loss_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        trigger_price: float,
    ) -> Optional[str]:
        """
        Выставить Stop Loss algo order для SPOT.

        Args:
            symbol: Торговая пара
            side: BUY или SELL (закрывающая сторона)
            quantity: Размер
            trigger_price: SL триггер цена

        Returns:
            algo order ID или None
        """
        # Форматируем trigger price с фиксированными 6 знаками после запятой
        # Это важно для корректной обработки биржей!
        formatted_trigger = f"{trigger_price:.6f}"

        data = {
            "instId": symbol,
            "tdMode": "cash",
            "side": "buy" if side == OrderSide.BUY else "sell",
            "ordType": "conditional",
            "sz": str(quantity),
            # Примечание: tgtCcy НЕ поддерживается для algo orders!
            "slTriggerPx": formatted_trigger,  # Для SL
            "slOrdPx": "-1",
        }

        # 🔧 КРИТИЧНО: Для sandbox нужен специальный режим!
        if self.sandbox:
            data["tdMode"] = "cash"  # SPOT для sandbox

        try:
            result = await self._make_request("POST", "/trade/order-algo", data=data)

            if result.get("code") == "0" and result.get("data"):
                algo_id = result["data"][0].get("algoId")
                logger.info(f"✅ SL algo order placed: {algo_id} @ ${trigger_price}")
                return algo_id
            else:
                logger.error(f"❌ SL algo order failed: {result.get('msg')}")
                return None
        except Exception as e:
            logger.error(f"Error placing SL algo order: {e}")
            return None

    async def place_oco_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        tp_trigger_price: float,
        sl_trigger_price: float,
    ) -> Optional[str]:
        """
        Размещение OCO (One-Cancels-Other) ордера с TP и SL.

        OCO ордер объединяет TP и SL в один - при срабатывании одного,
        второй автоматически отменяется.

        Args:
            symbol: Торговая пара
            side: Направление закрытия (SELL для LONG, BUY для SHORT)
            quantity: Количество в базовой валюте
            tp_trigger_price: Take Profit триггер цена
            sl_trigger_price: Stop Loss триггер цена

        Returns:
            algo order ID или None
        """
        logger.debug(f"🔍 PLACE_OCO_ORDER DEBUG:")
        logger.debug(f"   Symbol: {symbol}")
        logger.debug(f"   Side: {side}")
        logger.debug(f"   Quantity: {quantity}")
        logger.debug(f"   TP Trigger: {tp_trigger_price}")
        logger.debug(f"   SL Trigger: {sl_trigger_price}")
        logger.debug(f"   Sandbox Mode: {self.sandbox}")

        # 🔥 КРИТИЧНО: Проверяем баланс ПЕРЕД размещением OCO!
        try:
            base_asset = symbol.split("-")[0]
            quote_asset = symbol.split("-")[1]

            # Проверяем займы
            borrowed_base = await self.get_borrowed_balance(base_asset)
            borrowed_quote = await self.get_borrowed_balance(quote_asset)

            if borrowed_base > 0 or borrowed_quote > 0:
                logger.error(
                    f"🚨 OCO BLOCKED: BORROWED FUNDS DETECTED! "
                    f"{base_asset}: {borrowed_base:.6f} | "
                    f"{quote_asset}: {borrowed_quote:.6f}"
                )
                logger.error("🚫 OCO ORDER BLOCKED - НЕ ТОРГУЕМ С ЗАЙМАМИ!")
                return None

            # Проверяем баланс для OCO
            if side == OrderSide.SELL:  # LONG закрытие - нужен ETH/BTC
                asset_balance = await self.get_balance(base_asset)
                # 🔧 КРИТИЧНО: Для BTC нужен больший запас
                required_balance = quantity * (1.1 if symbol == "BTC-USDT" else 1.0)
                if asset_balance < required_balance:
                    logger.error(
                        f"🚨 OCO BLOCKED: НЕДОСТАТОЧНО {base_asset}! "
                        f"Есть: {asset_balance:.8f}, Нужно: {required_balance:.8f}"
                    )
                    logger.error("🚫 OCO ORDER BLOCKED - НЕ БЕРЕМ ЗАЙМЫ!")
                    return None
            else:  # BUY - SHORT закрытие - нужен USDT
                quote_balance = await self.get_balance(quote_asset)
                # 🔧 КРИТИЧНО: Для BTC нужен больший запас USDT
                multiplier = 1.1 if symbol == "BTC-USDT" else 1.0
                required_quote = quantity * tp_trigger_price * multiplier
                if quote_balance < required_quote:
                    logger.error(
                        f"🚨 OCO BLOCKED: НЕДОСТАТОЧНО {quote_asset}! "
                        f"Есть: {quote_balance:.2f}, Нужно: {required_quote:.2f}"
                    )
                    logger.error("🚫 OCO ORDER BLOCKED - НЕ БЕРЕМ ЗАЙМЫ!")
                    return None

        except Exception as e:
            logger.error(f"❌ Failed to check balance for OCO: {e}")
            logger.error("🚫 OCO ORDER BLOCKED - Ошибка проверки баланса!")
            return None

        # 🔧 КРИТИЧНО: Проверяем правильность TP/SL цен для направления закрытия
        logger.debug(f"🔍 OCO PRICE VALIDATION:")
        logger.debug(f"   Symbol: {symbol}")
        logger.debug(f"   Side: {side}")
        logger.debug(f"   TP Trigger: {tp_trigger_price}")
        logger.debug(f"   SL Trigger: {sl_trigger_price}")

        # 🔧 КРИТИЧНО: Адаптируем TP/SL под правила OKX
        try:
            ticker = await self.get_ticker(symbol)
            current_price = float(ticker["last"])
            logger.debug(f"   Current Price: {current_price}")

            # Определяем минимальные отступы для разных активов
            if symbol == "BTC-USDT":
                min_tp_percent = 1.0  # 1% минимум для BTC TP
                min_sl_percent = 0.8  # 0.8% минимум для BTC SL
            elif symbol == "ETH-USDT":
                min_tp_percent = 0.8  # 0.8% минимум для ETH TP
                min_sl_percent = 0.6  # 0.6% минимум для ETH SL
            else:
                min_tp_percent = 0.5  # 0.5% минимум для остальных
                min_sl_percent = 0.4  # 0.4% минимум для остальных

            min_tp_distance = current_price * (min_tp_percent / 100)
            min_sl_distance = current_price * (min_sl_percent / 100)

            # Адаптируем TP/SL под требования OKX
            adjusted_tp = tp_trigger_price
            adjusted_sl = sl_trigger_price

            if side == OrderSide.SELL:  # Закрытие LONG
                if tp_trigger_price - current_price < min_tp_distance:
                    adjusted_tp = current_price + min_tp_distance
                    logger.info(
                        f"🎯 Адаптирую TP под OKX: {tp_trigger_price:.2f} → {adjusted_tp:.2f} (+{min_tp_percent}%)"
                    )
                if current_price - sl_trigger_price < min_sl_distance:
                    adjusted_sl = current_price - min_sl_distance
                    logger.info(
                        f"🎯 Адаптирую SL под OKX: {sl_trigger_price:.2f} → {adjusted_sl:.2f} (-{min_sl_percent}%)"
                    )
            else:  # BUY - закрытие SHORT
                if current_price - tp_trigger_price < min_tp_distance:
                    adjusted_tp = current_price - min_tp_distance
                    logger.info(
                        f"🎯 Адаптирую TP под OKX: {tp_trigger_price:.2f} → {adjusted_tp:.2f} (-{min_tp_percent}%)"
                    )
                if sl_trigger_price - current_price < min_sl_distance:
                    adjusted_sl = current_price + min_sl_distance
                    logger.info(
                        f"🎯 Адаптирую SL под OKX: {sl_trigger_price:.2f} → {adjusted_sl:.2f} (+{min_sl_percent}%)"
                    )

            # Используем адаптированные цены
            tp_trigger_price = adjusted_tp
            sl_trigger_price = adjusted_sl
            logger.info(
                f"✅ Финальные TP/SL: TP=${tp_trigger_price:.2f}, SL=${sl_trigger_price:.2f}"
            )

        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить текущую цену для валидации: {e}")

        # Для SELL (закрытие LONG): TP > current_price, SL < current_price
        # Для BUY (закрытие SHORT): TP < current_price, SL > current_price
        if side == OrderSide.SELL:  # Закрытие LONG
            if tp_trigger_price <= sl_trigger_price:
                logger.error(
                    f"❌ OCO ERROR: For SELL (LONG close), TP ({tp_trigger_price}) must be > SL ({sl_trigger_price})"
                )
                return None
        else:  # BUY - закрытие SHORT
            if tp_trigger_price >= sl_trigger_price:
                logger.error(
                    f"❌ OCO ERROR: For BUY (SHORT close), TP ({tp_trigger_price}) must be < SL ({sl_trigger_price})"
                )
                return None

        # Форматируем trigger prices с фиксированными 6 знаками
        formatted_tp = f"{tp_trigger_price:.6f}"
        formatted_sl = f"{sl_trigger_price:.6f}"

        data = {
            "instId": symbol,
            "tdMode": "cash",  # SPOT
            "side": "buy" if side == OrderSide.BUY else "sell",
            "ordType": "oco",
            "sz": str(quantity),
            "autoBorrow": "false",  # 🔥 КРИТИЧНО: Запрещаем займы!
            # "reduceOnly": "true",  # ❌ УБРАНО: Не поддерживается в SPOT режиме
            "tpTriggerPx": formatted_tp,
            "tpOrdPx": "-1",  # Market при триггере TP
            "slTriggerPx": formatted_sl,
            "slOrdPx": "-1",  # Market при триггере SL
        }

        # 🔧 КРИТИЧНО: Для sandbox нужен специальный режим!
        if self.sandbox:
            data["tdMode"] = "cash"  # SPOT для sandbox

        # КРИТИЧНО! tgtCcy нужен ТОЛЬКО для BUY (SHORT закрытие)
        # Для SELL (LONG закрытие) sz в базовой валюте по умолчанию
        if side == OrderSide.BUY:
            data["tgtCcy"] = "base_ccy"

        try:
            result = await self._make_request("POST", "/trade/order-algo", data=data)

            if result.get("code") == "0" and result.get("data"):
                algo_id = result["data"][0].get("algoId")
                logger.info(
                    f"✅ OCO order placed: {algo_id} | "
                    f"TP @ ${tp_trigger_price:.2f}, SL @ ${sl_trigger_price:.2f}"
                )
                return algo_id
            else:
                logger.error(f"❌ OCO order failed: {result.get('msg')}")
                return None
        except Exception as e:
            logger.error(f"Error placing OCO order: {e}")
            return None

    async def get_algo_orders(
        self, symbol: Optional[str] = None, algo_type: str = "conditional"
    ) -> List[Dict]:
        """
        Получить список активных algo orders (TP/SL).

        Args:
            symbol: Торговая пара (опционально)
            algo_type: Тип algo order ("conditional", "oco", "trigger")

        Returns:
            Список algo orders
        """
        logger.debug(f"🔍 GET_ALGO_ORDERS DEBUG:")
        logger.debug(f"   Symbol: {symbol}")
        logger.debug(f"   Algo Type: {algo_type}")
        logger.debug(f"   Sandbox Mode: {self.sandbox}")

        # 🔧 КРИТИЧНО: В sandbox многие алгоритмические ордера не поддерживаются
        if self.sandbox:
            logger.warning(
                f"⚠️ SANDBOX MODE: Algorithmic orders may not be fully supported"
            )
            logger.warning(f"   Skipping algo order retrieval for {algo_type}")
            return []  # Возвращаем пустой список в sandbox

        # 🔧 КРИТИЧНО: OCO в SPOT работают как trigger ордера!
        if algo_type == "oco":
            # Получаем ВСЕ алгоритмические ордера БЕЗ фильтра ordType
            params = {
                "instType": "SPOT",
                "state": "effective",  # ✅ Видим все активные + частично исполненные
                "ordType": "oco",  # ✅ Добавляем ordType для SPOT
            }
            if symbol:
                params["instId"] = symbol

            try:
                # ✅ Используем исправленный _make_request вместо прямого HTTP
                result = await self._make_request(
                    "GET", "/trade/orders-algo-pending", params=params
                )

                # 🔧 КРИТИЧНО: Детальная диагностика
                logger.debug(f"OCO API Response: {result}")

                if result.get("data"):
                    all_orders = result["data"]
                    logger.debug(f"📊 Total algo orders found: {len(all_orders)}")

                    # Логируем все ордера для диагностики
                    for i, order in enumerate(all_orders):
                        logger.debug(
                            f"   Order {i}: {order.get('ordType')} - {order.get('instId')} - {order.get('state')}"
                        )
                        if order.get("tpTriggerPx") or order.get("slTriggerPx"):
                            logger.debug(
                                f"   → Has TP/SL triggers: TP={order.get('tpTriggerPx')}, SL={order.get('slTriggerPx')}"
                            )

                    # Фильтруем OCO ордера (они приходят как trigger)
                    oco_orders = []
                    for order in all_orders:
                        # OCO ордера имеют специальные поля
                        if order.get("ordType") == "trigger" and (
                            order.get("tpTriggerPx") or order.get("slTriggerPx")
                        ):
                            oco_orders.append(order)

                    logger.debug(f"✅ Found {len(oco_orders)} OCO orders (as trigger)")

                    # 🔧 ЕСЛИ OCO НЕ НАЙДЕНЫ - пробуем вернуть ВСЕ триггерные ордера
                    if len(oco_orders) == 0 and len(all_orders) > 0:
                        logger.warning(
                            f"⚠️ OCO not found as trigger, returning all orders: {all_orders}"
                        )
                        return all_orders

                    return oco_orders
                else:
                    logger.debug("No algo orders found")
                    logger.debug(f"API Response: {result}")
                    return []

            except Exception as e:
                logger.error(f"Error getting OCO orders: {e}")
                return []

        # Для других типов - стандартная логика
        params = {
            "instType": "SPOT",
            "state": "live",  # Только активные ордера
        }

        # 🔧 КРИТИЧНО: Для OCO ордеров нужен специальный параметр!
        # ✅ НЕ добавляем ordType для SPOT (вызывает 51000)
        # Для SPOT всегда работаем без ordType
        if algo_type == "oco":
            # Для OCO в SPOT не добавляем ordType - OKX сам определит тип
            pass
        elif algo_type == "conditional":
            params["ordType"] = "conditional"
        elif algo_type == "trigger":
            params["ordType"] = "trigger"

        if symbol:
            params["instId"] = symbol

        try:
            # ✅ Используем исправленный _make_request
            result = await self._make_request(
                "GET", "/trade/orders-algo-pending", params=params
            )
            return result.get("data", [])

        except Exception as e:
            logger.error(f"Error getting algo orders: {e}")
            return []

    async def check_account_mode(self) -> Dict[str, str]:
        """
        Проверяет режим торговли аккаунта.

        Returns:
            Dict с информацией о режиме торговли
        """
        try:
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            request_path = "/api/v5/account/config"

            signature = self._generate_signature(timestamp, "GET", request_path, "")

            headers = {
                "OK-ACCESS-KEY": self.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
            }

            if self.sandbox:
                headers["x-simulated-trading"] = "1"

            url = f"{self.base_url}{request_path}"

            # 🔧 КРИТИЧНО: Для GET запросов передаем пустой body
            async with self.session.get(url, headers=headers) as response:
                result = await response.json()

                if result.get("code") == "0" and result.get("data"):
                    config = result["data"][0]
                    return {
                        "account_level": config.get("acctLv", "N/A"),
                        "position_mode": config.get("posMode", "N/A"),
                        "auto_loan": config.get("autoLoan", "N/A"),
                        "greeks_type": config.get("greeksType", "N/A"),
                        "level": config.get("level", "N/A"),
                    }
                else:
                    logger.error(f"Failed to get account config: {result}")
                    return {}

        except Exception as e:
            logger.error(f"Error checking account mode: {e}")
            return {}

    async def get_algo_order_status(self, algo_id: str) -> Optional[Dict]:
        """
        Получить статус конкретного algo ордера.

        Args:
            algo_id: ID algo ордера

        Returns:
            Информация об ордере или None если не найден
        """
        try:
            # 🔧 КРИТИЧНО: Проверяем статус OCO (сначала история, потом активные)
            # История (если уже закрыт)
            result = await self._make_request(
                "GET",
                "/trade/orders-algo-history",
                params={
                    "ordType": "oco",
                    "instType": "SPOT",
                },
            )

            # Ищем наш algoId в истории
            if result.get("data"):
                for order in result["data"]:
                    if order.get("algoId") == algo_id:
                        logger.debug(
                            f"✅ Found OCO {algo_id} in history: "
                            f"state={order.get('state')}, "
                            f"actualSide={order.get('actualSide')}"
                        )
                        return order

            # Если не в истории - проверяем активные
            result = await self._make_request(
                "GET",
                "/trade/orders-algo-pending",
                params={
                    "ordType": "oco",
                    "instType": "SPOT",
                },
            )

            # Ищем наш algoId в активных
            if result.get("data"):
                for order in result["data"]:
                    if order.get("algoId") == algo_id:
                        logger.debug(
                            f"✅ Found OCO {algo_id} in pending: "
                            f"state={order.get('state')}"
                        )
                        return order

            logger.debug(f"⚪ OCO {algo_id} not found (neither history nor pending)")
            return None

        except Exception as e:
            logger.error(f"❌ Error checking OCO status {algo_id}: {e}")
            return None

    async def get_recent_fills(
        self, symbol: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        """
        Получить последние исполненные ордера (fills).

        🔥 КРИТИЧНО для отслеживания OCO закрытий!

        Args:
            symbol: Торговая пара (опционально, если None - все пары)
            limit: Максимум записей (по умолчанию 100)

        Returns:
            List[Dict]: Список исполненных ордеров
        """
        try:
            # 🔥 ИСПРАВЛЕНО: НЕ передаем instId - это ломает подпись!
            # Получаем ВСЕ fills, потом фильтруем по symbol на клиенте
            params = {
                "instType": "SPOT",
                "limit": str(limit),
            }

            result = await self._make_request(
                "GET",
                "/trade/fills",
                params=params,
            )

            if result.get("data"):
                fills = result["data"]

                # Фильтруем по symbol если указан
                if symbol:
                    fills = [f for f in fills if f.get("instId") == symbol]

                logger.debug(
                    f"✅ Retrieved {len(fills)} fills"
                    + (f" for {symbol}" if symbol else "")
                )
                return fills

            return []

        except Exception as e:
            logger.error(f"❌ Error getting fills: {e}")
            return []

    async def cancel_algo_order(self, algo_id: str, symbol: str) -> bool:
        """
        Отменить algo order (TP/SL).

        Args:
            algo_id: ID algo ордера
            symbol: Торговая пара

        Returns:
            True если успешно отменен
        """
        logger.debug(f"🔍 CANCEL_ALGO_ORDER DEBUG:")
        logger.debug(f"   Algo ID: {algo_id}")
        logger.debug(f"   Symbol: {symbol}")
        logger.debug(f"   Sandbox Mode: {self.sandbox}")

        # 🔧 КРИТИЧНО: В sandbox OCO ордера мгновенно исчезают
        if self.sandbox:
            logger.warning(f"⚠️ SANDBOX MODE: OCO orders disappear instantly")
            logger.warning(f"   Skipping cancellation for algo_id: {algo_id}")
            return True  # Возвращаем True в sandbox (имитируем успех)

        data = {
            "instId": symbol,
            "algoId": algo_id,
        }

        try:
            result = await self._make_request(
                "POST", "/trade/cancel-algo-order", data=data
            )
            if result.get("code") == "0":
                logger.info(f"✅ Algo order {algo_id} cancelled")
                return True
            else:
                logger.warning(
                    f"⚠️ Failed to cancel algo order {algo_id}: {result.get('msg')}"
                )
                return False
        except Exception as e:
            logger.error(f"Error cancelling algo order {algo_id}: {e}")
            return False

    def _convert_status(self, okx_status: str) -> OrderStatus:
        """Convert OKX status to our OrderStatus enum"""
        status_map = {
            "live": OrderStatus.PENDING,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
        }
        return status_map.get(okx_status, OrderStatus.PENDING)

    # WebSocket Methods (placeholder)
    async def subscribe_ticker(self, symbol: str) -> AsyncGenerator[Tick, None]:
        """Subscribe to ticker updates"""
        logger.warning("WebSocket ticker subscription not implemented")
        yield Tick(
            symbol=symbol, price=0.0, volume=0.0, timestamp=int(time.time() * 1000)
        )

    async def subscribe_orderbook(self, symbol: str) -> AsyncGenerator[Dict, None]:
        """Subscribe to orderbook updates"""
        logger.warning("WebSocket orderbook subscription not implemented")
        yield {}

    async def subscribe_trades(self, symbol: str) -> AsyncGenerator[Trade, None]:
        """Subscribe to trade updates"""
        logger.warning("WebSocket trades subscription not implemented")
        yield Trade(
            id="0",
            symbol=symbol,
            side=OrderSide.BUY,
            price=0.0,
            quantity=0.0,
            timestamp=int(time.time() * 1000),
        )

    # Utility Methods
    async def get_exchange_info(self) -> Dict:
        """Get exchange information"""
        result = await self._make_request(
            "GET", "/public/instruments", params={"instType": "SPOT"}
        )
        return {
            "symbols": [inst["instId"] for inst in result["data"]],
            "timeframes": [
                "1m",
                "3m",
                "5m",
                "15m",
                "30m",
                "1h",
                "2h",
                "4h",
                "6h",
                "12h",
                "1d",
                "1w",
                "1M",
                "3M",
            ],
        }

    async def test_connection(self) -> bool:
        """Test API connection"""
        try:
            result = await self._make_request("GET", "/system/status")
            success = result.get("code") == "0"
            if success:
                logger.info("✅ OKX API connection successful")
            else:
                logger.error("❌ OKX API connection failed")
            return success
        except Exception as e:
            logger.error(f"❌ OKX API connection failed: {e}")
            return False

    async def get_market_data(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> List[OHLCV]:
        """Get market data (OHLCV candles) for a symbol"""
        try:
            # Convert timeframe to OKX format
            timeframe_map = {
                "1m": "1m",
                "3m": "3m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1H",
                "2h": "2H",
                "4h": "4H",
                "6h": "6H",
                "12h": "12H",
                "1d": "1D",
                "1w": "1W",
                "1M": "1M",
                "3M": "3M",
            }

            okx_timeframe = timeframe_map.get(timeframe, "1m")

            result = await self._make_request(
                "GET",
                "/market/candles",
                params={"instId": symbol, "bar": okx_timeframe, "limit": str(limit)},
            )

            if result.get("code") != "0":
                raise Exception(f"API error: {result.get('msg', 'Unknown error')}")

            candles = []
            for candle_data in result.get("data", []):
                candle = OHLCV(
                    timestamp=int(candle_data[0]),
                    symbol=symbol,
                    open=float(candle_data[1]),
                    high=float(candle_data[2]),
                    low=float(candle_data[3]),
                    close=float(candle_data[4]),
                    volume=float(candle_data[5]),
                    timeframe=timeframe,
                )
                candles.append(candle)

            # OKX возвращает свечи в обратном порядке (новые первыми)
            # Разворачиваем, чтобы старые свечи были первыми
            # (для правильного расчета индикаторов)
            return list(reversed(candles))

        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}")
            return []

    async def stream_ticks(self, symbol: str) -> AsyncGenerator[Tick, None]:
        """Stream real-time tick data for a symbol"""
        try:
            ws_url = "wss://ws.okx.com:8443/ws/v5/public"

            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url) as ws:
                    # Subscribe to ticker data
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [{"channel": "tickers", "instId": symbol}],
                    }
                    await ws.send_str(json.dumps(subscribe_msg))

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)

                                if data.get("arg", {}).get("channel") == "tickers":
                                    ticker_data = data.get("data", [])
                                    if ticker_data:
                                        tick_data = ticker_data[0]
                                        tick = Tick(
                                            symbol=tick_data["instId"],
                                            price=float(tick_data["last"]),
                                            volume=float(tick_data["vol24h"]),
                                            timestamp=int(tick_data["ts"]),
                                        )
                                        yield tick

                            except Exception as e:
                                logger.error(f"Error processing tick data: {e}")
                                continue

                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WebSocket error: {ws.exception()}")
                            break

        except Exception as e:
            logger.error(f"Error streaming ticks for {symbol}: {e}")
            raise
