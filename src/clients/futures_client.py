# src/clients/futures_client.py
import asyncio
import base64
import hashlib
import hmac
import json
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

        # ✅ ОПТИМИЗАЦИЯ: Логируем компоненты подписи только при ошибках
        # Убрано избыточное DEBUG логирование каждого API запроса (экономия ~50% логов)
        # Можно включить обратно при необходимости отладки API проблем
        # logger.debug(f"Signature components: {method} {endpoint}")

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

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Retry логика для таймаутов и ошибок подключения
        max_retries = 3
        retry_delay = 1.0  # Начальная задержка в секундах

        for attempt in range(max_retries):
            try:
                # Увеличиваем таймаут для запросов (30 секунд)
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                async with self.session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    data=body,
                    timeout=timeout,
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
                            raise RuntimeError(
                                f"OKX API: Endpoint not found (404): {url}"
                            )
                        else:
                            logger.error(
                                f"⚠️ Неожиданный HTML ответ от OKX: {text[:500]}"
                            )
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
                        logger.error(
                            f"❌ OKX API вернул статус {resp.status}: {resp_data}"
                        )
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

            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (
                        2**attempt
                    )  # Экспоненциальная задержка
                    logger.warning(
                        f"⏱️ Таймаут при запросе к OKX (попытка {attempt + 1}/{max_retries}): "
                        f"{method} {url}, повтор через {wait_time:.1f}с"
                    )
                    await asyncio.sleep(wait_time)
                    # Обновляем timestamp и подпись для новой попытки
                    timestamp = (
                        datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                    )
                    sign_str = timestamp + method.upper() + request_path + body
                    signature = base64.b64encode(
                        hmac.new(
                            self.secret_key.encode(), sign_str.encode(), hashlib.sha256
                        ).digest()
                    ).decode()
                    headers["OK-ACCESS-TIMESTAMP"] = timestamp
                    headers["OK-ACCESS-SIGN"] = signature
                    continue
                else:
                    logger.error(
                        f"❌ Превышен таймаут при запросе к OKX после {max_retries} попыток: {method} {url}"
                    )
                    raise
            except OSError as e:
                # Обработка WinError 121 (превышен таймаут семафора) и других ошибок подключения
                error_str = str(e).lower()
                if (
                    "121" in str(e)
                    or "семафор" in error_str
                    or "semaphore" in error_str
                    or "timeout" in error_str
                ):
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2**attempt)
                        logger.warning(
                            f"⏱️ Таймаут семафора при запросе к OKX (попытка {attempt + 1}/{max_retries}): "
                            f"{method} {url}, ошибка: {e}, повтор через {wait_time:.1f}с"
                        )
                        await asyncio.sleep(wait_time)
                        # Обновляем timestamp и подпись для новой попытки
                        timestamp = (
                            datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
                            + "Z"
                        )
                        sign_str = timestamp + method.upper() + request_path + body
                        signature = base64.b64encode(
                            hmac.new(
                                self.secret_key.encode(),
                                sign_str.encode(),
                                hashlib.sha256,
                            ).digest()
                        ).decode()
                        headers["OK-ACCESS-TIMESTAMP"] = timestamp
                        headers["OK-ACCESS-SIGN"] = signature
                        continue
                    else:
                        logger.error(
                            f"❌ Превышен таймаут семафора при запросе к OKX после {max_retries} попыток: {method} {url}, ошибка: {e}"
                        )
                        raise
                else:
                    # Другие OSError - пробрасываем дальше
                    raise
            except aiohttp.ClientError as e:
                # Ошибки подключения aiohttp (Cannot connect to host и т.д.)
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2**attempt)
                    logger.warning(
                        f"⏱️ Ошибка подключения к OKX (попытка {attempt + 1}/{max_retries}): "
                        f"{method} {url}, ошибка: {e}, повтор через {wait_time:.1f}с"
                    )
                    await asyncio.sleep(wait_time)
                    # Обновляем timestamp и подпись для новой попытки
                    timestamp = (
                        datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                    )
                    sign_str = timestamp + method.upper() + request_path + body
                    signature = base64.b64encode(
                        hmac.new(
                            self.secret_key.encode(), sign_str.encode(), hashlib.sha256
                        ).digest()
                    ).decode()
                    headers["OK-ACCESS-TIMESTAMP"] = timestamp
                    headers["OK-ACCESS-SIGN"] = signature
                    continue
                else:
                    logger.error(
                        f"❌ Ошибка подключения к OKX после {max_retries} попыток: {method} {url}, ошибка: {e}"
                    )
                    raise
            except asyncio.CancelledError:
                logger.debug(f"Запрос к OKX отменен: {method} {url}")
                raise  # Пробрасываем дальше
            except Exception as e:
                # Для других ошибок не делаем retry (ошибки API, авторизации и т.д.)
                logger.error(f"Ошибка при запросе к OKX ({method} {url}): {e}")
                raise

    # ---------- Account & Margin ----------
    async def get_account_config(self) -> dict:
        """Получить настройки аккаунта (PosMode, уровень и т.д.)"""
        return await self._make_request("GET", "/api/v5/account/config")

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
        elif "SOL" in symbol:
            default = 0.01  # ✅ SOL обычно 0.01
        elif "DOGE" in symbol:
            default = 1.0  # ✅ DOGE обычно 1.0
        elif "XRP" in symbol:
            default = 1.0  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: XRP обычно 1.0 (как DOGE)
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

    async def get_price_limits(self, symbol: str) -> dict:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получает лимиты цены биржи для символа
        Использует лучшие цены из стакана для более точного расчета

        Returns:
            dict с ключами: max_buy_price, min_sell_price, best_bid, best_ask, current_price
        """
        try:
            inst_id = f"{symbol}-SWAP"
            import aiohttp

            async with aiohttp.ClientSession() as session:
                # ✅ ПРИОРИТЕТ 1: Получаем лучшие цены из стакана (самые актуальные)
                orderbook_url = (
                    f"https://www.okx.com/api/v5/market/books?instId={inst_id}&sz=5"
                )
                async with session.get(orderbook_url) as book_resp:
                    if book_resp.status == 200:
                        book_data = await book_resp.json()
                        if book_data.get("code") == "0" and book_data.get("data"):
                            book = book_data["data"][0]
                            asks = book.get("asks", [])
                            bids = book.get("bids", [])
                            if asks and bids:
                                # Берем лучшие цены из стакана
                                best_ask = float(asks[0][0])
                                best_bid = float(bids[0][0])
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем более консервативные лимиты
                                # Проблема: OKX использует динамические лимиты, которые могут быть строже
                                # Решение: используем более консервативные лимиты на основе spread
                                # Для SELL: минимум должен быть ближе к best_ask (внутри спреда)
                                # Для BUY: максимум должен быть ближе к best_bid (внутри спреда)
                                spread = best_ask - best_bid
                                # ✅ ИСПРАВЛЕНО: Используем минимальный offset для скальпинга (0.1% максимум)
                                # Проблема: 50% спреда ставило ордера слишком далеко (0.3-0.5% от цены)
                                # Решение: используем фиксированный 0.1% offset для быстрого исполнения
                                # Для скальпинга нужны ордера близко к рынку для экономии комиссий
                                max_buy_price = (
                                    best_ask * 1.001
                                )  # ✅ ИСПРАВЛЕНО: 0.1% выше best_ask (было 50% спреда)
                                min_sell_price = (
                                    best_bid * 0.999
                                )  # ✅ ИСПРАВЛЕНО: 0.1% ниже best_bid (было 50% спреда)

                                # ✅ ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА: Убеждаемся, что лимиты не слишком далеко
                                # Это защита от ошибок в расчетах
                                if max_buy_price > best_ask * 1.001:
                                    max_buy_price = (
                                        best_ask * 1.001
                                    )  # ✅ ИСПРАВЛЕНО: Не более 0.1% (было 1%)
                                if min_sell_price < best_bid * 0.999:
                                    min_sell_price = (
                                        best_bid * 0.999
                                    )  # ✅ ИСПРАВЛЕНО: Не более 0.1% (было 1%)

                                # Получаем текущую цену из тикера
                                ticker_url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                                async with session.get(ticker_url) as ticker_resp:
                                    if ticker_resp.status == 200:
                                        ticker_data = await ticker_resp.json()
                                        if ticker_data.get(
                                            "code"
                                        ) == "0" and ticker_data.get("data"):
                                            ticker = ticker_data["data"][0]
                                            current_price = float(
                                                ticker.get("last", "0")
                                            )

                                            logger.debug(
                                                f"💰 Лимиты цены для {symbol}: "
                                                f"best_bid={best_bid:.2f}, best_ask={best_ask:.2f}, "
                                                f"current={current_price:.2f}, "
                                                f"min_sell={min_sell_price:.2f}, max_buy={max_buy_price:.2f}"
                                            )

                                            return {
                                                "max_buy_price": max_buy_price,
                                                "min_sell_price": min_sell_price,
                                                "best_bid": best_bid,
                                                "best_ask": best_ask,
                                                "current_price": current_price,
                                            }

                                # Если не получили текущую цену, используем среднюю из стакана
                                current_price = (best_ask + best_bid) / 2
                                return {
                                    "max_buy_price": max_buy_price,
                                    "min_sell_price": min_sell_price,
                                    "best_bid": best_bid,
                                    "best_ask": best_ask,
                                    "current_price": current_price,
                                }

                # ✅ FALLBACK: Если не получили стакан, используем тикер
                ticker_url = (
                    f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                )
                async with session.get(ticker_url) as ticker_resp:
                    if ticker_resp.status == 200:
                        ticker_data = await ticker_resp.json()
                        if ticker_data.get("code") == "0" and ticker_data.get("data"):
                            ticker = ticker_data["data"][0]
                            current_price = float(ticker.get("last", "0"))
                            # ✅ ИСПРАВЛЕНО: Используем минимальный offset для скальпинга (0.1% максимум)
                            # Проблема: 0.5% лимиты ставили ордера слишком далеко
                            # Решение: используем 0.1% offset для быстрого исполнения
                            max_buy_price = (
                                current_price * 1.001
                            )  # ✅ ИСПРАВЛЕНО: +0.1% от текущей цены (было 0.5%)
                            min_sell_price = (
                                current_price * 0.999
                            )  # ✅ ИСПРАВЛЕНО: -0.1% от текущей цены (было 0.5%)

                            logger.debug(
                                f"💰 Лимиты цены для {symbol} (fallback): "
                                f"current={current_price:.2f}, "
                                f"min_sell={min_sell_price:.2f}, max_buy={max_buy_price:.2f}"
                            )

                            return {
                                "max_buy_price": max_buy_price,
                                "min_sell_price": min_sell_price,
                                "best_bid": current_price * 0.999,  # Примерно
                                "best_ask": current_price * 1.001,  # Примерно
                                "current_price": current_price,
                            }
        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить лимиты цены для {symbol}: {e}")

        return None

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
            if "eq" in pos and pos.get("eq"):
                eq_value = pos["eq"]
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что это не пустая строка
                if eq_value and str(eq_value).strip():
                    try:
                        equity = float(eq_value)
                        if equity > 0:  # Проверяем что результат валидный
                            logger.debug(
                                f"✅ equity получен из 'eq' для {symbol}: {equity:.2f}"
                            )
                        else:
                            equity = 0.0
                    except (ValueError, TypeError) as e:
                        logger.debug(
                            f"⚠️ Не удалось преобразовать eq для {symbol}: {e}, значение={eq_value}"
                        )
                        equity = 0.0
                else:
                    logger.debug(f"⚠️ Пустое значение eq для {symbol}: '{eq_value}'")
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
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что значения не пустые строки
                if "margin" in pos and pos.get("margin"):
                    margin_str = str(pos["margin"]).strip()
                    if margin_str:  # Проверяем что не пустая строка
                        margin = float(margin_str)
                if "upl" in pos and pos.get("upl"):
                    upl_str = str(pos["upl"]).strip()
                    if upl_str:
                        upl = float(upl_str)
                elif "uPnl" in pos and pos.get("uPnl"):
                    upnl_str = str(pos["uPnl"]).strip()
                    if upnl_str:
                        upl = float(upnl_str)
            except (ValueError, TypeError) as e:
                logger.debug(f"⚠️ Ошибка конвертации margin/upl для {symbol}: {e}")
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
    async def set_leverage(
        self, symbol: str, leverage: int, pos_side: Optional[str] = None
    ) -> dict:
        """Установить плечо (1 раз на символ)"""
        # ✅ ИСПРАВЛЕНИЕ: Для isolated margin mode posSide может быть необязательным
        # Но некоторые режимы (например, hedge mode) требуют posSide
        # В sandbox режиме может потребоваться posSide даже для isolated mode
        data = {
            "instId": f"{symbol}-SWAP",
            "lever": str(leverage),
            "mgnMode": "isolated",
        }

        # ✅ НОВОЕ: Пробуем установить leverage с posSide, если указан
        # Это может потребоваться для sandbox или для некоторых режимов позиций
        if pos_side:
            data["posSide"] = pos_side

        # ✅ ИСПРАВЛЕНИЕ: Retry логика для обработки rate limit (429)
        max_retries = 3
        retry_delay = 0.5  # 500ms

        for attempt in range(max_retries):
            try:
                return await self._make_request(
                    "POST",
                    "/api/v5/account/set-leverage",
                    data=data,
                )
            except RuntimeError as e:
                # Проверяем, является ли это ошибкой rate limit (429)
                error_str = str(e)
                if (
                    "429" in error_str
                    or "Too Many Requests" in error_str
                    or "rate limit" in error_str.lower()
                ):
                    if attempt < max_retries - 1:
                        # Увеличиваем задержку с каждой попыткой (exponential backoff)
                        delay = retry_delay * (2**attempt)
                        logger.warning(
                            f"⚠️ Rate limit (429) при установке leverage для {symbol}, "
                            f"повторная попытка {attempt + 1}/{max_retries} через {delay:.1f}с..."
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(
                            f"❌ Не удалось установить leverage для {symbol} после {max_retries} попыток: {e}"
                        )
                        raise
                else:
                    # Это не ошибка rate limit, пробрасываем дальше
                    raise

    # ---------- Orders ----------
    async def place_futures_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: Optional[float] = None,
        order_type: str = "market",
        size_in_contracts: bool = False,
        reduce_only: bool = False,
        post_only: bool = False,  # ✅ НОВОЕ: Post-only опция для гарантии maker fee
        cl_ord_id: Optional[
            str
        ] = None,  # ✅ КРИТИЧЕСКОЕ: Уникальный ID для предотвращения дубликатов
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
            reduce_only: Если True, ордер только закрывает позицию (не открывает новую)
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

        # ✅ НОВОЕ: Post-only опция для лимитных ордеров (из конфига)
        # postOnly гарантирует maker fee (0.02% вместо 0.05%), но может не исполниться сразу
        # По умолчанию post_only=false для быстрого исполнения в скальпинге
        # Если post_only=true - ордер гарантированно будет maker, но может висеть дольше
        if order_type == "limit" and post_only:
            payload["postOnly"] = "true"  # Гарантирует maker fee

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем параметр reduce_only
        # Это гарантирует, что ордер закроет существующую позицию, а не откроет новую
        # ВАЖНО: Для isolated margin OKX требует posSide даже при reduceOnly!
        if reduce_only:
            payload["reduceOnly"] = "true"
            # Определяем posSide на основе стороны закрытия
            # Если закрываем long - продаем (side="sell"), значит была long
            # Если закрываем short - покупаем (side="buy"), значит была short
            if side.lower() == "sell":
                payload["posSide"] = "long"  # Закрываем long позицию
            elif side.lower() == "buy":
                payload["posSide"] = "short"  # Закрываем short позицию
        else:
            # Для открытия новых позиций добавляем posSide
            if side.lower() == "buy":
                payload["posSide"] = "long"
            elif side.lower() == "sell":
                payload["posSide"] = "short"

        if price:
            payload["px"] = str(price)

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавляем clOrdId для предотвращения дубликатов
        # OKX требует уникальный clOrdId (макс 32 символа)
        if cl_ord_id:
            payload["clOrdId"] = cl_ord_id[:32]  # Ограничиваем до 32 символов

        return await self._make_request("POST", "/api/v5/trade/order", data=payload)

    async def place_oco_order(
        self, symbol: str, side: str, size: float, tp_price: float, sl_price: float
    ) -> dict:
        """OCO для фьючей (min distance 0,01 % = 10 bips)"""
        # Определяем size_step для инструмента (ПРАВИЛЬНЫЕ минимальные lot sizes для OKX SWAP!)
        if "BTC" in symbol:
            size_step = 0.001  # ✅ 0.001 BTC минимум для BTC-USDT-SWAP
        elif "ETH" in symbol:
            size_step = 0.01  # ✅ 0.01 ETH минимум для ETH-USDT-SWAP
        elif "SOL" in symbol:
            size_step = 0.01  # ✅ 0.01 SOL минимум для SOL-USDT-SWAP
        elif "XRP" in symbol:
            size_step = 1.0  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: 1.0 XRP минимум для XRP-USDT-SWAP (как DOGE)
        elif "DOGE" in symbol:
            size_step = 1.0  # ✅ 1.0 DOGE минимум для DOGE-USDT-SWAP
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

    async def get_funding_payment_history(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list:
        """
        Получение истории funding payments (платежей за финансирование).

        OKX API endpoint: /api/v5/account/bills
        Тип: funding (платежи за финансирование)

        Args:
            symbol: Торговый символ (опционально)
            start_time: Начальное время (опционально)
            end_time: Конечное время (опционально)
            limit: Максимальное количество записей (по умолчанию 100)

        Returns:
            Список funding payments
        """
        params = {
            "instType": "SWAP",
            "type": "funding",  # Тип: funding (платежи за финансирование)
            "limit": str(limit),
        }

        if symbol:
            params["instId"] = f"{symbol}-SWAP"

        if start_time:
            # OKX использует timestamp в миллисекундах
            params["before"] = str(int(start_time.timestamp() * 1000))

        if end_time:
            params["after"] = str(int(end_time.timestamp() * 1000))

        try:
            data = await self._make_request(
                "GET", "/api/v5/account/bills", params=params
            )
            if data.get("code") == "0":
                return data.get("data", [])
            else:
                logger.warning(
                    f"⚠️ Ошибка получения истории funding payments: {data.get('msg', 'Unknown error')}"
                )
                return []
        except Exception as e:
            logger.error(
                f"❌ Ошибка запроса истории funding payments: {e}", exc_info=True
            )
            return []

    # ---------- Batch ----------
    async def batch_amend_orders(self, amend_list: list) -> dict:
        """До 20 ордеров за 1 запрос (аналогично spot)"""
        return await self._make_request(
            "POST", "/api/v5/trade/amend-batch", data={"amendData": amend_list}
        )
