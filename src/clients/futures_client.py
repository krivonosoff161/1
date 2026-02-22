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

# ✅ НОВОЕ (09.01.2026): Автоопределение VPN и адаптация соединения
from src.connection_quality_monitor import ConnectionQualityMonitor
from src.models import OHLCV


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
    async def get_ticker(self, symbol: str) -> dict:
        """
        Получить тикер (цену) для символа через REST API (для совместимости с ExitAnalyzer).
        Args:
            symbol: Торговый символ (например, 'ETH-USDT')
        Returns:
            dict с ключами 'last', 'bid', 'ask', 'high', 'low', 'vol', 'ts' и т.д., либо пустой dict при ошибке
        """
        try:
            result = await self._make_request(
                "GET",
                "/api/v5/market/ticker",
                params={"instId": f"{symbol}-SWAP"},
            )
            if result.get("code") == "0" and result.get("data"):
                ticker = result["data"][0]
                # Приводим к универсальному виду
                return {
                    "last": float(ticker.get("last", 0)),
                    "bid": float(ticker.get("bidPx", 0)),
                    "ask": float(ticker.get("askPx", 0)),
                    "high": float(ticker.get("high24h", 0)),
                    "low": float(ticker.get("low24h", 0)),
                    "vol": float(ticker.get("vol24h", 0)),
                    "ts": int(ticker.get("ts", 0)),
                }
            else:
                code = result.get("code")
                msg = result.get("msg")
                data_len = len(result.get("data", []) or [])
                logger.warning(
                    f"⚠️ get_ticker: unexpected response for {symbol}: "
                    f"code={code}, msg={msg}, instId={symbol}-SWAP, data_len={data_len}"
                )
        except Exception as e:
            logger.warning(f"⚠️ get_ticker: Ошибка получения тикера для {symbol}: {e}")
        return {}

    async def get_candles(
        self, symbol: str, timeframe: str = "1m", limit: int = 100
    ) -> list[OHLCV]:
        """
        Получить OHLCV свечи через REST API.
        """
        try:
            result = await self._make_request(
                "GET",
                "/api/v5/market/candles",
                params={
                    "instId": f"{symbol}-SWAP",
                    "bar": timeframe,
                    "limit": str(limit),
                },
            )
            if result.get("code") == "0" and result.get("data"):
                candles = []
                for candle in result["data"]:
                    if len(candle) >= 6:
                        ts_sec = int(candle[0]) // 1000
                        candles.append(
                            OHLCV(
                                timestamp=ts_sec,
                                symbol=symbol,
                                open=float(candle[1]),
                                high=float(candle[2]),
                                low=float(candle[3]),
                                close=float(candle[4]),
                                volume=float(candle[5]),
                                timeframe=timeframe,
                            )
                        )
                return list(reversed(candles))
        except Exception as e:
            logger.warning(f"⚠️ get_candles: Ошибка получения свечей для {symbol}: {e}")
        return []

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
        margin_mode: str = "isolated",
        pos_mode: str = "net_mode",
    ):
        self.base_url = "https://www.okx.com" if not sandbox else "https://www.okx.com"
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.sandbox = sandbox
        self.leverage = leverage
        self.margin_mode = (
            margin_mode if margin_mode in ("isolated", "cross") else "isolated"
        )
        # ✅ Учитываем режим позиций (net/long_short) для корректного posSide
        self.pos_mode = pos_mode or "net_mode"
        self.session = None
        self._session_lock = asyncio.Lock()
        self._lot_sizes_cache: dict = {}  # Кэш для lot sizes
        self._instrument_details_cache: dict = (
            {}
        )  # Кэш для instrument details (ctVal, lotSz, minSz)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Кэш leverage info с TTL 300s (5 минут) для снижения API calls
        self._leverage_info_cache: dict = (
            {}
        )  # Кэш: {symbol: {'max': 125, 'avail': [1,2,..], 'ts': now}}
        self._leverage_info_cache_ttl: float = (
            300.0  # TTL 5 минут (leverage меняется редко)
        )
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Кэш результатов round_leverage_to_available
        self._leverage_round_cache: dict = (
            {}
        )  # Кэш: {(symbol, desired_leverage): {'rounded': 20, 'ts': now}}
        self._leverage_round_cache_ttl: float = 300.0  # TTL 5 минут
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Кэш instrument info для снижения API calls
        self._instrument_info_cache: dict = (
            {}
        )  # Кэш: {inst_type: {'data': [...], 'ts': now}}
        self._instrument_info_cache_ttl: float = (
            300.0  # TTL 5 минут (instrument info меняется редко)
        )
        # ✅ ИСПРАВЛЕНИЕ (07.01.2026): Управление сессией для предотвращения keep-alive проблем
        self._session_created_at: Optional[float] = None
        self._session_max_age: float = (
            60.0  # Пересоздавать сессию каждые 60 секунд (будет перезаписан из monitor)
        )

        # ✅ НОВОЕ (09.01.2026): ConnectionQualityMonitor для автоопределения VPN
        self.connection_monitor = ConnectionQualityMonitor(
            check_interval=60.0, test_url="https://www.okx.com/api/v5/public/time"
        )
        self._monitor_started = False

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Circuit Breaker для защиты от массовых сбоев API
        self.consecutive_failures = 0  # Счётчик последовательных сбоев
        self.circuit_open = False  # Флаг открытого circuit breaker
        self.circuit_open_until: Optional[
            float
        ] = None  # Время закрытия circuit breaker
        self.circuit_failure_threshold = (
            5  # Порог для открытия circuit (5 подряд ошибок)
        )
        self.circuit_cooldown_seconds = 120  # Пауза при открытом circuit (2 минуты)

    async def close(self):
        """Graceful client/session shutdown."""
        try:
            await self._reset_session()
            logger.debug("OKXFuturesClient session closed")
        except Exception as e:
            logger.debug(f"Session close error: {e}")
            self.session = None

    async def _ensure_monitor_started(self) -> None:
        if self._monitor_started:
            return
        await self.connection_monitor.start()
        self._monitor_started = True
        logger.info("ConnectionQualityMonitor started")

    async def _reset_session(self) -> None:
        """Close current aiohttp session safely."""
        async with self._session_lock:
            if self.session and not self.session.closed:
                try:
                    await self.session.close()
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
            self.session = None
            self._session_created_at = None

    async def _ensure_session(self) -> None:
        """Ensure a single reusable aiohttp session exists."""
        if self.session and not self.session.closed:
            return

        async with self._session_lock:
            if self.session and not self.session.closed:
                return

            await self._ensure_monitor_started()
            connector_params = self.connection_monitor.get_connector_params()
            self._session_max_age = self.connection_monitor.get_session_max_age()
            connector = aiohttp.TCPConnector(**connector_params)
            self.session = aiohttp.ClientSession(connector=connector)
            self._session_created_at = time.time()

    # ---------- HTTP internals ----------
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Unified request with OKX signing (same as your spot client)"""

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Проверка Circuit Breaker перед запросом
        if self.circuit_open:
            if self.circuit_open_until and time.time() < self.circuit_open_until:
                elapsed = self.circuit_open_until - time.time()
                raise ConnectionError(
                    f"🔴 Circuit Breaker OPEN: API недоступен, ожидание восстановления ({elapsed:.0f}s)"
                )
            else:
                # Пробуем закрыть circuit
                logger.info(
                    "🔄 Circuit Breaker: Попытка восстановления соединения с API"
                )
                self.circuit_open = False
                self.circuit_open_until = None

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

        # ✅ ИСПРАВЛЕНИЕ (07.01.2026): Управление сессией с force_close для предотвращения keep-alive проблем
        await self._ensure_session()

        max_retries = 3
        retry_delay = 1.0  # Начальная задержка в секундах

        for attempt in range(max_retries):
            try:
                await self._ensure_session()

                # ✅ НОВОЕ (09.01.2026): Динамический timeout из ConnectionQualityMonitor
                timeout = self.connection_monitor.get_timeout_params()
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

                    # ✅ ИСПРАВЛЕНИЕ #9: Retry для 502 Bad Gateway ошибок
                    if resp.status == 502:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (
                                2**attempt
                            )  # Exponential backoff
                            logger.warning(
                                f"⚠️ OKX вернул 502 Bad Gateway (попытка {attempt + 1}/{max_retries}), "
                                f"повтор через {wait_time:.1f}с"
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(
                                f"❌ OKX вернул 502 Bad Gateway после {max_retries} попыток"
                            )
                            raise RuntimeError(
                                f"OKX API: 502 Bad Gateway after {max_retries} retries"
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

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Сброс счётчика при успешном запросе
                    self.consecutive_failures = 0
                    if self.circuit_open:
                        logger.info("✅ Circuit Breaker CLOSED: API восстановлен")
                        self.circuit_open = False
                        self.circuit_open_until = None

                    return resp_data

            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as e:
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
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Специальная обработка SSL ошибок
                error_str = str(e).lower()
                is_ssl_error = (
                    "ssl" in error_str
                    or "application_data_after_close_notify" in error_str
                    or "network name" in error_str
                    or "cannot connect to host" in error_str
                )

                # ✅ НОВОЕ (09.01.2026): Записываем SSL ошибку в ConnectionQualityMonitor
                if is_ssl_error:
                    self.connection_monitor.record_error(is_ssl_error=True)
                else:
                    self.connection_monitor.record_error(is_ssl_error=False)

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Retry для SSL ошибок
                if is_ssl_error and attempt < max_retries - 1:
                    wait_time = retry_delay * (2**attempt)
                    logger.warning(
                        f"🔒 SSL/Network ошибка при запросе к OKX (попытка {attempt + 1}/{max_retries}): "
                        f"{method} {url}, ошибка: {e}, повтор через {wait_time:.1f}с"
                    )
                    # Пересоздаем сессию при SSL ошибке
                    await self._reset_session()
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

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Circuit Breaker при network errors
                self.consecutive_failures += 1

                if self.consecutive_failures >= self.circuit_failure_threshold:
                    self.circuit_open = True
                    self.circuit_open_until = (
                        time.time() + self.circuit_cooldown_seconds
                    )
                    logger.critical(
                        f"🔴 Circuit Breaker OPEN: {self.consecutive_failures} подряд ошибок подключения. "
                        f"Пауза {self.circuit_cooldown_seconds}s. Торговля ПРИОСТАНОВЛЕНА!"
                    )
                    raise ConnectionError(
                        f"Circuit Breaker открыт из-за {self.consecutive_failures} последовательных сбоев"
                    )

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
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Специальная обработка "Connector is closed" для VPN
                error_str = str(e).lower()
                if (
                    "connector is closed" in error_str
                    or "session is closed" in error_str
                ):
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2**attempt)
                        logger.warning(
                            f"🔌 Connector/Session закрыт при VPN (попытка {attempt + 1}/{max_retries}): "
                            f"{method} {url}, переподключаемся через {wait_time:.1f}с"
                        )
                        await self._reset_session()
                        await asyncio.sleep(wait_time)
                        continue

                # Для других ошибок не делаем retry (ошибки API, авторизации и т.д.)
                logger.error(f"Ошибка при запросе к OKX ({method} {url}): {e}")
                raise

    # ---------- Account & Margin ----------
    async def get_account_config(self) -> dict:
        """Получить настройки аккаунта (PosMode, уровень и т.д.)"""
        return await self._make_request("GET", "/api/v5/account/config")

    async def get_instrument_info(self, inst_type: str = "SWAP") -> dict:
        """
        Получает информацию об инструментах (lot size, min size и т.д.).
        ✅ ГРОК ОПТИМИЗАЦИЯ: Использует кэш с TTL 300s для снижения API calls.
        """
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш
        cache_key = inst_type
        if cache_key in self._instrument_info_cache:
            cached_data = self._instrument_info_cache[cache_key]
            now = time.time()
            cache_age = now - cached_data.get("ts", 0)

            if cache_age < self._instrument_info_cache_ttl:
                # Кэш актуален
                logger.debug(
                    f"📊 [INSTRUMENT_INFO] {inst_type}: Из кэша (TTL {self._instrument_info_cache_ttl}s) | "
                    f"{len(cached_data.get('data', []))} инструментов"
                )
                return cached_data
            else:
                # Кэш устарел - удаляем
                logger.debug(
                    f"📊 [INSTRUMENT_INFO] {inst_type}: Кэш устарел ({cache_age:.1f}s > {self._instrument_info_cache_ttl}s), обновляем"
                )
                del self._instrument_info_cache[cache_key]

        # Запрашиваем с API
        logger.debug(f"📊 [INSTRUMENT_INFO] {inst_type}: Запрос к API...")
        data = await self._make_request(
            "GET", "/api/v5/public/instruments", params={"instType": inst_type}
        )

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Сохраняем в кэш с timestamp
        if data and data.get("code") == "0":
            self._instrument_info_cache[cache_key] = {
                "code": data.get("code"),
                "data": data.get("data", []),
                "ts": time.time(),
            }
            logger.debug(
                f"📊 [INSTRUMENT_INFO] {inst_type}: Сохранено в кэш | "
                f"{len(data.get('data', []))} инструментов"
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
                    # Получаем leverage info
                    leverage_info = await self.get_instrument_leverage_info(symbol)

                    details = {
                        "ctVal": float(inst.get("ctVal", 0.01)),  # Contract value
                        "lotSz": float(inst.get("lotSz", 0.01)),  # Lot size
                        "minSz": float(inst.get("minSz", 0.01)),  # Minimum size
                        "tickSz": float(
                            inst.get("tickSz", 0.1)
                        ),  # ✅ НОВОЕ (КИМИ): Tick size для округления цены
                        "max_leverage": leverage_info[
                            "max_leverage"
                        ],  # ✅ НОВОЕ: Максимальный leverage
                        "available_leverages": leverage_info[
                            "available_leverages"
                        ],  # ✅ НОВОЕ: Доступные leverage
                    }
                    self._instrument_details_cache[symbol] = details
                    logger.debug(
                        f"📋 Детали инструмента {symbol}: ctVal={details['ctVal']}, lotSz={details['lotSz']}, "
                        f"minSz={details['minSz']}, max_leverage={details['max_leverage']}x"
                    )
                    return details
        except Exception as e:
            logger.warning(
                f"⚠️ Не удалось получить детали инструмента для {symbol}: {e}"
            )

        # Fallback на значения по умолчанию
        # Получаем leverage info для fallback
        leverage_info = await self.get_instrument_leverage_info(symbol)

        if "BTC" in symbol:
            default_details = {
                "ctVal": 0.01,
                "lotSz": 0.01,
                "minSz": 0.01,
                "tickSz": 0.1,  # ✅ НОВОЕ (КИМИ): BTC tick size обычно 0.1
                "max_leverage": leverage_info["max_leverage"],
                "available_leverages": leverage_info["available_leverages"],
            }
        elif "ETH" in symbol:
            default_details = {
                "ctVal": 0.1,
                "lotSz": 0.01,
                "minSz": 0.01,
                "tickSz": 0.01,  # ✅ НОВОЕ (КИМИ): ETH tick size обычно 0.01
                "max_leverage": leverage_info["max_leverage"],
                "available_leverages": leverage_info["available_leverages"],
            }
        else:
            default_details = {
                "ctVal": 0.01,
                "lotSz": 0.01,
                "minSz": 0.01,
                "tickSz": 0.01,  # ✅ НОВОЕ (КИМИ): Fallback tick size
                "max_leverage": leverage_info["max_leverage"],
                "available_leverages": leverage_info["available_leverages"],
            }

        self._instrument_details_cache[symbol] = default_details
        logger.warning(f"⚠️ Используем fallback детали для {symbol}: {default_details}")
        return default_details

    async def get_instrument_leverage_info(self, symbol: str) -> dict:
        """
        Получает информацию о доступных leverage для символа.

        Args:
            symbol: Торговый символ (например, "BTC", "ETH", "SOL")

        Returns:
            dict с ключами:
                - max_leverage: Максимальный leverage для символа (int)
                - available_leverages: Список доступных leverage (List[int])
        """
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш с TTL
        if symbol in self._leverage_info_cache:
            cached_info = self._leverage_info_cache[symbol]
            now = time.time()
            cache_age = now - cached_info.get("ts", 0)

            if cache_age < self._leverage_info_cache_ttl:
                # Кэш актуален
                logger.debug(
                    f"📊 [LEVERAGE_INFO] {symbol}: Из кэша (TTL {self._leverage_info_cache_ttl}s) | "
                    f"max={cached_info['max_leverage']}x, "
                    f"available={cached_info['available_leverages']}"
                )
                return {
                    "max_leverage": cached_info["max_leverage"],
                    "available_leverages": cached_info["available_leverages"],
                }
            else:
                # Кэш устарел - удаляем
                logger.debug(
                    f"📊 [LEVERAGE_INFO] {symbol}: Кэш устарел ({cache_age:.1f}s > {self._leverage_info_cache_ttl}s), обновляем"
                )
                del self._leverage_info_cache[symbol]

        try:
            inst_id = f"{symbol}-SWAP"
            logger.info(
                f"📊 [LEVERAGE_INFO] {symbol}: Запрос к API для получения leverage информации..."
            )
            instruments = await self.get_instrument_info()

            logger.debug(
                f"📊 [LEVERAGE_INFO] {symbol}: Получен ответ от API, ищем {inst_id} в {len(instruments.get('data', []))} инструментах"
            )

            found = False
            for inst in instruments.get("data", []):
                if inst.get("instId") == inst_id:
                    found = True
                    # Получаем maxLever из API
                    max_lever_str = inst.get("maxLever", "125")
                    logger.info(
                        f"📊 [LEVERAGE_INFO] {symbol}: Найден инструмент {inst_id}, "
                        f"maxLever из API='{max_lever_str}'"
                    )
                    try:
                        max_leverage = int(max_lever_str)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"⚠️ [LEVERAGE_INFO] {symbol}: Не удалось преобразовать maxLever='{max_lever_str}' в int, "
                            f"используем fallback=125x"
                        )
                        max_leverage = 125  # Fallback на стандартный максимум

                    # Генерируем список доступных leverage
                    # OKX обычно поддерживает: 1, 2, 3, 5, 10, 20, 50, 75, 100, 125
                    available_leverages = []
                    leverage_steps = [1, 2, 3, 5, 10, 20, 50, 75, 100, 125]

                    for step in leverage_steps:
                        if step <= max_leverage:
                            available_leverages.append(step)

                    # Если max_leverage не в списке шагов, добавляем его
                    if max_leverage not in available_leverages:
                        available_leverages.append(max_leverage)
                        available_leverages.sort()

                    leverage_info = {
                        "max_leverage": max_leverage,
                        "available_leverages": available_leverages,
                    }

                    # ✅ ГРОК ОПТИМИЗАЦИЯ: Сохраняем в кэш с timestamp
                    self._leverage_info_cache[symbol] = {
                        "max_leverage": max_leverage,
                        "available_leverages": available_leverages,
                        "ts": time.time(),
                    }

                    logger.info(
                        f"✅ [LEVERAGE_INFO] {symbol}: Получено с биржи | "
                        f"max_leverage={max_leverage}x, "
                        f"available_leverages={available_leverages}"
                    )

                    return leverage_info

            if not found:
                logger.warning(
                    f"⚠️ [LEVERAGE_INFO] {symbol}: Инструмент {inst_id} не найден в ответе API"
                )
        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить leverage info для {symbol}: {e}")

        # Fallback на стандартные значения
        default_leverage_info = {
            "max_leverage": 125,
            "available_leverages": [1, 2, 3, 5, 10, 20, 50, 75, 100, 125],
        }
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Сохраняем fallback в кэш с timestamp
        self._leverage_info_cache[symbol] = {
            "max_leverage": 125,
            "available_leverages": [1, 2, 3, 5, 10, 20, 50, 75, 100, 125],
            "ts": time.time(),
        }
        logger.warning(
            f"⚠️ [LEVERAGE_INFO] {symbol}: Fallback | "
            f"max={default_leverage_info['max_leverage']}x, "
            f"available={default_leverage_info['available_leverages']}"
        )
        return default_leverage_info

    async def round_leverage_to_available(
        self, symbol: str, desired_leverage: int
    ) -> int:
        """
        Округляет leverage до ближайшего доступного для символа.
        ✅ ГРОК ОПТИМИЗАЦИЯ: Использует кэш результатов для снижения API calls.

        Args:
            symbol: Торговый символ
            desired_leverage: Желаемый leverage

        Returns:
            Округленный leverage (доступный для символа)
        """
        try:
            # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш результатов округления
            cache_key = (symbol, desired_leverage)
            if cache_key in self._leverage_round_cache:
                cached_result = self._leverage_round_cache[cache_key]
                now = time.time()
                cache_age = now - cached_result.get("ts", 0)

                if cache_age < self._leverage_round_cache_ttl:
                    # Кэш актуален
                    rounded_leverage = cached_result["rounded"]
                    logger.debug(
                        f"📊 [LEVERAGE_ROUND] {symbol}: Из кэша (TTL {self._leverage_round_cache_ttl}s) | "
                        f"desired={desired_leverage}x → rounded={rounded_leverage}x"
                    )
                    return rounded_leverage
                else:
                    # Кэш устарел - удаляем
                    del self._leverage_round_cache[cache_key]

            logger.info(
                f"📊 [LEVERAGE_ROUND] {symbol}: Начало округления | desired={desired_leverage}x"
            )
            leverage_info = await self.get_instrument_leverage_info(symbol)
            max_leverage = leverage_info["max_leverage"]
            available_leverages = leverage_info["available_leverages"]

            logger.info(
                f"📊 [LEVERAGE_ROUND] {symbol}: Получена информация | "
                f"max={max_leverage}x, available={available_leverages}"
            )

            # Если превышает максимум - ограничиваем до максимума
            if desired_leverage > max_leverage:
                rounded_leverage = max_leverage
                logger.info(
                    f"📊 [LEVERAGE_ROUND] {symbol}: Ограничение до максимума | "
                    f"desired={desired_leverage}x > max={max_leverage}x → {max_leverage}x"
                )
            # Если меньше минимума - возвращаем минимум
            elif desired_leverage < available_leverages[0]:
                rounded_leverage = available_leverages[0]
                logger.info(
                    f"📊 [LEVERAGE_ROUND] {symbol}: Округление до минимума | "
                    f"desired={desired_leverage}x < min={available_leverages[0]}x → {available_leverages[0]}x"
                )
            else:
                # Ищем ближайший доступный leverage
                rounded_leverage = min(
                    available_leverages, key=lambda x: abs(x - desired_leverage)
                )

                if rounded_leverage != desired_leverage:
                    logger.info(
                        f"✅ [LEVERAGE_ROUND] {symbol}: Округление выполнено | "
                        f"desired={desired_leverage}x → rounded={rounded_leverage}x "
                        f"(доступные: {available_leverages})"
                    )
                else:
                    logger.info(
                        f"✅ [LEVERAGE_ROUND] {symbol}: Округление не требуется | "
                        f"desired={desired_leverage}x уже доступен"
                    )

            # ✅ ГРОК ОПТИМИЗАЦИЯ: Сохраняем результат в кэш
            self._leverage_round_cache[cache_key] = {
                "rounded": rounded_leverage,
                "ts": time.time(),
            }

            return rounded_leverage

        except Exception as e:
            logger.error(
                f"❌ Ошибка округления leverage для {symbol}: {e}, "
                f"используем желаемый leverage={desired_leverage}x"
            )
            return desired_leverage

    async def get_price_limits(self, symbol: str) -> dict:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получает лимиты цены биржи для символа
        Использует лучшие цены из стакана для более точного расчета

        Returns:
            dict с ключами: max_buy_price, min_sell_price, best_bid, best_ask, current_price
        """
        # FIX 2026-02-22 P0: TTL-кэш 1s — предотвращает лавину HTTP при нескольких позициях
        # (до фикса: 30+ HTTP-запросов за цикл manage_positions при 3 позициях)
        import time as _time_module

        if not hasattr(self, "_price_limits_cache"):
            self._price_limits_cache: dict = {}
        _cache_ttl = 1.0
        _cached = self._price_limits_cache.get(symbol)
        if _cached is not None:
            _result, _ts = _cached
            if _time_module.time() - _ts < _cache_ttl:
                return _result

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

                                            _r = {
                                                "max_buy_price": max_buy_price,
                                                "min_sell_price": min_sell_price,
                                                "best_bid": best_bid,
                                                "best_ask": best_ask,
                                                "current_price": current_price,
                                                "timestamp": time.time(),
                                            }
                                            self._price_limits_cache[symbol] = (
                                                _r,
                                                _time_module.time(),
                                            )
                                            return _r

                                # Если не получили текущую цену, используем среднюю из стакана
                                current_price = (best_ask + best_bid) / 2
                                _r = {
                                    "max_buy_price": max_buy_price,
                                    "min_sell_price": min_sell_price,
                                    "best_bid": best_bid,
                                    "best_ask": best_ask,
                                    "current_price": current_price,
                                    "timestamp": time.time(),
                                }
                                self._price_limits_cache[symbol] = (
                                    _r,
                                    _time_module.time(),
                                )
                                return _r

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

                            _r = {
                                "max_buy_price": max_buy_price,
                                "min_sell_price": min_sell_price,
                                "timestamp": time.time(),
                                "best_bid": current_price * 0.999,
                                "best_ask": current_price * 1.001,
                                "current_price": current_price,
                            }
                            self._price_limits_cache[symbol] = (_r, _time_module.time())
                            return _r
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
            # Use configured margin mode to avoid OKX rejecting leverage updates in cross/portfolio.
            "mgnMode": self.margin_mode,
        }

        # ✅ НОВОЕ: Пробуем установить leverage с posSide, если указан
        # Это может потребоваться для sandbox или для некоторых режимов позиций
        if pos_side:
            data["posSide"] = pos_side

        # ✅ ИСПРАВЛЕНИЕ: Retry логика для обработки rate limit (429) и timeout (50004)
        max_retries = 5  # ✅ Увеличено с 3 до 5 для timeout ошибок
        retry_delay = 1.0  # ✅ Увеличено с 0.5 до 1.0 секунды

        for attempt in range(max_retries):
            try:
                response = await self._make_request(
                    "POST",
                    "/api/v5/account/set-leverage",
                    data=data,
                )
                logger.debug(
                    f"[LEVERAGE_SET] {symbol}: mgnMode={self.margin_mode}, "
                    f"posSide={pos_side or 'N/A'}, lever={leverage}x, response={response}"
                )
                return response
            except RuntimeError as e:
                # ✅ ИСПРАВЛЕНО: Обрабатываем rate limit (429) и timeout (50004)
                error_str = str(e)
                is_rate_limit = (
                    "429" in error_str
                    or "Too Many Requests" in error_str
                    or "rate limit" in error_str.lower()
                )
                is_timeout = (
                    "50004" in error_str
                    or "timeout" in error_str.lower()
                    or "API endpoint request timeout" in error_str
                )

                if is_rate_limit or is_timeout:
                    if attempt < max_retries - 1:
                        # Увеличиваем задержку с каждой попыткой (exponential backoff)
                        delay = retry_delay * (2**attempt)
                        error_type = (
                            "timeout (50004)" if is_timeout else "rate limit (429)"
                        )
                        logger.warning(
                            f"⚠️ {error_type} при установке leverage для {symbol}, "
                            f"повторная попытка {attempt + 1}/{max_retries} через {delay:.1f}с..."
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        error_type = (
                            "timeout (50004)" if is_timeout else "rate limit (429)"
                        )
                        logger.error(
                            f"❌ Не удалось установить leverage для {symbol} после {max_retries} попыток ({error_type}): {e}"
                        )
                        raise
                else:
                    # Это не ошибка rate limit или timeout, пробрасываем дальше
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
            "tdMode": self.margin_mode,
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
        # ВАЖНО: posSide нужен только в hedge (long_short_mode). В net_mode posSide НЕ отправляем.
        pos_mode = getattr(self, "pos_mode", "net_mode") or "net_mode"
        use_pos_side = str(pos_mode).lower() == "long_short_mode"
        if reduce_only:
            payload["reduceOnly"] = "true"
            if use_pos_side:
                # Определяем posSide на основе стороны закрытия
                # Если закрываем long - продаем (side="sell"), значит была long
                # Если закрываем short - покупаем (side="buy"), значит была short
                if side.lower() == "sell":
                    payload["posSide"] = "long"  # Закрываем long позицию
                elif side.lower() == "buy":
                    payload["posSide"] = "short"  # Закрываем short позицию
        else:
            # Для открытия новых позиций добавляем posSide только в hedge mode
            if use_pos_side:
                if side.lower() == "buy":
                    payload["posSide"] = "long"
                elif side.lower() == "sell":
                    payload["posSide"] = "short"

        if price:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (КИМИ): Округляем цену до tickSize OKX вместо 2 знаков
            tick_sz = instrument_details.get(
                "tickSz", 0.1
            )  # Получаем tickSize из деталей инструмента
            rounded_price = round_to_step(price, tick_sz)  # Округляем до tickSize

            if rounded_price != price:
                logger.debug(
                    f"📊 Цена округлена для {symbol}: {price:.8f} → {rounded_price:.8f} "
                    f"(tickSz={tick_sz})"
                )

            payload["px"] = str(rounded_price)

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавляем clOrdId для предотвращения дубликатов
        # OKX требует уникальный clOrdId (макс 32 символа)
        if cl_ord_id:
            payload["clOrdId"] = cl_ord_id[:32]  # Ограничиваем до 32 символов

        try:
            return await self._make_request("POST", "/api/v5/trade/order", data=payload)
        except RuntimeError as e:
            error_text = str(e).lower()
            if "posside" in error_text and "posSide" in payload:
                payload_no_pos = dict(payload)
                payload_no_pos.pop("posSide", None)
                logger.warning(
                    f"⚠️ place_order: posSide rejected by OKX for {symbol}, retry without posSide"
                )
                return await self._make_request(
                    "POST", "/api/v5/trade/order", data=payload_no_pos
                )
            raise

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
            "tdMode": self.margin_mode,
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

    async def place_algo_order(
        self,
        symbol: str,
        side: str,
        size: float,
        trigger_price: float,
        order_price: str = "-1",
        order_type: str = "conditional",
        reduce_only: bool = True,
    ) -> dict:
        """
        Размещение algo order (conditional SL/TP) на бирже.

        Args:
            symbol: Торговый символ (например, "BTC-USDT")
            side: Направление ("buy" или "sell")
            size: Размер позиции
            trigger_price: Цена срабатывания (triggerPx)
            order_price: Цена исполнения ("-1" для market order)
            order_type: Тип ордера ("conditional", "oco", "trigger")
            reduce_only: Только закрытие позиции (True для SL/TP)

        Returns:
            Ответ от биржи с algoId
        """
        # Определяем size_step для округления
        if "BTC" in symbol:
            size_step = 0.001
        elif "ETH" in symbol:
            size_step = 0.01
        elif "SOL" in symbol:
            size_step = 0.01
        elif "XRP" in symbol:
            size_step = 1.0
        elif "DOGE" in symbol:
            size_step = 1.0
        else:
            size_step = 0.001

        rounded_size = round_to_step(size, size_step)

        payload = {
            "instId": f"{symbol}-SWAP",
            "tdMode": self.margin_mode,
            "side": side,
            "ordType": order_type,
            "sz": str(rounded_size),
            "triggerPx": str(trigger_price),
            "orderPx": order_price,
        }

        if reduce_only:
            payload["reduceOnly"] = "true"

        logger.debug(
            f"Placing algo order: {symbol} {side} size={rounded_size} "
            f"trigger={trigger_price} type={order_type}"
        )

        return await self._make_request(
            "POST", "/api/v5/trade/order-algo", data=payload
        )

    async def amend_algo_order(
        self,
        symbol: str,
        algo_id: str,
        new_trigger_price: Optional[float] = None,
        new_size: Optional[float] = None,
    ) -> dict:
        """
        Изменение существующего algo order (для обновления SL при движении TSL).

        Args:
            symbol: Торговый символ
            algo_id: ID algo ордера (algoId)
            new_trigger_price: Новая цена срабатывания (опционально)
            new_size: Новый размер (опционально)

        Returns:
            Ответ от биржи
        """
        payload = {
            "instId": f"{symbol}-SWAP",
            "algoId": algo_id,
        }

        if new_trigger_price is not None:
            payload["newTpTriggerPx"] = str(new_trigger_price)

        if new_size is not None:
            # Определяем size_step для округления
            if "BTC" in symbol:
                size_step = 0.001
            elif "ETH" in symbol:
                size_step = 0.01
            elif "SOL" in symbol:
                size_step = 0.01
            elif "XRP" in symbol:
                size_step = 1.0
            elif "DOGE" in symbol:
                size_step = 1.0
            else:
                size_step = 0.001

            rounded_size = round_to_step(new_size, size_step)
            payload["newSz"] = str(rounded_size)

        logger.debug(
            f"Amending algo order: {symbol} algoId={algo_id} "
            f"new_trigger={new_trigger_price}"
        )

        return await self._make_request(
            "POST", "/api/v5/trade/amend-algos", data=payload
        )

    async def get_algo_orders(
        self, symbol: Optional[str] = None, order_type: str = "conditional"
    ) -> list:
        """
        Получение активных algo orders.

        Args:
            symbol: Торговый символ (опционально)
            order_type: Тип ордера ("conditional", "oco", "trigger")

        Returns:
            Список активных algo orders
        """
        params = {
            "instType": "SWAP",
            "ordType": order_type,
        }

        if symbol:
            params["instId"] = f"{symbol}-SWAP"

        try:
            data = await self._make_request(
                "GET", "/api/v5/trade/orders-algo-pending", params=params
            )
            return data.get("data", [])
        except Exception as e:
            logger.debug(f"Failed to get algo orders for {symbol}: {e}")
            return []

    async def cancel_algo_order(self, symbol: str, algo_id: str) -> dict:
        """
        Отмена algo order.

        Args:
            symbol: Торговый символ
            algo_id: ID algo ордера (algoId)

        Returns:
            Ответ от биржи
        """
        payload = [
            {
                "instId": f"{symbol}-SWAP",
                "algoId": algo_id,
            }
        ]

        return await self._make_request(
            "POST", "/api/v5/trade/cancel-algos", data=payload
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
        try:
            data = await self._make_request(
                "GET", "/api/v5/trade/orders-pending", params=params
            )
            return data.get("data", [])
        except Exception as e:
            error_str = str(e).lower()
            if "orders-pending" in error_str or "timeout" in error_str:
                raise TimeoutError(f"orders-pending timeout: {e}")
            raise

    async def get_order_by_clordid(self, symbol: str, cl_ord_id: str) -> list:
        """Получение ордера по client order id (clOrdId)"""
        params = {"instId": f"{symbol}-SWAP", "clOrdId": cl_ord_id}
        data = await self._make_request("GET", "/api/v5/trade/order", params=params)
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
