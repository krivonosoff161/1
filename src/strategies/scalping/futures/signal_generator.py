"""
Futures Signal Generator для скальпинг стратегии.

Основные функции:
- Генерация торговых сигналов для Futures
- Адаптация под Futures специфику (леверидж, маржа)
- Интеграция с техническими индикаторами
- Фильтрация сигналов по силе и качеству
"""

import asyncio
import copy
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.config import BotConfig, ScalpingConfig
from src.indicators import IndicatorManager
from src.models import OHLCV, MarketData
from src.strategies.modules.adaptive_regime_manager import \
    AdaptiveRegimeManager
from src.strategies.modules.correlation_filter import CorrelationFilter
from src.strategies.modules.multi_timeframe import MultiTimeframeFilter
from src.strategies.modules.pivot_points import PivotPointsFilter
from src.strategies.modules.volume_profile_filter import VolumeProfileFilter

from .filters import (FundingRateFilter, LiquidityFilter, MomentumFilter,
                      OrderFlowFilter, VolatilityRegimeFilter)


class FuturesSignalGenerator:
    """
    Генератор сигналов для Futures торговли

    Особенности:
    - Учет левериджа и маржи
    - Адаптация под Futures специфику
    - Интеграция с модулями фильтрации
    - Оптимизация для скальпинга
    """

    def __init__(self, config: BotConfig, client=None):
        """
        Инициализация Futures Signal Generator

        Args:
            config: Конфигурация бота
            client: OKX клиент (опционально, для фильтров)
        """
        self.config = config
        self.scalping_config = config.scalping
        self.client = client  # ✅ Сохраняем клиент для фильтров

        # Менеджер индикаторов
        from src.indicators import (ATR, MACD, RSI, BollingerBands,
                                    ExponentialMovingAverage,
                                    SimpleMovingAverage)

        self.indicator_manager = IndicatorManager()

        # ✅ ИСПРАВЛЕНИЕ: Получаем базовые периоды из конфига (из ranging как fallback)
        # Эти периоды используются для базовых расчетов, конкретные режимы используют свои параметры
        rsi_period = 14
        rsi_overbought = 70
        rsi_oversold = 30
        atr_period = 14
        sma_period = 20
        macd_fast = 12
        macd_slow = 26
        macd_signal = 9
        bb_period = 20
        bb_std_multiplier = 2.0
        ema_fast = 12
        ema_slow = 26

        # Получаем базовые параметры из конфига
        try:
            scalping_config = getattr(self.config, "scalping", None)
            if scalping_config:
                # Базовые параметры из scalping секции (если есть)
                if hasattr(scalping_config, "rsi_period"):
                    rsi_period = getattr(scalping_config, "rsi_period", 14)
                if hasattr(scalping_config, "rsi_overbought"):
                    rsi_overbought = getattr(scalping_config, "rsi_overbought", 70)
                if hasattr(scalping_config, "rsi_oversold"):
                    rsi_oversold = getattr(scalping_config, "rsi_oversold", 30)
                if hasattr(scalping_config, "macd_fast"):
                    macd_fast = getattr(scalping_config, "macd_fast", 12)
                if hasattr(scalping_config, "macd_slow"):
                    macd_slow = getattr(scalping_config, "macd_slow", 26)
                if hasattr(scalping_config, "macd_signal"):
                    macd_signal = getattr(scalping_config, "macd_signal", 9)
                if hasattr(scalping_config, "bb_period"):
                    bb_period = getattr(scalping_config, "bb_period", 20)
                if hasattr(scalping_config, "bb_std_dev"):
                    bb_std_multiplier = getattr(scalping_config, "bb_std_dev", 2.0)
                if hasattr(scalping_config, "ma_fast"):
                    ema_fast = getattr(scalping_config, "ma_fast", 12)
                if hasattr(scalping_config, "ma_slow"):
                    ema_slow = getattr(scalping_config, "ma_slow", 26)

                # Пытаемся получить периоды из ranging режима (как базовые)
                adaptive_regime = getattr(scalping_config, "adaptive_regime", None)
                if adaptive_regime:
                    ranging_params = None
                    if hasattr(adaptive_regime, "ranging_params"):
                        ranging_params = getattr(
                            adaptive_regime, "ranging_params", None
                        )
                    elif isinstance(adaptive_regime, dict):
                        ranging_params = adaptive_regime.get("ranging_params", {})

                    if ranging_params:
                        indicators = None
                        if hasattr(ranging_params, "indicators"):
                            indicators = getattr(ranging_params, "indicators", {})
                        elif isinstance(ranging_params, dict):
                            indicators = ranging_params.get("indicators", {})

                        if indicators:
                            # Используем периоды из ranging режима как базовые
                            if isinstance(indicators, dict):
                                # Из dict
                                if "sma_fast" in indicators:
                                    sma_period = indicators.get(
                                        "sma_fast", 20
                                    )  # Используем fast как базовый SMA
                                if "ema_fast" in indicators:
                                    ema_fast = indicators.get("ema_fast", 12)
                                if "ema_slow" in indicators:
                                    ema_slow = indicators.get("ema_slow", 26)
                                if "atr_period" in indicators:
                                    atr_period = indicators.get("atr_period", 14)
                            elif hasattr(indicators, "sma_fast"):
                                # Из атрибутов Pydantic модели
                                sma_period = getattr(indicators, "sma_fast", 20)
                                ema_fast = getattr(indicators, "ema_fast", 12)
                                ema_slow = getattr(indicators, "ema_slow", 26)
                                atr_period = getattr(indicators, "atr_period", 14)
        except Exception as e:
            logger.debug(
                f"⚠️ Не удалось получить периоды индикаторов из конфига: {e}, используем дефолтные"
            )

        # ✅ Добавляем индикаторы с параметрами из конфига
        self.indicator_manager.add_indicator(
            "RSI",
            RSI(period=rsi_period, overbought=rsi_overbought, oversold=rsi_oversold),
        )
        self.indicator_manager.add_indicator("ATR", ATR(period=atr_period))
        self.indicator_manager.add_indicator(
            "SMA", SimpleMovingAverage(period=sma_period)
        )
        # ✅ Добавляем индикаторы, которые используются в генерации сигналов
        self.indicator_manager.add_indicator(
            "MACD",
            MACD(
                fast_period=macd_fast, slow_period=macd_slow, signal_period=macd_signal
            ),
        )
        # ✅ ИСПРАВЛЕНИЕ: BollingerBands использует std_multiplier, а не std_dev
        self.indicator_manager.add_indicator(
            "BollingerBands",
            BollingerBands(period=bb_period, std_multiplier=bb_std_multiplier),
        )
        self.indicator_manager.add_indicator(
            "EMA_12", ExponentialMovingAverage(period=ema_fast)
        )
        self.indicator_manager.add_indicator(
            "EMA_26", ExponentialMovingAverage(period=ema_slow)
        )

        logger.debug(
            f"📊 Инициализированы индикаторы с параметрами из конфига: "
            f"RSI(period={rsi_period}), ATR({atr_period}), SMA({sma_period}), "
            f"MACD({macd_fast}/{macd_slow}/{macd_signal}), BB({bb_period}), "
            f"EMA({ema_fast}/{ema_slow})"
        )

        # Модули фильтрации - ИНТЕГРАЦИЯ адаптивных систем
        self.regime_manager = (
            None  # Инициализируется в initialize() (общий для всех символов)
        )
        self.regime_managers = {}  # ✅ Отдельный ARM для каждого символа
        self.symbol_profiles: Dict[str, Dict[str, Any]] = {}
        self.correlation_filter = None
        self.mtf_filter = None
        self.pivot_filter = None
        self.volume_filter = None
        self.funding_filter = None
        self.liquidity_filter = None
        self.order_flow_filter = None
        self.volatility_filter = None
        self.momentum_filter = None  # ✅ НОВОЕ: Momentum Filter
        self.impulse_config = None

        modules_config = getattr(self.config, "futures_modules", None)
        if modules_config:
            try:
                if getattr(modules_config, "funding_filter", None):
                    self.funding_filter = FundingRateFilter(
                        client=self.client,
                        config=modules_config.funding_filter,
                    )
                if getattr(modules_config, "liquidity_filter", None):
                    self.liquidity_filter = LiquidityFilter(
                        client=self.client,
                        config=modules_config.liquidity_filter,
                    )
                if getattr(modules_config, "order_flow", None):
                    self.order_flow_filter = OrderFlowFilter(
                        client=self.client,
                        config=modules_config.order_flow,
                    )
                if getattr(modules_config, "volatility_filter", None):
                    self.volatility_filter = VolatilityRegimeFilter(
                        config=modules_config.volatility_filter
                    )
                    self.impulse_config = getattr(
                        modules_config, "impulse_trading", None
                    )
            except Exception as filter_exc:
                logger.warning(
                    f"⚠️ Не удалось инициализировать futures-фильтры: {filter_exc}"
                )

        # Состояние
        self.is_initialized = False
        self.last_signals = {}
        self.signal_history = []

        logger.info("FuturesSignalGenerator инициализирован")

    @staticmethod
    def _to_dict(raw: Any) -> Dict[str, Any]:
        """Безопасное преобразование pydantic/объектов в dict."""
        if isinstance(raw, dict):
            return dict(raw)
        if hasattr(raw, "dict"):
            try:
                return dict(raw.dict(by_alias=True))  # type: ignore[attr-defined]
            except TypeError:
                return dict(raw.dict())  # type: ignore[attr-defined]
        if hasattr(raw, "__dict__"):
            return dict(raw.__dict__)
        return {}

    @staticmethod
    def _deep_merge_dict(
        base: Dict[str, Any], override: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Рекурсивное объединение словарей без изменения исходников."""
        result = copy.deepcopy(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = FuturesSignalGenerator._deep_merge_dict(
                    result[key], value
                )
            else:
                result[key] = copy.deepcopy(value)
        return result

    def _normalize_symbol_profiles(
        self, raw_profiles: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        profiles: Dict[str, Dict[str, Any]] = {}
        for symbol, profile in (raw_profiles or {}).items():
            normalized: Dict[str, Any] = {}
            profile_dict = self._to_dict(profile)
            for regime_name, regime_data in profile_dict.items():
                regime_key = str(regime_name).lower()
                if regime_key in {"__detection__", "detection"}:
                    normalized["__detection__"] = self._to_dict(regime_data)
                    continue
                regime_dict = self._to_dict(regime_data)
                for section, section_value in list(regime_dict.items()):
                    if isinstance(section_value, dict) or hasattr(
                        section_value, "__dict__"
                    ):
                        section_dict = self._to_dict(section_value)
                        for sub_key, sub_val in list(section_dict.items()):
                            if isinstance(sub_val, dict) or hasattr(
                                sub_val, "__dict__"
                            ):
                                section_dict[sub_key] = self._to_dict(sub_val)
                        regime_dict[section] = section_dict
                normalized[regime_key] = regime_dict
            profiles[symbol] = normalized
        return profiles

    async def initialize(self, ohlcv_data: Dict[str, List[OHLCV]] = None):
        """
        Инициализация генератора сигналов.

        Args:
            ohlcv_data: Исторические свечи для инициализации ARM
        """
        try:
            from src.strategies.modules.adaptive_regime_manager import \
                RegimeConfig

            # Инициализация ARM
            # ⚠️ ИСПРАВЛЕНИЕ: adaptive_regime находится в config.scalping, а не в config
            scalping_config = getattr(self.config, "scalping", None)
            adaptive_regime_config = None
            if scalping_config:
                if hasattr(scalping_config, "adaptive_regime"):
                    adaptive_regime_config = getattr(
                        scalping_config, "adaptive_regime", None
                    )
                elif isinstance(scalping_config, dict):
                    adaptive_regime_config = scalping_config.get("adaptive_regime", {})

            # Если adaptive_regime_config - это Pydantic модель, проверяем enabled
            enabled = False
            if adaptive_regime_config:
                if hasattr(adaptive_regime_config, "enabled"):
                    enabled = getattr(adaptive_regime_config, "enabled", False)
                elif isinstance(adaptive_regime_config, dict):
                    enabled = adaptive_regime_config.get("enabled", False)

            if adaptive_regime_config and enabled:
                try:
                    adaptive_regime_dict = self._to_dict(adaptive_regime_config)
                    detection_dict = self._to_dict(
                        adaptive_regime_dict.get("detection", {})
                    )
                    symbol_profiles_raw = adaptive_regime_dict.get(
                        "symbol_profiles", {}
                    )
                    self.symbol_profiles = self._normalize_symbol_profiles(
                        symbol_profiles_raw
                    )

                    def extract_regime_params(regime_name: str) -> Dict[str, Any]:
                        return self._to_dict(
                            adaptive_regime_dict.get(regime_name, {}) or {}
                        )

                    # ✅ ИСПРАВЛЕНИЕ: Сохраняем extract_regime_params для использования в фильтрах
                    self._extract_regime_params = extract_regime_params
                    self._adaptive_regime_dict = adaptive_regime_dict

                    from src.strategies.modules.adaptive_regime_manager import (
                        IndicatorParameters, ModuleParameters,
                        RegimeParameters)

                    def create_regime_params(
                        regime_name: str,
                        override: Optional[Dict[str, Any]] = None,
                    ) -> RegimeParameters:
                        params_dict = extract_regime_params(regime_name)
                        if override:
                            params_dict = self._deep_merge_dict(params_dict, override)
                        indicators_dict = params_dict.get("indicators", {})
                        modules_dict = params_dict.get("modules", {})

                        indicators = IndicatorParameters(
                            rsi_overbought=indicators_dict.get("rsi_overbought", 70),
                            rsi_oversold=indicators_dict.get("rsi_oversold", 30),
                            volume_threshold=indicators_dict.get(
                                "volume_threshold", 1.1
                            ),
                            sma_fast=indicators_dict.get("sma_fast", 10),
                            sma_slow=indicators_dict.get("sma_slow", 30),
                            ema_fast=indicators_dict.get("ema_fast", 10),
                            ema_slow=indicators_dict.get("ema_slow", 30),
                            atr_period=indicators_dict.get("atr_period", 14),
                            min_volatility_atr=indicators_dict.get(
                                "min_volatility_atr", 0.0005
                            ),
                        )

                        mtf_dict = modules_dict.get("multi_timeframe", {})
                        corr_dict = modules_dict.get("correlation_filter", {})
                        time_dict = modules_dict.get("time_filter", {})
                        pivot_dict = modules_dict.get("pivot_points", {})
                        vp_dict = modules_dict.get("volume_profile", {})
                        adx_dict = modules_dict.get("adx_filter", {})

                        modules = ModuleParameters(
                            mtf_block_opposite=mtf_dict.get("block_opposite", True),
                            mtf_score_bonus=mtf_dict.get("score_bonus", 2),
                            mtf_confirmation_timeframe=mtf_dict.get(
                                "confirmation_timeframe", "15m"
                            ),
                            correlation_threshold=corr_dict.get(
                                "correlation_threshold", 0.7
                            ),
                            max_correlated_positions=corr_dict.get(
                                "max_correlated_positions", 2
                            ),
                            block_same_direction_only=corr_dict.get(
                                "block_same_direction_only", True
                            ),
                            prefer_overlaps=time_dict.get("prefer_overlaps", True),
                            avoid_low_liquidity_hours=time_dict.get(
                                "avoid_low_liquidity_hours", True
                            ),
                            pivot_level_tolerance_percent=pivot_dict.get(
                                "level_tolerance_percent", 0.25
                            ),
                            pivot_score_bonus_near_level=pivot_dict.get(
                                "score_bonus_near_level", 1
                            ),
                            pivot_use_last_n_days=pivot_dict.get("use_last_n_days", 5),
                            vp_score_bonus_in_value_area=vp_dict.get(
                                "score_bonus_in_value_area", 1
                            ),
                            vp_score_bonus_near_poc=vp_dict.get(
                                "score_bonus_near_poc", 1
                            ),
                            vp_poc_tolerance_percent=vp_dict.get(
                                "poc_tolerance_percent", 0.25
                            ),
                            vp_lookback_candles=vp_dict.get("lookback_candles", 200),
                            adx_threshold=adx_dict.get("adx_threshold", 18.0),
                            adx_di_difference=adx_dict.get("adx_di_difference", 1.5),
                        )

                        return RegimeParameters(
                            min_score_threshold=params_dict.get(
                                "min_score_threshold", 3.0
                            ),
                            max_trades_per_hour=params_dict.get(
                                "max_trades_per_hour", 15
                            ),
                            position_size_multiplier=params_dict.get(
                                "position_size_multiplier", 1.0
                            ),
                            tp_atr_multiplier=params_dict.get("tp_atr_multiplier", 2.0),
                            sl_atr_multiplier=params_dict.get("sl_atr_multiplier", 1.0),
                            max_holding_minutes=params_dict.get(
                                "max_holding_minutes", 15
                            ),
                            cooldown_after_loss_minutes=params_dict.get(
                                "cooldown_after_loss_minutes", 3
                            ),
                            pivot_bonus_multiplier=params_dict.get(
                                "pivot_bonus_multiplier", 1.0
                            ),
                            volume_profile_bonus_multiplier=params_dict.get(
                                "volume_profile_bonus_multiplier", 1.0
                            ),
                            indicators=indicators,
                            modules=modules,
                            ph_enabled=params_dict.get("ph_enabled", True),
                            ph_threshold=params_dict.get("ph_threshold", 0.20),
                            ph_time_limit=params_dict.get("ph_time_limit", 300),
                        )

                    base_trending_threshold = detection_dict.get(
                        "trending_adx_threshold", 20.0
                    )
                    base_ranging_threshold = detection_dict.get(
                        "ranging_adx_threshold", 15.0
                    )
                    base_high_vol = detection_dict.get(
                        "high_volatility_threshold", 0.03
                    )
                    base_low_vol = detection_dict.get("low_volatility_threshold", 0.02)
                    base_trend_strength = detection_dict.get(
                        "trend_strength_percent", 2.0
                    )
                    base_min_duration = detection_dict.get(
                        "min_regime_duration_minutes", 15
                    )
                    base_confirmations = detection_dict.get("required_confirmations", 3)

                    trending_params = create_regime_params("trending")
                    ranging_params = create_regime_params("ranging")
                    choppy_params = create_regime_params("choppy")

                    regime_config = RegimeConfig(
                        enabled=True,
                        trending_adx_threshold=base_trending_threshold,
                        ranging_adx_threshold=base_ranging_threshold,
                        high_volatility_threshold=base_high_vol,
                        low_volatility_threshold=base_low_vol,
                        trend_strength_percent=base_trend_strength,
                        min_regime_duration_minutes=base_min_duration,
                        required_confirmations=base_confirmations,
                        trending_params=trending_params,
                        ranging_params=ranging_params,
                        choppy_params=choppy_params,
                    )
                    self.regime_manager = AdaptiveRegimeManager(regime_config)

                    if ohlcv_data:
                        await self.regime_manager.initialize(ohlcv_data)

                    for symbol in self.scalping_config.symbols:
                        symbol_profile = self.symbol_profiles.get(symbol, {})
                        symbol_detection = self._deep_merge_dict(
                            detection_dict,
                            symbol_profile.get("__detection__", {}),
                        )
                        symbol_trending_params = create_regime_params(
                            "trending",
                            symbol_profile.get("trending", {}).get("arm"),
                        )
                        symbol_ranging_params = create_regime_params(
                            "ranging",
                            symbol_profile.get("ranging", {}).get("arm"),
                        )
                        symbol_choppy_params = create_regime_params(
                            "choppy",
                            symbol_profile.get("choppy", {}).get("arm"),
                        )

                        symbol_regime_config = RegimeConfig(
                            enabled=True,
                            trending_adx_threshold=symbol_detection.get(
                                "trending_adx_threshold", base_trending_threshold
                            ),
                            ranging_adx_threshold=symbol_detection.get(
                                "ranging_adx_threshold", base_ranging_threshold
                            ),
                            high_volatility_threshold=symbol_detection.get(
                                "high_volatility_threshold", base_high_vol
                            ),
                            low_volatility_threshold=symbol_detection.get(
                                "low_volatility_threshold", base_low_vol
                            ),
                            trend_strength_percent=symbol_detection.get(
                                "trend_strength_percent", base_trend_strength
                            ),
                            min_regime_duration_minutes=symbol_detection.get(
                                "min_regime_duration_minutes", base_min_duration
                            ),
                            required_confirmations=symbol_detection.get(
                                "required_confirmations", base_confirmations
                            ),
                            trending_params=symbol_trending_params,
                            ranging_params=symbol_ranging_params,
                            choppy_params=symbol_choppy_params,
                        )
                        self.regime_managers[symbol] = AdaptiveRegimeManager(
                            symbol_regime_config
                        )
                        if ohlcv_data and symbol in ohlcv_data:
                            await self.regime_managers[symbol].initialize(
                                {symbol: ohlcv_data[symbol]}
                            )

                    logger.info(
                        f"✅ Adaptive Regime Manager инициализирован: "
                        f"общий + {len(self.regime_managers)} для символов"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ ARM инициализация не удалась: {e}")
                    self.regime_manager = None
            else:
                logger.info("⚠️ Adaptive Regime Manager отключен в конфиге")

            # ✅ Инициализация Multi-Timeframe фильтра
            try:
                from src.strategies.modules.multi_timeframe import (
                    MTFConfig, MultiTimeframeFilter)

                # ✅ ИСПРАВЛЕНИЕ: Используем параметры из базового конфига или режима
                # Получаем параметры MTF из базового конфига (или дефолты)
                base_mtf_config = None
                if hasattr(self.scalping_config, "multi_timeframe"):
                    base_mtf_config = self.scalping_config.multi_timeframe
                elif isinstance(self.scalping_config, dict):
                    base_mtf_config = self.scalping_config.get("multi_timeframe", {})

                # Получаем параметры из базового конфига или используем дефолты
                mtf_timeframe = "5m"  # По умолчанию 5m для futures
                mtf_score_bonus = 2
                mtf_block_opposite = (
                    False  # ✅ ИЗМЕНЕНО: false по умолчанию (соответствует режимам)
                )

                if base_mtf_config:
                    if isinstance(base_mtf_config, dict):
                        mtf_timeframe = base_mtf_config.get(
                            "confirmation_timeframe", mtf_timeframe
                        )
                        mtf_score_bonus = base_mtf_config.get(
                            "score_bonus", mtf_score_bonus
                        )
                        mtf_block_opposite = base_mtf_config.get(
                            "block_opposite", mtf_block_opposite
                        )
                    elif hasattr(base_mtf_config, "confirmation_timeframe"):
                        mtf_timeframe = getattr(
                            base_mtf_config, "confirmation_timeframe", mtf_timeframe
                        )
                        mtf_score_bonus = getattr(
                            base_mtf_config, "score_bonus", mtf_score_bonus
                        )
                        mtf_block_opposite = getattr(
                            base_mtf_config, "block_opposite", mtf_block_opposite
                        )

                # Создаем конфигурацию MTF
                mtf_config = MTFConfig(
                    confirmation_timeframe=mtf_timeframe,
                    score_bonus=mtf_score_bonus,
                    block_opposite=mtf_block_opposite,  # ✅ Используем из конфига (по умолчанию False)
                    ema_fast_period=8,
                    ema_slow_period=21,
                    cache_ttl_seconds=30,  # Кэш на 30 секунд
                )

                # Инициализируем MTF фильтр (client может быть None - свечи получаем напрямую)
                self.mtf_filter = MultiTimeframeFilter(
                    client=self.client, config=mtf_config  # Может быть None
                )

                logger.info(
                    f"✅ Multi-Timeframe Filter инициализирован: "
                    f"таймфрейм={mtf_config.confirmation_timeframe}, "
                    f"block_opposite={mtf_config.block_opposite}"
                )
            except Exception as e:
                logger.warning(f"⚠️ MTF инициализация не удалась: {e}")
                self.mtf_filter = None

            # ✅ Инициализация Correlation Filter
            try:
                from src.strategies.modules.correlation_filter import (
                    CorrelationFilter, CorrelationFilterConfig)

                # Получаем параметры из базового конфига
                corr_config_data = None
                if hasattr(self.scalping_config, "correlation_filter"):
                    corr_config_data = self.scalping_config.correlation_filter
                elif isinstance(self.scalping_config, dict):
                    corr_config_data = self.scalping_config.get(
                        "correlation_filter", {}
                    )

                corr_enabled = True  # По умолчанию включен
                # ✅ АДАПТИВНО: correlation_threshold из конфига по режиму
                regime_name_corr = "ranging"  # Fallback
                try:
                    if hasattr(self, "regime_manager") and self.regime_manager:
                        regime_obj = self.regime_manager.get_current_regime()
                        if regime_obj:
                            regime_name_corr = (
                                regime_obj.lower()
                                if isinstance(regime_obj, str)
                                else str(regime_obj).lower()
                            )
                except:
                    pass

                signal_gen_config_corr = getattr(
                    self.scalping_config, "signal_generator", {}
                )
                thresholds_config = {}
                if isinstance(signal_gen_config_corr, dict):
                    thresholds_dict = signal_gen_config_corr.get("thresholds", {})
                    if thresholds_dict:
                        thresholds_config = (
                            thresholds_dict.get("by_regime", {}).get(
                                regime_name_corr, {}
                            )
                            if regime_name_corr
                            else {}
                        )
                        if not thresholds_config:
                            thresholds_config = thresholds_dict  # Fallback на базовые
                else:
                    thresholds_obj = getattr(signal_gen_config_corr, "thresholds", None)
                    if thresholds_obj:
                        by_regime = getattr(thresholds_obj, "by_regime", None)
                        if by_regime and regime_name_corr:
                            thresholds_config = getattr(by_regime, regime_name_corr, {})
                        if not thresholds_config:
                            thresholds_config = thresholds_obj  # Fallback на базовые

                corr_threshold = (
                    thresholds_config.get("correlation_threshold", 0.7)
                    if isinstance(thresholds_config, dict)
                    else getattr(thresholds_config, "correlation_threshold", 0.7)
                )
                corr_max_positions = 2
                corr_block_same_direction = True

                if corr_config_data:
                    if isinstance(corr_config_data, dict):
                        corr_threshold = corr_config_data.get(
                            "correlation_threshold", corr_threshold
                        )
                        corr_max_positions = corr_config_data.get(
                            "max_correlated_positions", corr_max_positions
                        )
                        corr_block_same_direction = corr_config_data.get(
                            "block_same_direction_only", corr_block_same_direction
                        )
                    elif hasattr(corr_config_data, "correlation_threshold"):
                        corr_threshold = getattr(
                            corr_config_data, "correlation_threshold", corr_threshold
                        )
                        corr_max_positions = getattr(
                            corr_config_data,
                            "max_correlated_positions",
                            corr_max_positions,
                        )
                        corr_block_same_direction = getattr(
                            corr_config_data,
                            "block_same_direction_only",
                            corr_block_same_direction,
                        )

                corr_config = CorrelationFilterConfig(
                    enabled=corr_enabled,
                    correlation_threshold=corr_threshold,
                    max_correlated_positions=corr_max_positions,
                    block_same_direction_only=corr_block_same_direction,
                )

                # CorrelationFilter требует OKXClient, но у нас может быть futures client
                # Используем self.client (может быть None - тогда фильтр не инициализируется)
                if self.client:
                    # Если client не OKXClient, можно попробовать адаптировать или пропустить
                    try:
                        self.correlation_filter = CorrelationFilter(
                            client=self.client,
                            config=corr_config,
                            all_symbols=self.scalping_config.symbols,
                        )
                        logger.info(
                            f"✅ Correlation Filter инициализирован: "
                            f"threshold={corr_threshold}, max_positions={corr_max_positions}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Correlation Filter инициализация не удалась "
                            f"(возможно несовместимый client): {e}"
                        )
                        self.correlation_filter = None
                else:
                    logger.warning("⚠️ Correlation Filter пропущен: client не доступен")
                    self.correlation_filter = None
            except Exception as e:
                logger.warning(f"⚠️ Correlation Filter инициализация не удалась: {e}")
                self.correlation_filter = None

            # ✅ Инициализация Pivot Points Filter
            try:
                from src.strategies.modules.pivot_points import (
                    PivotPointsConfig, PivotPointsFilter)

                # Получаем параметры из базового конфига
                pivot_config_data = None
                if hasattr(self.scalping_config, "pivot_points"):
                    pivot_config_data = self.scalping_config.pivot_points
                elif isinstance(self.scalping_config, dict):
                    pivot_config_data = self.scalping_config.get("pivot_points", {})

                # Проверяем enabled флаг
                pivot_enabled = True  # По умолчанию включен
                if hasattr(self.scalping_config, "pivot_points_enabled"):
                    pivot_enabled = getattr(
                        self.scalping_config, "pivot_points_enabled", True
                    )
                    logger.info(
                        f"✅ Pivot Points enabled из атрибута: {pivot_enabled} (тип: {type(pivot_enabled)})"
                    )
                elif isinstance(self.scalping_config, dict):
                    pivot_enabled = self.scalping_config.get(
                        "pivot_points_enabled", True
                    )
                    logger.info(f"✅ Pivot Points enabled из dict: {pivot_enabled}")
                else:
                    logger.warning(
                        f"⚠️ Pivot Points: scalping_config не dict и нет атрибута, используем по умолчанию: {pivot_enabled}"
                    )
                    logger.warning(
                        f"⚠️ Тип scalping_config: {type(self.scalping_config)}, атрибуты: {dir(self.scalping_config)[:10]}"
                    )

                # ✅ АДАПТИВНО: pivot_tolerance из конфига по режиму
                regime_name_pivot = "ranging"  # Fallback
                try:
                    if hasattr(self, "regime_manager") and self.regime_manager:
                        regime_obj = self.regime_manager.get_current_regime()
                        if regime_obj:
                            regime_name_pivot = (
                                regime_obj.lower()
                                if isinstance(regime_obj, str)
                                else str(regime_obj).lower()
                            )
                except:
                    pass

                signal_gen_config_pivot = getattr(
                    self.scalping_config, "signal_generator", {}
                )
                thresholds_config_pivot = {}
                if isinstance(signal_gen_config_pivot, dict):
                    thresholds_dict = signal_gen_config_pivot.get("thresholds", {})
                    if thresholds_dict:
                        thresholds_config_pivot = (
                            thresholds_dict.get("by_regime", {}).get(
                                regime_name_pivot, {}
                            )
                            if regime_name_pivot
                            else {}
                        )
                        if not thresholds_config_pivot:
                            thresholds_config_pivot = (
                                thresholds_dict  # Fallback на базовые
                            )
                else:
                    thresholds_obj = getattr(
                        signal_gen_config_pivot, "thresholds", None
                    )
                    if thresholds_obj:
                        by_regime = getattr(thresholds_obj, "by_regime", None)
                        if by_regime and regime_name_pivot:
                            thresholds_config_pivot = getattr(
                                by_regime, regime_name_pivot, {}
                            )
                        if not thresholds_config_pivot:
                            thresholds_config_pivot = (
                                thresholds_obj  # Fallback на базовые
                            )

                pivot_tolerance = (
                    thresholds_config_pivot.get("pivot_tolerance", 0.003)
                    if isinstance(thresholds_config_pivot, dict)
                    else getattr(thresholds_config_pivot, "pivot_tolerance", 0.003)
                )
                pivot_bonus = 1
                pivot_timeframe = "1D"
                pivot_use_days = 1

                if pivot_config_data:
                    if isinstance(pivot_config_data, dict):
                        # ✅ ИСПРАВЛЕНО: Если "enabled" есть в pivot_config_data - используем его
                        # Если нет - оставляем pivot_enabled из pivot_points_enabled (верхний уровень)
                        logger.debug(f"📊 pivot_config_data (dict): {pivot_config_data}")
                        if "enabled" in pivot_config_data:
                            old_enabled = pivot_enabled
                            pivot_enabled = pivot_config_data.get(
                                "enabled", pivot_enabled
                            )
                            logger.debug(
                                f"📊 Pivot Points enabled из pivot_config_data: {old_enabled} → {pivot_enabled}"
                            )
                        else:
                            logger.debug(
                                f"📊 pivot_config_data не содержит 'enabled', оставляем {pivot_enabled} из pivot_points_enabled"
                            )
                        # Иначе оставляем pivot_enabled как есть (из pivot_points_enabled)
                        pivot_tolerance = pivot_config_data.get(
                            "level_tolerance_percent", pivot_tolerance
                        )
                        pivot_bonus = pivot_config_data.get(
                            "score_bonus_near_level", pivot_bonus
                        )
                        pivot_timeframe = pivot_config_data.get(
                            "daily_timeframe", pivot_timeframe
                        )
                        pivot_use_days = pivot_config_data.get(
                            "use_last_n_days", pivot_use_days
                        )
                    elif hasattr(pivot_config_data, "level_tolerance_percent"):
                        # ✅ ИСПРАВЛЕНО: Если атрибут enabled есть - используем его, иначе оставляем из верхнего уровня
                        if hasattr(pivot_config_data, "enabled"):
                            pivot_enabled = getattr(
                                pivot_config_data, "enabled", pivot_enabled
                            )
                        # Иначе оставляем pivot_enabled как есть (из pivot_points_enabled)
                        pivot_tolerance = getattr(
                            pivot_config_data,
                            "level_tolerance_percent",
                            pivot_tolerance,
                        )
                        pivot_bonus = getattr(
                            pivot_config_data, "score_bonus_near_level", pivot_bonus
                        )
                        pivot_timeframe = getattr(
                            pivot_config_data, "daily_timeframe", pivot_timeframe
                        )
                        pivot_use_days = getattr(
                            pivot_config_data, "use_last_n_days", pivot_use_days
                        )

                if pivot_enabled and self.client:
                    pivot_config = PivotPointsConfig(
                        enabled=True,
                        daily_timeframe=pivot_timeframe,
                        use_last_n_days=pivot_use_days,
                        level_tolerance_percent=pivot_tolerance,
                        score_bonus_near_level=pivot_bonus,
                        cache_ttl_seconds=3600,  # 1 час кэш
                    )

                    try:
                        self.pivot_filter = PivotPointsFilter(
                            client=self.client,
                            config=pivot_config,
                        )
                        logger.info(
                            f"✅ Pivot Points Filter инициализирован: "
                            f"tolerance={pivot_tolerance:.2%}, bonus={pivot_bonus}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Pivot Points Filter инициализация не удалась: {e}"
                        )
                        self.pivot_filter = None
                else:
                    reason = []
                    if not pivot_enabled:
                        reason.append("отключен в конфиге (pivot_enabled=False)")
                    if not self.client:
                        reason.append("client не доступен (self.client is None)")
                    logger.warning(
                        f"⚠️ Pivot Points Filter не инициализирован: {', '.join(reason) if reason else 'неизвестная причина'} "
                        f"(pivot_enabled={pivot_enabled}, client={'есть' if self.client else 'None'})"
                    )
                    self.pivot_filter = None
            except Exception as e:
                logger.warning(f"⚠️ Pivot Points Filter инициализация не удалась: {e}")
                self.pivot_filter = None

            # ✅ Инициализация Volume Profile Filter
            try:
                from src.strategies.modules.volume_profile_filter import (
                    VolumeProfileConfig, VolumeProfileFilter)

                # Получаем параметры из базового конфига
                vp_config_data = None
                if hasattr(self.scalping_config, "volume_profile"):
                    vp_config_data = self.scalping_config.volume_profile
                elif isinstance(self.scalping_config, dict):
                    vp_config_data = self.scalping_config.get("volume_profile", {})

                # Проверяем enabled флаг
                vp_enabled = True  # По умолчанию включен
                if hasattr(self.scalping_config, "volume_profile_enabled"):
                    vp_enabled = getattr(
                        self.scalping_config, "volume_profile_enabled", True
                    )
                    logger.info(
                        f"✅ Volume Profile enabled из атрибута: {vp_enabled} (тип: {type(vp_enabled)})"
                    )
                elif isinstance(self.scalping_config, dict):
                    vp_enabled = self.scalping_config.get(
                        "volume_profile_enabled", True
                    )
                    logger.info(f"✅ Volume Profile enabled из dict: {vp_enabled}")
                else:
                    logger.warning(
                        f"⚠️ Volume Profile: scalping_config не dict и нет атрибута, используем по умолчанию: {vp_enabled}"
                    )
                    logger.warning(
                        f"⚠️ Тип scalping_config: {type(self.scalping_config)}, атрибуты: {dir(self.scalping_config)[:10]}"
                    )

                vp_timeframe = "1H"
                vp_lookback = 100
                vp_buckets = 50
                # ✅ АДАПТИВНО: volume_profile параметры из конфига по режиму (используем thresholds_config_pivot)
                vp_va_percent = (
                    thresholds_config_pivot.get("volume_profile_va_percent", 70.0)
                    if isinstance(thresholds_config_pivot, dict)
                    else getattr(
                        thresholds_config_pivot, "volume_profile_va_percent", 70.0
                    )
                )
                vp_bonus_va = 1
                vp_bonus_poc = 1
                vp_poc_tolerance = (
                    thresholds_config_pivot.get("volume_profile_poc_tolerance", 0.005)
                    if isinstance(thresholds_config_pivot, dict)
                    else getattr(
                        thresholds_config_pivot, "volume_profile_poc_tolerance", 0.005
                    )
                )

                if vp_config_data:
                    if isinstance(vp_config_data, dict):
                        # ✅ ИСПРАВЛЕНО: Если "enabled" есть в vp_config_data - используем его
                        # Если нет - оставляем vp_enabled из volume_profile_enabled (верхний уровень)
                        logger.debug(f"📊 vp_config_data (dict): {vp_config_data}")
                        if "enabled" in vp_config_data:
                            old_enabled = vp_enabled
                            vp_enabled = vp_config_data.get("enabled", vp_enabled)
                            logger.debug(
                                f"📊 Volume Profile enabled из vp_config_data: {old_enabled} → {vp_enabled}"
                            )
                        else:
                            logger.debug(
                                f"📊 vp_config_data не содержит 'enabled', оставляем {vp_enabled} из volume_profile_enabled"
                            )
                        vp_timeframe = vp_config_data.get(
                            "lookback_timeframe", vp_timeframe
                        )
                        vp_lookback = vp_config_data.get(
                            "lookback_candles", vp_lookback
                        )
                        vp_buckets = vp_config_data.get("price_buckets", vp_buckets)
                        vp_va_percent = vp_config_data.get(
                            "value_area_percent", vp_va_percent
                        )
                        vp_bonus_va = vp_config_data.get(
                            "score_bonus_in_value_area", vp_bonus_va
                        )
                        vp_bonus_poc = vp_config_data.get(
                            "score_bonus_near_poc", vp_bonus_poc
                        )
                        vp_poc_tolerance = vp_config_data.get(
                            "poc_tolerance_percent", vp_poc_tolerance
                        )
                    elif hasattr(vp_config_data, "lookback_timeframe"):
                        # ✅ ИСПРАВЛЕНО: Если атрибут enabled есть - используем его, иначе оставляем из верхнего уровня
                        if hasattr(vp_config_data, "enabled"):
                            vp_enabled = getattr(vp_config_data, "enabled", vp_enabled)
                        # Иначе оставляем vp_enabled как есть (из volume_profile_enabled)
                        vp_timeframe = getattr(
                            vp_config_data, "lookback_timeframe", vp_timeframe
                        )
                        vp_lookback = getattr(
                            vp_config_data, "lookback_candles", vp_lookback
                        )
                        vp_buckets = getattr(
                            vp_config_data, "price_buckets", vp_buckets
                        )
                        vp_va_percent = getattr(
                            vp_config_data, "value_area_percent", vp_va_percent
                        )
                        vp_bonus_va = getattr(
                            vp_config_data, "score_bonus_in_value_area", vp_bonus_va
                        )
                        vp_bonus_poc = getattr(
                            vp_config_data, "score_bonus_near_poc", vp_bonus_poc
                        )
                        vp_poc_tolerance = getattr(
                            vp_config_data, "poc_tolerance_percent", vp_poc_tolerance
                        )

                if vp_enabled and self.client:
                    vp_config = VolumeProfileConfig(
                        enabled=True,
                        lookback_timeframe=vp_timeframe,
                        lookback_candles=vp_lookback,
                        price_buckets=vp_buckets,
                        value_area_percent=vp_va_percent,
                        score_bonus_in_value_area=vp_bonus_va,
                        score_bonus_near_poc=vp_bonus_poc,
                        poc_tolerance_percent=vp_poc_tolerance,
                        cache_ttl_seconds=600,  # 10 минут кэш
                    )

                    try:
                        self.volume_filter = VolumeProfileFilter(
                            client=self.client,
                            config=vp_config,
                        )
                        logger.info(
                            f"✅ Volume Profile Filter инициализирован: "
                            f"timeframe={vp_timeframe}, lookback={vp_lookback}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Volume Profile Filter инициализация не удалась: {e}"
                        )
                        self.volume_filter = None
                else:
                    reason = []
                    if not vp_enabled:
                        reason.append("отключен в конфиге (vp_enabled=False)")
                    if not self.client:
                        reason.append("client не доступен (self.client is None)")
                    logger.warning(
                        f"⚠️ Volume Profile Filter не инициализирован: {', '.join(reason) if reason else 'неизвестная причина'} "
                        f"(vp_enabled={vp_enabled}, client={'есть' if self.client else 'None'})"
                    )
                    self.volume_filter = None
            except Exception as e:
                logger.warning(
                    f"⚠️ Volume Profile Filter инициализация не удалась: {e}"
                )
                self.volume_filter = None

            self.is_initialized = True
            logger.info("✅ FuturesSignalGenerator инициализирован")

        except Exception as e:
            logger.error(f"Ошибка инициализации FuturesSignalGenerator: {e}")
            self.is_initialized = True  # Все равно продолжаем

    async def generate_signals(
        self, current_positions: Dict = None
    ) -> List[Dict[str, Any]]:
        """
        Генерация торговых сигналов

        Args:
            current_positions: Текущие открытые позиции для CorrelationFilter

        Returns:
            Список торговых сигналов
        """
        if not self.is_initialized:
            logger.warning("SignalGenerator не инициализирован")
            return []

        try:
            signals = []

            # Генерация сигналов для каждой торговой пары
            # ✅ Детекция режима для каждого символа отдельно
            for symbol in self.scalping_config.symbols:
                # Получаем данные один раз для символа (оптимизация)
                market_data = await self._get_market_data(symbol)
                if not market_data:
                    continue

                # Обновляем режим ARM для текущего символа (используем персональный ARM если есть)
                regime_manager = self.regime_managers.get(symbol) or self.regime_manager

                if (
                    regime_manager
                    and market_data.ohlcv_data
                    and len(market_data.ohlcv_data) >= 50
                ):
                    try:
                        # Берем последнюю цену закрытия как current_price
                        current_price = market_data.ohlcv_data[-1].close

                        # Обновляем режим на основе свежих данных (detect_regime не async)
                        detection_result = regime_manager.detect_regime(
                            market_data.ohlcv_data, current_price
                        )
                        current_regime = regime_manager.get_current_regime()
                        # ✅ ОПТИМИЗАЦИЯ: Логируем режим только при изменении или раз в N минут
                        # logger.debug(f"🧠 ARM режим для {symbol}: {current_regime}")
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка обновления режима ARM для {symbol}: {e}"
                        )

                # Генерируем сигналы для текущего символа (передаем уже полученные данные)
                symbol_signals = await self._generate_symbol_signals(
                    symbol, market_data, current_positions=current_positions
                )
                signals.extend(symbol_signals)

            # Фильтрация и ранжирование сигналов
            filtered_signals = await self._filter_and_rank_signals(signals)

            # Обновление истории сигналов
            self._update_signal_history(filtered_signals)

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка генерации сигналов: {e}")
            return []

    async def _generate_symbol_signals(
        self,
        symbol: str,
        market_data: Optional[MarketData] = None,
        current_positions: Dict = None,
    ) -> List[Dict[str, Any]]:
        """Генерация сигналов для конкретной торговой пары

        Args:
            symbol: Торговая пара
            market_data: Рыночные данные (если не переданы - получим сами)
            current_positions: Текущие открытые позиции для CorrelationFilter
        """
        try:
            # Получение рыночных данных (если не переданы)
            if not market_data:
                market_data = await self._get_market_data(symbol)
            if not market_data:
                return []

            # Генерация базовых сигналов
            base_signals = await self._generate_base_signals(symbol, market_data)

            # Применение фильтров (передаем позиции для CorrelationFilter)
            filtered_signals = await self._apply_filters(
                symbol, base_signals, market_data, current_positions=current_positions
            )

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка генерации сигналов для {symbol}: {e}")
            return []

    async def _get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Получение рыночных данных - исторические свечи для индикаторов"""
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем ИСТОРИЧЕСКИЕ СВЕЧИ через REST API
            # Индикаторы (RSI, MACD и т.д.) требуют минимум 14-20 свечей для расчета!
            import time

            import aiohttp

            # Получаем последние 50 свечей 1m для расчета индикаторов
            inst_id = f"{symbol}-SWAP"
            url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1m&limit=50"

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == "0" and data.get("data"):
                            candles = data["data"]

                            # Конвертируем свечи из формата OKX в OHLCV
                            # OKX формат: [timestamp, open, high, low, close, volume, volumeCcy]
                            ohlcv_data = []
                            for candle in candles:
                                if len(candle) >= 6:
                                    ohlcv_item = OHLCV(
                                        timestamp=int(candle[0])
                                        // 1000,  # OKX возвращает в миллисекундах
                                        symbol=symbol,
                                        open=float(candle[1]),
                                        high=float(candle[2]),
                                        low=float(candle[3]),
                                        close=float(candle[4]),
                                        volume=float(candle[5]),
                                    )
                                    ohlcv_data.append(ohlcv_item)

                            if ohlcv_data:
                                # Сортируем по timestamp (старые -> новые)
                                ohlcv_data.sort(key=lambda x: x.timestamp)

                                logger.debug(
                                    f"📊 Получено {len(ohlcv_data)} свечей для {symbol}"
                                )

                                # Создаем MarketData с историческими свечами
                                return MarketData(
                                    symbol=symbol,
                                    timeframe="1m",
                                    ohlcv_data=ohlcv_data,
                                )
            logger.warning(f"⚠️ Не удалось получить исторические свечи для {symbol}")
            return None

        except Exception as e:
            logger.error(f"Ошибка получения данных для {symbol}: {e}", exc_info=True)
            return None

    async def _generate_base_signals(
        self, symbol: str, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация базовых торговых сигналов"""
        try:
            signals = []

            # Технические индикаторы
            indicator_results = self.indicator_manager.calculate_all(market_data)

            # ✅ ИСПРАВЛЕНИЕ: Конвертируем IndicatorResult в простой dict с значениями
            # indicator_results содержит объекты IndicatorResult, нужно извлечь значения
            indicators = {}
            for name, result in indicator_results.items():
                if hasattr(result, "value") and hasattr(result, "metadata"):
                    # Если это IndicatorResult, извлекаем данные правильно
                    if name.lower() == "macd":
                        # MACD: value = macd_line, metadata содержит macd_line, signal_line
                        metadata = result.metadata or {}
                        indicators["macd"] = {
                            "macd": metadata.get("macd_line", result.value),
                            "signal": metadata.get("signal_line", result.value),
                            "histogram": metadata.get("macd_line", result.value)
                            - metadata.get("signal_line", result.value),
                        }
                    elif name.lower() == "bollingerbands":
                        # BollingerBands: value = sma (middle), metadata содержит upper_band, lower_band
                        metadata = result.metadata or {}
                        indicators["bollinger_bands"] = {
                            "upper": metadata.get("upper_band", result.value),
                            "lower": metadata.get("lower_band", result.value),
                            "middle": result.value,  # middle = SMA
                        }
                    elif isinstance(result.value, dict):
                        # Для других сложных индикаторов value может быть dict
                        indicators[name.lower()] = result.value
                    else:
                        # Для простых индикаторов (RSI, ATR, SMA, EMA) - просто число
                        indicators[name.lower()] = result.value
                elif isinstance(result, dict):
                    # Если уже dict
                    indicators[name.lower()] = result
                else:
                    # Fallback
                    indicators[name.lower()] = result

            rsi_val = indicators.get("rsi", "N/A")
            macd_val = indicators.get("macd", {})
            if isinstance(macd_val, dict):
                macd_line = macd_val.get("macd", 0)
                signal_line = macd_val.get("signal", 0)
                histogram = macd_line - signal_line
                macd_str = (
                    f"macd={macd_line}, signal={signal_line}, histogram={histogram}"
                )
            else:
                macd_str = str(macd_val)

            # Добавляем EMA и BB для диагностики
            ema_12 = indicators.get("ema_12", 0)
            ema_26 = indicators.get("ema_26", 0)
            bb = indicators.get("bollinger_bands", {})
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование всех индикаторов (экономия ~30% логов)
            # Логируем только при генерации реальных сигналов (INFO уровень)
            # logger.debug(f"📊 Индикаторы для {symbol}: цена=${current_price:.2f}, RSI={rsi_val}")

            # RSI сигналы
            rsi_signals = await self._generate_rsi_signals(
                symbol, indicators, market_data
            )
            # ✅ ОПТИМИЗАЦИЯ: Логирование через INFO уровень при наличии сигналов
            # if rsi_signals:
            #     logger.debug(f"✅ RSI дал {len(rsi_signals)} сигнал(ов) для {symbol}")
            signals.extend(rsi_signals)

            # MACD сигналы
            macd_signals = await self._generate_macd_signals(
                symbol, indicators, market_data
            )
            # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование
            # if macd_signals:
            #     logger.debug(f"✅ MACD дал {len(macd_signals)} сигнал(ов) для {symbol}")
            signals.extend(macd_signals)

            # Bollinger Bands сигналы
            bb_signals = await self._generate_bollinger_signals(
                symbol, indicators, market_data
            )
            # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование
            # if bb_signals:
            #     logger.debug(f"✅ Bollinger Bands дал {len(bb_signals)} сигнал(ов) для {symbol}")
            signals.extend(bb_signals)

            # Moving Average сигналы
            ma_signals = await self._generate_ma_signals(
                symbol, indicators, market_data
            )
            signals.extend(ma_signals)

            current_regime = None
            regime_manager = self.regime_managers.get(symbol) or self.regime_manager
            if regime_manager:
                current_regime = regime_manager.get_current_regime()

            impulse_signals = self._detect_impulse_signals(
                symbol, market_data, indicators, current_regime
            )

            # ✅ ОПТИМИЗАЦИЯ: Логируем только если есть сигналы (INFO уровень) или важная информация
            # logger.debug(f"📊 Всего базовых сигналов для {symbol}: {len(signals)}")

            return signals

        except Exception as e:
            logger.error(f"Ошибка генерации базовых сигналов для {symbol}: {e}")
            return []

    def _get_regime_indicators_params(
        self, regime: str = None, symbol: str = None
    ) -> Dict:
        """
        Получить параметры индикаторов для режима из конфига.

        ПРИОРИТЕТ (от низкого к высокому):
        1. base (by_regime.{regime}.indicators - глобальные параметры режима)
        2. per-symbol (symbol_profiles.{symbol}.{regime}.indicators - per-symbol overrides)
        3. fallback (дефолтные значения)

        Args:
            regime: Режим ("trending"/"ranging"/"choppy") или None для текущего режима
            symbol: Символ для получения режима (использует персональный ARM если есть)

        Returns:
            Dict с параметрами индикаторов
        """
        # Используем персональный ARM для символа или общий
        regime_manager = None
        if symbol and symbol in self.regime_managers:
            regime_manager = self.regime_managers[symbol]
        elif self.regime_manager:
            regime_manager = self.regime_manager

        if not regime_manager:
            # Fallback: используем ranging параметры
            regime = "ranging"
        elif regime is None:
            # Получаем текущий режим от ARM
            regime = regime_manager.get_current_regime() or "ranging"

        regime_key = regime.lower() if regime else "ranging"
        base_indicators = {}
        symbol_indicators = {}

        # ✅ ПРИОРИТЕТ 1: Базовые параметры режима (by_regime.{regime}.indicators)
        try:
            scalping_config = getattr(self.config, "scalping", None)
            if scalping_config:
                adaptive_regime = getattr(scalping_config, "adaptive_regime", None)
                if adaptive_regime:
                    if isinstance(adaptive_regime, dict):
                        regime_params = adaptive_regime.get(regime_key, {})
                    else:
                        regime_params = getattr(adaptive_regime, regime_key, None)

                    if regime_params:
                        regime_params_dict = self._to_dict(regime_params)
                        indicators = regime_params_dict.get("indicators", {})
                        if indicators:
                            base_indicators = self._to_dict(indicators)
        except Exception as e:
            logger.debug(
                f"⚠️ Не удалось получить базовые параметры режима {regime_key}: {e}"
            )

        # ✅ ПРИОРИТЕТ 2: Per-symbol overrides (symbol_profiles.{symbol}.{regime}.indicators)
        if symbol:
            try:
                symbol_profiles = getattr(self, "symbol_profiles", {})
                if symbol_profiles and symbol in symbol_profiles:
                    symbol_profile = symbol_profiles[symbol]
                    symbol_profile_dict = self._to_dict(symbol_profile)
                    regime_profile = symbol_profile_dict.get(regime_key, {})
                    regime_profile_dict = self._to_dict(regime_profile)
                    indicators_config = regime_profile_dict.get("indicators", {})
                    if indicators_config:
                        symbol_indicators = self._to_dict(indicators_config)
                        logger.debug(
                            f"✅ Найдены per-symbol параметры индикаторов для {symbol} ({regime_key})"
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось получить per-symbol параметры для {symbol}: {e}"
                )

        # Объединяем: сначала базовые, затем per-symbol (per-symbol имеет приоритет)
        final_indicators = base_indicators.copy()
        final_indicators.update(symbol_indicators)  # Per-symbol перезаписывает базовые

        if final_indicators:
            logger.debug(
                f"✅ Параметры индикаторов для {regime_key}"
                + (f" ({symbol})" if symbol else "")
                + ": "
                f"RSI overbought={final_indicators.get('rsi_overbought', 70)}, "
                f"oversold={final_indicators.get('rsi_oversold', 30)}"
            )
            return final_indicators

        # ✅ ПРИОРИТЕТ 3: Fallback значения
        return {
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "ema_fast": 10,
            "ema_slow": 25,
        }

    async def _generate_rsi_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация RSI сигналов с режим-специфичными порогами"""
        signals = []

        try:
            rsi = indicators.get("rsi", 50)

            # ✅ Получаем режим-специфичные параметры для текущего символа
            regime_params = self._get_regime_indicators_params(symbol=symbol)
            rsi_oversold = regime_params.get("rsi_oversold", 30)
            rsi_overbought = regime_params.get("rsi_overbought", 70)

            # Получаем текущий режим для логирования
            regime_manager = self.regime_managers.get(symbol) or self.regime_manager
            current_regime = (
                regime_manager.get_current_regime() if regime_manager else "N/A"
            )

            # ✅ ОПТИМИЗАЦИЯ: Логируем RSI только при генерации сигналов (не каждый раз)
            # logger.debug(f"📊 RSI для {symbol}: значение={rsi:.2f}")

            # ✅ Получаем EMA для проверки тренда
            ema_fast = indicators.get("ema_12", 0)
            ema_slow = indicators.get("ema_26", 0)
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем confidence_config_rsi ДО всех условий
            # Получаем режим для confidence
            regime_name_for_conf = "ranging"  # Fallback
            try:
                if hasattr(self, "regime_manager") and self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        regime_name_for_conf = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except:
                pass

            # Получаем confidence значения из конфига
            signal_gen_config_conf = getattr(
                self.scalping_config, "signal_generator", {}
            )
            confidence_config_rsi = {}
            if isinstance(signal_gen_config_conf, dict):
                confidence_dict = signal_gen_config_conf.get("confidence", {})
                if regime_name_for_conf and confidence_dict:
                    regime_confidence = confidence_dict.get(regime_name_for_conf, {})
                    if isinstance(regime_confidence, dict):
                        confidence_config_rsi = regime_confidence
            else:
                confidence_obj = getattr(signal_gen_config_conf, "confidence", None)
                if confidence_obj and regime_name_for_conf:
                    regime_confidence = getattr(
                        confidence_obj, regime_name_for_conf, None
                    )
                    if regime_confidence:
                        confidence_config_rsi = {
                            "bullish_strong": getattr(
                                regime_confidence, "bullish_strong", 0.7
                            ),
                            "bullish_normal": getattr(
                                regime_confidence, "bullish_normal", 0.6
                            ),
                            "rsi_signal": getattr(regime_confidence, "rsi_signal", 0.6),
                        }

            # Перепроданность (покупка) - используем адаптивный порог
            if rsi < rsi_oversold:
                # Проверяем тренд через EMA - если конфликт, снижаем confidence
                is_downtrend = ema_fast < ema_slow and current_price < ema_fast

                # Нормализованная сила: от 0 до 1
                strength = min(1.0, (rsi_oversold - rsi) / rsi_oversold)

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                if is_downtrend:
                    # Конфликт: RSI oversold (LONG) vs EMA bearish (DOWN)
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        # Получаем режим
                        regime_name_rsi = "ranging"  # Fallback
                        if hasattr(self, "regime_manager") and self.regime_manager:
                            regime_obj = self.regime_manager.get_current_regime()
                            if regime_obj:
                                regime_name_rsi = (
                                    regime_obj.lower()
                                    if isinstance(regime_obj, str)
                                    else str(regime_obj).lower()
                                )
                        
                        adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_rsi, {})
                        else:
                            regime_config = getattr(adaptive_regime, regime_name_rsi, {})
                        
                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get("strength_multipliers", {})
                            conflict_multiplier = strength_multipliers.get("conflict", 0.5)
                        else:
                            strength_multipliers = getattr(regime_config, "strength_multipliers", None)
                            if strength_multipliers:
                                conflict_multiplier = getattr(strength_multipliers, "conflict", 0.5)
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить conflict_multiplier для {regime_name_rsi}: {e}")
                    
                    # ✅ ЗАДАЧА #7: Снижаем strength при конфликте
                    strength *= conflict_multiplier
                    
                    # ✅ АДАПТИВНО: Сниженная уверенность из конфига (50% от нормальной)
                    normal_conf = confidence_config_rsi.get("rsi_signal", 0.6)
                    confidence = (
                        normal_conf * 0.5
                    )  # Конфликт = 50% от нормальной уверенности
                    has_conflict = True
                    logger.debug(
                        f"⚡ RSI OVERSOLD с конфликтом для {symbol}: "
                        f"RSI oversold, но EMA/цена не bullish, "
                        f"strength снижен на {conflict_multiplier:.1%} (стало {strength:.3f})"
                    )
                else:
                    confidence = confidence_config_rsi.get(
                        "rsi_signal", 0.6
                    )  # ✅ АДАПТИВНО: Из конфига
                    has_conflict = False
                    # ✅ ОПТИМИЗАЦИЯ: Логируем только через INFO/ERROR, не DEBUG
                    # logger.debug(f"✅ RSI OVERSOLD сигнал для {symbol}: RSI={rsi:.2f}")

                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "rsi_oversold",
                        "strength": strength,
                        "price": current_price,
                        "timestamp": datetime.now(),
                        "indicator_value": rsi,
                        "confidence": confidence,
                        "has_conflict": has_conflict,  # ✅ Флаг конфликта для order_executor
                    }
                )

            # Перекупленность (продажа) - используем адаптивный порог
            elif rsi > rsi_overbought:
                # Проверяем тренд через EMA - если конфликт, снижаем confidence
                is_uptrend = ema_fast > ema_slow and current_price > ema_fast

                # Нормализованная сила: от 0 до 1
                strength = min(1.0, (rsi - rsi_overbought) / (100 - rsi_overbought))

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                # ✅ АДАПТИВНО: Используем confidence_config_rsi, полученный выше
                if is_uptrend:
                    # Конфликт: RSI overbought (SHORT) vs EMA bullish (UP)
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        # Получаем режим
                        regime_name_rsi = "ranging"  # Fallback
                        if hasattr(self, "regime_manager") and self.regime_manager:
                            regime_obj = self.regime_manager.get_current_regime()
                            if regime_obj:
                                regime_name_rsi = (
                                    regime_obj.lower()
                                    if isinstance(regime_obj, str)
                                    else str(regime_obj).lower()
                                )
                        
                        adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_rsi, {})
                        else:
                            regime_config = getattr(adaptive_regime, regime_name_rsi, {})
                        
                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get("strength_multipliers", {})
                            conflict_multiplier = strength_multipliers.get("conflict", 0.5)
                        else:
                            strength_multipliers = getattr(regime_config, "strength_multipliers", None)
                            if strength_multipliers:
                                conflict_multiplier = getattr(strength_multipliers, "conflict", 0.5)
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить conflict_multiplier для {regime_name_rsi}: {e}")
                    
                    # ✅ ЗАДАЧА #7: Снижаем strength при конфликте
                    strength *= conflict_multiplier
                    
                    # ✅ АДАПТИВНО: Сниженная уверенность из конфига (50% от нормальной)
                    normal_conf = confidence_config_rsi.get("rsi_signal", 0.6)
                    confidence = (
                        normal_conf * 0.5
                    )  # Конфликт = 50% от нормальной уверенности
                    has_conflict = True
                    logger.debug(
                        f"⚡ RSI OVERBOUGHT с конфликтом для {symbol}: "
                        f"RSI({rsi:.2f}) > overbought({rsi_overbought}), "
                        f"но EMA показывает восходящий тренд → быстрый скальп на коррекции, "
                        f"strength снижен на {conflict_multiplier:.1%} (стало {strength:.3f}), "
                        f"confidence={confidence:.1f}"
                    )
                else:
                    confidence = confidence_config_rsi.get(
                        "rsi_signal", 0.6
                    )  # ✅ АДАПТИВНО: Из конфига
                    has_conflict = False
                    # ✅ ОПТИМИЗАЦИЯ: Логируем только через INFO/ERROR, не DEBUG
                    # logger.debug(f"✅ RSI OVERBOUGHT сигнал для {symbol}: RSI={rsi:.2f}")

                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "rsi_overbought",
                        "strength": strength,
                        "price": current_price,
                        "timestamp": datetime.now(),
                        "indicator_value": rsi,
                        "confidence": confidence,
                        "has_conflict": has_conflict,  # ✅ Флаг конфликта для order_executor
                    }
                )

        except Exception as e:
            logger.error(f"Ошибка генерации RSI сигналов: {e}")

        return signals

    async def _generate_macd_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация MACD сигналов"""
        signals = []

        try:
            # ✅ АДАПТИВНО: Получаем confidence из конфига по режиму
            regime_name_macd = "ranging"  # Fallback
            try:
                if hasattr(self, "regime_manager") and self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        regime_name_macd = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except:
                pass

            signal_gen_config_macd = getattr(
                self.scalping_config, "signal_generator", {}
            )
            confidence_config_macd = {}
            if isinstance(signal_gen_config_macd, dict):
                confidence_dict = signal_gen_config_macd.get("confidence", {})
                if regime_name_macd and confidence_dict:
                    regime_confidence = confidence_dict.get(regime_name_macd, {})
                    if isinstance(regime_confidence, dict):
                        confidence_config_macd = regime_confidence
            else:
                confidence_obj = getattr(signal_gen_config_macd, "confidence", None)
                if confidence_obj and regime_name_macd:
                    regime_confidence = getattr(confidence_obj, regime_name_macd, None)
                    if regime_confidence:
                        confidence_config_macd = {
                            "macd_signal": getattr(
                                regime_confidence, "macd_signal", 0.65
                            ),
                        }

            macd_confidence = confidence_config_macd.get(
                "macd_signal", 0.65
            )  # Fallback

            macd = indicators.get("macd", {})
            macd_line = macd.get("macd", 0)
            signal_line = macd.get("signal", 0)
            # ✅ ИСПРАВЛЕНИЕ: Правильно вычисляем histogram
            histogram = macd.get("histogram", macd_line - signal_line)

            # ✅ ОПТИМИЗАЦИЯ: Логируем MACD только при генерации сигналов (не каждый раз)
            # logger.debug(f"🔍 MACD для {symbol}: histogram={histogram:.4f}")

            # ✅ ЗАДАЧА #7: Проверяем совпадение EMA и цены для MACD BULLISH
            # Для BULLISH: ema_fast>ema_slow AND price>ema_fast
            ema_fast = indicators.get("ema_12", 0)
            ema_slow = indicators.get("ema_26", 0)
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )
            
            # Пересечение MACD линии и сигнальной линии
            if macd_line > signal_line and histogram > 0:
                # ✅ ЗАДАЧА #7: Проверяем совпадение EMA и цены для BULLISH
                is_bullish_trend = ema_fast > ema_slow and current_price > ema_fast
                
                # Базовый strength из MACD histogram
                base_strength = min(abs(histogram) / 200.0, 1.0)
                
                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                if not is_bullish_trend:
                    # Конфликт: MACD bullish, но EMA/цена не bullish
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_macd, {})
                        else:
                            regime_config = getattr(adaptive_regime, regime_name_macd, {})
                        
                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get("strength_multipliers", {})
                            conflict_multiplier = strength_multipliers.get("conflict", 0.5)
                        else:
                            strength_multipliers = getattr(regime_config, "strength_multipliers", None)
                            if strength_multipliers:
                                conflict_multiplier = getattr(strength_multipliers, "conflict", 0.5)
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить conflict_multiplier для {regime_name_macd}: {e}")
                    
                    base_strength *= conflict_multiplier
                    logger.debug(
                        f"⚡ MACD BULLISH с конфликтом для {symbol}: "
                        f"MACD bullish, но EMA/цена не bullish (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, price={current_price:.2f}), "
                        f"strength снижен на {conflict_multiplier:.1%} (было {min(abs(histogram) / 200.0, 1.0):.3f}, стало {base_strength:.3f})"
                    )
                
                logger.debug(
                    f"✅ MACD BULLISH сигнал для {symbol}: macd({macd_line:.4f}) > signal({signal_line:.4f}), "
                    f"histogram={histogram:.4f} > 0, is_bullish_trend={is_bullish_trend}"
                )
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "macd_bullish",
                        "strength": base_strength,
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": histogram,
                        "confidence": macd_confidence,  # ✅ АДАПТИВНО: Из конфига
                    }
                )

            elif macd_line < signal_line and histogram < 0:
                # ✅ ЗАДАЧА #7: Проверяем совпадение EMA и цены для BEARISH
                # Для BEARISH: ema_fast<ema_slow AND price<ema_fast
                is_bearish_trend = ema_fast < ema_slow and current_price < ema_fast
                
                # Базовый strength из MACD histogram
                base_strength = min(abs(histogram) / 200.0, 1.0)
                
                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                if not is_bearish_trend:
                    # Конфликт: MACD bearish, но EMA/цена не bearish
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_macd, {})
                        else:
                            regime_config = getattr(adaptive_regime, regime_name_macd, {})
                        
                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get("strength_multipliers", {})
                            conflict_multiplier = strength_multipliers.get("conflict", 0.5)
                        else:
                            strength_multipliers = getattr(regime_config, "strength_multipliers", None)
                            if strength_multipliers:
                                conflict_multiplier = getattr(strength_multipliers, "conflict", 0.5)
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить conflict_multiplier для {regime_name_macd}: {e}")
                    
                    base_strength *= conflict_multiplier
                    logger.debug(
                        f"⚡ MACD BEARISH с конфликтом для {symbol}: "
                        f"MACD bearish, но EMA/цена не bearish (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, price={current_price:.2f}), "
                        f"strength снижен на {conflict_multiplier:.1%} (было {min(abs(histogram) / 200.0, 1.0):.3f}, стало {base_strength:.3f})"
                    )
                
                logger.debug(f"✅ MACD BEARISH сигнал для {symbol}: histogram={histogram:.4f}, is_bearish_trend={is_bearish_trend}")
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "macd_bearish",
                        "strength": base_strength,
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": histogram,
                        "confidence": macd_confidence,  # ✅ АДАПТИВНО: Из конфига
                    }
                )

        except Exception as e:
            logger.error(f"Ошибка генерации MACD сигналов: {e}")

        return signals

    async def _generate_bollinger_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация Bollinger Bands сигналов"""
        signals = []

        try:
            bb = indicators.get("bollinger_bands", {})
            upper = bb.get("upper", 0)
            lower = bb.get("lower", 0)
            middle = bb.get("middle", 0)
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            # ✅ ОПТИМИЗАЦИЯ: Логируем BB только при генерации сигналов (не каждый раз)
            # logger.debug(f"🔍 BB для {symbol}: цена={current_price:.2f}")

            # ✅ АДАПТИВНО: Получаем confidence для BB из конфига по режиму
            regime_name_bb = "ranging"  # Fallback
            try:
                if hasattr(self, "regime_manager") and self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        regime_name_bb = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except:
                pass

            signal_gen_config_bb = getattr(self.scalping_config, "signal_generator", {})
            confidence_config_bb = {}
            if isinstance(signal_gen_config_bb, dict):
                confidence_dict = signal_gen_config_bb.get("confidence", {})
                if regime_name_bb and confidence_dict:
                    regime_confidence = confidence_dict.get(regime_name_bb, {})
                    if isinstance(regime_confidence, dict):
                        confidence_config_bb = regime_confidence
            else:
                confidence_obj = getattr(signal_gen_config_bb, "confidence", None)
                if confidence_obj and regime_name_bb:
                    regime_confidence = getattr(confidence_obj, regime_name_bb, None)
                    if regime_confidence:
                        confidence_config_bb = {
                            "rsi_signal": getattr(regime_confidence, "rsi_signal", 0.6),
                        }

            bb_confidence = confidence_config_bb.get("rsi_signal", 0.6)  # Fallback

            # Отскок от нижней полосы (покупка)
            # ✅ ИСПРАВЛЕНИЕ: Не даем LONG сигнал в нисходящем тренде!
            if current_price <= lower and (middle - lower) > 0:
                # Проверяем тренд через EMA перед генерацией LONG сигнала
                ema_fast = indicators.get("ema_12", 0)
                ema_slow = indicators.get("ema_26", 0)

                # Если EMA показывает нисходящий тренд - НЕ даем LONG сигнал
                is_downtrend = ema_fast < ema_slow and current_price < ema_fast

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим, а не отменяем сигнал
                base_strength = min(
                    (lower - current_price) / (middle - lower)
                    if (middle - lower) > 0
                    else 0.5,
                    1.0,
                )
                
                if is_downtrend:
                    # Конфликт: BB oversold (LONG) vs EMA bearish (DOWN)
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_bb, {})
                        else:
                            regime_config = getattr(adaptive_regime, regime_name_bb, {})
                        
                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get("strength_multipliers", {})
                            conflict_multiplier = strength_multipliers.get("conflict", 0.5)
                        else:
                            strength_multipliers = getattr(regime_config, "strength_multipliers", None)
                            if strength_multipliers:
                                conflict_multiplier = getattr(strength_multipliers, "conflict", 0.5)
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить conflict_multiplier для {regime_name_bb}: {e}")
                    
                    # ✅ ЗАДАЧА #7: Снижаем strength при конфликте
                    base_strength *= conflict_multiplier
                    logger.debug(
                        f"⚡ BB OVERSOLD с конфликтом для {symbol}: "
                        f"цена({current_price:.2f}) <= lower({lower:.2f}), "
                        f"но EMA показывает нисходящий тренд (EMA_12={ema_fast:.2f} < EMA_26={ema_slow:.2f}), "
                        f"strength снижен на {conflict_multiplier:.1%} (стало {base_strength:.3f})"
                    )
                else:
                    logger.debug(
                        f"✅ BB OVERSOLD сигнал для {symbol}: "
                        f"цена({current_price:.2f}) <= lower({lower:.2f}), "
                        f"тренд не нисходящий (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f})"
                    )
                
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "bb_oversold",
                        "strength": base_strength,
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": current_price,
                        "confidence": bb_confidence,  # ✅ АДАПТИВНО: Из конфига
                    }
                )

            # Отскок от верхней полосы (продажа)
            # ✅ ИСПРАВЛЕНИЕ: Не даем SHORT сигнал в восходящем тренде!
            elif current_price >= upper and (upper - middle) > 0:
                # Проверяем тренд через EMA перед генерацией SHORT сигнала
                ema_fast = indicators.get("ema_12", 0)
                ema_slow = indicators.get("ema_26", 0)

                # Если EMA показывает восходящий тренд - НЕ даем SHORT сигнал
                is_uptrend = ema_fast > ema_slow and current_price > ema_fast

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим, а не отменяем сигнал
                base_strength = min(
                    (current_price - upper) / (upper - middle)
                    if (upper - middle) > 0
                    else 0.5,
                    1.0,
                )
                
                if is_uptrend:
                    # Конфликт: BB overbought (SHORT) vs EMA bullish (UP)
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_bb, {})
                        else:
                            regime_config = getattr(adaptive_regime, regime_name_bb, {})
                        
                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get("strength_multipliers", {})
                            conflict_multiplier = strength_multipliers.get("conflict", 0.5)
                        else:
                            strength_multipliers = getattr(regime_config, "strength_multipliers", None)
                            if strength_multipliers:
                                conflict_multiplier = getattr(strength_multipliers, "conflict", 0.5)
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить conflict_multiplier для {regime_name_bb}: {e}")
                    
                    # ✅ ЗАДАЧА #7: Снижаем strength при конфликте
                    base_strength *= conflict_multiplier
                    logger.debug(
                        f"⚡ BB OVERBOUGHT с конфликтом для {symbol}: "
                        f"цена({current_price:.2f}) >= upper({upper:.2f}), "
                        f"но EMA показывает восходящий тренд (EMA_12={ema_fast:.2f} > EMA_26={ema_slow:.2f}), "
                        f"strength снижен на {conflict_multiplier:.1%} (стало {base_strength:.3f})"
                    )
                else:
                    logger.debug(
                        f"✅ BB OVERBOUGHT сигнал для {symbol}: "
                        f"цена({current_price:.2f}) >= upper({upper:.2f}), "
                        f"тренд не восходящий (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f})"
                    )
                
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "bb_overbought",
                        "strength": base_strength,
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": current_price,
                        "confidence": bb_confidence,  # ✅ АДАПТИВНО: Из конфига
                    }
                )

        except Exception as e:
            logger.error(f"Ошибка генерации Bollinger Bands сигналов: {e}")

        return signals

    async def _generate_ma_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация Moving Average сигналов с проверкой направления движения цены"""
        signals = []

        try:
            ma_fast = indicators.get("ema_12", 0)
            ma_slow = indicators.get("ema_26", 0)
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            # ✅ АДАПТИВНО: Получаем параметры signal_generator из конфига (ПЕРЕД использованием)
            # Получаем режим рынка для всех параметров
            regime_name_ma = "ranging"  # Fallback значение
            try:
                if hasattr(self, "regime_manager") and self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        regime_name_ma = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось получить режим рынка: {e}, используем fallback 'ranging'"
                )

            # ✅ АДАПТИВНО: Получаем параметры signal_generator из конфига (ПЕРЕД использованием)
            # Инициализируем fallback значения на случай ошибки
            price_change_threshold = 0.0005  # Fallback
            strength_multiplier = 2000.0  # Fallback
            strength_reduction_neutral = 0.9  # Fallback

            try:
                signal_gen_config_ma = getattr(
                    self.scalping_config, "signal_generator", {}
                )
                if isinstance(signal_gen_config_ma, dict):
                    price_change_threshold = signal_gen_config_ma.get(
                        "price_change_threshold", 0.0005
                    )
                    strength_multiplier = signal_gen_config_ma.get(
                        "strength_multiplier", 2000.0
                    )
                    strength_reduction_neutral = signal_gen_config_ma.get(
                        "strength_reduction_neutral", 0.9
                    )
                elif signal_gen_config_ma:
                    price_change_threshold = getattr(
                        signal_gen_config_ma, "price_change_threshold", 0.0005
                    )
                    strength_multiplier = getattr(
                        signal_gen_config_ma, "strength_multiplier", 2000.0
                    )
                    strength_reduction_neutral = getattr(
                        signal_gen_config_ma, "strength_reduction_neutral", 0.9
                    )
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось получить параметры signal_generator из конфига: {e}, используем fallback значения"
                )

            # ✅ УЛУЧШЕНИЕ: Проверяем направление движения цены (последние 3-5 свечей)
            price_direction = None  # "up", "down", "neutral"
            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= 5:
                # Берем последние 5 свечей для определения направления
                recent_candles = market_data.ohlcv_data[-5:]
                closes = [c.close for c in recent_candles]

                # Сравниваем первую и последнюю цену в окне
                price_change = (
                    (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0
                )

                # ✅ АДАПТИВНО: Порог изменения цены из конфига (определяется выше)
                if price_change > price_change_threshold:  # Рост > порог
                    price_direction = "up"
                elif price_change < -price_change_threshold:  # Падение > порог
                    price_direction = "down"
                else:
                    price_direction = "neutral"

                # Также проверяем последние 3 свечи для более быстрой реакции
                if len(recent_candles) >= 3:
                    short_closes = [c.close for c in recent_candles[-3:]]
                    short_change = (
                        (short_closes[-1] - short_closes[0]) / short_closes[0]
                        if short_closes[0] > 0
                        else 0
                    )
                    # Если короткий тренд сильнее - используем его
                    if abs(short_change) > abs(price_change) * 1.5:
                        if short_change > price_change_threshold:
                            price_direction = "up"
                        elif short_change < -price_change_threshold:
                            price_direction = "down"

            # ✅ ДИАГНОСТИКА: Логируем значения для анализа
            logger.debug(
                f"🔍 MA для {symbol}: EMA_12={ma_fast:.2f}, EMA_26={ma_slow:.2f}, "
                f"цена={current_price:.2f}, ma_fast>ma_slow={ma_fast > ma_slow}, "
                f"цена>ma_fast={current_price > ma_fast if ma_fast > 0 else False}, "
                f"направление_цены={price_direction}"
            )

            # ✅ УЛУЧШЕНИЕ: Проверка минимальной разницы EMA для генерации сигнала
            # Избегаем ложных сигналов при минимальной разнице EMA
            ma_difference_pct = (
                abs(ma_fast - ma_slow) / ma_slow * 100 if ma_slow > 0 else 0
            )

            # ✅ АДАПТИВНО: Получаем min_ma_difference_pct из конфига (ПРИОРИТЕТ: per-symbol > режим > fallback)
            min_ma_difference_pct = 0.1  # Fallback значение
            try:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сначала проверяем per-symbol overrides из symbol_profiles
                symbol_profile_found = False
                try:
                    adaptive_regime = getattr(
                        self.scalping_config, "adaptive_regime", {}
                    )
                    adaptive_dict = (
                        adaptive_regime
                        if isinstance(adaptive_regime, dict)
                        else (
                            adaptive_regime.__dict__
                            if hasattr(adaptive_regime, "__dict__")
                            else {}
                        )
                    )
                    symbol_profiles = adaptive_dict.get("symbol_profiles", {})

                    if symbol and symbol_profiles and symbol in symbol_profiles:
                        symbol_profile = symbol_profiles[symbol]
                        symbol_profile_dict = (
                            symbol_profile
                            if isinstance(symbol_profile, dict)
                            else (
                                symbol_profile.__dict__
                                if hasattr(symbol_profile, "__dict__")
                                else {}
                            )
                        )
                        regime_profile = symbol_profile_dict.get(regime_name_ma, {})
                        regime_profile_dict = (
                            regime_profile
                            if isinstance(regime_profile, dict)
                            else (
                                regime_profile.__dict__
                                if hasattr(regime_profile, "__dict__")
                                else {}
                            )
                        )
                        indicators_config = regime_profile_dict.get("indicators", {})
                        indicators_dict = (
                            indicators_config
                            if isinstance(indicators_config, dict)
                            else (
                                indicators_config.__dict__
                                if hasattr(indicators_config, "__dict__")
                                else {}
                            )
                        )

                        if "min_ma_difference_pct" in indicators_dict:
                            min_ma_difference_pct = float(
                                indicators_dict["min_ma_difference_pct"]
                            )
                            symbol_profile_found = True
                            logger.debug(
                                f"✅ PER-SYMBOL: min_ma_difference_pct для {symbol} ({regime_name_ma}): {min_ma_difference_pct}%"
                            )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Не удалось получить per-symbol min_ma_difference_pct для {symbol}: {e}"
                    )

                # ✅ Если per-symbol не найден - используем глобальный порог режима
                if not symbol_profile_found:
                    try:
                        adaptive_regime = getattr(
                            self.scalping_config, "adaptive_regime", {}
                        )
                        adaptive_dict = (
                            adaptive_regime
                            if isinstance(adaptive_regime, dict)
                            else (
                                adaptive_regime.__dict__
                                if hasattr(adaptive_regime, "__dict__")
                                else {}
                            )
                        )

                        # Ищем режим в конфиге
                        regime_config = adaptive_dict.get(regime_name_ma, {})
                        regime_config_dict = (
                            regime_config
                            if isinstance(regime_config, dict)
                            else (
                                regime_config.__dict__
                                if hasattr(regime_config, "__dict__")
                                else {}
                            )
                        )

                        # Получаем indicators из режима
                        indicators_config = regime_config_dict.get("indicators", {})
                        indicators_dict = (
                            indicators_config
                            if isinstance(indicators_config, dict)
                            else (
                                indicators_config.__dict__
                                if hasattr(indicators_config, "__dict__")
                                else {}
                            )
                        )

                        if "min_ma_difference_pct" in indicators_dict:
                            min_ma_difference_pct = float(
                                indicators_dict["min_ma_difference_pct"]
                            )
                            logger.debug(
                                f"✅ ГЛОБАЛЬНЫЙ: min_ma_difference_pct для {regime_name_ma}: {min_ma_difference_pct}%"
                            )
                        elif isinstance(adaptive_regime, dict) or hasattr(
                            adaptive_regime, regime_name_ma
                        ):
                            # Альтернативный способ доступа через Pydantic объект
                            regime_config = getattr(
                                adaptive_regime, regime_name_ma, None
                            )
                            if regime_config:
                                indicators_config = getattr(
                                    regime_config, "indicators", None
                                )
                                if indicators_config:
                                    min_ma_difference_pct = getattr(
                                        indicators_config, "min_ma_difference_pct", 0.1
                                    )
                                    logger.debug(
                                        f"✅ ГЛОБАЛЬНЫЙ (Pydantic): min_ma_difference_pct для {regime_name_ma}: {min_ma_difference_pct}%"
                                    )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить глобальный min_ma_difference_pct для {regime_name_ma}: {e}"
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось получить адаптивный min_ma_difference_pct: {e}, используем fallback 0.1%"
                )

            # ✅ АДАПТИВНО: Получаем confidence значения по режиму
            confidence_config = {}
            if isinstance(signal_gen_config_ma, dict):
                confidence_dict = signal_gen_config_ma.get("confidence", {})
                if regime_name_ma and confidence_dict:
                    regime_confidence = confidence_dict.get(regime_name_ma, {})
                    if isinstance(regime_confidence, dict):
                        confidence_config = regime_confidence
            else:
                confidence_obj = getattr(signal_gen_config_ma, "confidence", None)
                if confidence_obj and regime_name_ma:
                    regime_confidence = getattr(confidence_obj, regime_name_ma, None)
                    if regime_confidence:
                        confidence_config = {
                            "bullish_strong": getattr(
                                regime_confidence, "bullish_strong", 0.7
                            ),
                            "bullish_normal": getattr(
                                regime_confidence, "bullish_normal", 0.6
                            ),
                            "bearish_strong": getattr(
                                regime_confidence, "bearish_strong", 0.7
                            ),
                            "bearish_normal": getattr(
                                regime_confidence, "bearish_normal", 0.6
                            ),
                            "macd_signal": getattr(
                                regime_confidence, "macd_signal", 0.65
                            ),
                            "rsi_signal": getattr(regime_confidence, "rsi_signal", 0.6),
                        }

            # Fallback confidence значения
            if not confidence_config:
                confidence_config = {
                    "bullish_strong": 0.7,
                    "bullish_normal": 0.6,
                    "bearish_strong": 0.7,
                    "bearish_normal": 0.6,
                    "macd_signal": 0.65,
                    "rsi_signal": 0.6,
                }

            # Пересечение быстрой и медленной MA
            if ma_fast > ma_slow and current_price > ma_fast and ma_slow > 0:
                # ✅ УЛУЧШЕНИЕ: Проверяем минимальную разницу EMA
                if ma_difference_pct < min_ma_difference_pct:
                    logger.debug(
                        f"⚠️ MA BULLISH сигнал ОТМЕНЕН для {symbol}: "
                        f"разница EMA слишком мала ({ma_difference_pct:.3f}% < {min_ma_difference_pct}%)"
                    )
                # ✅ УЛУЧШЕНИЕ: Не даем bullish сигнал если цена падает
                elif price_direction == "down":
                    logger.debug(
                        f"⚠️ MA BULLISH сигнал ОТМЕНЕН для {symbol}: "
                        f"EMA показывает bullish, но цена падает (направление={price_direction})"
                    )
                else:
                    # ✅ ИСПРАВЛЕНИЕ: Правильный расчет strength для MA BULLISH
                    # strength = процентное изменение между EMA (в долях, не процентах)
                    strength = (ma_fast - ma_slow) / ma_slow  # Например: 0.0005 = 0.05%
                    # ✅ АДАПТИВНО: Множитель strength из конфига
                    # Логика: разница 0.05% → strength = 0.05% * multiplier = 100% = 1.0
                    # Разница 0.01% → strength = 0.01% * multiplier = 20% = 0.2
                    # Это позволит даже маленьким разницам EMA давать разумный strength
                    strength = min(
                        1.0, abs(strength) * strength_multiplier
                    )  # ✅ АДАПТИВНО: Из конфига
                    # Снижаем силу сигнала если направление neutral (не подтверждено)
                    if price_direction == "neutral":
                        strength *= (
                            strength_reduction_neutral  # ✅ АДАПТИВНО: Из конфига
                        )

                    logger.debug(
                        f"✅ MA BULLISH сигнал для {symbol}: EMA_12({ma_fast:.2f}) > EMA_26({ma_slow:.2f}), "
                        f"цена({current_price:.2f}) > EMA_12, направление={price_direction}, strength={strength:.4f}"
                    )
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "ma_bullish",
                            "strength": strength,
                            "price": market_data.ohlcv_data[-1].close
                            if market_data.ohlcv_data
                            else 0.0,
                            "timestamp": datetime.now(),
                            "indicator_value": ma_fast,
                            "confidence": confidence_config.get("bullish_strong", 0.7)
                            if price_direction == "up"
                            else confidence_config.get(
                                "bullish_normal", 0.5
                            ),  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

            elif ma_fast < ma_slow and current_price < ma_fast and ma_slow > 0:
                # ✅ УЛУЧШЕНИЕ: Проверяем минимальную разницу EMA
                if ma_difference_pct < min_ma_difference_pct:
                    logger.debug(
                        f"⚠️ MA BEARISH сигнал ОТМЕНЕН для {symbol}: "
                        f"разница EMA слишком мала ({ma_difference_pct:.3f}% < {min_ma_difference_pct}%)"
                    )
                # ✅ УЛУЧШЕНИЕ: Не даем bearish сигнал если цена растет
                elif price_direction == "up":
                    logger.debug(
                        f"⚠️ MA BEARISH сигнал ОТМЕНЕН для {symbol}: "
                        f"EMA показывает bearish, но цена растет (направление={price_direction})"
                    )
                else:
                    # ✅ ИСПРАВЛЕНИЕ: Правильный расчет strength для MA BEARISH
                    # strength = процентное изменение между EMA (в долях, не процентах)
                    strength = (ma_slow - ma_fast) / ma_slow  # Например: 0.0005 = 0.05%
                    # ✅ АДАПТИВНО: Множитель strength из конфига
                    # Логика: разница 0.05% → strength = 0.05% * multiplier = 100% = 1.0
                    # Разница 0.01% → strength = 0.01% * multiplier = 20% = 0.2
                    # Это позволит даже маленьким разницам EMA давать разумный strength
                    strength = min(
                        1.0, abs(strength) * strength_multiplier
                    )  # ✅ АДАПТИВНО: Из конфига
                    # Снижаем силу сигнала если направление neutral
                    if price_direction == "neutral":
                        strength *= (
                            strength_reduction_neutral  # ✅ АДАПТИВНО: Из конфига
                        )

                    logger.debug(
                        f"✅ MA BEARISH сигнал для {symbol}: EMA_12({ma_fast:.2f}) < EMA_26({ma_slow:.2f}), "
                        f"цена({current_price:.2f}) < EMA_12, направление={price_direction}, strength={strength:.4f}"
                    )
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "ma_bearish",
                            "strength": strength,
                            "price": market_data.ohlcv_data[-1].close
                            if market_data.ohlcv_data
                            else 0.0,
                            "timestamp": datetime.now(),
                            "indicator_value": ma_fast,
                            "confidence": confidence_config.get("bearish_strong", 0.7)
                            if price_direction == "down"
                            else confidence_config.get(
                                "bearish_normal", 0.5
                            ),  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

        except Exception as e:
            logger.error(f"Ошибка генерации Moving Average сигналов: {e}")

        return signals

    def _detect_impulse_signals(
        self,
        symbol: str,
        market_data: MarketData,
        indicators: Dict[str, Any],
        current_regime: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.impulse_config or not getattr(
            self.impulse_config, "enabled", False
        ):
            return []

        config = self.impulse_config
        regime_key = (current_regime or "ranging").lower()
        symbol_profile = self.symbol_profiles.get(symbol, {})
        regime_profile = symbol_profile.get(regime_key, {})
        impulse_profile = self._to_dict(regime_profile.get("impulse", {}))

        detection_keys = {
            "lookback_candles",
            "min_body_atr_ratio",
            "min_volume_ratio",
            "pivot_lookback",
            "min_breakout_percent",
            "max_wick_ratio",
        }
        detection_values = {
            "lookback_candles": config.lookback_candles,
            "min_body_atr_ratio": config.min_body_atr_ratio,
            "min_volume_ratio": config.min_volume_ratio,
            "pivot_lookback": config.pivot_lookback,
            "min_breakout_percent": config.min_breakout_percent,
            "max_wick_ratio": config.max_wick_ratio,
        }
        for key in detection_keys:
            if impulse_profile.get(key) is not None:
                detection_values[key] = impulse_profile[key]

        candles = market_data.ohlcv_data
        if not candles or len(candles) < detection_values["lookback_candles"]:
            return []

        current_candle = candles[-1]
        prev_candles = candles[-(detection_values["lookback_candles"] + 1) : -1]
        if not prev_candles:
            return []

        def _calc_atr(candles_seq: List[OHLCV]) -> float:
            if len(candles_seq) < 2:
                return 0.0
            trs: List[float] = []
            prev_close = candles_seq[0].close
            for candle in candles_seq[1:]:
                high = candle.high
                low = candle.low
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close),
                )
                trs.append(tr)
                prev_close = candle.close
            return sum(trs) / len(trs) if trs else 0.0

        atr_period = 14
        atr_slice = candles[-(atr_period + 1) :]
        atr_value = _calc_atr(atr_slice) if atr_slice else 0.0
        if atr_value <= 0:
            return []

        body = current_candle.close - current_candle.open
        direction = "buy" if body >= 0 else "sell"
        body_abs = abs(body)
        body_ratio = body_abs / atr_value

        avg_volume = sum(c.volume for c in prev_candles) / max(len(prev_candles), 1)
        if (
            avg_volume <= 0
            or current_candle.volume < avg_volume * detection_values["min_volume_ratio"]
        ):
            return []

        pivot_level = None
        if direction == "buy":
            upper_wick = current_candle.high - current_candle.close
            reference_highs = candles[-(detection_values["pivot_lookback"] + 1) : -1]
            pivot_level = max(c.high for c in reference_highs)
            breakout_ok = current_candle.close >= pivot_level * (
                1 + detection_values["min_breakout_percent"]
            )
            wick_ratio = (upper_wick / body_abs) if body_abs > 0 else 0
            if not breakout_ok or wick_ratio > detection_values["max_wick_ratio"]:
                return []
        else:
            upper_wick = current_candle.high - current_candle.open
            reference_lows = candles[-(detection_values["pivot_lookback"] + 1) : -1]
            pivot_level = min(c.low for c in reference_lows)
            breakout_ok = current_candle.close <= pivot_level * (
                1 - detection_values["min_breakout_percent"]
            )
            wick_ratio = (upper_wick / body_abs) if body_abs > 0 else 0
            if not breakout_ok or wick_ratio > detection_values["max_wick_ratio"]:
                return []

        strength = min(
            1.0,
            body_ratio / detection_values["min_body_atr_ratio"],
        )
        meta = {
            "body_ratio_atr": round(body_ratio, 3),
            "volume_ratio": round(current_candle.volume / max(avg_volume, 1e-9), 3),
            "pivot_level": pivot_level,
            "close": current_candle.close,
            "high": current_candle.high,
            "low": current_candle.low,
        }

        logger.info(
            f"🚀 Импульсный сигнал {symbol} {direction.upper()}: тело/ATR={body_ratio:.2f}, "
            f"объём x{meta['volume_ratio']:.2f}, пробой уровня {pivot_level:.4f}"
        )

        relax_cfg = getattr(config, "relax", None)
        trailing_cfg = getattr(config, "trailing", None)

        signal = {
            "symbol": symbol,
            "side": "buy" if direction == "buy" else "sell",
            "type": "impulse_breakout",
            "strength": strength,
            "price": current_candle.close,
            "timestamp": datetime.now(),
            "indicator_value": body_ratio,
            "confidence": 0.9,
            "is_impulse": True,
            "impulse_meta": meta,
        }

        relax_payload: Dict[str, float] = {}
        if relax_cfg:
            relax_payload = {
                "liquidity": getattr(relax_cfg, "liquidity_multiplier", 1.0),
                "order_flow": getattr(relax_cfg, "order_flow_multiplier", 1.0),
                "allow_mtf_bypass": getattr(relax_cfg, "allow_mtf_bypass", False),
                "bypass_correlation": getattr(relax_cfg, "bypass_correlation", False),
            }
        if "relax" in impulse_profile:
            relax_overrides = self._to_dict(impulse_profile.get("relax", {}))
            relax_payload.update(relax_overrides)
        if relax_payload:
            signal["impulse_relax"] = relax_payload

        trailing_payload: Dict[str, float] = {}
        if trailing_cfg:
            trailing_payload = {
                "initial_trail": getattr(trailing_cfg, "initial_trail", 0.0),
                "max_trail": getattr(trailing_cfg, "max_trail", 0.0),
                "min_trail": getattr(trailing_cfg, "min_trail", 0.0),
                "step_profit": getattr(trailing_cfg, "step_profit", 0.0),
                "step_trail": getattr(trailing_cfg, "step_trail", 0.0),
                "aggressive_max_trail": getattr(
                    trailing_cfg, "aggressive_max_trail", None
                ),
                "loss_cut_percent": getattr(trailing_cfg, "loss_cut_percent", None),
                "timeout_minutes": getattr(trailing_cfg, "timeout_minutes", None),
            }
        if "trailing" in impulse_profile:
            trailing_overrides = self._to_dict(impulse_profile.get("trailing", {}))
            trailing_payload = self._deep_merge_dict(
                trailing_payload, trailing_overrides
            )
        if trailing_payload:
            signal["impulse_trailing"] = trailing_payload

        return [signal]

    async def _apply_filters(
        self,
        symbol: str,
        signals: List[Dict[str, Any]],
        market_data: MarketData,
        current_positions: Dict = None,
    ) -> List[Dict[str, Any]]:
        """Применение фильтров к сигналам

        Args:
            symbol: Торговая пара
            signals: Список сигналов
            market_data: Рыночные данные
            current_positions: Текущие открытые позиции для CorrelationFilter
        """
        try:
            filtered_signals = []

            for signal in signals:
                # ✅ КОНФИГУРИРУЕМАЯ Блокировка SHORT/LONG сигналов по конфигу (по умолчанию разрешены обе стороны)
                signal_side = signal.get("side", "").lower()
                allow_short = getattr(
                    self.config.scalping, "allow_short_positions", True
                )
                allow_long = getattr(self.config.scalping, "allow_long_positions", True)

                if signal_side == "sell" and not allow_short:
                    logger.debug(
                        f"⛔ SHORT сигнал заблокирован для {symbol}: "
                        f"allow_short_positions={allow_short} (только LONG стратегия)"
                    )
                    continue
                elif signal_side == "buy" and not allow_long:
                    logger.debug(
                        f"⛔ LONG сигнал заблокирован для {symbol}: "
                        f"allow_long_positions={allow_long} (только SHORT стратегия)"
                    )
                    continue

                # ✅ Добавляем текущие позиции в сигнал для CorrelationFilter
                if current_positions:
                    signal["current_positions"] = current_positions

                impulse_relax = signal.get("impulse_relax") or {}
                is_impulse = signal.get("is_impulse", False)

                regime_manager = self.regime_managers.get(symbol) or self.regime_manager
                current_regime_name = (
                    regime_manager.get_current_regime() if regime_manager else None
                )
                if current_regime_name:
                    signal["regime"] = current_regime_name

                symbol_profile = self.symbol_profiles.get(symbol, {})
                regime_key = (current_regime_name or "ranging").lower()
                regime_profile = symbol_profile.get(regime_key, {})
                filters_profile = self._to_dict(regime_profile.get("filters", {}))

                # ✅ ИСПРАВЛЕНИЕ: Объединяем режим-специфичные параметры из by_regime с per-symbol overrides
                if (
                    hasattr(self, "_extract_regime_params")
                    and self._extract_regime_params
                ):
                    base_regime_params = self._extract_regime_params(regime_key)
                    base_regime_filters = self._to_dict(
                        base_regime_params.get("filters", {})
                    )
                    # Объединяем: сначала базовые параметры режима, затем per-symbol overrides
                    filters_profile = self._deep_merge_dict(
                        base_regime_filters, filters_profile
                    )

                liquidity_override = self._to_dict(filters_profile.get("liquidity", {}))
                order_flow_override = self._to_dict(
                    filters_profile.get("order_flow", {})
                )
                funding_override = self._to_dict(filters_profile.get("funding", {}))
                volatility_override = self._to_dict(
                    filters_profile.get("volatility", {})
                )

                symbol_impulse_profile = self._to_dict(
                    regime_profile.get("impulse", {})
                )
                if is_impulse and symbol_impulse_profile:
                    override_relax = self._to_dict(
                        symbol_impulse_profile.get("relax", {})
                    )
                    if override_relax:
                        impulse_relax.update(override_relax)
                    override_trailing = self._to_dict(
                        symbol_impulse_profile.get("trailing", {})
                    )
                    if override_trailing:
                        merged_trailing = self._deep_merge_dict(
                            signal.get("impulse_trailing", {}), override_trailing
                        )
                        signal["impulse_trailing"] = merged_trailing

                liquidity_relax = 1.0
                order_flow_relax = 1.0
                if is_impulse:
                    try:
                        liquidity_relax = float(impulse_relax.get("liquidity", 1.0))
                    except (TypeError, ValueError):
                        liquidity_relax = 1.0
                    try:
                        order_flow_relax = float(impulse_relax.get("order_flow", 1.0))
                    except (TypeError, ValueError):
                        order_flow_relax = 1.0
                bypass_correlation = bool(
                    is_impulse and impulse_relax.get("bypass_correlation", False)
                )
                bypass_mtf = bool(
                    is_impulse and impulse_relax.get("allow_mtf_bypass", False)
                )

                # ✅ ИСПРАВЛЕНИЕ: Проверяем что фильтры инициализированы перед вызовом
                # Проверка режима рынка (используем персональный ARM для символа если есть)
                regime_manager = self.regime_managers.get(symbol) or self.regime_manager
                current_regime_name = (
                    regime_manager.get_current_regime() if regime_manager else None
                )
                if regime_manager:
                    try:
                        if not await regime_manager.is_signal_valid(
                            signal, market_data
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован ARM")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки ARM для {symbol}: {e}, пропускаем фильтр"
                        )

                # ✅ Проверка корреляции (если фильтр инициализирован)
                # Обновляем параметры CorrelationFilter из текущего режима перед проверкой
                if self.correlation_filter:
                    if bypass_correlation:
                        logger.debug(
                            f"🔓 CorrelationFilter пропущен (impulse) для {symbol}"
                        )
                    else:
                        try:
                            # Получаем параметры CorrelationFilter из текущего режима ARM
                            if regime_manager:
                                regime_params = regime_manager.get_current_parameters()
                                if regime_params and hasattr(regime_params, "modules"):
                                    # Обновляем параметры CorrelationFilter из текущего режима
                                    from src.strategies.modules.correlation_filter import \
                                        CorrelationFilterConfig

                                    corr_modules = regime_params.modules
                                    corr_new_config = CorrelationFilterConfig(
                                        enabled=True,
                                        correlation_threshold=corr_modules.correlation_threshold,
                                        max_correlated_positions=corr_modules.max_correlated_positions,
                                        block_same_direction_only=corr_modules.block_same_direction_only,
                                    )
                                    self.correlation_filter.update_parameters(
                                        corr_new_config
                                    )

                            if not await self.correlation_filter.is_signal_valid(
                                signal, market_data
                            ):
                                logger.debug(
                                    f"🔍 Сигнал {symbol} отфильтрован CorrelationFilter"
                                )
                                continue
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Ошибка проверки CorrelationFilter для {symbol}: {e}, пропускаем фильтр"
                            )

                # ✅ Проверка мультитаймфрейма (если фильтр инициализирован)
                # Обновляем параметры MTF из текущего режима перед проверкой
                if self.mtf_filter:
                    if bypass_mtf:
                        logger.info(f"🔓 MTF пропущен (impulse) для {symbol}")
                    else:
                        try:
                            # Получаем параметры MTF из текущего режима ARM
                            if regime_manager:
                                regime_params = regime_manager.get_current_parameters()
                                if regime_params and hasattr(regime_params, "modules"):
                                    # Обновляем параметры MTF из текущего режима
                                    from src.strategies.modules.multi_timeframe import \
                                        MTFConfig

                                    mtf_modules = regime_params.modules
                                    # ✅ ИСПРАВЛЕНО: Округляем score_bonus до int (может быть float в конфиге)
                                    score_bonus_value = getattr(
                                        mtf_modules, "mtf_score_bonus", 1
                                    )
                                    if isinstance(score_bonus_value, float):
                                        score_bonus_value = int(
                                            round(score_bonus_value)
                                        )

                                    mtf_new_config = MTFConfig(
                                        confirmation_timeframe=mtf_modules.mtf_confirmation_timeframe,
                                        score_bonus=score_bonus_value,  # ✅ ИСПРАВЛЕНО: Округляем float до int
                                        block_opposite=mtf_modules.mtf_block_opposite,  # ✅ Используем из режима
                                        block_neutral=getattr(
                                            mtf_modules, "mtf_block_neutral", False
                                        ),  # ✅ НОВОЕ: Блокировка NEUTRAL трендов
                                        ema_fast_period=8,
                                        ema_slow_period=21,
                                        cache_ttl_seconds=30,
                                    )
                                    self.mtf_filter.update_parameters(mtf_new_config)

                            if not await self.mtf_filter.is_signal_valid(
                                signal, market_data
                            ):
                                logger.debug(f"🔍 Сигнал {symbol} отфильтрован MTF")
                                continue
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Ошибка проверки MTF для {symbol}: {e}, пропускаем фильтр"
                            )

                # ✅ Проверка pivot points (если фильтр инициализирован)
                # Обновляем параметры PivotPoints из текущего режима перед проверкой
                if self.pivot_filter:
                    try:
                        # Получаем параметры PivotPoints из текущего режима ARM
                        if regime_manager:
                            regime_params = regime_manager.get_current_parameters()
                            if regime_params and hasattr(regime_params, "modules"):
                                # Обновляем параметры PivotPoints напрямую в config
                                pivot_modules = regime_params.modules
                                self.pivot_filter.config.level_tolerance_percent = (
                                    pivot_modules.pivot_level_tolerance_percent
                                )
                                self.pivot_filter.config.score_bonus_near_level = (
                                    pivot_modules.pivot_score_bonus_near_level
                                )
                                # Примечание: use_last_n_days обычно не меняется при проверке

                        if not await self.pivot_filter.is_signal_valid(
                            signal, market_data
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован PivotPoints")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки PivotPoints для {symbol}: {e}, пропускаем фильтр"
                        )

                # ✅ Проверка volume profile (если фильтр инициализирован)
                # Обновляем параметры VolumeProfile из текущего режима перед проверкой
                if self.volume_filter:
                    try:
                        # Получаем параметры VolumeProfile из текущего режима ARM
                        if regime_manager:
                            regime_params = regime_manager.get_current_parameters()
                            if regime_params and hasattr(regime_params, "modules"):
                                # Обновляем параметры VolumeProfile напрямую в config
                                vp_modules = regime_params.modules
                                self.volume_filter.config.score_bonus_in_value_area = (
                                    vp_modules.vp_score_bonus_in_value_area
                                )
                                self.volume_filter.config.score_bonus_near_poc = (
                                    vp_modules.vp_score_bonus_near_poc
                                )
                                self.volume_filter.config.poc_tolerance_percent = (
                                    vp_modules.vp_poc_tolerance_percent
                                )
                                # Примечание: lookback_candles обычно не меняется при проверке

                        if not await self.volume_filter.is_signal_valid(
                            signal, market_data
                        ):
                            logger.debug(
                                f"🔍 Сигнал {symbol} отфильтрован VolumeProfile"
                            )
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки VolumeProfile для {symbol}: {e}, пропускаем фильтр"
                        )

                liquidity_snapshot = None
                if self.liquidity_filter:
                    try:
                        (
                            liquidity_ok,
                            liquidity_snapshot,
                        ) = await self.liquidity_filter.evaluate(
                            symbol,
                            regime=current_regime_name,
                            relax_multiplier=liquidity_relax,
                            thresholds_override=liquidity_override,
                        )
                        if not liquidity_ok:
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ LiquidityFilter ошибка для {symbol}: {e}, пропускаем фильтр"
                        )

                if self.order_flow_filter:
                    try:
                        order_flow_snapshot = liquidity_snapshot
                        if not await self.order_flow_filter.is_signal_valid(
                            symbol,
                            signal.get("side", ""),
                            snapshot=order_flow_snapshot,
                            regime=current_regime_name,
                            relax_multiplier=order_flow_relax,
                            overrides=order_flow_override,
                        ):
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ OrderFlowFilter ошибка для {symbol}: {e}, пропускаем фильтр"
                        )

                if self.funding_filter:
                    try:
                        if not await self.funding_filter.is_signal_valid(
                            symbol,
                            signal.get("side", ""),
                            overrides=funding_override,
                        ):
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ FundingRateFilter ошибка для {symbol}: {e}, пропускаем фильтр"
                        )

                if self.volatility_filter:
                    try:
                        if not self.volatility_filter.is_signal_valid(
                            symbol,
                            market_data,
                            overrides=volatility_override,
                        ):
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ VolatilityRegimeFilter ошибка для {symbol}: {e}, пропускаем фильтр"
                        )

                # ✅ НОВОЕ: Проверка Momentum Filter (из статьи Momentum Trading Strategy)
                if self.momentum_filter:
                    try:
                        # Получаем candles из market_data
                        candles = (
                            market_data.ohlcv_data
                            if market_data and market_data.ohlcv_data
                            else []
                        )
                        current_price = signal.get("price", 0.0)
                        if not current_price and candles:
                            current_price = candles[-1].close

                        # Получаем уровень из сигнала (если есть pivot или другой уровень)
                        level = signal.get("pivot_level") or signal.get("level")

                        # ✅ АДАПТИВНО: Передаем режим рынка в MomentumFilter
                        # Проверяем критерии Momentum Trading
                        is_valid, reason = await self.momentum_filter.evaluate(
                            symbol=symbol,
                            candles=candles,
                            current_price=current_price,
                            level=level,
                            market_regime=current_regime_name,  # ✅ АДАПТИВНО: Режим для адаптации порогов
                        )

                        if not is_valid:
                            logger.debug(
                                f"🔍 Сигнал {symbol} отфильтрован MomentumFilter: {reason}"
                            )
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ MomentumFilter ошибка для {symbol}: {e}, пропускаем фильтр"
                        )

                # Адаптация под Futures специфику
                futures_signal = await self._adapt_signal_for_futures(signal)
                filtered_signals.append(futures_signal)

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка применения фильтров: {e}", exc_info=True)
            # В случае ошибки возвращаем сигналы без фильтрации
            return signals

    async def _adapt_signal_for_futures(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Адаптация сигнала под Futures специфику"""
        try:
            # Добавление Futures-специфичных параметров
            futures_signal = signal.copy()

            # Учет левериджа в силе сигнала
            leverage = 3  # Futures по умолчанию 3x
            futures_signal["leverage_adjusted_strength"] = signal["strength"] * (
                leverage / 3
            )

            # Добавление параметров маржи
            futures_signal["margin_required"] = True
            futures_signal["liquidation_risk"] = self._calculate_liquidation_risk(
                signal
            )

            # Адаптация размера позиции
            futures_signal[
                "max_position_size"
            ] = await self._calculate_max_position_size(signal)

            return futures_signal

        except Exception as e:
            logger.error(f"Ошибка адаптации сигнала под Futures: {e}")
            return signal

    def _calculate_liquidation_risk(self, signal: Dict[str, Any]) -> float:
        """Расчет риска ликвидации"""
        try:
            # ✅ ИСПРАВЛЕНИЕ: Получаем leverage из scalping_config или используем значение по умолчанию
            leverage = getattr(self.scalping_config, "leverage", 3)
            # Если leverage не в scalping_config, используем дефолт 3x для Futures
            if leverage is None:
                leverage = 3

            strength = signal.get("strength", 0.5)

            # Чем выше леверидж и ниже сила сигнала, тем выше риск
            risk = (leverage / 10) * (1 - strength)
            return min(risk, 1.0)

        except Exception as e:
            logger.error(f"Ошибка расчета риска ликвидации: {e}")
            return 0.5

    async def _calculate_max_position_size(self, signal: Dict[str, Any]) -> float:
        """Расчет максимального размера позиции"""
        try:
            # Здесь нужно интегрироваться с MarginCalculator
            # Пока используем упрощенный расчет
            base_size = 0.001  # Базовый размер
            strength = signal.get("strength", 0.5)

            return base_size * strength

        except Exception as e:
            logger.error(f"Ошибка расчета максимального размера позиции: {e}")
            return 0.001

    async def _filter_and_rank_signals(
        self, signals: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Фильтрация и ранжирование сигналов"""
        try:
            # Фильтрация по минимальной силе
            # ✅ АДАПТИВНО: min_signal_strength из конфига по режиму
            regime_name_min_strength = "ranging"  # Fallback
            try:
                if hasattr(self, "regime_manager") and self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        regime_name_min_strength = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except:
                pass

            signal_gen_config_min = getattr(
                self.scalping_config, "signal_generator", {}
            )
            thresholds_config_min = {}
            if isinstance(signal_gen_config_min, dict):
                thresholds_dict = signal_gen_config_min.get("thresholds", {})
                if thresholds_dict:
                    thresholds_config_min = (
                        thresholds_dict.get("by_regime", {}).get(
                            regime_name_min_strength, {}
                        )
                        if regime_name_min_strength
                        else {}
                    )
                    if not thresholds_config_min:
                        thresholds_config_min = thresholds_dict  # Fallback на базовые
            else:
                thresholds_obj = getattr(signal_gen_config_min, "thresholds", None)
                if thresholds_obj:
                    by_regime = getattr(thresholds_obj, "by_regime", None)
                    if by_regime and regime_name_min_strength:
                        thresholds_config_min = getattr(
                            by_regime, regime_name_min_strength, {}
                        )
                    if not thresholds_config_min:
                        thresholds_config_min = thresholds_obj  # Fallback на базовые

            min_strength = (
                thresholds_config_min.get("min_signal_strength", 0.3)
                if isinstance(thresholds_config_min, dict)
                else getattr(thresholds_config_min, "min_signal_strength", 0.3)
            )
            # Fallback на базовый min_signal_strength из scalping_config если нет в thresholds
            if min_strength == 0.3 and hasattr(
                self.scalping_config, "min_signal_strength"
            ):
                min_strength = getattr(self.scalping_config, "min_signal_strength", 0.3)

            filtered_signals = [
                s for s in signals if s.get("strength", 0) >= min_strength
            ]

            # Ранжирование по силе и уверенности
            ranked_signals = sorted(
                filtered_signals,
                key=lambda x: (
                    x.get("strength", 0) * x.get("confidence", 0),
                    x.get("strength", 0),
                ),
                reverse=True,
            )

            # Ограничение количества сигналов
            max_signals = self.scalping_config.max_concurrent_signals
            return ranked_signals[:max_signals]

        except Exception as e:
            logger.error(f"Ошибка фильтрации и ранжирования сигналов: {e}")
            return signals

    def _update_signal_history(self, signals: List[Dict[str, Any]]):
        """Обновление истории сигналов"""
        try:
            timestamp = datetime.now()

            for signal in signals:
                signal_record = {
                    "timestamp": timestamp,
                    "symbol": signal.get("symbol"),
                    "side": signal.get("side"),
                    "strength": signal.get("strength"),
                    "type": signal.get("type"),
                }

                self.signal_history.append(signal_record)

            # Ограничение истории последними 1000 записями
            if len(self.signal_history) > 1000:
                self.signal_history = self.signal_history[-1000:]

        except Exception as e:
            logger.error(f"Ошибка обновления истории сигналов: {e}")

    def get_signal_statistics(self) -> Dict[str, Any]:
        """Получение статистики сигналов"""
        try:
            if not self.signal_history:
                return {"total_signals": 0}

            # Подсчет по типам сигналов
            signal_types = {}
            for record in self.signal_history:
                signal_type = record.get("type", "unknown")
                signal_types[signal_type] = signal_types.get(signal_type, 0) + 1

            # Подсчет по направлениям
            buy_signals = sum(1 for r in self.signal_history if r.get("side") == "buy")
            sell_signals = sum(
                1 for r in self.signal_history if r.get("side") == "sell"
            )

            return {
                "total_signals": len(self.signal_history),
                "buy_signals": buy_signals,
                "sell_signals": sell_signals,
                "signal_types": signal_types,
                "last_signal_time": self.signal_history[-1]["timestamp"]
                if self.signal_history
                else None,
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики сигналов: {e}")
            return {"error": str(e)}


# Пример использования
if __name__ == "__main__":
    # Создаем конфигурацию
    config = BotConfig(
        api_key="test_key",
        secret_key="test_secret",  # nosec B106
        passphrase="test_passphrase",
        sandbox=True,
        scalping=ScalpingConfig(
            symbols=["BTC-USDT", "ETH-USDT"],
            min_signal_strength=0.3,
            max_concurrent_signals=5,
        ),
    )

    # Создаем генератор сигналов
    generator = FuturesSignalGenerator(config)

    print("FuturesSignalGenerator готов к работе")
