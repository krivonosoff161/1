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
        self._instrument_details_cache: dict = (
            {}
        )  # Кэш для instrument details (ctVal, lotSz, minSz)

    async def close(self):
        """Корректное закрытие клиента и сессии"""
        try:
            if self.session and not self.session.closed:
                await self.session.close()
                # Даем время на корректное закрытие
                await asyncio.sleep(0.1)
                logger.debug("✅ OKXFuturesClient сессия закрыта")
        except Exception as e:
            logger.debug(f"⚠️ Ошибка при закрытии сессии: {e}")

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
            "Accept": "application/json",  # ✅ Явно указываем что ожидаем JSON
            "x-simulated-trading": "1" if self.sandbox else "0",
        }

        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()

        try:
            async with self.session.request(
                method, url, headers=headers, params=params, data=body
            ) as resp:
                # 🔥 ИСПРАВЛЕНИЕ: Проверяем content-type перед парсингом JSON
                content_type = resp.headers.get("Content-Type", "").lower()

                # Если OKX вернул HTML вместо JSON - это ошибка (rate limit, 403, 404 и т.д.)
                if "text/html" in content_type:
                    # Получаем текст для диагностики
                    text = await resp.text()
                    logger.error(
                        f"❌ OKX вернул HTML вместо JSON! Status: {resp.status}, "
                        f"URL: {url}, Content-Type: {content_type}"
                    )
                    # Пытаемся найти причину в HTML (может быть rate limit или ошибка авторизации)
                    if "rate limit" in text.lower() or "too many" in text.lower():
                        logger.error(
                            "⚠️ Превышен rate limit OKX! Нужна задержка между запросами."
                        )
                        raise RuntimeError("OKX rate limit exceeded")
                    elif resp.status == 403:
                        logger.error(
                            "⚠️ Доступ запрещен (403). Проверьте API ключи и права доступа."
                        )
                        raise RuntimeError("OKX API: Access forbidden (403)")
                    elif resp.status == 404:
                        logger.error("⚠️ Endpoint не найден (404). Проверьте URL.")
                        raise RuntimeError(f"OKX API: Endpoint not found (404): {url}")
                    else:
                        logger.error(f"⚠️ Неожиданный HTML ответ от OKX: {text[:500]}")
                        raise RuntimeError(
                            f"OKX API returned HTML instead of JSON. "
                            f"Status: {resp.status}, Content-Type: {content_type}"
                        )

                # Парсим JSON только если это действительно JSON
                try:
                    resp_data = await resp.json()
                except Exception as e:
                    # Если не удалось распарсить JSON, логируем и выбрасываем ошибку
                    text = await resp.text()
                    logger.error(
                        f"❌ Ошибка парсинга JSON от OKX: {e}, "
                        f"Status: {resp.status}, Content-Type: {content_type}, "
                        f"Response: {text[:500]}"
                    )
                    raise RuntimeError(
                        f"Failed to parse JSON response from OKX: {e}, "
                        f"Status: {resp.status}"
                    )

                # Проверяем статус ответа
                if resp.status != 200:
                    logger.error(f"❌ OKX API вернул статус {resp.status}: {resp_data}")
                    raise RuntimeError(
                        f"OKX API error: status {resp.status}, data: {resp_data}"
                    )

                if resp_data.get("code") != "0":
                    logger.error("OKX API error: %s", resp_data)
                    raise RuntimeError(resp_data)

                # ✅ ЛОГИРОВАНИЕ КОМИССИИ: Если это ответ на размещение ордера, логируем комиссию
                if method == "POST" and "/trade/order" in url:
                    try:
                        order_data = resp_data.get("data", [])
                        if order_data and len(order_data) > 0:
                            fee = order_data[0].get("fee", "N/A")
                            fee_ccy = order_data[0].get("feeCcy", "N/A")
                            if fee != "N/A" and fee:
                                logger.info(
                                    f"💰 Комиссия за ордер {order_data[0].get('ordId', 'N/A')}: "
                                    f"{fee} {fee_ccy} (или будет списана при исполнении)"
                                )
                    except Exception as e:
                        logger.debug(f"Не удалось залогировать комиссию: {e}")

                return resp_data

        except asyncio.CancelledError:
            logger.debug(f"Запрос к OKX отменен: {method} {url}")
            raise  # Пробрасываем дальше
        except Exception as e:
            logger.error(f"Ошибка при запросе к OKX ({method} {url}): {e}")
            raise

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

    async def get_instrument_details(self, symbol: str) -> dict:
        """Получает детали инструмента (ctVal, lotSz, minSz) для конкретного символа"""
        # Проверяем кэш
        if symbol in self._instrument_details_cache:
            return self._instrument_details_cache[symbol]

        try:
            inst_id = f"{symbol}-SWAP"
            instruments = await self.get_instrument_info()

            for inst in instruments.get("data", []):
                if inst.get("instId") == inst_id:
                    details = {
                        "ctVal": float(inst.get("ctVal", 0.01)),  # Contract value
                        "lotSz": float(inst.get("lotSz", 0.01)),  # Lot size
                        "minSz": float(inst.get("minSz", 0.01)),  # Minimum size
                    }
                    self._instrument_details_cache[symbol] = details
                    logger.debug(
                        f"📋 Детали инструмента {symbol}: ctVal={details['ctVal']}, lotSz={details['lotSz']}, minSz={details['minSz']}"
                    )
                    return details
        except Exception as e:
            logger.warning(
                f"⚠️ Не удалось получить детали инструмента для {symbol}: {e}"
            )

        # Fallback на значения по умолчанию
        if "BTC" in symbol:
            default_details = {"ctVal": 0.01, "lotSz": 0.01, "minSz": 0.01}
        elif "ETH" in symbol:
            default_details = {"ctVal": 0.1, "lotSz": 0.01, "minSz": 0.01}
        else:
            default_details = {"ctVal": 0.01, "lotSz": 0.01, "minSz": 0.01}

        self._instrument_details_cache[symbol] = default_details
        logger.warning(f"⚠️ Используем fallback детали для {symbol}: {default_details}")
        return default_details

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
        try:
            data = await self._make_request(
                "GET",
                "/api/v5/account/positions",
                params={"instType": "SWAP", "instId": f"{symbol}-SWAP"},
            )
            # Проверяем что data есть и не пустой
            if not data or not data.get("data") or len(data["data"]) == 0:
                logger.debug(
                    f"⚠️ Позиция {symbol} не найдена в get_margin_info (пустой список)"
                )
                return {}

            pos = data["data"][0]

            # 🔍 DEBUG: Логируем доступные поля для отладки (первый раз)
            if not hasattr(self, "_logged_position_fields"):
                self._logged_position_fields = set()
            if symbol not in self._logged_position_fields:
                available_fields = list(pos.keys())
                logger.debug(f"📋 Доступные поля в позиции {symbol}: {available_fields}")
                logger.debug(f"📋 Пример позиции {symbol}: {pos}")
                self._logged_position_fields.add(symbol)

            # ⚠️ ИСПРАВЛЕНИЕ: Для изолированной маржи equity = margin + unrealizedPnl
            # Проверяем наличие ключей и считаем equity правильно
            equity = 0.0

            # Способ 1: Прямое поле 'eq' (если есть)
            if "eq" in pos and pos.get("eq") and str(pos["eq"]).strip():
                try:
                    equity = float(pos["eq"])
                    logger.debug(f"✅ equity получен из 'eq' для {symbol}: {equity:.2f}")
                except (ValueError, TypeError) as e:
                    logger.debug(f"⚠️ Не удалось преобразовать eq для {symbol}: {e}")
                    equity = 0.0

            # Способ 2: Расчет equity = margin + unrealizedPnl (для изолированной маржи)
            if equity == 0:
                margin = 0.0
                unrealized_pnl = 0.0

                try:
                    if "margin" in pos and pos.get("margin"):
                        margin = float(pos["margin"])
                except (ValueError, TypeError):
                    pass

                try:
                    if "upl" in pos and pos.get("upl"):  # unrealizedPnl
                        unrealized_pnl = float(pos["upl"])
                    elif "uPnl" in pos and pos.get("uPnl"):
                        unrealized_pnl = float(pos["uPnl"])
                    elif "unrealizedPnl" in pos and pos.get("unrealizedPnl"):
                        unrealized_pnl = float(pos["unrealizedPnl"])
                except (ValueError, TypeError):
                    pass

                if margin > 0:
                    equity = margin + unrealized_pnl
                    logger.debug(
                        f"✅ equity рассчитан для {symbol}: margin={margin:.2f} + upl={unrealized_pnl:.2f} = {equity:.2f}"
                    )

            # Способ 3: availEq как последний вариант
            if equity == 0:
                if "availEq" in pos and pos.get("availEq"):
                    try:
                        equity = float(pos["availEq"])
                        logger.debug(
                            f"⚠️ Используем availEq для {symbol}: {equity:.2f}"
                        )
                    except (ValueError, TypeError):
                        pass

            # Получаем margin и upl для расчета PnL%
            margin = 0.0
            upl = 0.0
            try:
                if "margin" in pos and pos.get("margin"):
                    margin = float(pos["margin"])
                if "upl" in pos and pos.get("upl"):
                    upl = float(pos["upl"])
                elif "uPnl" in pos and pos.get("uPnl"):
                    upl = float(pos["uPnl"])
            except (ValueError, TypeError):
                pass

            return {
                "equity": equity,
                "margin": margin,
                "upl": upl,
                "unrealized_pnl": upl,  # Alias для совместимости
                "liqPx": float(pos["liqPx"]) if pos.get("liqPx") else None,
                "mgnRatio": float(pos["mgnRatio"]) if pos.get("mgnRatio") else None,
            }
        except KeyError as e:
            logger.debug(f"⚠️ KeyError в get_margin_info для {symbol}: {e}")
            return {}
        except Exception as e:
            logger.warning(f"⚠️ Ошибка в get_margin_info для {symbol}: {e}")
            return {}

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
        size_in_contracts: bool = False,
    ) -> dict:
        """
        Рыночный или лимитный ордер

        Args:
            symbol: Символ (например, "BTC-USDT")
            side: "buy" или "sell"
            size: Размер позиции (в монетах, если size_in_contracts=False, иначе в контрактах)
            price: Цена для лимитного ордера
            order_type: "market" или "limit"
            size_in_contracts: Если True, size уже в контрактах; если False - в монетах (нужна конвертация)
        """
        # Получаем детали инструмента (ctVal, lotSz, minSz)
        instrument_details = await self.get_instrument_details(symbol)
        ct_val = instrument_details.get("ctVal", 0.01)
        lot_sz = instrument_details.get("lotSz", 0.01)
        min_sz = instrument_details.get("minSz", 0.01)

        # Конвертируем размер из монет в контракты, если нужно
        if not size_in_contracts:
            # size в монетах (BTC/ETH) → конвертируем в контракты
            size_in_contracts_value = size / ct_val
            logger.debug(
                f"📊 Конвертация {symbol}: {size:.6f} монет → {size_in_contracts_value:.6f} контрактов (ctVal={ct_val})"
            )
        else:
            # size уже в контрактах
            size_in_contracts_value = size

        # Проверяем минимальный размер
        if size_in_contracts_value < min_sz:
            error_msg = f"Размер позиции {size_in_contracts_value:.6f} контрактов меньше минимума {min_sz:.6f} для {symbol}"
            logger.error(f"❌ {error_msg}")
            return {"code": "1", "msg": error_msg, "data": []}

        # Округляем размер в контрактах до lotSz
        rounded_size = round_to_step(size_in_contracts_value, lot_sz)

        # Проверяем, что после округления размер >= min_sz
        if rounded_size < min_sz:
            rounded_size = min_sz
            logger.warning(
                f"⚠️ Размер после округления меньше минимума, используем минимум: {min_sz}"
            )

        # Форматируем до нужного количества знаков
        if lot_sz == 0.0001:
            formatted_size = f"{rounded_size:.4f}"  # 4 знака после запятой
        elif lot_sz == 0.001:
            formatted_size = f"{rounded_size:.3f}"  # 3 знака после запятой
        elif lot_sz == 0.01:
            formatted_size = f"{rounded_size:.2f}"  # 2 знака после запятой
        else:
            formatted_size = f"{rounded_size:.6f}"

        if rounded_size != size_in_contracts_value:
            logger.info(
                f"Размер округлен с {size_in_contracts_value:.6f} до {formatted_size} контрактов "
                f"(lotSz={lot_sz}, исходный размер в монетах={size:.6f})"
            )

        payload = {
            "instId": f"{symbol}-SWAP",
            "tdMode": "isolated",
            "side": side,
            "sz": formatted_size,
            "ordType": order_type,
        }

        # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для закрытия позиций используем reduceOnly!
        # Это гарантирует, что ордер закроет существующую позицию, а не откроет новую
        # ВАЖНО: Для isolated margin OKX требует posSide даже при reduceOnly!
        if size_in_contracts:
            # Это закрытие позиции - добавляем reduceOnly
            # ⚠️ ДЛЯ ISOLATED MARGIN нужно указать posSide даже при reduceOnly!
            payload["reduceOnly"] = "true"
            # Определяем posSide на основе стороны закрытия
            # Если закрываем long - продаем (side="sell"), значит была long
            # Если закрываем short - покупаем (side="buy"), значит была short
            if side.lower() == "sell":
                payload["posSide"] = "long"  # Закрываем long позицию
            elif side.lower() == "buy":
                payload["posSide"] = "short"  # Закрываем short позицию
        else:
            # Добавляем posSide для открытия новых позиций
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
