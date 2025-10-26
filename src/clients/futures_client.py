# src/clients/futures_client.py
import asyncio
import base64
import hashlib
import hmac
import json
import math
import time
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
from loguru import logger


def round_to_step(value: float, step: float) -> float:
    """
    Округление до указанного шага (для OKX size_step).

    Args:
        value: Значение для округления
        step: Шаг округления

    Returns:
        Округленное значение
    """
    if step == 0:
        return value
    # Округляем к ближайшему кратному step
    if value % step == 0:
        return value
    # Используем round вместо ceil для более корректного округления
    return round(value / step) * step


class OKXFuturesClient:
    """
    OKX Futures API Client (USDT-Margined Perpetual Swaps)
    - isolated margin only (safe-by-default)
    - fixed leverage 3× (can be changed per symbol)
    - sandbox support
    - full margin & liquidation data
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        passphrase: str,
        sandbox: bool = True,
        leverage: int = 3,
    ):
        self.base_url = "https://www.okx.com" if not sandbox else "https://www.okx.com"
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.sandbox = sandbox
        self.leverage = leverage
        self.session = None
        self._lot_sizes_cache: dict = {}  # Кэш для lot sizes

    # ---------- HTTP internals ----------
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Unified request with OKX signing (same as your spot client)"""
        url = self.base_url + endpoint
        # OKX requires timestamp in ISO 8601 format with milliseconds
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        # Build sign string
        body = json.dumps(data, separators=(",", ":")) if data else ""

        # Для GET запросов с параметрами нужно включить их в подпись
        if method.upper() == "GET" and params:
            from urllib.parse import urlencode

            query_string = "?" + urlencode(params, doseq=True)
            request_path = endpoint + query_string
        else:
            request_path = endpoint

        sign_str = timestamp + method.upper() + request_path + body

        # Логируем компоненты подписи для отладки
        logger.debug(f"Signature components:")
        logger.debug(f"  Timestamp: {timestamp}")
        logger.debug(f"  Method: {method.upper()}")
        logger.debug(f"  Endpoint: {endpoint}")
        logger.debug(f"  Body: '{body}'")
        logger.debug(f"  Full message: '{sign_str}'")

        signature = base64.b64encode(
            hmac.new(
                self.secret_key.encode(), sign_str.encode(), hashlib.sha256
            ).digest()
        ).decode()

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "x-simulated-trading": "1" if self.sandbox else "0",
        }

        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()

        async with self.session.request(
            method, url, headers=headers, params=params, data=body
        ) as resp:
            resp_data = await resp.json()
            if resp_data.get("code") != "0":
                logger.error("OKX API error: %s", resp_data)
                raise RuntimeError(resp_data)
            return resp_data

    # ---------- Account & Margin ----------
    async def get_instrument_info(self, inst_type: str = "SWAP") -> dict:
        """Получает информацию об инструментах (lot size, min size и т.д.)"""
        data = await self._make_request(
            "GET", "/api/v5/public/instruments", params={"instType": inst_type}
        )
        return data

    async def get_lot_size(self, symbol: str) -> float:
        """Получает минимальный lot size для символа"""
        # Проверяем кэш
        if symbol in self._lot_sizes_cache:
            return self._lot_sizes_cache[symbol]

        try:
            inst_id = f"{symbol}-SWAP"
            instruments = await self.get_instrument_info()

            for inst in instruments.get("data", []):
                if inst.get("instId") == inst_id:
                    lot_sz = inst.get("lotSz")
                    if lot_sz:
                        lot_size = float(lot_sz)
                        self._lot_sizes_cache[symbol] = lot_size
                        logger.info(
                            f"📏 Получен lot size из API для {symbol}: {lot_size}"
                        )
                        return lot_size
        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить lot size из API для {symbol}: {e}")

        # Fallback на значения по умолчанию
        if "BTC" in symbol:
            default = 0.001
        elif "ETH" in symbol:
            default = 0.01
        else:
            default = 0.001

        self._lot_sizes_cache[symbol] = default
        logger.warning(f"⚠️ Используем fallback lot size для {symbol}: {default}")
        return default

    async def get_balance(self) -> float:
        """Возвращает USDT equity (единый для spot и фьючей)"""
        data = await self._make_request("GET", "/api/v5/account/balance")

        # Проверка наличия data в ответе - если нет, это ошибка
        if "data" not in data:
            logger.error("Нет данных о балансе в ответе API")
            raise RuntimeError(f"Invalid response: {data}")

        if not data["data"]:
            logger.error("Пустой ответ от API")
            raise RuntimeError(f"Empty response: {data}")

        for detail in data["data"][0].get("details", []):
            if detail.get("ccy") == "USDT":
                return float(detail["eq"])
        return 0.0

    async def get_margin_info(self, symbol: str) -> dict:
        """Isolated-margin info: equity, liqPx, mgnRatio"""
        data = await self._make_request(
            "GET",
            "/api/v5/account/positions",
            params={"instType": "SWAP", "instId": f"{symbol}-SWAP"},
        )
        if not data["data"]:
            return {}
        pos = data["data"][0]
        return {
            "equity": float(pos["eq"]),
            "liqPx": float(pos["liqPx"]) if pos["liqPx"] else None,
            "mgnRatio": float(pos["mgnRatio"]) if pos["mgnRatio"] else None,
        }

    # ---------- Leverage ----------
    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Установить плечо (1 раз на символ)"""
        return await self._make_request(
            "POST",
            "/api/v5/account/set-leverage",
            data={
                "instId": f"{symbol}-SWAP",
                "lever": str(leverage),
                "mgnMode": "isolated",
                "posSide": "net",  # Используем net позицию
            },
        )

    # ---------- Orders ----------
    async def place_futures_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: Optional[float] = None,
        order_type: str = "market",
    ) -> dict:
        """Рыночный или лимитный ордер"""
        # Получаем реальный lot size из API
        size_step = await self.get_lot_size(symbol)

        # Округляем размер до OKX size_step
        rounded_size = round_to_step(size, size_step)

        # Форматируем до нужного количества знаков
        if size_step == 0.0001:
            formatted_size = f"{rounded_size:.4f}"  # 4 знака после запятой
        elif size_step == 0.001:
            formatted_size = f"{rounded_size:.3f}"  # 3 знака после запятой
        elif size_step == 0.01:
            formatted_size = f"{rounded_size:.2f}"  # 2 знака после запятой
        else:
            formatted_size = f"{rounded_size:.6f}"

        if rounded_size != size:
            logger.info(
                f"Размер округлен с {size:.6f} до {formatted_size} "
                f"(step={size_step})"
            )

        payload = {
            "instId": f"{symbol}-SWAP",
            "tdMode": "isolated",
            "side": side,
            "sz": formatted_size,
            "ordType": order_type,
        }

        # Добавляем posSide только для SWAP
        if "SWAP" in f"{symbol}-SWAP":
            # Определяем posSide на основе side
            if side.lower() == "buy":
                payload["posSide"] = "long"
            elif side.lower() == "sell":
                payload["posSide"] = "short"

        if price:
            payload["px"] = str(price)

        return await self._make_request("POST", "/api/v5/trade/order", data=payload)

    async def place_oco_order(
        self, symbol: str, side: str, size: float, tp_price: float, sl_price: float
    ) -> dict:
        """OCO для фьючей (min distance 0,01 % = 10 bips)"""
        # Определяем size_step для инструмента (ПРАВИЛЬНЫЕ минимальные lot sizes для OKX SWAP!)
        if "BTC" in symbol:
            size_step = 0.001  # ✅ 0.001 BTC минимум для BTC-USDT-SWAP (можно отправить 0.0001, но принимается только 0.001+)
        elif "ETH" in symbol:
            size_step = 0.01  # ✅ 0.01 ETH минимум для ETH-USDT-SWAP (проверим)
        else:
            size_step = 0.001  # По умолчанию

        # Округляем размер до OKX size_step
        rounded_size = round_to_step(size, size_step)

        if rounded_size != size:
            logger.info(
                f"Размер OCO округлен с {size:.6f} до {rounded_size:.6f} "
                f"(step={size_step})"
            )

        payload = {
            "instId": f"{symbol}-SWAP",
            "tdMode": "isolated",
            "side": side,
            "sz": str(rounded_size),
            "ordType": "oco",
            "tpTriggerPx": str(tp_price),
            "tpOrdPx": "-1",  # рыночный TP
            "slTriggerPx": str(sl_price),
            "slOrdPx": "-1",  # рыночный SL
        }
        return await self._make_request(
            "POST", "/api/v5/trade/order-algo", data=payload
        )

    async def cancel_order(self, symbol: str, order_id: str) -> dict:
        return await self._make_request(
            "POST",
            "/api/v5/trade/cancel-order",
            data={"instId": f"{symbol}-SWAP", "ordId": order_id},
        )

    async def get_positions(self, symbol: Optional[str] = None) -> list:
        params = {"instType": "SWAP"}
        if symbol:
            params["instId"] = f"{symbol}-SWAP"
        data = await self._make_request(
            "GET", "/api/v5/account/positions", params=params
        )
        return data["data"]

    async def get_active_orders(self, symbol: Optional[str] = None) -> list:
        """Получение активных ордеров"""
        params = {"instType": "SWAP"}
        if symbol:
            params["instId"] = f"{symbol}-SWAP"
        data = await self._make_request(
            "GET", "/api/v5/trade/orders-pending", params=params
        )
        return data.get("data", [])

    # ---------- Batch ----------
    async def batch_amend_orders(self, amend_list: list) -> dict:
        """До 20 ордеров за 1 запрос (аналогично spot)"""
        return await self._make_request(
            "POST", "/api/v5/trade/amend-batch", data={"amendData": amend_list}
        )

    # ---------- Graceful shutdown ----------
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
