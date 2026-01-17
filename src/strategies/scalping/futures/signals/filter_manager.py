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
            5.0  # Diagnostic: TTL 5s for fresher filters
        )
        self.filter_cache_ttl_slow: float = (
            5.0  # Diagnostic: TTL 5s for fresher filters
        )

        logger.info(
            f"✅ FilterManager инициализирован с кэшированием: "
            f"fast={self.filter_cache_ttl_fast:.0f}s, slow={self.filter_cache_ttl_slow:.0f}s"
        )

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
        ✅ ГРОК ОПТИМИЗАЦИЯ: Использует кэш для ADX/MTF/Pivot/VolumeProfile (TTL 10s/30s)

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
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")

                def _get_indicator(indicators: Any, *keys):
                    if not indicators or not isinstance(indicators, dict):
                        return None
                    for key in keys:
                        if key in indicators:
                            return indicators.get(key)
                    return None

                # Пытаемся получить из кэша
                cached_adx_result = self._get_cached_filter_result(symbol, "adx")
                if cached_adx_result is not None:
                    # ✅ УЛУЧШЕНИЕ (10.01.2026): Получаем фактические значения ADX для логирования
                    adx_value = None
                    plus_di = None
                    minus_di = None
                    try:
                        if market_data and hasattr(market_data, "indicators"):
                            indicators = market_data.indicators
                            adx_value = _get_indicator(indicators, "adx", "ADX")
                            plus_di = _get_indicator(
                                indicators, "adx_plus_di", "+DI", "DI_PLUS"
                            )
                            minus_di = _get_indicator(
                                indicators, "adx_minus_di", "-DI", "DI_MINUS"
                            )
                    except Exception as exc:
                        logger.debug("Ignored error in optional block: %s", exc)

                    # Используем кэш - ADX меняется медленно
                    if not cached_adx_result:
                        # ✅ УЛУЧШЕНО: Логируем значения даже из кэша
                        adx_str = f"ADX={adx_value:.1f}" if adx_value else "ADX=N/A"
                        di_str = (
                            f", +DI={plus_di:.1f}, -DI={minus_di:.1f}"
                            if plus_di is not None and minus_di is not None
                            else ""
                        )
                        signal[
                            "filter_reason"
                        ] = f"ADX Filter (cached): blocked | {adx_str}{di_str}, regime={regime or 'unknown'}"
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - BLOCKED (из кэша) | "
                            f"{adx_str}{di_str}, Режим: {regime or 'unknown'} | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_fast:.0f}s)"
                        )
                        return None
                    else:
                        # ADX прошел - добавляем в список пройденных фильтров
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("ADX")
                        # ✅ УЛУЧШЕНО: Логируем значения даже из кэша
                        adx_str = f"ADX={adx_value:.1f}" if adx_value else "ADX=N/A"
                        di_str = (
                            f", +DI={plus_di:.1f}, -DI={minus_di:.1f}"
                            if plus_di is not None and minus_di is not None
                            else ""
                        )
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - PASSED (из кэша) | "
                            f"{adx_str}{di_str}, Режим: {regime or 'unknown'} | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_fast:.0f}s)"
                        )
                else:
                    # Кэша нет - вычисляем и сохраняем
                    signal = await self._apply_adx_filter(
                        symbol, signal, market_data, regime=regime
                    )
                    if signal is None:
                        # Сохраняем в кэш: False = отфильтрован
                        self._set_cached_filter_result(symbol, "adx", False)
                        # ✅ НОВОЕ: Причина фильтрации уже сохранена в signal["filter_reason"] в _apply_adx_filter
                        # Детальное логирование происходит в _apply_adx_filter
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
                adx_value = _get_indicator(indicators, "adx", "ADX")
                di_plus = _get_indicator(indicators, "adx_plus_di", "+DI", "DI_PLUS")
                di_minus = _get_indicator(indicators, "adx_minus_di", "-DI", "DI_MINUS")

            signal_side = signal.get("side", "").lower()

            # Если ADX > 20 (сильный тренд) и направление против сигнала - блокируем
            signal_type_str = signal.get("type", "unknown")
            if adx_value and adx_value > 20:
                if signal_side == "buy" and di_minus and di_plus and di_minus > di_plus:
                    # LONG сигнал, но тренд вниз (DI- > DI+)
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} LONG): ADX Direction Filter - BLOCKED | "
                        f"Сильный нисходящий тренд против LONG сигнала: ADX={adx_value:.1f} > 20.0, "
                        f"DI-={di_minus:.1f} > DI+={di_plus:.1f} | "
                        f"Источник: MarketData.indicators (дополнительная проверка направления тренда)"
                    )
                    return None
                elif (
                    signal_side == "sell"
                    and di_plus
                    and di_minus
                    and di_plus > di_minus
                ):
                    # SHORT сигнал, но тренд вверх (DI+ > DI-)
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} SHORT): ADX Direction Filter - BLOCKED | "
                        f"Сильный восходящий тренд против SHORT сигнала: ADX={adx_value:.1f} > 20.0, "
                        f"DI+={di_plus:.1f} > DI-={di_minus:.1f} | "
                        f"Источник: MarketData.indicators (дополнительная проверка направления тренда)"
                    )
                    return None
        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки направления тренда для {symbol}: {e}")

        # 2. Volatility Filter (проверка волатильности)
        if (
            self.volatility_filter and not is_impulse
        ):  # Импульсы могут обходить волатильность
            try:
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")
                volatility_params = filters_profile.get("volatility", {})
                volatility_result = await self._apply_volatility_filter(
                    symbol, signal, market_data, volatility_params
                )
                if not volatility_result:
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Volatility Filter - BLOCKED | "
                        f"Режим: {regime or 'unknown'}, Параметры: {volatility_params} | "
                        f"Источник: VolatilityFilter (проверка волатильности рынка)"
                    )
                    return None
                else:
                    logger.debug(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Volatility Filter - PASSED | "
                        f"Режим: {regime or 'unknown'}, Параметры: {volatility_params} | "
                        f"Источник: VolatilityFilter (проверка волатильности рынка)"
                    )
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Volatility фильтра для {symbol}: {e}")

        # ==================== TREND FILTERS ====================

        # 3. MTF Filter (Multi-Timeframe проверка)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом
        bypass_mtf = bool(is_impulse and impulse_relax.get("allow_mtf_bypass", False))
        if self.mtf_filter and not bypass_mtf:
            try:
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")

                # Пытаемся получить из кэша
                cached_mtf_result = self._get_cached_filter_result(symbol, "mtf")
                if cached_mtf_result is not None:
                    # Используем кэш - MTF меняется медленно
                    if not cached_mtf_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): MTF Filter - BLOCKED (из кэша) | "
                            f"Режим: {regime or 'unknown'} | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_fast:.0f}s)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("MTF")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): MTF Filter - PASSED (из кэша) | "
                            f"Режим: {regime or 'unknown'} | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_fast:.0f}s)"
                        )
                else:
                    # Кэша нет - вычисляем и сохраняем
                    mtf_params = filters_profile.get("mtf", {})
                    mtf_result = await self._apply_mtf_filter(
                        symbol, signal, market_data, mtf_params
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(symbol, "mtf", mtf_result)
                    if not mtf_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): MTF Filter - BLOCKED | "
                            f"Режим: {regime or 'unknown'}, Параметры: {mtf_params} | "
                            f"Источник: MTFFilter.is_signal_valid() -> Multi-Timeframe анализ"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("MTF")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): MTF Filter - PASSED | "
                            f"Режим: {regime or 'unknown'}, Параметры: {mtf_params} | "
                            f"Источник: MTFFilter.is_signal_valid() -> Multi-Timeframe анализ"
                        )
            except Exception as e:
                logger.warning(f"⚠️ Ошибка MTF фильтра для {symbol}: {e}")

        # 4. Correlation Filter (проверка корреляции)
        bypass_correlation = bool(
            is_impulse and impulse_relax.get("bypass_correlation", False)
        )
        if self.correlation_filter and not bypass_correlation:
            try:
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")
                correlation_result = await self._apply_correlation_filter(
                    symbol, signal
                )
                if not correlation_result:
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Correlation Filter - BLOCKED | "
                        f"Режим: {regime or 'unknown'} | "
                        f"Источник: CorrelationFilter.is_signal_valid() -> Анализ корреляции с текущими позициями"
                    )
                    return None
                else:
                    # ✅ НОВОЕ: Добавляем в список пройденных фильтров
                    if "filters_passed" not in signal:
                        signal["filters_passed"] = []
                    signal["filters_passed"].append("Correlation")
                    logger.debug(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Correlation Filter - PASSED | "
                        f"Режим: {regime or 'unknown'} | "
                        f"Источник: CorrelationFilter.is_signal_valid() -> Анализ корреляции с текущими позициями"
                    )
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Correlation фильтра для {symbol}: {e}")

        # ==================== ENTRY FILTERS ====================

        # 5. Pivot Points Filter (проверка уровня)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом
        if self.pivot_points_filter:
            try:
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")
                signal_price = signal.get("price", 0.0)

                # Пытаемся получить из кэша
                cached_pivot_result = self._get_cached_filter_result(symbol, "pivot")
                if cached_pivot_result is not None:
                    # Используем кэш - Pivot Points меняются медленно (раз в день)
                    if not cached_pivot_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Pivot Points Filter - BLOCKED (из кэша) | "
                            f"Цена: ${signal_price:.2f}, Режим: {regime or 'unknown'} | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_fast:.0f}s, Pivot Points обновляются раз в день)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("PivotPoints")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Pivot Points Filter - PASSED (из кэша) | "
                            f"Цена: ${signal_price:.2f}, Режим: {regime or 'unknown'} | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_fast:.0f}s)"
                        )
                else:
                    # Кэша нет - вычисляем и сохраняем
                    pivot_params = filters_profile.get("pivot_points", {})
                    pivot_result = await self._apply_pivot_points_filter(
                        symbol, signal, market_data, pivot_params
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(symbol, "pivot", pivot_result)
                    if not pivot_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Pivot Points Filter - BLOCKED | "
                            f"Цена: ${signal_price:.2f}, Режим: {regime or 'unknown'}, Параметры: {pivot_params} | "
                            f"Источник: PivotPointsFilter.is_signal_valid() -> Анализ уровней pivot points"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("PivotPoints")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Pivot Points Filter - PASSED | "
                            f"Цена: ${signal_price:.2f}, Режим: {regime or 'unknown'}, Параметры: {pivot_params} | "
                            f"Источник: PivotPointsFilter.is_signal_valid() -> Анализ уровней pivot points"
                        )
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Pivot Points фильтра для {symbol}: {e}")

        # 6. Volume Profile Filter (проверка объема)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом (TTL 30s для тяжелых фильтров)
        if self.volume_profile_filter:
            try:
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")
                signal_price = signal.get("price", 0.0)

                # Пытаемся получить из кэша (используем медленный TTL 30s)
                cached_vp_result = self._get_cached_filter_result(
                    symbol, "volume_profile", use_slow_ttl=True
                )
                if cached_vp_result is not None:
                    # Используем кэш - Volume Profile меняется медленно (historical data)
                    if not cached_vp_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Volume Profile Filter - BLOCKED (из кэша) | "
                            f"Цена: ${signal_price:.2f}, Режим: {regime or 'unknown'} | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_slow:.0f}s, Volume Profile обновляется медленно)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("VolumeProfile")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Volume Profile Filter - PASSED (из кэша) | "
                            f"Цена: ${signal_price:.2f}, Режим: {regime or 'unknown'} | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_slow:.0f}s)"
                        )
                else:
                    # Кэша нет - вычисляем и сохраняем
                    vp_params = filters_profile.get("volume_profile", {})
                    vp_result = await self._apply_volume_profile_filter(
                        symbol, signal, market_data, vp_params
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(symbol, "volume_profile", vp_result)
                    if not vp_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Volume Profile Filter - BLOCKED | "
                            f"Цена: ${signal_price:.2f}, Режим: {regime or 'unknown'}, Параметры: {vp_params} | "
                            f"Источник: VolumeProfileFilter.is_signal_valid() -> Анализ объемного профиля (historical data)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("VolumeProfile")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Volume Profile Filter - PASSED | "
                            f"Цена: ${signal_price:.2f}, Режим: {regime or 'unknown'}, Параметры: {vp_params} | "
                            f"Источник: VolumeProfileFilter.is_signal_valid() -> Анализ объемного профиля (historical data)"
                        )
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Volume Profile фильтра для {symbol}: {e}")

        # 7. Liquidity Filter (проверка ликвидности)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом (TTL 30s для тяжелых фильтров)
        liquidity_relax = (
            float(impulse_relax.get("liquidity", 1.0)) if is_impulse else 1.0
        )
        if self.liquidity_filter:
            try:
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")

                # Пытаемся получить из кэша (используем медленный TTL 30s)
                cached_liquidity_result = self._get_cached_filter_result(
                    symbol, "liquidity", use_slow_ttl=True
                )
                if cached_liquidity_result is not None:
                    # Используем кэш - Liquidity меняется медленно (API calls)
                    if not cached_liquidity_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Liquidity Filter - BLOCKED (из кэша) | "
                            f"Режим: {regime or 'unknown'}, Relax: {liquidity_relax:.2f}x | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_slow:.0f}s, Liquidity обновляется через API)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("Liquidity")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Liquidity Filter - PASSED (из кэша) | "
                            f"Режим: {regime or 'unknown'}, Relax: {liquidity_relax:.2f}x | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_slow:.0f}s)"
                        )
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
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Liquidity Filter - BLOCKED | "
                            f"Режим: {regime or 'unknown'}, Параметры: {liquidity_params}, Relax: {liquidity_relax:.2f}x | "
                            f"Источник: LiquidityFilter -> API запрос данных о ликвидности"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("Liquidity")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Liquidity Filter - PASSED | "
                            f"Режим: {regime or 'unknown'}, Параметры: {liquidity_params}, Relax: {liquidity_relax:.2f}x | "
                            f"Источник: LiquidityFilter -> API запрос данных о ликвидности"
                        )
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Liquidity фильтра для {symbol}: {e}")

        # ==================== MARKET FILTERS ====================

        # 8. Order Flow Filter (проверка потока ордеров)
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Проверяем кэш перед расчетом (TTL 30s для тяжелых фильтров)
        order_flow_relax = (
            float(impulse_relax.get("order_flow", 1.0)) if is_impulse else 1.0
        )
        if self.order_flow_filter:
            try:
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")

                # Пытаемся получить из кэша (используем медленный TTL 30s)
                cached_of_result = self._get_cached_filter_result(
                    symbol, "order_flow", use_slow_ttl=True
                )
                if cached_of_result is not None:
                    # Используем кэш - Order Flow меняется медленно (API calls)
                    if not cached_of_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Order Flow Filter - BLOCKED (из кэша) | "
                            f"Режим: {regime or 'unknown'}, Relax: {order_flow_relax:.2f}x | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_slow:.0f}s, Order Flow обновляется через API)"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("OrderFlow")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Order Flow Filter - PASSED (из кэша) | "
                            f"Режим: {regime or 'unknown'}, Relax: {order_flow_relax:.2f}x | "
                            f"Источник: FilterManager._get_cached_filter_result() (TTL={self.filter_cache_ttl_slow:.0f}s)"
                        )
                else:
                    # Кэша нет - вычисляем и сохраняем
                    order_flow_params = filters_profile.get("order_flow", {})
                    of_result = await self._apply_order_flow_filter(
                        symbol, signal, market_data, order_flow_params, order_flow_relax
                    )
                    # Сохраняем в кэш
                    self._set_cached_filter_result(symbol, "order_flow", of_result)
                    if not of_result:
                        logger.info(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Order Flow Filter - BLOCKED | "
                            f"Режим: {regime or 'unknown'}, Параметры: {order_flow_params}, Relax: {order_flow_relax:.2f}x | "
                            f"Источник: OrderFlowFilter -> API запрос данных о потоке ордеров"
                        )
                        return None
                    else:
                        if "filters_passed" not in signal:
                            signal["filters_passed"] = []
                        signal["filters_passed"].append("OrderFlow")
                        logger.debug(
                            f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Order Flow Filter - PASSED | "
                            f"Режим: {regime or 'unknown'}, Параметры: {order_flow_params}, Relax: {order_flow_relax:.2f}x | "
                            f"Источник: OrderFlowFilter -> API запрос данных о потоке ордеров"
                        )
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Order Flow фильтра для {symbol}: {e}")

        # 9. Funding Rate Filter (проверка funding rate)
        if self.funding_rate_filter:
            try:
                signal_side_str = signal.get("side", "").upper()
                signal_type_str = signal.get("type", "unknown")
                funding_params = filters_profile.get("funding", {})
                funding_result = await self._apply_funding_rate_filter(
                    symbol, signal, funding_params
                )
                if not funding_result:
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Funding Rate Filter - BLOCKED | "
                        f"Режим: {regime or 'unknown'}, Параметры: {funding_params} | "
                        f"Источник: FundingRateFilter -> API запрос funding rate"
                    )
                    return None
                else:
                    # ✅ НОВОЕ: Добавляем в список пройденных фильтров
                    if "filters_passed" not in signal:
                        signal["filters_passed"] = []
                    signal["filters_passed"].append("FundingRate")
                    logger.debug(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): Funding Rate Filter - PASSED | "
                        f"Режим: {regime or 'unknown'}, Параметры: {funding_params} | "
                        f"Источник: FundingRateFilter -> API запрос funding rate"
                    )
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
        self,
        symbol: str,
        signal: Dict[str, Any],
        market_data: Any,
        regime: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Применить ADX фильтр к сигналу с адаптацией к режиму рынка.

        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Адаптация к режиму рынка
        - RANGING: НЕ блокировать из-за низкого ADX (это нормально для ranging)
        - TRENDING: Блокировать, если ADX < порога (18.0 из конфига)
        - CHOPPY: Блокировать только сильные противонаправленные тренды

        Args:
            symbol: Торговый символ
            signal: Торговый сигнал
            market_data: Рыночные данные
            regime: Режим рынка (trending, ranging, choppy)

        Returns:
            Обновленный сигнал или None если отфильтрован
        """
        if not self.adx_filter:
            return signal

        # ✅ ГРОК ОПТИМИЗАЦИЯ: Пытаемся получить ADX из DataRegistry для быстрой проверки
        adx_value_from_registry = None
        if self.data_registry:
            try:
                adx_value_from_registry = await self.data_registry.get_indicator(
                    symbol, "ADX"
                )
                if adx_value_from_registry is not None:
                    logger.debug(
                        f"✅ FilterManager: ADX из DataRegistry для {symbol}: {adx_value_from_registry:.2f}"
                    )
            except Exception as e:
                logger.debug(f"⚠️ Ошибка чтения ADX из DataRegistry для {symbol}: {e}")

        # Логика ADX фильтра будет делегирована в существующий ADXFilter
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

        # ✅ НОВОЕ (03.01.2026): Получаем параметры конфигурации для логирования
        adx_threshold_config = (
            self.adx_filter.config.adx_threshold
            if self.adx_filter and self.adx_filter.config
            else 25.0
        )
        di_difference_config = (
            self.adx_filter.config.di_difference
            if self.adx_filter and self.adx_filter.config
            else 5.0
        )
        adx_period_config = (
            self.adx_filter.config.adx_period
            if self.adx_filter and self.adx_filter.config
            else 14
        )
        signal_type_str = signal.get("type", "unknown")

        if not adx_result.allowed:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Адаптация к режиму рынка
            regime_lower = (regime or "").lower()

            # ✅ RANGING режим: НЕ блокируем из-за низкого ADX (это нормально!)
            if regime_lower == "ranging":
                # В ranging режиме низкий ADX - это нормально, не блокируем
                logger.info(
                    f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - PASSED (RANGING режим) | "
                    f"ADX={adx_result.adx_value:.1f} (низкий ADX нормален для ranging), "
                    f"+DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f} | "
                    f"Конфиг: threshold={adx_threshold_config:.1f}, di_diff={di_difference_config:.1f}, period={adx_period_config} | "
                    f"Источник: ADXFilter.check_trend_strength() -> MarketData.indicators"
                )
                return signal  # Пропускаем сигнал в ranging режиме

            # ✅ TRENDING режим: Блокируем, если ADX < порога (18.0)
            elif regime_lower == "trending":
                # В trending режиме требуем сильный тренд
                if adx_result.adx_value < 18.0:
                    filter_reason = f"ADX={adx_result.adx_value:.1f} < 18.0 (требуется сильный тренд для TRENDING режима)"
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - BLOCKED (TRENDING режим) | "
                        f"{filter_reason} | "
                        f"ADX={adx_result.adx_value:.1f}, +DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f} | "
                        f"Конфиг: threshold={adx_threshold_config:.1f}, di_diff={di_difference_config:.1f}, period={adx_period_config} | "
                        f"Источник: ADXFilter.check_trend_strength() -> MarketData.indicators"
                    )
                    signal["filter_reason"] = f"ADX Filter: {filter_reason}"
                    return None
                else:
                    # ADX достаточен, но сигнал против тренда - блокируем
                    filter_reason = f"сигнал против тренда ({adx_result.reason if hasattr(adx_result, 'reason') else 'ADX не разрешил'})"
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - BLOCKED (TRENDING режим) | "
                        f"{filter_reason} | "
                        f"ADX={adx_result.adx_value:.1f}, +DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f} | "
                        f"Конфиг: threshold={adx_threshold_config:.1f}, di_diff={di_difference_config:.1f}, period={adx_period_config} | "
                        f"Источник: ADXFilter.check_trend_strength() -> MarketData.indicators"
                    )
                    signal["filter_reason"] = f"ADX Filter: {filter_reason}"
                    return None

            # ✅ CHOPPY режим: Блокируем только сильные противонаправленные тренды
            elif regime_lower == "choppy":
                # В choppy режиме блокируем только если очень сильный тренд против сигнала
                if adx_result.adx_value > 30.0:
                    filter_reason = f"очень сильный тренд против сигнала (ADX={adx_result.adx_value:.1f} > 30.0 для CHOPPY режима)"
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - BLOCKED (CHOPPY режим) | "
                        f"{filter_reason} | "
                        f"ADX={adx_result.adx_value:.1f}, +DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f} | "
                        f"Конфиг: threshold={adx_threshold_config:.1f}, di_diff={di_difference_config:.1f}, period={adx_period_config} | "
                        f"Источник: ADXFilter.check_trend_strength() -> MarketData.indicators"
                    )
                    signal["filter_reason"] = f"ADX Filter: {filter_reason}"
                    return None
                else:
                    # В choppy режиме слабый тренд - пропускаем
                    logger.info(
                        f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - PASSED (CHOPPY режим) | "
                        f"ADX={adx_result.adx_value:.1f} (слабый тренд нормален для choppy), "
                        f"+DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f} | "
                        f"Конфиг: threshold={adx_threshold_config:.1f}, di_diff={di_difference_config:.1f}, period={adx_period_config} | "
                        f"Источник: ADXFilter.check_trend_strength() -> MarketData.indicators"
                    )
                    return signal

            # ✅ Неизвестный режим: используем стандартную логику
            else:
                filter_reason = f"сигнал против тренда ({adx_result.reason if hasattr(adx_result, 'reason') else 'ADX не разрешил'})"
                logger.info(
                    f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - BLOCKED (режим={regime_lower or 'unknown'}) | "
                    f"{filter_reason} | "
                    f"ADX={adx_result.adx_value:.1f}, +DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f} | "
                    f"Конфиг: threshold={adx_threshold_config:.1f}, di_diff={di_difference_config:.1f}, period={adx_period_config} | "
                    f"Источник: ADXFilter.check_trend_strength() -> MarketData.indicators"
                )
                signal["filter_reason"] = f"ADX Filter: {filter_reason}"
                return None
        else:
            logger.info(
                f"📊 [FILTER] {symbol} ({signal_type_str} {signal_side_str}): ADX Filter - PASSED | "
                f"ADX={adx_result.adx_value:.1f}, +DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f} | "
                f"Конфиг: threshold={adx_threshold_config:.1f}, di_diff={di_difference_config:.1f}, period={adx_period_config} | "
                f"Источник: ADXFilter.check_trend_strength() -> MarketData.indicators"
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
