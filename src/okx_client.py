"""
OKX Exchange API client with corrected signature
"""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiohttp
from loguru import logger

from src.config import APIConfig
from src.models import (OHLCV, Balance, MarketData, Order, OrderSide,
                        OrderStatus, OrderType, Position, PositionSide, Tick,
                        Trade)


class OKXClient:
    """OKX Exchange API client with corrected signature"""

    def __init__(self, config: APIConfig):
        self.config = config
        self.api_key = config.api_key
        self.api_secret = config.api_secret
        self.passphrase = config.passphrase
        self.sandbox = config.sandbox

        # API endpoints - OKX использует один URL для всех режимов
        self.base_url = "https://www.okx.com"
        self.session: Optional[aiohttp.ClientSession] = None

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
        logger.debug(f"Signature components:")
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

        # URL для запроса (без query - их передаём через params)
        url = f"{self.base_url}/api/v5{endpoint}"

        body = json.dumps(data) if data else ""
        # For GET requests, body should be empty
        if method.upper() == "GET":
            body = ""

        # ✅ Передаём полный путь с query string в подпись
        headers = self._get_headers(method, full_path, body)

        # Debug logging (только для отладки)
        logger.debug(f"Request: {method} {endpoint}")
        logger.debug(f"Body: {body}")
        logger.debug(f"Headers: {headers}")

        try:
            async with self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=body,
            ) as response:
                result = await response.json()

                if result.get("code") != "0":
                    logger.error(f"OKX API error: {result}")
                    raise Exception(f"API Error: {result.get('msg', 'Unknown error')}")

                return result

        except Exception as e:
            logger.error(f"Request failed: {e}")
            logger.error(f"Failed request details: {method} {endpoint}")
            if params:
                logger.error(f"Params: {params}")
            if data:
                logger.error(f"Data: {data}")
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
        }

        # КРИТИЧНО! tgtCcy='quote_ccy' для MARKET BUY (безопасно, без займов)
        if order_type == OrderType.MARKET and side == OrderSide.BUY:
            data["tgtCcy"] = "quote_ccy"

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
            # Примечание: tgtCcy НЕ поддерживается для algo orders!
            "tpTriggerPx": formatted_trigger,  # Для TP
            "tpOrdPx": "-1",  # Market при триггере
        }

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
        # Форматируем trigger prices с фиксированными 6 знаками
        formatted_tp = f"{tp_trigger_price:.6f}"
        formatted_sl = f"{sl_trigger_price:.6f}"

        data = {
            "instId": symbol,
            "tdMode": "cash",  # SPOT
            "side": "buy" if side == OrderSide.BUY else "sell",
            "ordType": "oco",
            "sz": str(quantity),
            "tpTriggerPx": formatted_tp,
            "tpOrdPx": "-1",  # Market при триггере TP
            "slTriggerPx": formatted_sl,
            "slOrdPx": "-1",  # Market при триггере SL
        }

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
        params = {
            "instType": "SPOT",
            "ordType": algo_type,
        }
        if symbol:
            params["instId"] = symbol

        try:
            result = await self._make_request(
                "GET", "/trade/orders-algo-pending", params=params
            )
            return result.get("data", [])
        except Exception as e:
            logger.error(f"Error getting algo orders: {e}")
            return []

    async def get_algo_order_status(self, algo_id: str) -> Optional[Dict]:
        """
        Получить статус конкретного algo ордера.

        Args:
            algo_id: ID algo ордера

        Returns:
            Информация об ордере или None если не найден
        """
        try:
            # 🔧 ИСПРАВЛЕНИЕ: Сначала пробуем активные ордера
            result = await self._make_request(
                "GET",
                "/trade/orders-algo-pending",
                params={"algoId": algo_id, "instType": "SPOT", "ordType": "oco"},
            )

            if result.get("data") and len(result["data"]) > 0:
                return result["data"][0]
            
            # Если не найден в активных, проверяем историю
            # (ордер мог уже исполниться)
            result = await self._make_request(
                "GET",
                "/trade/orders-algo-history",
                params={"algoId": algo_id, "instType": "SPOT", "ordType": "oco"},
            )

            if result.get("data") and len(result["data"]) > 0:
                return result["data"][0]
            
            return None
        except Exception as e:
            logger.debug(f"Could not get algo order status for {algo_id}: {e}")
            return None

    async def cancel_algo_order(self, algo_id: str, symbol: str) -> bool:
        """
        Отменить algo order (TP/SL).

        Args:
            algo_id: ID algo ордера
            symbol: Торговая пара

        Returns:
            True если успешно отменен
        """
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
            # Разворачиваем, чтобы старые свечи были первыми (для правильного расчета индикаторов)
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
