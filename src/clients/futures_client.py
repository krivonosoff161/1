# src/clients/futures_client.py
import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
from loguru import logger
import math


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
        timestamp = str(time.time())

        # Build sign string
        body = json.dumps(data) if data else ""
        sign_str = timestamp + method.upper() + endpoint + body
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
    async def get_balance(self) -> float:
        """Возвращает USDT equity (единый для spot и фьючей)"""
        data = await self._make_request("GET", "/api/v5/account/balance")
        for detail in data["data"][0]["details"]:
            if detail["ccy"] == "USDT":
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
        # Определяем size_step для инструмента
        if "BTC" in symbol:
            size_step = 0.001  # 0.001 BTC для BTC
        elif "ETH" in symbol:
            size_step = 0.01  # 0.01 ETH для ETH
        else:
            size_step = 0.001  # По умолчанию
        
        # Округляем размер до OKX size_step
        rounded_size = round_to_step(size, size_step)
        
        if rounded_size != size:
            logger.info(
                f"Размер округлен с {size:.6f} до {rounded_size:.6f} "
                f"(step={size_step})"
            )
        
        payload = {
            "instId": f"{symbol}-SWAP",
            "tdMode": "isolated",
            "side": side,
            "sz": str(rounded_size),
            "ordType": order_type,
            "lever": str(self.leverage),
        }
        if price:
            payload["px"] = str(price)

        return await self._make_request("POST", "/api/v5/trade/order", data=payload)

    async def place_oco_order(
        self, symbol: str, side: str, size: float, tp_price: float, sl_price: float
    ) -> dict:
        """OCO для фьючей (min distance 0,01 % = 10 bips)"""
        # Определяем size_step для инструмента
        if "BTC" in symbol:
            size_step = 0.001  # 0.001 BTC для BTC
        elif "ETH" in symbol:
            size_step = 0.01  # 0.01 ETH для ETH
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
            "lever": str(self.leverage),
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
