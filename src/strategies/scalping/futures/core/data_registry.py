"""
DataRegistry - Единый реестр всех данных.

Это единый источник истины для всех данных в системе:
- Market data (цены, объемы, свечи)
- Indicators (ADX, MA, RSI, etc.)
- Regimes (trending, ranging, choppy) с параметрами
- Balance и balance profile
- Margin данные
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from src.models import OHLCV

from .candle_buffer import CandleBuffer


class DataRegistry:
    async def _check_market_data_fresh(self, symbol: str, max_age: float = 1.0) -> bool:
        """
        Проверяет, что рыночные данные свежие (не старше max_age секунд).

        ✅ FIX (22.01.2026): Адаптивный TTL для REST fallback данных
        - REST_FALLBACK: TTL = 30 сек (терпим устаревание пока WebSocket стартует)
        - WebSocket: TTL = 1 сек (жесткий контроль live данных)
        """
        async with self._lock:
            md = self._market_data.get(symbol, {})
            updated_at = md.get("updated_at")
            if not updated_at or not isinstance(updated_at, datetime):
                logger.error(
                    f"❌ DataRegistry: Нет актуальных данных для {symbol} (нет updated_at)"
                )
                return False

            # ✅ FIX (22.01.2026): Адаптивный TTL - OKX присылает тикеры ОЧЕНЬ редко
            # Проблема: OKX Sandbox/Public WebSocket присылает тикеры с интервалом:
            # - BTC: 4-10 сек
            # - ETH/SOL: 10-20 сек
            # - XRP/DOGE: 30-60 сек (low liquidity pairs)
            # Решение: Увеличили TTL до 60 сек чтобы избежать ложных ошибок
            source = md.get("source", "WEBSOCKET")
            if max_age is not None and max_age > 0:
                effective_max_age = float(max_age)
            else:
                # Если max_age не задан — используем TTL реестра (а не жёсткий 60s)
                effective_max_age = float(getattr(self, "market_data_ttl", 60.0))

            age = (datetime.now() - updated_at).total_seconds()
            if age > effective_max_age:
                logger.error(
                    f"❌ DataRegistry: Данные для {symbol} устарели на {age:.2f}s (> {effective_max_age}s) [source={source}]"
                )
                return False
            return True

    """
    Единый реестр всех данных.

    Хранит:
    - market_data: рыночные данные (цены, объемы, свечи)
    - indicators: индикаторы (ADX, MA, RSI, etc.)
    - regimes: режимы рынка с параметрами
    - balance: баланс и профиль баланса
    - margin: данные маржи

    Thread-safe операции через asyncio.Lock
    """

    def __init__(self):
        """Инициализация реестра"""
        self._market_data: Dict[str, Dict[str, Any]] = {}
        self._indicators: Dict[str, Dict[str, Any]] = {}
        self._regimes: Dict[str, Dict[str, Any]] = {}
        self._balance: Optional[Dict[str, Any]] = None
        self._margin: Optional[Dict[str, Any]] = None
        self._candle_buffers: Dict[str, Dict[str, CandleBuffer]] = {}
        self._lock = asyncio.Lock()
        # 🔇 Для условного логирования баланса (только при значительном изменении)
        self._last_logged_balance: Optional[float] = None
        # FIX (2026-02-21): timestamp последнего WS positions обновления (из handle_private_ws_positions)
        # Используется TCC update_state() для решения: делать REST или доверять WS
        self._ws_positions_ts: float = 0.0
        # Phase 3 (2026-02-21): Event-driven TCC wake-up.
        # WS ticker → set event → TCC просыпается немедленно (вместо asyncio.sleep).
        # Снижает latency сигнала: ~1000ms → ~50ms на fast pairs.
        self._ws_tick_event: asyncio.Event = asyncio.Event()
        # TTL для данных (секунды)
        self.market_data_ttl = 5.0
        self.indicator_ttl = 2.0
        self.regime_ttl = 10.0
        self.balance_ttl = 10.0
        self.margin_ttl = 10.0

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (25.01.2026): Кэширование REST API для предотвращения спама
        self._rest_ticker_cache: Dict[str, Dict[str, Any]] = {}
        self._rest_cache_ttl = 3.0  # FIX (2026-02-19): Кэш REST ответов 1.0→3.0 (снижаем REST спам при stale WS)
        self._rest_api_semaphore = asyncio.Semaphore(
            5
        )  # Max 5 concurrent REST requests
        self._rest_fallback_counter: Dict[
            str, int
        ] = {}  # Счетчик fallback для каждого символа
        self._ws_reconnect_callback = None
        self._last_ws_reconnect_ts: Dict[str, float] = {}
        self._last_ws_reconnect_global_ts: float = 0.0
        self._ws_reconnect_cooldown = 30.0
        self._require_ws_source_for_fresh = True
        self._slo_monitor = None
        self._decision_max_age: Dict[str, float] = {
            "entry": 3.0,
            "exit_normal": 5.0,
            "exit_critical": 10.0,
            "orders": 1.0,
            "monitoring": 15.0,
        }

    def set_slo_monitor(self, slo_monitor: Any) -> None:
        """Attach optional SLO monitor for runtime counters."""
        self._slo_monitor = slo_monitor

    def set_ws_reconnect_callback(self, callback) -> None:
        """Установить async callback для инициирования WS reconnect."""
        self._ws_reconnect_callback = callback

    async def _maybe_trigger_ws_reconnect(
        self, symbol: str, fallback_count: int, reason: str
    ) -> None:
        """Try to trigger WS reconnect with cooldown."""
        if not self._ws_reconnect_callback:
            return
        now = time.time()
        # Global cooldown to avoid reconnect storms when several symbols stale together.
        if now - self._last_ws_reconnect_global_ts < self._ws_reconnect_cooldown:
            return
        last_ts = self._last_ws_reconnect_ts.get(symbol, 0)
        if now - last_ts < self._ws_reconnect_cooldown:
            return
        self._last_ws_reconnect_global_ts = now
        self._last_ws_reconnect_ts[symbol] = now
        try:
            try:
                await self._ws_reconnect_callback(
                    symbol=symbol, fallback_count=fallback_count, reason=reason
                )
            except TypeError:
                await self._ws_reconnect_callback()
            logger.warning(
                f"WS reconnect requested for {symbol} (fallback_count={fallback_count}, reason={reason})"
            )
        except Exception as e:
            logger.debug(f"WS reconnect callback failed for {symbol}: {e}")

    async def is_stale(self, symbol: str) -> bool:
        """Проверяет, устарели ли рыночные данные для символа"""
        async with self._lock:
            md = self._market_data.get(symbol, {})
            updated_at = md.get("updated_at")
            if not updated_at or not isinstance(updated_at, datetime):
                return True
            age = (datetime.now() - updated_at).total_seconds()
            return age > self.market_data_ttl

    async def is_ws_fresh(self, symbol: str, max_age: float = 3.0) -> bool:
        """Проверяет, что цена пришла из WS и свежая (для торговли)."""
        async with self._lock:
            md = self._market_data.get(symbol, {})
            updated_at = md.get("updated_at")
            if not updated_at or not isinstance(updated_at, datetime):
                return False
            source = md.get("source", "WEBSOCKET")
            age = (datetime.now() - updated_at).total_seconds()
            if self._require_ws_source_for_fresh and source != "WEBSOCKET":
                logger.debug(
                    f"DataRegistry.is_ws_fresh({symbol}): source={source} not WEBSOCKET"
                )
                return False
            if age > float(max_age):
                logger.debug(
                    f"DataRegistry.is_ws_fresh({symbol}): age={age:.2f}s > max={float(max_age):.2f}s, source={source}"
                )
                return False
            return True

    def set_require_ws_source_for_fresh(self, required: bool) -> None:
        """Настроить, требует ли is_ws_fresh источник WEBSOCKET."""
        self._require_ws_source_for_fresh = bool(required)

    def configure_decision_max_age(self, mapping: Optional[Dict[str, Any]]) -> None:
        """Override decision max-age thresholds for entry/exit/order contexts."""
        if not isinstance(mapping, dict):
            return
        for key, value in mapping.items():
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if parsed <= 0:
                continue
            self._decision_max_age[str(key)] = parsed

    def get_decision_max_age(
        self, context: Optional[str], fallback: float = 15.0
    ) -> float:
        if context:
            try:
                ctx_value = self._decision_max_age.get(str(context))
                if ctx_value is not None:
                    return float(ctx_value)
            except (TypeError, ValueError):
                pass
        return float(fallback)

    async def auto_reinit(self, symbol: str, fetch_market_data_callback=None):
        """Автоматически реинициализирует данные, если они устарели"""
        if await self.is_stale(symbol):
            logger.warning(
                f"⚠️ DataRegistry: Данные для {symbol} устарели, авто-реинициализация..."
            )
            if fetch_market_data_callback:
                try:
                    new_data = await fetch_market_data_callback(symbol)
                    if new_data:
                        await self.update_market_data(symbol, new_data)
                        logger.info(
                            f"✅ DataRegistry: Данные для {symbol} обновлены через авто-реинициализацию"
                        )
                        return True
                except Exception as e:
                    logger.error(
                        f"❌ DataRegistry: Ошибка авто-реинициализации {symbol}: {e}"
                    )
            return False
        return True

    # ==================== MARKET DATA ====================

    async def update_market_data(self, symbol: str, data: Dict[str, Any]) -> None:
        """
        Обновить рыночные данные для символа.

        Args:
            symbol: Торговый символ
            data: Рыночные данные (price, volume, candles, etc.)
        """
        async with self._lock:
            if symbol not in self._market_data:
                self._market_data[symbol] = {}

            self._market_data[symbol].update(data)
            self._market_data[symbol]["updated_at"] = datetime.now()

            # Сброс счетчика REST fallback при восстановлении WS-потока
            try:
                if self._market_data[symbol].get("source") == "WEBSOCKET":
                    self._rest_fallback_counter[symbol] = 0
            except Exception:
                pass

            logger.debug(f"✅ DataRegistry: Обновлены market data для {symbol}")
            try:
                updated = self._market_data[symbol].get("updated_at")
                price = self._market_data[symbol].get("price") or self._market_data[
                    symbol
                ].get("last_price")
                source = self._market_data[symbol].get("source")
                age = (datetime.now() - updated).total_seconds() if updated else None
                logger.debug(
                    f"▶️ market_data {symbol}: price={price} source={source} age={age:.2f if age is not None else 'N/A'}"
                )
            except Exception:
                pass

        # Phase 3: Сигналим TCC о новом WS тике (вне лока — мгновенная операция).
        # TCC использует asyncio.wait_for(event.wait()) вместо asyncio.sleep.
        if data.get("source") == "WEBSOCKET":
            self._ws_tick_event.set()

    async def get_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получить рыночные данные для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Рыночные данные или None
        """
        if not await self._check_market_data_fresh(
            symbol, max_age=self.market_data_ttl
        ):
            return None
        async with self._lock:
            return (
                self._market_data.get(symbol, {}).copy()
                if symbol in self._market_data
                else None
            )

    async def get_price_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Return a point-in-time price snapshot for exit decisions.

        Returns:
            dict with keys: price, source, age, updated_at
        """
        async with self._lock:
            md = self._market_data.get(symbol, {})
            updated_at = md.get("updated_at")
            price = md.get("price") or md.get("last_price")
            source = md.get("source")

        age = None
        if updated_at and isinstance(updated_at, datetime):
            age = (datetime.now() - updated_at).total_seconds()

        if price is None and source is None and age is None:
            return None
        return {
            "price": price,
            "source": source,
            "age": age,
            "updated_at": updated_at,
        }

    @staticmethod
    def _to_positive_float(value: Any) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return parsed

    @staticmethod
    def _extract_ticker_price(ticker: Dict[str, Any]) -> Optional[float]:
        if not isinstance(ticker, dict):
            return None
        for field in ("markPx", "last", "lastPx"):
            price = DataRegistry._to_positive_float(ticker.get(field))
            if price is not None:
                return price
        return None

    async def get_decision_price_snapshot(
        self,
        symbol: str,
        client=None,
        max_age: Optional[float] = None,
        context: Optional[str] = None,
        allow_rest_fallback: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Единый snapshot цены для decision-пайплайнов (ExitAnalyzer/TSL/PositionMonitor).

        Returns:
            {
                "price": float,
                "source": str,
                "age": Optional[float],
                "updated_at": datetime|None,
                "stale": bool,
                "rest_fallback": bool,
            }
        """

        def _finalize_snapshot(
            result: Optional[Dict[str, Any]]
        ) -> Optional[Dict[str, Any]]:
            if not self._slo_monitor:
                return result
            try:
                rest_fallback = bool(result and result.get("rest_fallback"))
                self._slo_monitor.record_decision_snapshot(rest_fallback=rest_fallback)
                if rest_fallback and str(context or "").lower() == "entry":
                    self._slo_monitor.record_event("ws_stale_signal_fallback")
            except Exception:
                pass
            return result

        if max_age is not None:
            try:
                resolved_max_age = float(max_age)
            except (TypeError, ValueError):
                resolved_max_age = self.get_decision_max_age(context, fallback=15.0)
        else:
            resolved_max_age = self.get_decision_max_age(context, fallback=15.0)
        if resolved_max_age <= 0:
            resolved_max_age = self.get_decision_max_age(context, fallback=15.0)

        snapshot = await self.get_price_snapshot(symbol)
        if snapshot:
            price = self._to_positive_float(snapshot.get("price"))
            source = snapshot.get("source")
            updated_at = snapshot.get("updated_at")
            age_raw = snapshot.get("age")
            try:
                age = float(age_raw) if age_raw is not None else None
            except (TypeError, ValueError):
                age = None
            stale = bool(age is not None and age > resolved_max_age)
            if price is not None and not stale:
                return _finalize_snapshot(
                    {
                        "price": price,
                        "source": source or "WEBSOCKET",
                        "age": age,
                        "updated_at": updated_at,
                        "stale": False,
                        "rest_fallback": False,
                        "context": context,
                        "max_age": resolved_max_age,
                    }
                )
        else:
            price = None
            source = None
            updated_at = None
            age = None
            stale = True

        if not allow_rest_fallback or client is None:
            if price is None:
                return _finalize_snapshot(None)
            return _finalize_snapshot(
                {
                    "price": price,
                    "source": source or "UNKNOWN",
                    "age": age,
                    "updated_at": updated_at,
                    "stale": stale,
                    "rest_fallback": False,
                    "context": context,
                    "max_age": resolved_max_age,
                }
            )

        try:
            cache_key = f"{symbol}_decision_ticker"
            cached = self._rest_ticker_cache.get(cache_key)
            if (
                cached
                and (datetime.now() - cached["timestamp"]).total_seconds()
                < self._rest_cache_ttl
            ):
                fresh_price = self._to_positive_float(cached.get("price"))
            else:
                fresh_price = None
                async with self._rest_api_semaphore:
                    await asyncio.sleep(0.1)
                    ticker = await client.get_ticker(symbol)
                    fresh_price = self._extract_ticker_price(ticker or {})
                    if fresh_price is not None:
                        self._rest_ticker_cache[cache_key] = {
                            "price": fresh_price,
                            "timestamp": datetime.now(),
                        }

            if fresh_price is None:
                if price is None:
                    return _finalize_snapshot(None)
                return _finalize_snapshot(
                    {
                        "price": price,
                        "source": source or "UNKNOWN",
                        "age": age,
                        "updated_at": updated_at,
                        "stale": stale,
                        "rest_fallback": False,
                        "context": context,
                        "max_age": resolved_max_age,
                    }
                )

            # Keep WS freshness semantics stable: REST fallback must not overwrite
            # WS source/updated_at used by watchdog and freshness gates.
            async with self._lock:
                md = self._market_data.setdefault(symbol, {})
                md["last_rest_price"] = fresh_price
                md["last_rest_updated_at"] = datetime.now()
                md["last_decision_price"] = fresh_price
                md["last_decision_source"] = "REST_FALLBACK"

            self._rest_fallback_counter[symbol] = (
                self._rest_fallback_counter.get(symbol, 0) + 1
            )
            fallback_count = self._rest_fallback_counter[symbol]
            if fallback_count > 20:
                await self._maybe_trigger_ws_reconnect(
                    symbol=symbol,
                    fallback_count=fallback_count,
                    reason="decision_snapshot",
                )

            return _finalize_snapshot(
                {
                    "price": fresh_price,
                    "source": "REST_FALLBACK",
                    "age": 0.0,
                    "updated_at": datetime.now(),
                    "stale": False,
                    "rest_fallback": True,
                    "context": context,
                    "max_age": resolved_max_age,
                }
            )
        except Exception as e:
            logger.debug(f"Decision snapshot REST fallback failed for {symbol}: {e}")
            if price is None:
                return _finalize_snapshot(None)
            return _finalize_snapshot(
                {
                    "price": price,
                    "source": source or "UNKNOWN",
                    "age": age,
                    "updated_at": updated_at,
                    "stale": stale,
                    "rest_fallback": False,
                    "context": context,
                    "max_age": resolved_max_age,
                }
            )

    async def get_price(self, symbol: str) -> Optional[float]:
        """
        Получить текущую цену символа.

        Args:
            symbol: Торговый символ

        Returns:
            Цена или None
        """
        # ✅ ИСПРАВЛЕНО (23.01.2026): используем TTL DataRegistry
        # OKX присылает тикеры медленно (4-60s), лучше устаревшая цена чем None
        if not await self._check_market_data_fresh(
            symbol, max_age=self.market_data_ttl
        ):
            return None
        async with self._lock:
            market_data = self._market_data.get(symbol, {})
            return market_data.get("price") or market_data.get("last_price")

    async def get_fresh_price_for_exit_analyzer(
        self, symbol: str, client=None, max_age: Optional[float] = None
    ) -> Optional[float]:
        """
        Get fresh price for ExitAnalyzer via unified decision snapshot.
        """
        snapshot = await self.get_decision_price_snapshot(
            symbol=symbol,
            client=client,
            context="exit_normal",
            max_age=max_age,
            allow_rest_fallback=True,
        )
        if not snapshot:
            logger.error(f"ExitAnalyzer: NO FRESH PRICE for {symbol}")
            return None
        return self._to_positive_float(snapshot.get("price"))

    async def get_fresh_price_for_orders(
        self, symbol: str, client=None
    ) -> Optional[float]:
        """
        Get fresh price for OrderExecutor via unified decision snapshot.
        """
        snapshot = await self.get_decision_price_snapshot(
            symbol=symbol,
            client=client,
            context="orders",
            allow_rest_fallback=True,
        )
        if not snapshot:
            logger.error(f"OrderExecutor: NO FRESH PRICE for {symbol}")
            return None
        return self._to_positive_float(snapshot.get("price"))

    async def get_fresh_price_for_signals(
        self, symbol: str, client=None, max_age: Optional[float] = None
    ) -> Optional[float]:
        """
        Get fresh price for SignalGenerator via unified decision snapshot.
        """
        snapshot = await self.get_decision_price_snapshot(
            symbol=symbol,
            client=client,
            context="entry",
            max_age=max_age,
            allow_rest_fallback=True,
        )
        if not snapshot:
            logger.warning(f"SignalGenerator: NO FRESH PRICE for {symbol}")
            return None
        return self._to_positive_float(snapshot.get("price"))

    async def get_mark_price(self, symbol: str) -> Optional[float]:
        """
        Get mark price for futures. If mark price is unavailable, use last known price.
        """
        if not await self._check_market_data_fresh(symbol, max_age=1.0):
            return None

        async with self._lock:
            market_data = self._market_data.get(symbol, {})
            mark_px = market_data.get("markPx") or market_data.get("mark_px")
            if mark_px and isinstance(mark_px, (int, float)) and mark_px > 0:
                return float(mark_px)
            return self._to_positive_float(
                market_data.get("price") or market_data.get("last_price")
            )

    async def peek_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Return raw market_data without TTL checks.
        Used for diagnostics and controlled stale-data fallbacks.
        """
        async with self._lock:
            data = self._market_data.get(symbol)
            if data:
                updated_at = data.get("updated_at")
                source = data.get("source")
                price = data.get("price") or data.get("last_price")
                logger.debug(
                    f"peek_market_data {symbol}: price={price} source={source} updated_at={updated_at}"
                )
                return dict(data)
            return None

    # ==================== INDICATORS ====================

    async def update_indicator(
        self, symbol: str, indicator_name: str, value: Any
    ) -> None:
        """
        Обновить значение индикатора.

        Args:
            symbol: Торговый символ
            indicator_name: Название индикатора (adx, ma_fast, ma_slow, etc.)
            value: Значение индикатора
        """
        async with self._lock:
            if symbol not in self._indicators:
                self._indicators[symbol] = {}

            self._indicators[symbol][indicator_name] = value
            self._indicators[symbol]["updated_at"] = datetime.now()

            logger.debug(
                f"✅ DataRegistry: Обновлен индикатор {indicator_name} для {symbol}"
            )

    async def update_indicators(self, symbol: str, indicators: Dict[str, Any]) -> None:
        """
        Обновить несколько индикаторов сразу.

        Args:
            symbol: Торговый символ
            indicators: Словарь индикаторов {indicator_name -> value}
        """
        async with self._lock:
            if symbol not in self._indicators:
                self._indicators[symbol] = {}

            self._indicators[symbol].update(indicators)
            self._indicators[symbol]["updated_at"] = datetime.now()

            logger.debug(f"✅ DataRegistry: Обновлены индикаторы для {symbol}")

    async def get_indicator(self, symbol: str, indicator_name: str) -> Optional[Any]:
        """
        Получить значение индикатора.

        Args:
            symbol: Торговый символ
            indicator_name: Название индикатора

        Returns:
            Значение индикатора или None
        """
        async with self._lock:
            return (
                self._indicators.get(symbol, {}).get(indicator_name)
                if symbol in self._indicators
                else None
            )

    async def get_indicators(
        self, symbol: str, check_freshness: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Получить все индикаторы для символа.

        Args:
            symbol: Торговый символ
            check_freshness: Проверять актуальность индикаторов (по умолчанию True)
                           Если ADX старше 1 секунды → вернуть None для пересчета

        Returns:
            Словарь всех индикаторов или None (если данные устарели или отсутствуют)
        """
        async with self._lock:
            if symbol not in self._indicators:
                return None

            indicators = self._indicators.get(symbol, {}).copy()

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Проверка актуальности ADX (TTL 1 секунда)
            if check_freshness and "updated_at" in indicators:
                updated_at = indicators.get("updated_at")
                if updated_at and isinstance(updated_at, datetime):
                    time_diff = (datetime.now() - updated_at).total_seconds()
                    if time_diff > 1.0:  # ADX старше 1 секунды - считается устаревшим
                        logger.debug(
                            f"⚠️ DataRegistry: Индикаторы для {symbol} устарели "
                            f"(прошло {time_diff:.2f}с > 1.0с), требуется пересчет"
                        )
                        return None  # Возвращаем None для пересчета

            return indicators

    # ==================== REGIMES ====================

    async def update_regime(
        self,
        symbol: str,
        regime: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Обновить режим рынка для символа.

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            params: Параметры режима (tp_percent, sl_percent, etc.)
        """
        async with self._lock:
            if symbol not in self._regimes:
                self._regimes[symbol] = {}

            self._regimes[symbol]["regime"] = regime
            if params:
                self._regimes[symbol]["params"] = params.copy()
            self._regimes[symbol]["updated_at"] = datetime.now()

            logger.debug(f"✅ DataRegistry: Обновлен режим для {symbol}: {regime}")

    async def get_regime(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получить режим рынка для символа.

        Args:
            symbol: Торговый символ

        Returns:
            {regime: str, params: dict, updated_at: datetime} или None
        """
        async with self._lock:
            return (
                self._regimes.get(symbol, {}).copy()
                if symbol in self._regimes
                else None
            )

    async def get_regime_name(self, symbol: str) -> Optional[str]:
        """
        Получить название режима для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Название режима (trending, ranging, choppy) или None
        """
        async with self._lock:
            regime_data = self._regimes.get(symbol, {})
            return regime_data.get("regime") if regime_data else None

    # ==================== BALANCE ====================

    async def update_balance(
        self, balance: float, profile: Optional[str] = None, source: str = "REST"
    ) -> None:
        """
        Обновить баланс и профиль баланса.

        Args:
            balance: Текущий баланс
            profile: Профиль баланса (small, medium, large)
            source: Источник данных — "REST" или "ACCOUNT_WS"
        """
        import time as _time

        async with self._lock:
            self._balance = {
                "balance": balance,
                "profile": profile,
                "updated_at": datetime.now(),
                "source": source,
                # FIX (2026-02-21): храним unix ts для быстрого расчёта age без datetime
                "ws_ts": _time.time() if source == "ACCOUNT_WS" else 0.0,
            }

            # 🔇 УСЛОВНОЕ ЛОГИРОВАНИЕ (2026-02-08): Логируем только при значительном изменении баланса (>1%)
            # Раскомментировать для постоянного логирования
            should_log = False
            if self._last_logged_balance is None:
                should_log = True  # Первое обновление всегда логируем
            elif self._last_logged_balance > 0:
                change_pct = (
                    abs(balance - self._last_logged_balance) / self._last_logged_balance
                )
                if change_pct >= 0.01:  # Изменение >= 1%
                    should_log = True

            if should_log:
                logger.info(
                    f"✅ DataRegistry: Обновлен баланс: {balance:.2f} USDT "
                    f"(profile={profile}, source={source})"
                )
                self._last_logged_balance = balance

    async def get_balance(self) -> Optional[Dict[str, Any]]:
        """
        Получить баланс и профиль.

        Returns:
            {balance: float, profile: str, updated_at: datetime} или None
        """
        async with self._lock:
            return self._balance.copy() if self._balance else None

    async def get_balance_value(self) -> Optional[float]:
        """
        Получить значение баланса.

        Returns:
            Баланс или None
        """
        async with self._lock:
            return self._balance.get("balance") if self._balance else None

    async def get_balance_ws_age(self) -> float:
        """
        FIX (2026-02-21): Возвращает возраст последнего ACCOUNT_WS обновления баланса.

        Returns:
            Секунды с последнего ACCOUNT_WS обновления, или 9999 если не было WS обновлений.
            Используется модулями для решения: делать REST get_balance() или нет.
        """
        import time as _time

        async with self._lock:
            if not self._balance:
                return 9999.0
            if self._balance.get("source") != "ACCOUNT_WS":
                return 9999.0
            ws_ts = self._balance.get("ws_ts", 0.0)
            if ws_ts <= 0:
                return 9999.0
            return _time.time() - ws_ts

    def update_ws_positions_ts(self) -> None:
        """
        FIX (2026-02-21): Обновить timestamp последнего WS positions обновления.
        Вызывается из WSCoordinator.handle_private_ws_positions() при каждом приходе данных.
        Синхронный (не async) — вызывается из горячего WS callback'а.
        """
        import time as _time

        self._ws_positions_ts = _time.time()

    def get_ws_positions_age(self) -> float:
        """
        FIX (2026-02-21): Возраст последнего WS positions обновления в секундах.
        Используется TCC.update_state() для решения: делать REST get_positions() или нет.

        Returns:
            Секунды с последнего WS обновления позиций, или 9999 если данных не было.
        """
        import time as _time

        if self._ws_positions_ts <= 0:
            return 9999.0
        return _time.time() - self._ws_positions_ts

    async def get_balance_profile(self) -> Optional[str]:
        """
        Получить профиль баланса.

        Returns:
            Профиль баланса (small, medium, large) или None
        """
        async with self._lock:
            return self._balance.get("profile") if self._balance else None

    # ==================== MARGIN ====================

    async def update_margin(
        self,
        used: float,
        available: Optional[float] = None,
        total: Optional[float] = None,
    ) -> None:
        """
        Обновить данные маржи.

        Args:
            used: Использованная маржа
            available: Доступная маржа
            total: Общая маржа
        """
        async with self._lock:
            self._margin = {
                "used": used,
                "available": available,
                "total": total,
                "updated_at": datetime.now(),
            }

            available_str = f"{available:.2f}" if available is not None else "N/A"
            logger.debug(
                f"✅ DataRegistry: Обновлена маржа: used={used:.2f}, available={available_str}"
            )

    async def get_margin(self) -> Optional[Dict[str, Any]]:
        """
        Получить данные маржи.

        Returns:
            {used: float, available: float, total: float, updated_at: datetime} или None
        """
        async with self._lock:
            return self._margin.copy() if self._margin else None

    async def get_margin_used(self) -> Optional[float]:
        """
        Получить использованную маржу.

        Returns:
            Использованная маржа или None
        """
        async with self._lock:
            return self._margin.get("used") if self._margin else None

    # ==================== SYNC METHODS (для совместимости) ====================

    def get_price_sync(self, symbol: str) -> Optional[float]:
        """
        Синхронная версия get_price (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Args:
            symbol: Торговый символ

        Returns:
            Цена или None
        """
        market_data = self._market_data.get(symbol, {})
        return market_data.get("price") or market_data.get("last_price")

    def get_regime_name_sync(self, symbol: str) -> Optional[str]:
        """
        Синхронная версия get_regime_name (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Args:
            symbol: Торговый символ

        Returns:
            Название режима или None
        """
        regime_data = self._regimes.get(symbol, {})
        return regime_data.get("regime") if regime_data else None

    def get_balance_profile_sync(self) -> Optional[str]:
        """
        Синхронная версия get_balance_profile (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Returns:
            Профиль баланса или None
        """
        return self._balance.get("profile") if self._balance else None

    # ==================== CANDLES ====================

    async def add_candle(self, symbol: str, timeframe: str, candle: OHLCV) -> None:
        """
        Добавить новую свечу в буфер для символа и таймфрейма.

        Если свеча для новой минуты (или нового таймфрейма) - закрывает последнюю и добавляет новую.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)
            candle: Свеча OHLCV
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                self._candle_buffers[symbol] = {}

            if timeframe not in self._candle_buffers[symbol]:
                # Создаем новый буфер для таймфрейма
                max_size = (
                    200 if timeframe == "1m" else 100
                )  # 200 для 1m, 100 для остальных
                self._candle_buffers[symbol][timeframe] = CandleBuffer(
                    max_size=max_size
                )
                logger.debug(
                    f"📊 DataRegistry: Создан CandleBuffer для {symbol} {timeframe} (max_size={max_size})"
                )

            # Добавляем свечу в буфер
            await self._candle_buffers[symbol][timeframe].add_candle(candle)

            # ✅ P0-1 FIX: Сбрасываем stale флаг при получении свежей свечи
            # Проверяем, что свеча свежая (не старше 2 минут)
            candle_ts = getattr(candle, "timestamp", None)
            if candle_ts and (time.time() - float(candle_ts)) < 120:
                self.clear_candle_buffer_stale(symbol, timeframe)

            logger.debug(
                f"📊 DataRegistry: Добавлена свеча {symbol} {timeframe} "
                f"(timestamp={candle.timestamp}, price={candle.close:.2f})"
            )

    async def update_last_candle(
        self,
        symbol: str,
        timeframe: str,
        high: Optional[float] = None,
        low: Optional[float] = None,
        close: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> bool:
        """
        Обновить последнюю (формирующуюся) свечу для символа и таймфрейма.

        Используется когда свеча еще формируется (не завершилась).

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)
            high: Новая максимальная цена
            low: Новая минимальная цена
            close: Новая цена закрытия
            volume: Новый объем

        Returns:
            True если свеча обновлена, False если буфер не существует или пуст
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                return False

            if timeframe not in self._candle_buffers[symbol]:
                return False

            buffer = self._candle_buffers[symbol][timeframe]
            return await buffer.update_last_candle(high, low, close, volume)

    async def get_candles(self, symbol: str, timeframe: str) -> List[OHLCV]:
        """
        Получить все свечи для символа и таймфрейма.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)

        Returns:
            Список свечей (от старых к новым) или пустой список
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                return []

            if timeframe not in self._candle_buffers[symbol]:
                return []

            buffer = self._candle_buffers[symbol][timeframe]
            return await buffer.get_candles()

    async def get_last_candle(self, symbol: str, timeframe: str) -> Optional[OHLCV]:
        """
        Получить последнюю свечу для символа и таймфрейма.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)

        Returns:
            Последняя свеча или None
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                return None

            if timeframe not in self._candle_buffers[symbol]:
                return None

            buffer = self._candle_buffers[symbol][timeframe]
            return await buffer.get_last_candle()

    async def initialize_candles(
        self,
        symbol: str,
        timeframe: str,
        candles: List[OHLCV],
        max_size: Optional[int] = None,
    ) -> None:
        """
        Инициализировать буфер свечей для символа и таймфрейма.

        Используется при старте бота для загрузки исторических свечей.

        ✅ P0-1 FIX: Проверяем свежесть свечей и помечаем буфер как stale если данные устарели.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)
            candles: Список свечей для инициализации
            max_size: Максимальный размер буфера (по умолчанию: 200 для 1m, 100 для остальных)
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                self._candle_buffers[symbol] = {}

            # Определяем max_size если не передан
            if max_size is None:
                max_size = 200 if timeframe == "1m" else 100

            # Создаем новый буфер
            buffer = CandleBuffer(max_size=max_size)
            self._candle_buffers[symbol][timeframe] = buffer

            # Добавляем все свечи
            for candle in candles:
                await buffer.add_candle(candle)

            # ✅ P0-1 FIX: Проверяем свежесть последней свечи
            if candles:
                last_candle = candles[-1]
                last_ts = getattr(last_candle, "timestamp", None)
                if last_ts:
                    age_seconds = time.time() - float(last_ts)
                    # Если свеча старше 2 минут - помечаем как stale
                    if age_seconds > 120:
                        logger.warning(
                            f"⚠️ [STALE CANDLES] {symbol} {timeframe}: "
                            f"последняя свеча {age_seconds:.0f}s old "
                            f"(ts={last_ts}, close={getattr(last_candle, 'close', 'N/A')}). "
                            f"Буфер помечен как STALE - ожидаем свежие данные от WebSocket."
                        )
                        # Сохраняем метаданные о stale статусе
                        if symbol not in self._market_data:
                            self._market_data[symbol] = {}
                        self._market_data[symbol][f"_{timeframe}_stale"] = True
                        self._market_data[symbol][
                            f"_{timeframe}_stale_since"
                        ] = time.time()

            logger.info(
                f"📊 DataRegistry: Инициализирован буфер свечей для {symbol} {timeframe} "
                f"({len(candles)} свечей, max_size={max_size})"
            )

    def validate_ohlcv_data(
        self, symbol: str, candles: List[OHLCV]
    ) -> tuple[bool, List[str]]:
        """
        🔴 BUG #9 FIX (09.01.2026): Validate OHLCV data quality before use

        Проверяет качество данных свечей:
        - Отсутствие NaN/None значений
        - Положительные цены (close > 0, high >= close, etc.)
        - Отсутствие больших разрывов между свечами
        - Последовательность временных меток

        Args:
            symbol: Торговый символ
            candles: Список свечей (OHLCV объекты или dict)

        Returns:
            (is_valid, error_list) - tuple[bool, List[str]]
            is_valid=True если все проверки пройдены
            error_list содержит описание проблем если есть
        """
        errors = []

        if not candles:
            errors.append("No candles provided")
            return False, errors

        try:
            # Проверяем каждую свечу
            prev_close = None
            prev_timestamp = None

            for i, candle in enumerate(candles):
                try:
                    # Извлекаем значения (поддерживаем dict и OHLCV объекты)
                    if isinstance(candle, dict):
                        timestamp = candle.get("timestamp") or candle.get("time")
                        open_price = float(candle.get("o") or candle.get("open", 0))
                        high_price = float(candle.get("h") or candle.get("high", 0))
                        low_price = float(candle.get("l") or candle.get("low", 0))
                        close_price = float(candle.get("c") or candle.get("close", 0))
                        volume = float(candle.get("v") or candle.get("volume", 0))
                    else:
                        # Это OHLCV объект
                        timestamp = getattr(
                            candle, "timestamp", getattr(candle, "time", None)
                        )
                        open_price = float(getattr(candle, "open", 0))
                        high_price = float(getattr(candle, "high", 0))
                        low_price = float(getattr(candle, "low", 0))
                        close_price = float(getattr(candle, "close", 0))
                        volume = float(getattr(candle, "volume", 0))

                    # ✅ Check 1: No NaN/None/Zero prices
                    if not all(
                        [open_price > 0, high_price > 0, low_price > 0, close_price > 0]
                    ):
                        errors.append(
                            f"Candle {i}: Invalid prices - "
                            f"o={open_price}, h={high_price}, l={low_price}, c={close_price}"
                        )
                        continue

                    # ✅ Check 2: OHLC relationships
                    if not (
                        high_price >= close_price >= low_price >= open_price
                        or high_price >= open_price >= low_price >= close_price
                    ):
                        # More relaxed: high >= max(o,c) and low <= min(o,c)
                        if not (
                            high_price >= max(open_price, close_price)
                            and low_price <= min(open_price, close_price)
                        ):
                            errors.append(
                                f"Candle {i}: Invalid OHLC relationships - "
                                f"o={open_price}, h={high_price}, l={low_price}, c={close_price}"
                            )
                            continue

                    # ✅ Check 3: Price gaps (if we have previous close)
                    if prev_close is not None and prev_close > 0:
                        price_change_pct = (
                            abs((open_price - prev_close) / prev_close) * 100
                        )
                        # Flag large gaps (> 5%) but don't reject them
                        if price_change_pct > 5.0:
                            logger.warning(
                                f"{symbol} Candle {i}: Large price gap {price_change_pct:.2f}% "
                                f"(prev_close={prev_close}, open={open_price})"
                            )

                    # ✅ Check 4: Timestamp sequentiality
                    if prev_timestamp is not None:
                        if timestamp and prev_timestamp:
                            try:
                                ts_curr = (
                                    int(timestamp)
                                    if isinstance(timestamp, (int, float))
                                    else timestamp
                                )
                                ts_prev = (
                                    int(prev_timestamp)
                                    if isinstance(prev_timestamp, (int, float))
                                    else prev_timestamp
                                )
                                if ts_curr <= ts_prev:
                                    errors.append(
                                        f"Candle {i}: Non-sequential timestamps - "
                                        f"prev={prev_timestamp}, curr={timestamp}"
                                    )
                            except (TypeError, ValueError):
                                pass  # Can't compare timestamps, skip this check

                    prev_close = close_price
                    prev_timestamp = timestamp

                except (TypeError, ValueError, AttributeError) as e:
                    errors.append(f"Candle {i}: Data extraction error - {str(e)}")
                    continue

            # If we have errors, determine severity
            if errors:
                # Log the issues
                logger.warning(
                    f"🔴 Data quality issues for {symbol} ({len(errors)} errors):"
                )
                for err in errors[:5]:  # Show first 5 errors
                    logger.warning(f"   - {err}")
                if len(errors) > 5:
                    logger.warning(f"   ... and {len(errors) - 5} more errors")

                # Decide if we should use the data
                # If more than 20% of candles have errors, data is invalid
                error_rate = len(errors) / len(candles)
                if error_rate > 0.2:
                    return False, errors

            return True, errors

        except Exception as e:
            logger.error(
                f"❌ Error validating OHLCV data for {symbol}: {e}", exc_info=True
            )
            errors.append(f"Validation exception: {str(e)}")
            return False, errors

    def is_candle_buffer_stale(self, symbol: str, timeframe: str = "1m") -> bool:
        """
        ✅ P0-1 FIX: Проверяет, помечен ли буфер свечей как stale (устаревший).

        Используется при старте бота для блокировки сигналогенерации
        пока не придут свежие свечи от WebSocket.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (по умолчанию "1m")

        Returns:
            True если буфер stale (ожидаем свежие данные), False если данные свежие
        """
        md = self._market_data.get(symbol, {})
        stale_flag = md.get(f"_{timeframe}_stale", False)
        if stale_flag:
            # Проверяем, не истек ли таймаут ожидания (5 минут)
            stale_since = md.get(f"_{timeframe}_stale_since", 0)
            if time.time() - stale_since > 300:  # 5 минут
                logger.warning(
                    f"⏰ [STALE TIMEOUT] {symbol} {timeframe}: "
                    f"таймаут ожидания свежих свечей (5min). "
                    f"Снимаем stale флаг и разрешаем торговлю на свой страх и риск."
                )
                md[f"_{timeframe}_stale"] = False
                return False
        return stale_flag

    def clear_candle_buffer_stale(self, symbol: str, timeframe: str = "1m") -> None:
        """
        ✅ P0-1 FIX: Сбрасывает stale флаг при получении свежих свечей.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (по умолчанию "1m")
        """
        md = self._market_data.get(symbol, {})
        if md.get(f"_{timeframe}_stale", False):
            logger.info(
                f"✅ [STALE CLEARED] {symbol} {timeframe}: "
                f"получены свежие свечи, снимаем stale флаг."
            )
            md[f"_{timeframe}_stale"] = False
            md.pop(f"_{timeframe}_stale_since", None)

    def validate_price(
        self,
        symbol: str,
        price: float,
        reference_price: Optional[float] = None,
        price_history: Optional[List[float]] = None,
        max_std_deviations: float = 2.0,
        max_age_seconds: float = 5.0,
        price_timestamp: Optional[float] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        🔴 BUG #38 FIX (09.01.2026): Validate price data before use in calculations

        Проверяет качество ценовых данных:
        - Цена > 0
        - Цена не NaN/None
        - Цена в пределах разумного диапазона (not outlier)
        - Данные не устарели (timestamp свежий)

        Args:
            symbol: Торговый символ
            price: Проверяемая цена
            reference_price: Опорная цена для проверки отклонений
            price_history: История цен для расчета std deviation
            max_std_deviations: Макс отклонение в std deviations (по умолчанию 2.0)
            max_age_seconds: Макс возраст данных в секундах (по умолчанию 5.0)
            price_timestamp: Unix timestamp цены

        Returns:
            (is_valid, error_message) - tuple[bool, Optional[str]]
            is_valid=True если цена валидна, error_message=None
            is_valid=False если есть проблемы, error_message описывает проблему
        """
        try:
            # ✅ Check 1: Not None/NaN
            if price is None:
                return False, f"{symbol}: Price is None"

            try:
                price = float(price)
            except (TypeError, ValueError):
                return False, f"{symbol}: Cannot convert price to float: {price}"

            import math

            if math.isnan(price):
                return False, f"{symbol}: Price is NaN"

            # ✅ Check 2: Positive
            if price <= 0:
                return False, f"{symbol}: Price is not positive: {price}"

            # ✅ Check 3: Not stale (if timestamp provided)
            if price_timestamp is not None:
                try:
                    from datetime import datetime, timezone

                    current_time = datetime.now(timezone.utc).timestamp()
                    age_seconds = current_time - float(price_timestamp)
                    if age_seconds > max_age_seconds:
                        logger.warning(
                            f"⚠️ {symbol}: Price data is {age_seconds:.1f}s old "
                            f"(max: {max_age_seconds}s)"
                        )
                        # We warn but don't reject stale data
                except (TypeError, ValueError):
                    pass  # Can't check age, skip

            # ✅ Check 4: Within reasonable bounds (if reference price provided)
            if reference_price is not None and reference_price > 0:
                price_change_pct = (
                    abs((price - reference_price) / reference_price) * 100
                )

                # Simple check: price shouldn't deviate by more than 10% from reference
                if price_change_pct > 10.0:
                    logger.warning(
                        f"⚠️ {symbol}: Large deviation from reference "
                        f"({price_change_pct:.2f}%, price={price}, ref={reference_price})"
                    )

            # ✅ Check 5: Check against price history (std deviation outlier check)
            if price_history and len(price_history) >= 3:
                try:
                    import statistics

                    mean = statistics.mean(price_history)
                    if len(price_history) > 1:
                        stdev = statistics.stdev(price_history)
                    else:
                        stdev = 0.0

                    if stdev > 0:
                        z_score = abs((price - mean) / stdev)
                        if z_score > max_std_deviations:
                            logger.warning(
                                f"⚠️ {symbol}: Price is outlier "
                                f"(z-score={z_score:.2f}, price={price}, "
                                f"mean={mean:.2f}, stdev={stdev:.2f})"
                            )
                            # We warn but don't reject potential outliers
                except Exception:
                    pass  # Can't calculate stats, skip

            # All checks passed
            return True, None

        except Exception as e:
            logger.error(f"❌ Error validating price for {symbol}: {e}", exc_info=True)
            return False, f"Validation exception: {str(e)}"

    async def get_price_with_fallback(
        self,
        symbol: str,
        client: Optional[Any] = None,
    ) -> tuple[Optional[float], str]:
        """
        🔴 BUG #39 FIX (09.01.2026): Price recovery strategy with fallback chain

        Implements fallback chain to recover price when primary source unavailable:
        1. WebSocket current price (most recent)
        2. REST API last price (reliable)
        3. Order book mid price (real liquidity)
        4. Previous candle close (if recent, < 60s)
        5. Give up (return None)

        Args:
            symbol: Trading symbol
            client: OKX client for REST API calls

        Returns:
            (price, source) - tuple[Optional[float], str]
            price: The recovered price or None
            source: Where the price came from ("websocket", "rest_api", "order_book", "candle", "none")
        """
        try:
            # ✅ Strategy 1: WebSocket current price
            market_data = await self.get_market_data(symbol)
            if market_data:
                current_price = market_data.get("current_price") or market_data.get(
                    "price"
                )
                if current_price and current_price > 0:
                    is_valid, _ = self.validate_price(symbol, current_price)
                    if is_valid:
                        logger.debug(
                            f"✅ {symbol}: Got price from WebSocket: {current_price}"
                        )
                        return current_price, "websocket"

            # ✅ Strategy 2: REST API last price
            if client:
                try:
                    ticker_data = await client.get_ticker(symbol)
                    if ticker_data:
                        last_price = float(
                            ticker_data.get("last") or ticker_data.get("lastPx", 0)
                        )
                        if last_price > 0:
                            is_valid, _ = self.validate_price(symbol, last_price)
                            if is_valid:
                                logger.debug(
                                    f"✅ {symbol}: Got price from REST API: {last_price}"
                                )
                                return last_price, "rest_api"
                except Exception as e:
                    logger.warning(
                        f"⚠️ {symbol}: Failed to get price from REST API: {e}"
                    )

            # ✅ Strategy 3: Order book mid price
            if client:
                try:
                    book_data = await client.get_order_book(symbol, depth=1)
                    if book_data:
                        bids = book_data.get("bids", [])
                        asks = book_data.get("asks", [])
                        if bids and asks:
                            bid_price = float(bids[0][0]) if bids[0] else 0
                            ask_price = float(asks[0][0]) if asks[0] else 0
                            if bid_price > 0 and ask_price > 0:
                                mid_price = (bid_price + ask_price) / 2.0
                                is_valid, _ = self.validate_price(symbol, mid_price)
                                if is_valid:
                                    logger.debug(
                                        f"✅ {symbol}: Got price from order book: {mid_price}"
                                    )
                                    return mid_price, "order_book"
                except Exception as e:
                    logger.warning(
                        f"⚠️ {symbol}: Failed to get price from order book: {e}"
                    )

            # ✅ Strategy 4: Previous candle close (if recent)
            try:
                candles = await self.get_candles(symbol, "1m")
                if candles and len(candles) > 0:
                    # Get the last (most recent) candle
                    last_candle = candles[-1]
                    close_price = None

                    if isinstance(last_candle, dict):
                        close_price = float(
                            last_candle.get("c") or last_candle.get("close", 0)
                        )
                        timestamp = last_candle.get("time") or last_candle.get(
                            "timestamp"
                        )
                    else:
                        close_price = float(getattr(last_candle, "close", 0))
                        timestamp = getattr(last_candle, "timestamp", None)

                    if close_price and close_price > 0:
                        # Check if candle is recent (< 60 seconds old)
                        is_recent = True
                        if timestamp:
                            try:
                                from datetime import datetime, timezone

                                current_time = datetime.now(timezone.utc).timestamp()
                                age_seconds = current_time - float(timestamp)
                                is_recent = age_seconds < 60.0
                                if not is_recent:
                                    logger.warning(
                                        f"⚠️ {symbol}: Candle is {age_seconds:.1f}s old (> 60s)"
                                    )
                            except (TypeError, ValueError):
                                pass  # Can't check age

                        if is_recent:
                            is_valid, _ = self.validate_price(symbol, close_price)
                            if is_valid:
                                logger.debug(
                                    f"✅ {symbol}: Got price from candle close: {close_price}"
                                )
                                return close_price, "candle"
            except Exception as e:
                logger.warning(f"⚠️ {symbol}: Failed to get price from candle: {e}")

            # ✅ Strategy 5: Give up
            logger.error(f"❌ {symbol}: All price recovery strategies failed")
            return None, "none"

        except Exception as e:
            logger.error(f"❌ Error in price recovery for {symbol}: {e}", exc_info=True)
            return None, "none"
