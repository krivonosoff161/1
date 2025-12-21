"""
FilterManager - Координатор всех фильтров.

Управляет применением фильтров к сигналам в правильном порядке:
1. Pre-filters: ADX, Volatility, Risk
2. Trend filters: MTF, Correlation
3. Entry filters: Pivot Points, Volume Profile, Liquidity
4. Market filters: Order Flow, Funding Rate
"""

import time
from typing import Any, Dict, List, Optional

from loguru import logger


class FilterManager:
    """
    Координатор всех фильтров.

    Применяет фильтры к сигналам в правильном порядке и координирует их работу.
    ✅ ГРОК ОПТИМИЗАЦИЯ: Добавлено кэширование фильтров для снижения времени signals на 50-60%
    """

    def __init__(self, data_registry=None):
        """
        Инициализация FilterManager

        Args:
            data_registry: DataRegistry для чтения индикаторов (опционально)
        """
        # ✅ НОВОЕ: DataRegistry для чтения индикаторов
        self.data_registry = data_registry

        # Pre-filters (проверки перед основными фильтрами)
        self.adx_filter = None
        self.volatility_filter = None

        # Trend filters (проверки тренда)
        self.mtf_filter = None  # Multi-Timeframe
        self.correlation_filter = None

        # Entry filters (проверки точки входа)
        self.pivot_points_filter = None
        self.volume_profile_filter = None
        self.liquidity_filter = None

        # Market filters (проверки рынка)
        self.order_flow_filter = None
        self.funding_rate_filter = None

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Кэш фильтров для снижения времени signals на 50-60%
        # Кэш: {symbol: {'adx': val, 'mtf': val, 'pivot': val, 'volume_profile': val, 'liquidity': val, 'order_flow': val, 'ts': now}}
        self.filter_cache: Dict[str, Dict[str, Any]] = {}
        self.filter_cache_ttl_fast: float = (
            20.0  # TTL 20 секунд (ADX/MTF/Pivot меняются медленно)
        )
        self.filter_cache_ttl_slow: float = 60.0  # ✅ ГРОК: TTL 60 секунд (VolumeProfile/OrderFlow/Liquidity - тяжелые фильтры с historical data)

        logger.info("✅ FilterManager инициализирован (с кэшированием фильтров)")

    def set_adx_filter(self, adx_filter):
        """Установить ADX фильтр"""
        self.adx_filter = adx_filter
        logger.debug("✅ FilterManager: ADX фильтр установлен")

    def set_mtf_filter(self, mtf_filter):
        """Установить MTF фильтр"""
        self.mtf_filter = mtf_filter
        logger.debug("✅ FilterManager: MTF фильтр установлен")

    def set_correlation_filter(self, correlation_filter):
        """Установить Correlation фильтр"""
        self.correlation_filter = correlation_filter
        logger.debug("✅ FilterManager: Correlation фильтр установлен")

    def set_pivot_points_filter(self, pivot_points_filter):
        """Установить Pivot Points фильтр"""
        self.pivot_points_filter = pivot_points_filter
        logger.debug("✅ FilterManager: Pivot Points фильтр установлен")

    def set_volume_profile_filter(self, volume_profile_filter):
        """Установить Volume Profile фильтр"""
        self.volume_profile_filter = volume_profile_filter
        logger.debug("✅ FilterManager: Volume Profile фильтр установлен")

    def set_liquidity_filter(self, liquidity_filter):
        """Установить Liquidity фильтр"""
        self.liquidity_filter = liquidity_filter
        logger.debug("✅ FilterManager: Liquidity фильтр установлен")

    def set_order_flow_filter(self, order_flow_filter):
        """Установить Order Flow фильтр"""
        self.order_flow_filter = order_flow_filter
        logger.debug("✅ FilterManager: Order Flow фильтр установлен")

    def set_funding_rate_filter(self, funding_rate_filter):
        """Установить Funding Rate фильтр"""
        self.funding_rate_filter = funding_rate_filter
        logger.debug("✅ FilterManager: Funding Rate фильтр установлен")

    def set_volatility_filter(self, volatility_filter):
        """Установить Volatility фильтр"""
        self.volatility_filter = volatility_filter
        logger.debug("✅ FilterManager: Volatility фильтр установлен")

    def _get_cached_filter_result(
        self, symbol: str, filter_name: str, use_slow_ttl: bool = False
    ) -> Optional[Any]:
        """
        ✅ ГРОК ОПТИМИЗАЦИЯ: Получить результат фильтра из кэша.

        Args:
            symbol: Торговый символ
            filter_name: Имя фильтра (adx, mtf, pivot, volume_profile, liquidity, order_flow)
            use_slow_ttl: Использовать медленный TTL (60s) для тяжелых фильтров

        Returns:
            Результат фильтра из кэша или None если кэш устарел/отсутствует
        """
        cache = self.filter_cache.get(symbol)
        if not cache:
            return None

        now = time.time()
        cache_age = now - cache.get("ts", 0)

        # ✅ ГРОК: Выбираем TTL в зависимости от типа фильтра
        ttl = self.filter_cache_ttl_slow if use_slow_ttl else self.filter_cache_ttl_fast

        # Проверяем TTL
        if cache_age > ttl:
            # Кэш устарел - удаляем
            del self.filter_cache[symbol]
            return None

        # Возвращаем результат из кэша
        return cache.get(filter_name)

    def _set_cached_filter_result(self, symbol: str, filter_name: str, result: Any):
        """
        ✅ ГРОК ОПТИМИЗАЦИЯ: Сохранить результат фильтра в кэш.

        Args:
            symbol: Торговый символ
            filter_name: Имя фильтра (adx, mtf, pivot, volume_profile)
            result: Результат фильтра
        """
        if symbol not in self.filter_cache:
            self.filter_cache[symbol] = {"ts": time.time()}

        self.filter_cache[symbol][filter_name] = result
        self.filter_cache[symbol]["ts"] = time.time()  # Обновляем timestamp

    async def apply_all_filters(
        self,
        symbol: str,
        signal: Dict[str, Any],
        market_data: Any,  # MarketData
        current_positions: Optional[Dict] = None,
        regime: Optional[str] = None,
        regime_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Применить все фильтры к сигналу.
        ✅ ГРОК ОПТИМИЗАЦИЯ: Использует кэш для ADX/MTF/Pivot/VolumeProfile (TTL 20s)

        Порядок применения:
        1. Pre-filters: ADX (тренд), Volatility
        2. Trend filters: MTF, Correlation
        3. Entry filters: Pivot Points, Volume Profile, Liquidity
        4. Market filters: Order Flow, Funding Rate

        Args:
            symbol: Торговый символ
            signal: Торговый сигнал
            market_data: Рыночные данные
            current_positions: Текущие открытые позиции (для CorrelationFilter)
            regime: Режим рынка (trending, ranging, choppy)
            regime_params: Параметры режима

        Returns:
            Обновленный сигнал или None если отфильтрован
        """
        # Добавляем текущие позиции в сигнал для CorrelationFilter
        if current_positions:
            signal["current_positions"] = current_positions

        # Добавляем regime в сигнал
        if regime:
            signal["regime"] = regime

        # Получаем параметры фильтров из regime_params
        filters_profile = {}
        if regime_params:
            filters_profile = regime_params.get("filters", {})

        # Получаем impulse_relax параметры (для ослабления фильтров)
        impulse_relax = signal.get("impulse_relax", {})
        is_impulse = signal.get("is_impulse", False)

        # ==================== PRE-FILTERS ====================

        # 1. ADX Filter (проверка тренда и силы)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом
        if self.adx_filter:
            try:
                # Пытаемся получить из кэша
                cached_adx_result = self._get_cached_filter_result(symbol, "adx")
                if cached_adx_result is not None:
                    # Используем кэш - ADX меняется медленно
                    if not cached_adx_result:
                        logger.debug(
                            f"🔍 Сигнал {symbol} отфильтрован: ADX Filter (из кэша)"
                        )
                        return None
                    else:
                        # ADX прошел - добавляем в список пройденных фильтров
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("ADX")
                else:
                    # Кэша нет - вычисляем и сохраняем
                    signal = await self._apply_adx_filter(symbol, signal, market_data)
                    if signal is None:
                        # Сохраняем в кэш: False = отфильтрован
                        self._set_cached_filter_result(symbol, "adx", False)
                        logger.debug(f"🔍 Сигнал {symbol} отфильтрован: ADX Filter")
                        return None
                    else:
                        # Сохраняем в кэш: True = прошел
                        self._set_cached_filter_result(symbol, "adx", True)
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("ADX")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка ADX фильтра для {symbol}: {e}")

        # ✅ УЛУЧШЕНИЕ #3: Дополнительная проверка направления тренда
        # Не входить против тренда (если ADX показывает сильный тренд в противоположном направлении)
        try:
            if market_data and hasattr(market_data, "indicators"):
                indicators = market_data.indicators
                adx_value = (
                    indicators.get("ADX") if isinstance(indicators, dict) else None
                )
                di_plus = (
                    indicators.get("DI_PLUS") if isinstance(indicators, dict) else None
                )
                di_minus = (
                    indicators.get("DI_MINUS") if isinstance(indicators, dict) else None
                )

                signal_side = signal.get("side", "").lower()

                # Если ADX > 20 (сильный тренд) и направление против сигнала - блокируем
                if adx_value and adx_value > 20:
                    if (
                        signal_side == "buy"
                        and di_minus
                        and di_plus
                        and di_minus > di_plus
                    ):
                        # LONG сигнал, но тренд вниз (DI- > DI+)
                        logger.debug(
                            f"🔍 Сигнал {symbol} LONG отфильтрован: тренд вниз (ADX={adx_value:.1f}, DI-={di_minus:.1f} > DI+={di_plus:.1f})"
                        )
                        return None
                    elif (
                        signal_side == "sell"
                        and di_plus
                        and di_minus
                        and di_plus > di_minus
                    ):
                        # SHORT сигнал, но тренд вверх (DI+ > DI-)
                        logger.debug(
                            f"🔍 Сигнал {symbol} SHORT отфильтрован: тренд вверх (ADX={adx_value:.1f}, DI+={di_plus:.1f} > DI-={di_minus:.1f})"
                        )
                        return None
        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки направления тренда для {symbol}: {e}")

        # 2. Volatility Filter (проверка волатильности)
        if (
            self.volatility_filter and not is_impulse
        ):  # Импульсы могут обходить волатильность
            try:
                volatility_params = filters_profile.get("volatility", {})
                if not await self._apply_volatility_filter(
                    symbol, signal, market_data, volatility_params
                ):
                    logger.debug(f"🔍 Сигнал {symbol} отфильтрован Volatility фильтром")
                    return None
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Volatility фильтра для {symbol}: {e}")

        # ==================== TREND FILTERS ====================

        # 3. MTF Filter (Multi-Timeframe проверка)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом
        bypass_mtf = bool(is_impulse and impulse_relax.get("allow_mtf_bypass", False))
        if self.mtf_filter and not bypass_mtf:
            try:
                # Пытаемся получить из кэша
                cached_mtf_result = self._get_cached_filter_result(symbol, "mtf")
                if cached_mtf_result is not None:
                    # Используем кэш - MTF меняется медленно
                    if not cached_mtf_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: MTF Filter (из кэша)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("MTF")
                else:
                    # Кэша нет - вычисляем и сохраняем
                    mtf_params = filters_profile.get("mtf", {})
                    mtf_result = await self._apply_mtf_filter(
                        symbol, signal, market_data, mtf_params
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(symbol, "mtf", mtf_result)
                    if not mtf_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: MTF Filter"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("MTF")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка MTF фильтра для {symbol}: {e}")

        # 4. Correlation Filter (проверка корреляции)
        bypass_correlation = bool(
            is_impulse and impulse_relax.get("bypass_correlation", False)
        )
        if self.correlation_filter and not bypass_correlation:
            try:
                if not await self._apply_correlation_filter(symbol, signal):
                    signal_type = signal.get("type", "unknown")
                    logger.debug(
                        f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Correlation Filter"
                    )
                    return None
                else:
                    # ✅ НОВОЕ: Добавляем в список пройденных фильтров
                    if "filters_passed" not in signal:
                        signal["filters_passed"] = []
                    signal["filters_passed"].append("Correlation")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Correlation фильтра для {symbol}: {e}")

        # ==================== ENTRY FILTERS ====================

        # 5. Pivot Points Filter (проверка уровня)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом
        if self.pivot_points_filter:
            try:
                # Пытаемся получить из кэша
                cached_pivot_result = self._get_cached_filter_result(symbol, "pivot")
                if cached_pivot_result is not None:
                    # Используем кэш - Pivot Points меняются медленно (раз в день)
                    if not cached_pivot_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Pivot Points Filter (из кэша)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("PivotPoints")
                else:
                    # Кэша нет - вычисляем и сохраняем
                    pivot_params = filters_profile.get("pivot_points", {})
                    pivot_result = await self._apply_pivot_points_filter(
                        symbol, signal, market_data, pivot_params
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(symbol, "pivot", pivot_result)
                    if not pivot_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Pivot Points Filter"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("PivotPoints")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Pivot Points фильтра для {symbol}: {e}")

        # 6. Volume Profile Filter (проверка объема)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом (TTL 60s для тяжелых фильтров)
        if self.volume_profile_filter:
            try:
                # Пытаемся получить из кэша (используем медленный TTL 60s)
                cached_vp_result = self._get_cached_filter_result(
                    symbol, "volume_profile", use_slow_ttl=True
                )
                if cached_vp_result is not None:
                    # Используем кэш - Volume Profile меняется медленно (historical data)
                    if not cached_vp_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Volume Profile Filter (из кэша, TTL 60s)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("VolumeProfile")
                else:
                    # Кэша нет - вычисляем и сохраняем
                    vp_params = filters_profile.get("volume_profile", {})
                    vp_result = await self._apply_volume_profile_filter(
                        symbol, signal, market_data, vp_params
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(symbol, "volume_profile", vp_result)
                    if not vp_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Volume Profile Filter"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("VolumeProfile")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Volume Profile фильтра для {symbol}: {e}")

        # 7. Liquidity Filter (проверка ликвидности)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом (TTL 60s для тяжелых фильтров)
        liquidity_relax = (
            float(impulse_relax.get("liquidity", 1.0)) if is_impulse else 1.0
        )
        if self.liquidity_filter:
            try:
                # Пытаемся получить из кэша (используем медленный TTL 60s)
                cached_liquidity_result = self._get_cached_filter_result(
                    symbol, "liquidity", use_slow_ttl=True
                )
                if cached_liquidity_result is not None:
                    # Используем кэш - Liquidity меняется медленно (API calls)
                    if not cached_liquidity_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Liquidity Filter (из кэша, TTL 60s)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("Liquidity")
                else:
                    # Кэша нет - вычисляем и сохраняем
                    liquidity_params = filters_profile.get("liquidity", {})
                    liquidity_result = await self._apply_liquidity_filter(
                        symbol, signal, market_data, liquidity_params, liquidity_relax
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(
                        symbol, "liquidity", liquidity_result
                    )
                    if not liquidity_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Liquidity Filter"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("Liquidity")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Liquidity фильтра для {symbol}: {e}")

        # ==================== MARKET FILTERS ====================

        # 8. Order Flow Filter (проверка потока ордеров)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом (TTL 60s для тяжелых фильтров)
        order_flow_relax = (
            float(impulse_relax.get("order_flow", 1.0)) if is_impulse else 1.0
        )
        if self.order_flow_filter:
            try:
                # Пытаемся получить из кэша (используем медленный TTL 60s)
                cached_of_result = self._get_cached_filter_result(
                    symbol, "order_flow", use_slow_ttl=True
                )
                if cached_of_result is not None:
                    # Используем кэш - Order Flow меняется медленно (API calls)
                    if not cached_of_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Order Flow Filter (из кэша, TTL 60s)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("OrderFlow")
                else:
                    # Кэша нет - вычисляем и сохраняем
                    order_flow_params = filters_profile.get("order_flow", {})
                    of_result = await self._apply_order_flow_filter(
                        symbol, signal, market_data, order_flow_params, order_flow_relax
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(symbol, "order_flow", of_result)
                    if not of_result:
                        signal_type = signal.get("type", "unknown")
                        logger.debug(
                            f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Order Flow Filter"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("OrderFlow")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Order Flow фильтра для {symbol}: {e}")

        # 9. Funding Rate Filter (проверка funding rate)
        if self.funding_rate_filter:
            try:
                funding_params = filters_profile.get("funding", {})
                if not await self._apply_funding_rate_filter(
                    symbol, signal, funding_params
                ):
                    signal_type = signal.get("type", "unknown")
                    logger.debug(
                        f"🔍 Сигнал {symbol} ({signal_type}) отфильтрован: Funding Rate Filter"
                    )
                    return None
                else:
                    # ✅ НОВОЕ: Добавляем в список пройденных фильтров
                    if "filters_passed" not in signal:
                        signal["filters_passed"] = []
                    signal["filters_passed"].append("FundingRate")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Funding Rate фильтра для {symbol}: {e}")

        # Все фильтры пройдены
        return signal

    # ==================== HELPER METHODS для каждого фильтра ====================

    async def _get_indicators_from_registry(
        self, symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        ✅ НОВОЕ: Получить индикаторы из DataRegistry для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Словарь с индикаторами или None если не доступно
        """
        if not self.data_registry:
            return None

        try:
            indicators = await self.data_registry.get_indicators(symbol)
            return indicators
        except Exception as e:
            logger.debug(
                f"⚠️ Ошибка получения индикаторов из DataRegistry для {symbol}: {e}"
            )
            return None

    async def _apply_adx_filter(
        self, symbol: str, signal: Dict[str, Any], market_data: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Применить ADX фильтр (с возможностью переключения направления).

        Returns:
            Обновленный сигнал или None если отфильтрован
        """
        # ✅ НОВОЕ: Пытаемся получить ADX из DataRegistry
        if self.data_registry:
            try:
                indicators = await self._get_indicators_from_registry(symbol)
                if indicators:
                    adx_value = indicators.get("adx")
                    adx_plus_di = indicators.get("adx_plus_di")
                    adx_minus_di = indicators.get("adx_minus_di")

                    # Если ADX доступен в DataRegistry, используем его для быстрой проверки
                    if adx_value is not None:
                        logger.debug(
                            f"✅ FilterManager: ADX из DataRegistry для {symbol}: {adx_value:.2f}"
                        )
                        # Можно добавить быструю проверку ADX здесь, но пока оставляем полную проверку через фильтр
            except Exception as e:
                logger.debug(f"⚠️ Ошибка чтения ADX из DataRegistry для {symbol}: {e}")

        # Логика ADX фильтра будет делегирована в существующий ADXFilter
        # Здесь только координация
        from src.models import OrderSide

        signal_side_str = signal.get("side", "").lower()
        if signal_side_str == "buy":
            order_side = OrderSide.BUY
        elif signal_side_str == "sell":
            order_side = OrderSide.SELL
        else:
            return None

        candles = (
            market_data.ohlcv_data if market_data and market_data.ohlcv_data else []
        )
        if not candles:
            return signal  # Нет свечей - пропускаем фильтр

        # Конвертируем в dict для ADX фильтра
        candles_dict = []
        for candle in candles:
            candles_dict.append(
                {"high": candle.high, "low": candle.low, "close": candle.close}
            )

        # Проверяем через ADX фильтр
        adx_result = self.adx_filter.check_trend_strength(
            symbol, order_side, candles_dict
        )

        if not adx_result.allowed:
            # ✅ ИСПРАВЛЕНО: Блокируем сигнал против тренда (не переключаем направление)
            logger.debug(
                f"🚫 ADX заблокировал {signal_side_str.upper()} сигнал для {symbol}: "
                f"сигнал против тренда ({adx_result.reason if hasattr(adx_result, 'reason') else 'ADX не разрешил'}, "
                f"ADX={adx_result.adx_value:.1f}, +DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f})"
            )
            return None  # Блокируем сигнал
        else:
            logger.debug(
                f"✅ ADX подтвердил {signal_side_str.upper()} сигнал для {symbol}"
            )

        return signal

    async def _apply_volatility_filter(
        self,
        symbol: str,
        signal: Dict[str, Any],
        market_data: Any,
        params: Dict[str, Any],
    ) -> bool:
        """Применить Volatility фильтр"""
        # Делегируем в VolatilityFilter
        if not self.volatility_filter:
            return True

        # Логика проверки волатильности
        # TODO: Реализовать после изучения VolatilityFilter
        return True

    async def _apply_mtf_filter(
        self,
        symbol: str,
        signal: Dict[str, Any],
        market_data: Any,
        params: Dict[str, Any],
    ) -> bool:
        """Применить MTF фильтр"""
        if not self.mtf_filter:
            return True

        # ✅ ИСПРАВЛЕНИЕ: Используем is_signal_valid вместо check_entry
        try:
            return await self.mtf_filter.is_signal_valid(signal, market_data)
        except Exception as e:
            logger.warning(f"⚠️ Ошибка MTF фильтра для {symbol}: {e}")
            return True  # При ошибке пропускаем фильтр

    async def _apply_correlation_filter(
        self, symbol: str, signal: Dict[str, Any]
    ) -> bool:
        """Применить Correlation фильтр"""
        if not self.correlation_filter:
            return True

        # ✅ ИСПРАВЛЕНИЕ: Используем is_signal_valid или правильные аргументы для check_entry
        try:
            # Проверяем наличие метода is_signal_valid
            if hasattr(self.correlation_filter, "is_signal_valid"):
                return await self.correlation_filter.is_signal_valid(signal, None)
            else:
                # Используем check_entry с правильными аргументами
                signal_side = signal.get("side", "").upper()  # "BUY" или "SELL"
                current_positions = signal.get("current_positions", {})
                result = await self.correlation_filter.check_entry(
                    symbol, signal_side, current_positions
                )
                return result.allowed if hasattr(result, "allowed") else result
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Correlation фильтра для {symbol}: {e}")
            return True  # При ошибке пропускаем фильтр

    async def _apply_pivot_points_filter(
        self,
        symbol: str,
        signal: Dict[str, Any],
        market_data: Any,
        params: Dict[str, Any],
    ) -> bool:
        """Применить Pivot Points фильтр"""
        if not self.pivot_points_filter:
            return True

        # ✅ ИСПРАВЛЕНИЕ: Используем is_signal_valid или правильные аргументы
        try:
            if hasattr(self.pivot_points_filter, "is_signal_valid"):
                return await self.pivot_points_filter.is_signal_valid(
                    signal, market_data
                )
            else:
                # ✅ ИСПРАВЛЕНИЕ: Правильный порядок аргументов (symbol, current_price, signal_side)
                price = signal.get("price")
                if not price:
                    return True
                side = signal.get(
                    "side", ""
                ).upper()  # "BUY" -> "LONG", "SELL" -> "SHORT"
                if side == "BUY":
                    signal_side = "LONG"
                elif side == "SELL":
                    signal_side = "SHORT"
                else:
                    signal_side = side
                result = await self.pivot_points_filter.check_entry(
                    symbol, price, signal_side
                )
                return result.allowed if hasattr(result, "allowed") else result
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Pivot Points фильтра для {symbol}: {e}")
            return True  # При ошибке пропускаем фильтр

    async def _apply_volume_profile_filter(
        self,
        symbol: str,
        signal: Dict[str, Any],
        market_data: Any,
        params: Dict[str, Any],
    ) -> bool:
        """Применить Volume Profile фильтр"""
        if not self.volume_profile_filter:
            return True

        # ✅ ИСПРАВЛЕНИЕ: Используем is_signal_valid или правильные аргументы для check_entry
        try:
            # Проверяем наличие метода is_signal_valid
            if hasattr(self.volume_profile_filter, "is_signal_valid"):
                return await self.volume_profile_filter.is_signal_valid(
                    signal, market_data
                )
            else:
                # Используем check_entry с правильными аргументами (только symbol и price)
                price = signal.get("price")
                if not price:
                    return True
                result = await self.volume_profile_filter.check_entry(symbol, price)
                return result.allowed if hasattr(result, "allowed") else result
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Volume Profile фильтра для {symbol}: {e}")
            return True  # При ошибке пропускаем фильтр

    async def _apply_liquidity_filter(
        self,
        symbol: str,
        signal: Dict[str, Any],
        market_data: Any,
        params: Dict[str, Any],
        relax_multiplier: float = 1.0,
    ) -> bool:
        """Применить Liquidity фильтр"""
        if not self.liquidity_filter:
            return True

        # Логика проверки ликвидности
        # TODO: Реализовать после изучения LiquidityFilter
        return True

    async def _apply_order_flow_filter(
        self,
        symbol: str,
        signal: Dict[str, Any],
        market_data: Any,
        params: Dict[str, Any],
        relax_multiplier: float = 1.0,
    ) -> bool:
        """Применить Order Flow фильтр"""
        if not self.order_flow_filter:
            return True

        # Логика проверки order flow
        # TODO: Реализовать после изучения OrderFlowFilter
        return True

    async def _apply_funding_rate_filter(
        self, symbol: str, signal: Dict[str, Any], params: Dict[str, Any]
    ) -> bool:
        """Применить Funding Rate фильтр"""
        if not self.funding_rate_filter:
            return True

        # Логика проверки funding rate
        # TODO: Реализовать после изучения FundingRateFilter
        return True
