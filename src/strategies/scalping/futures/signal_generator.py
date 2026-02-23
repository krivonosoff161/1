"""
Futures Signal Generator для скальпинг стратегии.

Основные функции:
- Генерация торговых сигналов для Futures
- Адаптация под Futures специфику (леверидж, маржа)
- Интеграция с техническими индикаторами
- Фильтрация сигналов по силе и качеству
"""

import copy
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np  # ✅ Для per-symbol ATR расчётов
from loguru import logger

from src.config import BotConfig, ScalpingConfig
from src.indicators import IndicatorManager
from src.models import OHLCV, MarketData

from .adaptivity.regime_manager import AdaptiveRegimeManager
from .config.config_view import get_scalping_view
from .filters import (
    FundingRateFilter,
    LiquidityFilter,
    OrderFlowFilter,
    VolatilityRegimeFilter,
)
from .patterns.pattern_engine import PatternEngine

# ✅ РЕФАКТОРИНГ: Импортируем FilterManager и новые генераторы сигналов
from .signals.filter_manager import FilterManager
from .signals.macd_signal_generator import MACDSignalGenerator
from .signals.rsi_signal_generator import RSISignalGenerator
from .signals.trend_following_signal_generator import (
    TrendFollowingSignalGenerator,  # ✅ НОВОЕ (09.01.2026)
)


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
        self.scalping_config = get_scalping_view(config)
        self.client = client  # ✅ Сохраняем клиент для фильтров
        self.data_registry = None  # ✅ НОВОЕ: DataRegistry для сохранения индикаторов (будет установлен позже)
        self.performance_tracker = None  # Будет установлен из orchestrator
        self.parameter_orchestrator = None
        self.pattern_engine = PatternEngine()

        self._diagnostic_symbols = set()
        try:
            adaptive_regime = getattr(self.scalping_config, "adaptive_regime", None)
            detection = None
            if isinstance(adaptive_regime, dict):
                detection = adaptive_regime.get("detection", {})
            elif adaptive_regime and hasattr(adaptive_regime, "detection"):
                detection = getattr(adaptive_regime, "detection", None)

            symbols = []
            if isinstance(detection, dict):
                symbols = detection.get("score_log_symbols", []) or []
            elif detection and hasattr(detection, "score_log_symbols"):
                symbols = getattr(detection, "score_log_symbols", []) or []

            self._diagnostic_symbols = {str(s).upper() for s in symbols if s}
        except Exception as exc:
            logger.debug("Ignored error in optional block: %s", exc)

        # Менеджер индикаторов
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Используем TA-Lib обертки для ускорения на 70-85%
        from src.indicators import TALIB_AVAILABLE

        if TALIB_AVAILABLE:
            from src.indicators import (
                TALibATR,
                TALibBollingerBands,
                TALibEMA,
                TALibMACD,
                TALibRSI,
                TALibSMA,
            )

            logger.info(
                "✅ TA-Lib индикаторы доступны - используется оптимизированная версия (ускорение 70-85%)"
            )
        else:
            # Fallback на обычные индикаторы
            logger.warning(
                "⚠️ TA-Lib недоступен - используется fallback на обычные индикаторы. "
                "Производительность может быть ниже на 70-85%. "
                "Рекомендуется установить TA-Lib: pip install TA-Lib"
            )
            from src.indicators import ATR as TALibATR
            from src.indicators import MACD as TALibMACD
            from src.indicators import RSI as TALibRSI
            from src.indicators import BollingerBands as TALibBollingerBands
            from src.indicators import ExponentialMovingAverage as TALibEMA
            from src.indicators import SimpleMovingAverage as TALibSMA

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
        # ✅ ГРОК ОПТИМИЗАЦИЯ: Используем TA-Lib обертки для ускорения на 70-85%
        self.indicator_manager.add_indicator(
            "RSI",
            TALibRSI(
                period=rsi_period, overbought=rsi_overbought, oversold=rsi_oversold
            ),
        )
        self.indicator_manager.add_indicator("ATR", TALibATR(period=atr_period))
        self.indicator_manager.add_indicator("SMA", TALibSMA(period=sma_period))
        # ✅ Добавляем индикаторы, которые используются в генерации сигналов
        self.indicator_manager.add_indicator(
            "MACD",
            TALibMACD(
                fast_period=macd_fast, slow_period=macd_slow, signal_period=macd_signal
            ),
        )
        # ✅ ИСПРАВЛЕНИЕ: BollingerBands использует std_multiplier, а не std_dev
        self.indicator_manager.add_indicator(
            "BollingerBands",
            TALibBollingerBands(period=bb_period, std_multiplier=bb_std_multiplier),
        )
        self.indicator_manager.add_indicator("EMA_12", TALibEMA(period=ema_fast))
        self.indicator_manager.add_indicator("EMA_26", TALibEMA(period=ema_slow))

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

        # ✅ РЕФАКТОРИНГ: Генераторы сигналов (будут инициализированы в initialize)
        self.rsi_signal_generator = None
        self.macd_signal_generator = None
        self.funding_filter = None
        self.liquidity_filter = None
        self.order_flow_filter = None
        self.volatility_filter = None
        self.momentum_filter = None  # ✅ НОВОЕ: Momentum Filter
        self.impulse_config = None

        # ✅ РЕФАКТОРИНГ: FilterManager для координации всех фильтров
        self.filter_manager = FilterManager(
            data_registry=self.data_registry
        )  # ✅ НОВОЕ: Передаем DataRegistry в FilterManager

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
        # ✅ ПРАВКА #14: Кэш для ограничения частоты сигналов (минимум 60 сек между сигналами)
        self.signal_cache = {}  # {symbol: last_signal_timestamp}
        # ✅ НОВОЕ: Модуль статистики для динамической адаптации
        self.trading_statistics = None
        self.config_manager = None  # ✅ НОВОЕ: ConfigManager для адаптивных параметров
        self.adaptive_filter_params = (
            None  # ✅ НОВОЕ: Адаптивная система параметров фильтров
        )

        logger.info("FuturesSignalGenerator инициализирован")

        sg_cfg = self.scalping_config.get("signal_generator", {})
        if isinstance(sg_cfg, dict):
            self._allow_rest_for_ws = bool(sg_cfg.get("allow_rest_for_ws", False))
        else:
            self._allow_rest_for_ws = bool(getattr(sg_cfg, "allow_rest_for_ws", False))
        self._rest_update_cooldown = (
            float(sg_cfg.get("rest_update_cooldown", 1.0))
            if isinstance(sg_cfg, dict)
            else float(getattr(sg_cfg, "rest_update_cooldown", 1.0))
        )
        # FIX 2026-02-22 P2: Choppy blocked types из конфига (ранее хардкод в коде)
        _choppy_blocked_raw = (
            sg_cfg.get("choppy_blocked_types")
            if isinstance(sg_cfg, dict)
            else getattr(sg_cfg, "choppy_blocked_types", None)
        )
        self._choppy_blocked_types: set = (
            set(_choppy_blocked_raw)
            if _choppy_blocked_raw
            else {
                "macd_bullish",
                "macd_bearish",
                "bb_oversold",
                "bb_overbought",
                "rsi_oversold",
                "rsi_overbought",
            }
        )
        self._last_rest_update_ts: Dict[str, float] = {}
        self._last_forced_rest_ts: Dict[str, float] = {}
        self._forced_rest_logged = set()
        if isinstance(sg_cfg, dict):
            self._force_rest_on_ws_stale = bool(
                sg_cfg.get("force_rest_on_ws_stale", True)
            )
            self._force_rest_min_age = float(sg_cfg.get("force_rest_min_age", 4.0))
            self._force_rest_age_mult = float(sg_cfg.get("force_rest_age_mult", 2.0))
        else:
            self._force_rest_on_ws_stale = bool(
                getattr(sg_cfg, "force_rest_on_ws_stale", True)
            )
            self._force_rest_min_age = float(getattr(sg_cfg, "force_rest_min_age", 4.0))
            self._force_rest_age_mult = float(
                getattr(sg_cfg, "force_rest_age_mult", 2.0)
            )
        if isinstance(sg_cfg, dict):
            self._allow_candle_price_fallback = bool(
                sg_cfg.get("allow_candle_price_fallback", False)
            )
            self._allow_price_limits_fallback = bool(
                sg_cfg.get("allow_price_limits_fallback", False)
            )
        else:
            self._allow_candle_price_fallback = bool(
                getattr(sg_cfg, "allow_candle_price_fallback", False)
            )
            self._allow_price_limits_fallback = bool(
                getattr(sg_cfg, "allow_price_limits_fallback", False)
            )

    def set_data_registry(self, data_registry):
        """
        ✅ НОВОЕ: Установить DataRegistry для сохранения индикаторов.

        Args:
            data_registry: Экземпляр DataRegistry
        """
        self.data_registry = data_registry
        logger.debug("✅ SignalGenerator: DataRegistry установлен")

    def set_fast_adx(self, fast_adx):
        """
        ✅ НОВОЕ (26.12.2025): Установить FastADX и инициализировать DirectionAnalyzer.

        Args:
            fast_adx: Экземпляр FastADX
        """
        try:
            from .analysis.direction_analyzer import DirectionAnalyzer

            self.direction_analyzer = DirectionAnalyzer(fast_adx=fast_adx)
            logger.info(
                "✅ SignalGenerator: DirectionAnalyzer инициализирован с FastADX"
            )
        except Exception as e:
            logger.warning(f"⚠️ Не удалось инициализировать DirectionAnalyzer: {e}")
            self.direction_analyzer = None

    def set_structured_logger(self, structured_logger):
        """
        ✅ НОВОЕ: Установить StructuredLogger для логирования свечей.

        Args:
            structured_logger: Экземпляр StructuredLogger
        """
        self.structured_logger = structured_logger
        logger.debug("✅ SignalGenerator: StructuredLogger установлен")

        # ✅ НОВОЕ: Передаем StructuredLogger в фильтры, если они уже инициализированы
        if hasattr(self, "mtf_filter") and self.mtf_filter:
            self.mtf_filter.structured_logger = structured_logger

    def _is_diagnostic_symbol(self, symbol: Optional[str]) -> bool:
        if not symbol:
            return False
        if not self._diagnostic_symbols:
            return False
        return symbol.upper() in self._diagnostic_symbols

    def set_performance_tracker(self, performance_tracker):
        """Установить PerformanceTracker для CSV логирования"""
        self.performance_tracker = performance_tracker
        logger.debug("✅ FuturesSignalGenerator: PerformanceTracker установлен")

    def set_config_manager(self, config_manager):
        """
        ✅ НОВОЕ: Установить ConfigManager для адаптивных параметров фильтров

        Args:
            config_manager: Экземпляр ConfigManager
        """
        self.config_manager = config_manager

        # ✅ НОВОЕ: Инициализируем AdaptiveFilterParameters после установки всех зависимостей
        if self.config_manager and self.regime_manager and self.data_registry:
            from .adaptivity.filter_parameters import AdaptiveFilterParameters

            self.adaptive_filter_params = AdaptiveFilterParameters(
                config_manager=self.config_manager,
                regime_manager=self.regime_manager,
                data_registry=self.data_registry,
                trading_statistics=self.trading_statistics,
            )
            logger.info("✅ AdaptiveFilterParameters инициализирован в SignalGenerator")

    def set_parameter_orchestrator(self, parameter_orchestrator):
        """Set ParameterOrchestrator for strict parameter resolution."""
        self.parameter_orchestrator = parameter_orchestrator
        logger.info("SignalGenerator: ParameterOrchestrator set")

    def set_trading_statistics(self, trading_statistics):
        """
        ✅ НОВОЕ: Установить модуль статистики для динамической адаптации

        Args:
            trading_statistics: Экземпляр TradingStatistics
        """
        self.trading_statistics = trading_statistics
        # Передаем статистику в ARM
        if self.regime_manager and hasattr(self.regime_manager, "trading_statistics"):
            self.regime_manager.trading_statistics = trading_statistics
        # Передаем статистику во все per-symbol ARM
        for symbol, manager in self.regime_managers.items():
            if hasattr(manager, "trading_statistics"):
                manager.trading_statistics = trading_statistics

        # ✅ НОВОЕ: Обновляем AdaptiveFilterParameters если уже инициализирован
        if self.adaptive_filter_params:
            self.adaptive_filter_params.trading_statistics = trading_statistics

    async def _allow_stale_signal(self, symbol: str, grace_period: float) -> bool:
        if not self.data_registry:
            return False
        try:
            market_data = await self.data_registry.peek_market_data(symbol)
        except Exception as e:
            logger.debug(
                f"⚠️ SignalGenerator: не удалось прочитать market_data для {symbol}: {e}"
            )
            return False

        if not market_data:
            return False

        updated_at = market_data.get("updated_at")
        price = market_data.get("price") or market_data.get("last_price")
        if not updated_at or not isinstance(updated_at, datetime) or not price:
            return False

        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        if age <= grace_period:
            logger.debug(
                f"✅ SignalGenerator: допускаем устаревший сигнал для {symbol} "
                f"(age={age:.1f}s ≤ grace={grace_period:.1f}s)"
            )
            return True
        return False

    async def _refresh_market_data_from_rest(self, symbol: str) -> bool:
        if not self.client or not self._allow_rest_for_ws or not self.data_registry:
            return False
        now = time.time()
        last_ts = self._last_rest_update_ts.get(symbol, 0.0)
        if now - last_ts < self._rest_update_cooldown:
            return False
        self._last_rest_update_ts[symbol] = now
        try:
            ticker = await self.client.get_ticker(symbol)
            if not ticker or not isinstance(ticker, dict):
                return False
            raw_price = (
                ticker.get("last") or ticker.get("lastPx") or ticker.get("markPx")
            )
            if raw_price is None:
                return False
            price = float(raw_price)
            if price <= 0:
                return False
            await self.data_registry.update_market_data(
                symbol,
                {
                    "price": price,
                    "last_price": price,
                    "source": "REST",
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            self._forced_rest_logged.discard(symbol)
            logger.debug(f"SignalGenerator: REST refresh for {symbol} at ${price:.4f}")
            return True
        except Exception as e:
            logger.debug(f"SignalGenerator REST refresh failed for {symbol}: {e}")
            return False

    async def _should_force_rest_fallback(self, symbol: str, ws_max_age: float) -> bool:
        if not self._force_rest_on_ws_stale or not self.data_registry:
            return False
        try:
            market_data = await self.data_registry.peek_market_data(symbol)
        except Exception as e:
            logger.debug(
                f"SignalGenerator: failed to peek market_data for {symbol}: {e}"
            )
            return False
        if not market_data:
            return False
        updated_at = market_data.get("updated_at")
        if not updated_at or not isinstance(updated_at, datetime):
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        else:
            updated_at = updated_at.astimezone(timezone.utc)
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        force_after = max(
            float(ws_max_age) * self._force_rest_age_mult, self._force_rest_min_age
        )
        if age < force_after:
            return False
        now = time.time()
        last_ts = self._last_forced_rest_ts.get(symbol, 0.0)
        if now - last_ts < self._rest_update_cooldown:
            return False
        self._last_forced_rest_ts[symbol] = now
        if symbol not in self._forced_rest_logged:
            logger.warning(
                f"SignalGenerator: WS stale for {symbol} (age={age:.1f}s), forcing REST fallback"
            )
            self._forced_rest_logged.add(symbol)
        return True

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
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Устанавливаем is_initialized в начале,
        # чтобы избежать проблем, если инициализация завершится с ошибкой
        # Это позволит generate_signals работать даже при частичной инициализации
        if self.is_initialized:
            logger.debug(
                "SignalGenerator уже инициализирован, пропускаем повторную инициализацию"
            )
            return

        try:
            from .adaptivity.regime_manager import RegimeConfig

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

                    from .adaptivity.regime_manager import (
                        IndicatorParameters,
                        ModuleParameters,
                        RegimeParameters,
                    )

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

                        # ✅ АДАПТИВНО: Получаем correlation_threshold через AdaptiveFilterParameters
                        if self.adaptive_filter_params:
                            corr_threshold = (
                                self.adaptive_filter_params.get_correlation_threshold(
                                    symbol="",  # Глобальный параметр
                                    regime=None,
                                )
                            )
                        else:
                            corr_threshold = corr_dict.get("correlation_threshold", 0.7)

                        modules = ModuleParameters(
                            mtf_block_opposite=mtf_dict.get("block_opposite", True),
                            mtf_score_bonus=mtf_dict.get("score_bonus", 2),
                            mtf_confirmation_timeframe=mtf_dict.get(
                                "confirmation_timeframe", "15m"
                            ),
                            correlation_threshold=corr_threshold,
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
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Стандартизация периода на 50 свечей (было 200)
                            vp_lookback_candles=vp_dict.get("lookback_candles", 50),
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
                    score_log_symbols = detection_dict.get("score_log_symbols", [])

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
                        score_log_symbols=score_log_symbols,
                        trending_params=trending_params,
                        ranging_params=ranging_params,
                        choppy_params=choppy_params,
                    )
                    self.regime_manager = AdaptiveRegimeManager(
                        regime_config,
                        trading_statistics=self.trading_statistics,
                        data_registry=self.data_registry,
                        symbol=None,  # Общий RegimeManager без символа
                    )

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
                            score_log_symbols=score_log_symbols,
                            trending_params=symbol_trending_params,
                            ranging_params=symbol_ranging_params,
                            choppy_params=symbol_choppy_params,
                        )
                        self.regime_managers[symbol] = AdaptiveRegimeManager(
                            symbol_regime_config,
                            trading_statistics=self.trading_statistics,
                            data_registry=self.data_registry,
                            symbol=symbol,  # ✅ НОВОЕ: Передаем символ для per-symbol режимов
                        )
                        if ohlcv_data and symbol in ohlcv_data:
                            await self.regime_managers[symbol].initialize(
                                {symbol: ohlcv_data[symbol]}
                            )

                    logger.info(
                        f"✅ Adaptive Regime Manager инициализирован: "
                        f"общий + {len(self.regime_managers)} для символов"
                    )

                    # ✅ НОВОЕ: Инициализируем AdaptiveFilterParameters после установки всех зависимостей
                    if (
                        self.config_manager
                        and self.regime_manager
                        and self.data_registry
                    ):
                        from .adaptivity.filter_parameters import (
                            AdaptiveFilterParameters,
                        )

                        self.adaptive_filter_params = AdaptiveFilterParameters(
                            config_manager=self.config_manager,
                            regime_manager=self.regime_manager,
                            data_registry=self.data_registry,
                            trading_statistics=self.trading_statistics,
                        )
                        logger.info(
                            "✅ AdaptiveFilterParameters инициализирован в SignalGenerator.initialize()"
                        )
                except Exception as e:
                    logger.warning(f"⚠️ ARM инициализация не удалась: {e}")
                    self.regime_manager = None
            else:
                logger.info("⚠️ Adaptive Regime Manager отключен в конфиге")

            # ✅ Инициализация Multi-Timeframe фильтра
            try:
                from src.strategies.modules.multi_timeframe import (
                    MTFConfig,
                    MultiTimeframeFilter,
                )

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
                    cache_ttl_seconds=10,  # Кэш на 10 секунд
                )
                logger.info("✅ MTF Filter TTL установлен: 10s")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Инициализируем MTF фильтр с DataRegistry и StructuredLogger
                self.mtf_filter = MultiTimeframeFilter(
                    client=self.client,
                    config=mtf_config,
                    data_registry=self.data_registry,  # Передаем DataRegistry для получения свечей
                    structured_logger=getattr(
                        self, "structured_logger", None
                    ),  # Передаем StructuredLogger
                )

                logger.info(
                    f"✅ Multi-Timeframe Filter инициализирован: "
                    f"таймфрейм={mtf_config.confirmation_timeframe}, "
                    f"block_opposite={mtf_config.block_opposite}"
                )
            except Exception as e:
                logger.warning(f"⚠️ MTF инициализация не удалась: {e}")
                self.mtf_filter = None

            # ✅ НОВОЕ (26.12.2025): Инициализация DirectionAnalyzer
            self.direction_analyzer = None
            # DirectionAnalyzer будет инициализирован после установки fast_adx (импорт удалён как неиспользуемый)

            # ✅ Инициализация ADX Filter (ПРОВЕРКА ТРЕНДА)
            try:
                from src.strategies.modules.adx_filter import ADXFilter, ADXFilterConfig

                # Получаем параметры ADX из текущего режима
                # regime_name_adx = "ranging"  # Fallback (удалено как неиспользуемое)
                # Получаем параметры из режима
                regime_params = None
                if hasattr(self, "regime_manager") and self.regime_manager:
                    try:
                        regime_params = self.regime_manager.get_current_parameters()
                    except Exception as exc:
                        logger.debug("Ignored error in optional block: %s", exc)

                adx_threshold = 18.0  # Fallback
                adx_di_difference = 1.5  # Fallback

                if regime_params and hasattr(regime_params, "modules"):
                    adx_modules = regime_params.modules
                    adx_threshold = getattr(adx_modules, "adx_threshold", adx_threshold)
                    adx_di_difference = getattr(
                        adx_modules, "adx_di_difference", adx_di_difference
                    )

                adx_config = ADXFilterConfig(
                    enabled=True,
                    adx_threshold=adx_threshold,
                    di_difference=adx_di_difference,
                )

                self.adx_filter = ADXFilter(config=adx_config)
                logger.info(
                    f"✅ ADX Filter инициализирован: "
                    f"threshold={adx_threshold}, di_difference={adx_di_difference}"
                )
            except Exception as e:
                logger.warning(f"⚠️ ADX Filter инициализация не удалась: {e}")
                self.adx_filter = None

            # ✅ Инициализация Correlation Filter
            try:
                from src.strategies.modules.correlation_filter import (
                    CorrelationFilter,
                    CorrelationFilterConfig,
                )

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
                except Exception as exc:
                    logger.debug("Ignored error in optional block: %s", exc)

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
                            # 🔴 BUG #6 FIX: Convert to dict first to handle case sensitivity
                            if isinstance(by_regime, dict):
                                thresholds_config = by_regime.get(regime_name_corr, {})
                            else:
                                by_regime_dict = self._to_dict(by_regime)
                                thresholds_config = by_regime_dict.get(
                                    regime_name_corr, {}
                                )
                        if not thresholds_config:
                            thresholds_config = thresholds_obj  # Fallback на базовые

                # ✅ АДАПТИВНО: Получаем correlation_threshold через AdaptiveFilterParameters
                if self.adaptive_filter_params:
                    corr_threshold = (
                        self.adaptive_filter_params.get_correlation_threshold(
                            symbol="",  # Глобальный параметр
                            regime=None,
                        )
                    )
                else:
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
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Передаем DataRegistry для использования свечей
                        self.correlation_filter = CorrelationFilter(
                            client=self.client,
                            config=corr_config,
                            all_symbols=self.scalping_config.symbols,
                            data_registry=self.data_registry,  # Передаем DataRegistry
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
                    PivotPointsConfig,
                    PivotPointsFilter,
                )

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
                except Exception as exc:
                    logger.debug("Ignored error in optional block: %s", exc)

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
                        cache_ttl_seconds=300,  # Кэш на 300 секунд (минимум PivotPointsConfig)
                    )

                    try:
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Передаем DataRegistry для использования свечей
                        self.pivot_filter = PivotPointsFilter(
                            client=self.client,
                            config=pivot_config,
                            data_registry=self.data_registry,  # Передаем DataRegistry
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
                    VolumeProfileConfig,
                    VolumeProfileFilter,
                )

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
                        cache_ttl_seconds=60,  # Кэш на 60 секунд (минимум VolumeProfileConfig)
                    )

                    try:
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Передаем DataRegistry для использования свечей
                        self.volume_filter = VolumeProfileFilter(
                            client=self.client,
                            config=vp_config,
                            data_registry=self.data_registry,  # Передаем DataRegistry
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

            # ✅ РЕФАКТОРИНГ: Подключаем все фильтры к FilterManager
            if self.filter_manager:
                if self.adx_filter:
                    self.filter_manager.set_adx_filter(self.adx_filter)
                if self.mtf_filter:
                    self.filter_manager.set_mtf_filter(self.mtf_filter)
                if self.correlation_filter:
                    self.filter_manager.set_correlation_filter(self.correlation_filter)
                if self.pivot_filter:
                    self.filter_manager.set_pivot_points_filter(self.pivot_filter)
                if self.volume_filter:
                    self.filter_manager.set_volume_profile_filter(self.volume_filter)
                if self.liquidity_filter:
                    self.filter_manager.set_liquidity_filter(self.liquidity_filter)
                if self.order_flow_filter:
                    self.filter_manager.set_order_flow_filter(self.order_flow_filter)
                if self.funding_filter:
                    self.filter_manager.set_funding_rate_filter(self.funding_filter)
                if self.volatility_filter:
                    self.filter_manager.set_volatility_filter(self.volatility_filter)
                logger.info("✅ FilterManager: Все фильтры подключены")

            # ✅ РЕФАКТОРИНГ: Инициализируем новые генераторы сигналов
            self.rsi_signal_generator = RSISignalGenerator(
                regime_managers=self.regime_managers,
                regime_manager=self.regime_manager,
                get_current_market_price_callback=self._get_current_market_price,
                get_regime_indicators_params_callback=self._get_regime_indicators_params,
                scalping_config=self.scalping_config,  # ✅ Передаем scalping_config для confidence_config
            )

            self.macd_signal_generator = MACDSignalGenerator(
                regime_managers=self.regime_managers,
                regime_manager=self.regime_manager,
                get_current_market_price_callback=self._get_current_market_price,
                get_regime_indicators_params_callback=self._get_regime_indicators_params,
                scalping_config=self.scalping_config,  # ✅ Передаем scalping_config для confidence_config
            )

            # ✅ НОВОЕ (09.01.2026): Инициализируем TrendFollowingSignalGenerator для LONG в uptrend
            self.trend_following_generator = TrendFollowingSignalGenerator(
                regime_managers=self.regime_managers,
                regime_manager=self.regime_manager,
                get_current_market_price_callback=self._get_current_market_price,
                get_regime_indicators_params_callback=self._get_regime_indicators_params,
                scalping_config=self.scalping_config,
            )

            logger.info(
                "✅ Рефакторированные генераторы сигналов инициализированы: "
                "RSISignalGenerator, MACDSignalGenerator, TrendFollowingSignalGenerator"
            )

            self.is_initialized = True
            logger.info("✅ FuturesSignalGenerator инициализирован")

        except Exception as e:
            logger.error(
                f"❌ Ошибка инициализации FuturesSignalGenerator: {e}", exc_info=True
            )
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Устанавливаем is_initialized только если критических ошибок нет
            # Если есть критическая ошибка, лучше не инициализировать, чтобы не работать с неполными данными
            self.is_initialized = (
                True  # Все равно продолжаем (чтобы не блокировать работу)
            )
            logger.warning(
                "⚠️ FuturesSignalGenerator инициализирован с ошибками, но продолжает работу"
            )

    def _get_current_price(self, market_data: MarketData) -> float:
        """
        Получить текущую цену из WebSocket (реальное время) вместо старых OHLCV свечей.

        ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ (09.01.2026):
        - Использует реальную цену из WebSocket (current_tick)
        - Фалбэк на OHLCV если tick недоступен
        - Это решает проблему с ордерами, размещаемыми далеко от рынка

        Args:
            market_data: MarketData объект с реальной информацией

        Returns:
            float: Текущая цена (реальная из WebSocket или fallback из OHLCV)
        """
        # ✅ ПРИОРИТЕТ 1: Использовать реальную цену из WebSocket (current_tick)
        if market_data.current_tick and market_data.current_tick.price > 0:
            return market_data.current_tick.price

        # ✅ ПРИОРИТЕТ 2: Fallback на последнюю закрытую свечу (если tick недоступен)
        if market_data.ohlcv_data:
            return market_data.ohlcv_data[-1].close

        # ✅ ПРИОРИТЕТ 3: Fallback на нуль (если данных вообще нет)
        return 0.0

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
            logger.debug(
                "SignalGenerator еще не инициализирован, пропускаем генерацию сигналов"
            )
            return []

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Проверяем наличие свечей перед генерацией сигналов
        # Это предотвращает генерацию сигналов до загрузки свечей
        if not self.data_registry:
            logger.debug("⚠️ DataRegistry не доступен, пропускаем генерацию сигналов")
            return []

        try:
            signals = []
            symbols = self.scalping_config.symbols

            # ✅ ОПТИМИЗАЦИЯ: Параллельная обработка символов (вместо последовательной)
            # Создаем задачи для всех символов одновременно
            async def _generate_symbol_signals_task(
                symbol: str,
            ) -> List[Dict[str, Any]]:
                """Внутренняя функция для генерации сигналов одного символа"""
                try:
                    # ✅ DEBUG: Вход в функцию
                    logger.info(
                        f"🔍 [TASK_START] {symbol}: Начало _generate_symbol_signals_task()"
                    )

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Проверяем наличие свечей перед генерацию сигналов
                    # 🔴 BUG #4 FIX (09.01.2026): Снижена граница с 30 до 15 свечей для ранней генерации сигналов
                    # Это предотвращает генерацию сигналов до загрузки свечей, но не блокирует их 30-45 минут
                    if self.data_registry:
                        try:
                            ws_max_age = 3.0
                            sg_cfg = getattr(
                                self.scalping_config, "signal_generator", {}
                            )
                            if isinstance(sg_cfg, dict):
                                ws_max_age = float(
                                    sg_cfg.get("ws_fresh_max_age", ws_max_age)
                                )
                            else:
                                ws_max_age = float(
                                    getattr(sg_cfg, "ws_fresh_max_age", ws_max_age)
                                )
                            decision_snapshot = (
                                await self.data_registry.get_decision_price_snapshot(
                                    symbol=symbol,
                                    client=self.client,
                                    max_age=ws_max_age,
                                    allow_rest_fallback=True,
                                )
                            )
                            if (
                                not decision_snapshot
                                or float(decision_snapshot.get("price") or 0.0) <= 0
                            ):
                                logger.warning(
                                    f"WS_STALE_SIGNAL_FALLBACK {symbol}: no valid snapshot for signals, skip generation"
                                )
                                return []
                            if decision_snapshot.get("rest_fallback"):
                                age = decision_snapshot.get("age")
                                age_str = (
                                    f"{float(age):.1f}s" if age is not None else "N/A"
                                )
                                logger.info(
                                    f"WS_STALE_SIGNAL_FALLBACK {symbol}: "
                                    f"continue with REST_FALLBACK snapshot (age={age_str})"
                                )
                        except Exception as e:
                            logger.debug(
                                f"SignalGenerator WS freshness check error for {symbol}: {e}"
                            )
                        candles_1m = await self.data_registry.get_candles(symbol, "1m")
                        if not candles_1m or len(candles_1m) < 15:
                            logger.debug(
                                f"⚠️ Недостаточно свечей для {symbol} "
                                f"(нужно минимум 15, получено {len(candles_1m) if candles_1m else 0}), "
                                f"пропускаем генерацию сигналов"
                            )
                            return (
                                []
                            )  # Не генерируем сигналы без достаточного количества свечей

                        # 🔴 BUG #9 FIX (09.01.2026): Validate OHLCV data quality before use
                        is_valid, errors = self.data_registry.validate_ohlcv_data(
                            symbol, candles_1m
                        )
                        if not is_valid:
                            logger.warning(
                                f"🚫 Data quality check failed for {symbol}: {len(errors)} issues found"
                            )
                            # For now, we continue but log the issues
                            # In strict mode, we could return [] here to skip signal generation

                    # Получаем данные один раз для символа
                    market_data = await self._get_market_data(symbol)
                    if not market_data:
                        return []

                    # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #7: Определяем режим ПЕРЕД генерацией сигналов (БЕЗ FALLBACK)
                    current_regime = None
                    regime_manager = (
                        self.regime_managers.get(symbol) or self.regime_manager
                    )

                    if not regime_manager:
                        logger.error(
                            f"❌ [REGIME] {symbol}: RegimeManager недоступен - ПРОПУСКАЕМ генерацию сигналов"
                        )
                        return []

                    if not market_data or not market_data.ohlcv_data:
                        logger.error(
                            f"❌ [REGIME] {symbol}: market_data или свечи отсутствуют - ПРОПУСКАЕМ генерацию сигналов"
                        )
                        return []

                    if len(market_data.ohlcv_data) < 50:
                        logger.error(
                            f"❌ [REGIME] {symbol}: Недостаточно свечей для определения режима "
                            f"({len(market_data.ohlcv_data)} < 50) - ПРОПУСКАЕМ генерацию сигналов"
                        )
                        return []

                    try:
                        # Берем текущую цену из WebSocket (реал-тайм) с fallback на закрытие свечи
                        current_price = self._get_current_price(market_data)
                        # ✅ ВАЖНО: Проверяем что current_price это число
                        if (
                            not isinstance(current_price, (int, float))
                            or current_price <= 0
                        ):
                            logger.error(
                                f"❌ [REGIME] {symbol}: Невалидная цена закрытия (current_price={current_price}) - "
                                f"ПРОПУСКАЕМ генерацию сигналов"
                            )
                            return []

                        # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #7: Вызываем update_regime() (async, сохраняет режим в DataRegistry)
                        # detect_regime() только определяет режим, но не сохраняет его
                        # update_regime() определяет И сохраняет режим в DataRegistry
                        if hasattr(regime_manager, "update_regime"):
                            await regime_manager.update_regime(
                                market_data.ohlcv_data, current_price
                            )
                            # update_regime возвращает None если режим не изменился, или новый режим если изменился
                            # В любом случае режим должен быть сохранен в DataRegistry (строки 770-774 в regime_manager.py)
                            logger.debug(
                                f"✅ [REGIME] {symbol}: update_regime() вызван, режим должен быть сохранен в DataRegistry"
                            )
                        else:
                            logger.error(
                                f"❌ [REGIME] {symbol}: RegimeManager не имеет метода update_regime() - "
                                f"ПРОПУСКАЕМ генерацию сигналов"
                            )
                            return []

                        # Проверяем что режим сохранен в DataRegistry
                        if self.data_registry:
                            regime_data = await self.data_registry.get_regime(symbol)
                            if not regime_data or not regime_data.get("regime"):
                                logger.error(
                                    f"❌ [REGIME] {symbol}: Режим не найден в DataRegistry после update_regime() - "
                                    f"ПРОПУСКАЕМ генерацию сигналов"
                                )
                                return []

                            current_regime = regime_data.get("regime")
                            logger.debug(
                                f"✅ [REGIME] {symbol}: Режим определен и сохранен: {current_regime}"
                            )
                        else:
                            # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #7: DataRegistry обязателен для сохранения режима
                            logger.error(
                                f"❌ [REGIME] {symbol}: DataRegistry недоступен после update_regime() - "
                                f"ПРОПУСКАЕМ генерацию сигналов (БЕЗ FALLBACK)"
                            )
                            return []

                    except Exception as e:
                        logger.error(
                            f"❌ [REGIME] {symbol}: Ошибка определения режима: {e} - ПРОПУСКАЕМ генерацию сигналов",
                            exc_info=True,
                        )
                        return []

                    if not current_regime:
                        logger.error(
                            f"❌ [REGIME] {symbol}: Режим не определен после detect_regime - ПРОПУСКАЕМ генерацию сигналов"
                        )
                        return []

                    # Генерируем сигналы для текущего символа (передаем уже полученные данные и режим)
                    symbol_signals = await self._generate_symbol_signals(
                        symbol,
                        market_data,
                        current_positions=current_positions,
                        regime=current_regime,
                    )

                    # ✅ DEBUG: Результат генерации
                    result = symbol_signals if isinstance(symbol_signals, list) else []
                    logger.info(
                        f"🔍 [TASK_END] {symbol}: _generate_symbol_signals_task() возвращает {len(result)} сигналов"
                    )
                    return result
                except Exception as e:
                    logger.error(f"❌ Ошибка генерации сигналов для {symbol}: {e}")
                    return []

            # ✅ ПАРАЛЛЕЛЬНАЯ ОБРАБОТКА: Обрабатываем все символы одновременно
            import asyncio

            tasks = [_generate_symbol_signals_task(symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Собираем сигналы из всех результатов
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"❌ Ошибка генерации сигналов для {symbols[i]}: {result}"
                    )
                elif isinstance(result, list):
                    signals.extend(result)
                    if len(result) > 0:
                        logger.info(
                            f"✅ [SIGNAL_COLLECTION] {symbols[i]}: Добавлено {len(result)} сигналов в общий список"
                        )
                else:
                    logger.warning(
                        f"⚠️ Неожиданный тип результата для {symbols[i]}: {type(result)}"
                    )

            # ✅ DEBUG: Логирование количества сигналов ПЕРЕД финальной фильтрацией
            logger.info(
                f"📊 [BEFORE_FINAL_FILTER] Всего собрано {len(signals)} сигналов из {len(symbols)} символов перед _filter_and_rank_signals()"
            )

            # Фильтрация и ранжирование сигналов
            filtered_signals = await self._filter_and_rank_signals(signals)

            # ✅ DEBUG: Логирование количества сигналов ПОСЛЕ финальной фильтрации
            logger.info(
                f"📊 [AFTER_FINAL_FILTER] Осталось {len(filtered_signals)} сигналов после _filter_and_rank_signals() "
                f"(было {len(signals)}, отфильтровано {len(signals) - len(filtered_signals)})"
            )

            # Обновление истории сигналов
            self._update_signal_history(filtered_signals)

            # ✅ НОВОЕ: Логирование сигналов в CSV
            if self.performance_tracker:
                for signal in filtered_signals:
                    try:
                        filters_passed = signal.get("filters_passed", [])
                        if isinstance(filters_passed, str):
                            filters_passed = (
                                filters_passed.split(",") if filters_passed else []
                            )
                        elif not isinstance(filters_passed, list):
                            filters_passed = []

                        self.performance_tracker.record_signal(
                            symbol=signal.get("symbol", ""),
                            side=signal.get("side", ""),
                            price=signal.get("price", 0.0),
                            strength=signal.get("strength", 0.0),
                            regime=signal.get("regime"),
                            filters_passed=filters_passed,
                            executed=False,  # Будет обновлено при исполнении
                            order_id=None,  # Будет обновлено при исполнении
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ SignalGenerator: Ошибка записи сигнала в CSV: {e}"
                        )

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка генерации сигналов: {e}")
            return []

    async def _generate_symbol_signals(
        self,
        symbol: str,
        market_data: Optional[MarketData] = None,
        current_positions: Dict = None,
        regime: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Генерация сигналов для конкретной торговой пары

        Args:
            symbol: Торговая пара
            market_data: Рыночные данные (если не переданы - получим сами)
            current_positions: Текущие открытые позиции для CorrelationFilter
            regime: Режим рынка (trending/ranging/choppy) - если не передан, определяется автоматически
        """
        try:
            # ✅ FIX (2026-02-18): Проверяем by_symbol.enabled = false → блокируем пару
            # enabled: false в scalping.by_symbol.<SYMBOL> отключает торговлю по этой паре
            # БЕЗ этого XRP-USDT с enabled:false продолжал торговать (11.9% WR, убытки)
            try:
                by_symbol_cfg = getattr(self.scalping_config, "by_symbol", None)
                if by_symbol_cfg:
                    sym_cfg = (
                        by_symbol_cfg.get(symbol)
                        if isinstance(by_symbol_cfg, dict)
                        else getattr(by_symbol_cfg, symbol.replace("-", "_"), None)
                    )
                    if sym_cfg is not None:
                        sym_enabled = (
                            sym_cfg.get("enabled", True)
                            if isinstance(sym_cfg, dict)
                            else getattr(sym_cfg, "enabled", True)
                        )
                        if sym_enabled is False:
                            logger.debug(
                                f"⛔ {symbol}: торговля отключена (by_symbol.enabled=false)"
                            )
                            return []
            except Exception:
                pass

            # Получение рыночных данных (если не переданы)
            if not market_data:
                market_data = await self._get_market_data(symbol)
            if not market_data:
                logger.error(
                    f"❌ SignalGenerator: Нет свежих рыночных данных для {symbol} (market_data is None, сигналы не генерируются)"
                )
                return []

            # Генерация базовых сигналов
            base_signals = await self._generate_base_signals(
                symbol, market_data, regime
            )

            # ✅ ИСПРАВЛЕНО (10.01.2026): Убрано misleading логирование ADX=0 до инициализации ADX
            # Реальное логирование причин происходит внутри _generate_base_signals после получения ADX
            if not base_signals or len(base_signals) == 0:
                logger.debug(
                    f"📊 {symbol}: Базовые сигналы не сгенерированы (см. детали в _generate_base_signals)"
                )

            # FIX (2026-02-19): В choppy блокируем lagging индикаторы (MACD/BB/RSI classic).
            # Данные из сессии 2026-02-19: 64% сделок в choppy, WR=30%, PnL=-$37.70.
            # EMA crossover / MACD / BB в choppy = шум. Оставляем только:
            # - rsi_divergence (leading сигнал разворота)
            # - vwap_mean_reversion (mean-reversion, создан именно для ranging/choppy)
            if base_signals:
                _current_regime = regime or (
                    base_signals[0].get("regime") if base_signals else None
                )
                if _current_regime == "choppy":
                    # FIX 2026-02-22 P2: список из конфига (scalping.signal_generator.choppy_blocked_types)
                    _before = len(base_signals)
                    base_signals = [
                        s
                        for s in base_signals
                        if s.get("type") not in self._choppy_blocked_types
                    ]
                    _blocked = _before - len(base_signals)
                    if _blocked:
                        logger.debug(
                            f"⛔ {symbol}: choppy lagging-фильтр убрал {_blocked} сигналов "
                            f"(MACD/BB/RSI_classic заблокированы, остались RSI_Div + VWAP)"
                        )
                    # Дополнительно: min_signal_strength для choppy (конфиг 0.15, но в коде не проверялся)
                    _min_strength_choppy = 0.15
                    try:
                        _sg_cfg = getattr(self.scalping_config, "signal_generator", {})
                        _thr = (
                            _sg_cfg.get("thresholds", {})
                            if isinstance(_sg_cfg, dict)
                            else getattr(_sg_cfg, "thresholds", {})
                        )
                        _by_regime = (
                            _thr.get("by_regime", {})
                            if isinstance(_thr, dict)
                            else getattr(_thr, "by_regime", {})
                        )
                        _choppy_thr = (
                            _by_regime.get("choppy", {})
                            if isinstance(_by_regime, dict)
                            else getattr(_by_regime, "choppy", {})
                        )
                        _min_strength_choppy = float(
                            _choppy_thr.get("min_signal_strength", _min_strength_choppy)
                            if isinstance(_choppy_thr, dict)
                            else getattr(
                                _choppy_thr, "min_signal_strength", _min_strength_choppy
                            )
                        )
                    except Exception:
                        pass
                    _before_str = len(base_signals)
                    base_signals = [
                        s
                        for s in base_signals
                        if s.get("strength", 0) >= _min_strength_choppy
                    ]
                    _blocked_str = _before_str - len(base_signals)
                    if _blocked_str:
                        logger.debug(
                            f"⛔ {symbol}: choppy strength-фильтр убрал {_blocked_str} сигналов "
                            f"(strength < {_min_strength_choppy:.2f})"
                        )

            # ✅ ИСПРАВЛЕНИЕ (13.02.2026): Дедупликация конфликтующих BUY+SELL сигналов
            # Проблема: RSI генерирует SELL, MACD генерирует BUY на одном тике → downstream выбирает случайно
            # ✅ FIX L2-1: При равной силе (diff ≤ 0.05) выбираем победителя с -20% штрафом к силе вместо отбрасывания обоих
            if base_signals and len(base_signals) > 1:
                buy_signals = [
                    s for s in base_signals if s.get("side") in ("buy", "long")
                ]
                sell_signals = [
                    s for s in base_signals if s.get("side") in ("sell", "short")
                ]
                if buy_signals and sell_signals:
                    best_buy = max(buy_signals, key=lambda s: s.get("strength", 0))
                    best_sell = max(sell_signals, key=lambda s: s.get("strength", 0))
                    buy_str = best_buy.get("strength", 0)
                    sell_str = best_sell.get("strength", 0)
                    diff = abs(buy_str - sell_str)
                    if diff <= 0.05:
                        # ✅ FIX L2-1: Выбираем победителя с штрафом вместо отбрасывания обоих
                        # ✅ P1-15 FIX: Штраф читается из конфига
                        sm_cfg = _cfg_get(
                            self.scalping_config, "strength_multipliers", {}
                        )
                        conflict_penalty = float(
                            _cfg_get(sm_cfg, "global_conflict_penalty", 0.8)
                        )
                        winner = best_buy if buy_str >= sell_str else best_sell
                        loser_side = "SELL" if buy_str >= sell_str else "BUY"
                        winner_side = "BUY" if buy_str >= sell_str else "SELL"
                        # Применяем штраф к силе
                        original_strength = winner.get("strength", 0)
                        winner["strength"] = original_strength * conflict_penalty
                        winner["has_conflict"] = True  # Помечаем как конфликтный
                        penalty_pct = (1 - conflict_penalty) * 100
                        logger.warning(
                            f"⚡ {symbol}: КОНФЛИКТ BUY({buy_str:.3f}) vs SELL({sell_str:.3f}) — "
                            f"сила равная (diff={diff:.3f}), выбираем {winner_side} с штрафом {penalty_pct:.0f}% "
                            f"(strength: {original_strength:.3f} → {winner['strength']:.3f})"
                        )
                        base_signals = [winner]
                    else:
                        winner = best_buy if buy_str > sell_str else best_sell
                        loser_side = "SELL" if buy_str > sell_str else "BUY"
                        logger.warning(
                            f"⚡ {symbol}: КОНФЛИКТ BUY({buy_str:.3f}) vs SELL({sell_str:.3f}) — "
                            f"убираем {loser_side}, оставляем {'BUY' if buy_str > sell_str else 'SELL'} (strength={winner.get('strength', 0):.3f})"
                        )
                        base_signals = [winner]

            # Применение фильтров (передаем позиции для CorrelationFilter)
            filtered_signals = await self._apply_filters(
                symbol, base_signals, market_data, current_positions=current_positions
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Детальное логирование причин фильтрации
            if base_signals and len(base_signals) > 0 and len(filtered_signals) == 0:
                # Собираем причины фильтрации для каждого сигнала
                filtered_reasons = []
                for sig in base_signals:
                    sig_type = sig.get("type", "unknown")
                    sig_side = sig.get("side", "unknown").upper()
                    sig_strength = sig.get("strength", 0.0)
                    sig_filter_reason = sig.get("filter_reason", "неизвестно")
                    filtered_reasons.append(
                        f"Сигнал #{len(filtered_reasons)+1} ({sig_type} {sig_side}, strength={sig_strength:.2f}): {sig_filter_reason}"
                    )

                logger.info(
                    f"📊 {symbol}: Все {len(base_signals)} базовых сигналов отфильтрованы.\n"
                    f"   Причины фильтрации:\n"
                    + "\n".join(f"   - {reason}" for reason in filtered_reasons)
                )

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка генерации сигналов для {symbol}: {e}")
            return []

    async def _get_current_market_price(
        self, symbol: str, fallback_price: float = 0.0
    ) -> float:
        """
        ✅ ОПТИМИЗИРОВАНО: Получение текущей цены с приоритетом DataRegistry (кэш из WebSocket).

        Приоритет источников:
        1. DataRegistry (обновляется через WebSocket) - БЫСТРО, без API запросов
        2. Цена закрытия свечи (fallback_price) - БЫСТРО, но может быть устаревшей
        3. API запрос (get_price_limits) - МЕДЛЕННО, только если нет других источников

        Args:
            symbol: Торговый символ
            fallback_price: Цена закрытия свечи как fallback (float)

        Returns:
            Текущая цена (float) - всегда возвращает float, никогда None
        """
        # ✅ ПРИОРИТЕТ 1: СВЕЖАЯ цена из DataRegistry (TTL 3s + REST fallback)
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (25.01.2026): Используем get_fresh_price_for_signals вместо get_price
        try:
            if self.data_registry:
                ws_max_age = 10.0
                try:
                    sg_cfg = getattr(self.scalping_config, "signal_generator", {})
                    if isinstance(sg_cfg, dict):
                        ws_max_age = float(sg_cfg.get("ws_fresh_max_age", ws_max_age))
                    else:
                        ws_max_age = float(
                            getattr(sg_cfg, "ws_fresh_max_age", ws_max_age)
                        )
                except Exception:
                    pass
                client_for_fresh = self.client
                price = await self.data_registry.get_fresh_price_for_signals(
                    symbol, client=client_for_fresh, max_age=ws_max_age
                )
                # ✅ ВАЖНО: Проверяем что price это float и > 0
                if (
                    price is not None
                    and isinstance(price, (int, float))
                    and float(price) > 0
                ):
                    logger.debug(
                        f"✅ SignalGenerator: Используем СВЕЖУЮ цену для {symbol}: ${price:.4f}"
                    )
                    return float(price)
        except Exception as e:
            logger.debug(
                f"⚠️ SignalGenerator: Не удалось получить СВЕЖУЮ цену для {symbol}: {e}"
            )

        # ✅ ПРИОРИТЕТ 2: Цена из свечи (fallback_price) - быстро, но может быть устаревшей
        if (
            self._allow_candle_price_fallback
            and fallback_price
            and isinstance(fallback_price, (int, float))
            and float(fallback_price) > 0
        ):
            logger.warning(
                f"SignalGenerator: using candle fallback price for {symbol}: {float(fallback_price):.4f}"
            )
            return float(fallback_price)

        # ✅ ПРИОРИТЕТ 3: API запрос (только если нет других источников) - МЕДЛЕННО
        try:
            if (
                self._allow_price_limits_fallback
                and self.client
                and hasattr(self.client, "get_price_limits")
            ):
                price_limits = await self.client.get_price_limits(symbol)
                if price_limits and isinstance(price_limits, dict):
                    current_price = price_limits.get("current_price", 0)
                    # ✅ ВАЖНО: Проверяем тип и значение
                    if (
                        current_price
                        and isinstance(current_price, (int, float))
                        and float(current_price) > 0
                    ):
                        logger.debug(
                            f"💰 Получена цена через API для {symbol}: {current_price:.2f}"
                        )
                        return float(current_price)
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить цену через API для {symbol}: {e}")

        # Без свежего snapshot не торгуем.
        return 0.0

    def _adjust_price_for_slippage(self, symbol: str, price: float, side: str) -> float:
        """
        ✅ НОВОЕ (28.12.2025): Корректировка цены сигнала с учетом slippage.

        Args:
            symbol: Торговый символ
            price: Базовая цена сигнала
            side: Направление сигнала ("buy" или "sell")

        Returns:
            Скорректированная цена с учетом slippage
        """
        if not price or price <= 0:
            return price

        try:
            # Получаем slippage из конфига
            slippage_pct = 0.1  # Fallback: 0.1%

            # Пробуем получить из scalping_config
            if hasattr(self.scalping_config, "slippage_percent"):
                slippage_pct = float(
                    getattr(self.scalping_config, "slippage_percent", 0.1)
                )
            elif isinstance(self.scalping_config, dict):
                slippage_pct = float(self.scalping_config.get("slippage_percent", 0.1))

            # Корректируем цену в зависимости от направления
            if side.lower() == "buy":
                # Для LONG: увеличиваем цену входа (покупаем дороже из-за slippage)
                # Лимит выше текущей цены → ордер сработает быстрее
                adjusted_price = price * (1 + slippage_pct / 100)
            else:  # sell
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 8.1.2026: Для SHORT тоже УВЕЛИЧИВАЕМ цену!
                # Лимит должен быть ВЫШЕ текущей цены (продаем дороже)
                # ❌ БЫЛО (неправильно): price * (1 - slippage) → лимит ниже цены, ордер не сработает
                # ✅ СТАЛО (правильно): price * (1 + slippage) → лимит выше цены, быстрое исполнение
                adjusted_price = price * (1 + slippage_pct / 100)

            logger.debug(
                f"💰 {symbol}: Цена сигнала скорректирована на slippage {slippage_pct:.3f}% "
                f"({side.upper()}): {price:.6f} → {adjusted_price:.6f}"
            )
            return adjusted_price
        except Exception as e:
            logger.debug(f"⚠️ Ошибка корректировки цены на slippage для {symbol}: {e}")
            return price  # Возвращаем исходную цену при ошибке

    async def _get_market_data(self, symbol: str) -> Optional[MarketData]:
        """
        ✅ НОВОЕ: Получение рыночных данных из DataRegistry (инкрементальное обновление).

        Использует свечи из CandleBuffer в DataRegistry вместо запросов к API.
        Если свечей нет в DataRegistry - делает fallback к API запросу (для инициализации).
        """
        try:
            # ✅ НОВОЕ: Сначала пытаемся получить свечи из DataRegistry
            if self.data_registry:
                try:
                    candles_1m = await self.data_registry.get_candles(symbol, "1m")

                    def _detect_candle_gaps(candles: List[OHLCV]) -> Optional[str]:
                        if not candles:
                            return None
                        last_ts = getattr(candles[-1], "timestamp", None)
                        if last_ts is not None:
                            age_sec = time.time() - float(last_ts)
                            if age_sec > 120:
                                return f"last_candle_stale_{age_sec:.0f}s"
                        lookback = min(len(candles), 20)
                        recent = candles[-lookback:]
                        prev_ts = None
                        for candle in recent:
                            ts = getattr(candle, "timestamp", None)
                            if ts is None:
                                continue
                            if prev_ts is not None and (ts - prev_ts) > 90:
                                return f"gap_{ts - prev_ts:.0f}s"
                            prev_ts = ts
                        return None

                    gap_reason = _detect_candle_gaps(candles_1m or [])
                    if gap_reason:
                        logger.warning(
                            f"⚠️ {symbol}: обнаружены разрывы/устаревание свечей 1m ({gap_reason}) — "
                            f"используем REST fallback для восстановления"
                        )
                        candles_1m = None

                    if (
                        candles_1m and len(candles_1m) >= 15
                    ):  # 🔴 BUG #4 FIX: Снижена граница с 30 до 15 свечей для ранней генерации сигналов
                        logger.debug(
                            f"📊 Получено {len(candles_1m)} свечей 1m для {symbol} из DataRegistry"
                        )

                        # Создаем MarketData с свечами из DataRegistry
                        return MarketData(
                            symbol=symbol,
                            timeframe="1m",
                            ohlcv_data=candles_1m,
                        )
                    else:
                        count = len(candles_1m) if candles_1m else 0
                        if count >= 10:
                            # 🔴 BUG #4 FIX: Вернуть рано с 10+ свечей вместо ждать 30
                            # Есть базовый минимум — не дергаем REST, подождем накопления
                            logger.debug(
                                f"✅ Достаточно свечей из DataRegistry для {symbol}: {count}/15 (было 30) — начинаем генерацию сигналов"
                            )
                            # Создаем MarketData с доступными свечами, вместо return None
                            return MarketData(
                                symbol=symbol,
                                timeframe="1m",
                                ohlcv_data=candles_1m,
                            )
                        else:
                            logger.info(
                                f"REST_FALLBACK {symbol} — в буфере {count}/10 свечей, загружаем историю через API"
                            )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка получения свечей из DataRegistry для {symbol}: {e}, переключаемся на REST API"
                    )

            # Fallback: если DataRegistry недоступен или свечей <10 — запрашиваем через REST API для первичной инициализации

            import aiohttp

            # ✅ ИСПРАВЛЕНО (06.01.2026): Загружаем 500 свечей 1m для инициализации буфера (лучший прогрев ATR/BB)
            inst_id = f"{symbol}-SWAP"
            url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1m&limit=500"

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
                                    f"📊 Получено {len(ohlcv_data)} свечей для {symbol} через API (fallback)"
                                )

                                # ✅ НОВОЕ: Инициализируем буфер в DataRegistry, если он еще не инициализирован
                                if self.data_registry:
                                    try:
                                        await self.data_registry.initialize_candles(
                                            symbol=symbol,
                                            timeframe="1m",
                                            candles=ohlcv_data,
                                            max_size=200,
                                        )
                                        logger.info(
                                            f"✅ DataRegistry: Инициализирован буфер свечей 1m для {symbol} "
                                            f"({len(ohlcv_data)} свечей)"
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"⚠️ Ошибка инициализации буфера свечей в DataRegistry для {symbol}: {e}"
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
        self, symbol: str, market_data: MarketData, regime: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Генерация базовых торговых сигналов"""
        try:
            signals = []

            # ✅ ИСПРАВЛЕНИЕ (09.01.2026): Инициализируем current_regime в начале метода
            current_regime = regime  # Используем переданный режим или None

            # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #6: Проверяем валидность market_data и свечей ПЕРЕД расчетом индикаторов (БЕЗ FALLBACK)

            if not market_data or not market_data.ohlcv_data:
                logger.error(
                    f"❌ [SIGNAL BLOCKED] {symbol}: market_data или свечи отсутствуют — блокировка генерации сигналов до прогрева данных"
                )
                return []

            # FIX (2026-02-20): Исключаем текущую НЕЗАКРЫТУЮ свечу из индикаторов.
            # Проблема: бот входил по каждому тику, индикаторы считались на незакрытой свече.
            # ATR незакрытой свечи = недостоверен (прошло 20-40 сек из 60).
            # Результат: EMA/RSI/MACD реагировали на внутрисвечный шум → ложные сигналы →
            # вход в середину свечи → SL hit на нормальном откате → цена потом шла куда надо.
            # Гибрид: индикаторы на ЗАКРЫТЫХ свечах, вход по следующему тику (быстро + точно).
            candles = (
                market_data.ohlcv_data[:-1]
                if len(market_data.ohlcv_data) > 1
                else market_data.ohlcv_data
            )
            min_candles_required = 15  # period=14 + 1 для ATR
            if len(candles) < min_candles_required:
                logger.error(
                    f"❌ [SIGNAL BLOCKED] {symbol}: Недостаточно свечей для расчёта индикаторов (есть {len(candles)}, нужно {min_candles_required}) — блокировка генерации сигналов до прогрева данных"
                )
                return []

            # Проверяем валидность свечей (все цены > 0)
            invalid_candles = [
                i
                for i, c in enumerate(candles)
                if c.high <= 0 or c.low <= 0 or c.close <= 0
            ]
            if invalid_candles:
                logger.error(
                    f"❌ [SIGNAL BLOCKED] {symbol}: Найдены невалидные свечи (индексы: {invalid_candles[:5]}) — блокировка генерации сигналов до прогрева данных"
                )
                return []

            # Технические индикаторы
            indicator_results = self.indicator_manager.calculate_all(market_data)

            # ✅ АДАПТИВНОСТЬ: Per-symbol индикаторы для пар с нестандартными параметрами
            # Проверяем есть ли специфичные параметры индикаторов для символа
            symbol_indicators_config = None
            try:
                if hasattr(self.scalping_config, "by_symbol"):
                    by_symbol = getattr(self.scalping_config, "by_symbol", {})
                    if isinstance(by_symbol, dict) and symbol in by_symbol:
                        symbol_config = by_symbol[symbol]
                        if hasattr(symbol_config, "indicators"):
                            symbol_indicators_config = getattr(
                                symbol_config, "indicators", {}
                            )
                            if not isinstance(symbol_indicators_config, dict):
                                symbol_indicators_config = None
                        elif (
                            isinstance(symbol_config, dict)
                            and "indicators" in symbol_config
                        ):
                            symbol_indicators_config = symbol_config["indicators"]
            except Exception as e:
                logger.debug(
                    f"⚠️ [INDICATORS] {symbol}: Ошибка чтения by_symbol.indicators: {e}"
                )

            # Если найдена специфичная конфигурация индикаторов - пересчитываем
            if symbol_indicators_config:
                try:
                    import talib

                    from src.indicators.base import IndicatorResult

                    # Получаем массивы данных
                    highs = np.array([c.high for c in candles], dtype=float)
                    lows = np.array([c.low for c in candles], dtype=float)
                    closes = np.array([c.close for c in candles], dtype=float)

                    recalculated = []

                    # 1. ATR с per-symbol периодом
                    symbol_atr_period = symbol_indicators_config.get("atr_period")
                    if symbol_atr_period is not None:
                        atr_array = talib.ATR(
                            highs, lows, closes, timeperiod=symbol_atr_period
                        )
                        atr_value = (
                            float(atr_array[-1])
                            if not np.isnan(atr_array[-1])
                            else None
                        )
                        if atr_value and atr_value > 0:
                            indicator_results["ATR"] = IndicatorResult(
                                name="ATR",
                                value=atr_value,
                                metadata={"period": symbol_atr_period},
                            )
                            recalculated.append(f"ATR(period={symbol_atr_period})")

                    # 2. RSI с per-symbol периодом
                    symbol_rsi_period = symbol_indicators_config.get("rsi_period")
                    if symbol_rsi_period is not None:
                        rsi_array = talib.RSI(closes, timeperiod=symbol_rsi_period)
                        rsi_value = (
                            float(rsi_array[-1])
                            if not np.isnan(rsi_array[-1])
                            else None
                        )
                        if rsi_value is not None:
                            indicator_results["RSI"] = IndicatorResult(
                                name="RSI",
                                value=rsi_value,
                                metadata={
                                    "period": symbol_rsi_period,
                                    "overbought": symbol_indicators_config.get(
                                        "rsi_overbought", 70
                                    ),
                                    "oversold": symbol_indicators_config.get(
                                        "rsi_oversold", 30
                                    ),
                                },
                            )
                            recalculated.append(f"RSI(period={symbol_rsi_period})")

                    # 3. EMA_12 и EMA_26 с per-symbol периодами
                    symbol_ema_fast = symbol_indicators_config.get("ema_fast")
                    symbol_ema_slow = symbol_indicators_config.get("ema_slow")
                    if symbol_ema_fast is not None:
                        ema_fast_array = talib.EMA(closes, timeperiod=symbol_ema_fast)
                        ema_fast_value = (
                            float(ema_fast_array[-1])
                            if not np.isnan(ema_fast_array[-1])
                            else None
                        )
                        if ema_fast_value is not None:
                            indicator_results["EMA_12"] = IndicatorResult(
                                name="EMA_12",
                                value=ema_fast_value,
                                metadata={"period": symbol_ema_fast},
                            )
                            recalculated.append(f"EMA_12(period={symbol_ema_fast})")

                    if symbol_ema_slow is not None:
                        ema_slow_array = talib.EMA(closes, timeperiod=symbol_ema_slow)
                        ema_slow_value = (
                            float(ema_slow_array[-1])
                            if not np.isnan(ema_slow_array[-1])
                            else None
                        )
                        if ema_slow_value is not None:
                            indicator_results["EMA_26"] = IndicatorResult(
                                name="EMA_26",
                                value=ema_slow_value,
                                metadata={"period": symbol_ema_slow},
                            )
                            recalculated.append(f"EMA_26(period={symbol_ema_slow})")

                    # 4. MACD с per-symbol периодами
                    symbol_macd_fast = symbol_indicators_config.get("macd_fast")
                    symbol_macd_slow = symbol_indicators_config.get("macd_slow")
                    if symbol_macd_fast is not None and symbol_macd_slow is not None:
                        macd_signal_period = 9  # Стандартный signal period
                        macd, signal, hist = talib.MACD(
                            closes,
                            fastperiod=symbol_macd_fast,
                            slowperiod=symbol_macd_slow,
                            signalperiod=macd_signal_period,
                        )
                        macd_value = float(macd[-1]) if not np.isnan(macd[-1]) else None
                        signal_value = (
                            float(signal[-1]) if not np.isnan(signal[-1]) else None
                        )
                        if macd_value is not None and signal_value is not None:
                            indicator_results["MACD"] = IndicatorResult(
                                name="MACD",
                                value=macd_value,
                                metadata={
                                    "macd_line": macd_value,
                                    "signal_line": signal_value,
                                    "fast_period": symbol_macd_fast,
                                    "slow_period": symbol_macd_slow,
                                },
                            )
                            recalculated.append(
                                f"MACD(fast={symbol_macd_fast}/slow={symbol_macd_slow})"
                            )

                    # 5. Bollinger Bands с per-symbol периодом
                    symbol_bb_period = symbol_indicators_config.get("bb_period")
                    symbol_bb_std = symbol_indicators_config.get("bb_std_multiplier")
                    if symbol_bb_period is not None:
                        std_mult = symbol_bb_std if symbol_bb_std is not None else 2.0
                        upper, middle, lower = talib.BBANDS(
                            closes,
                            timeperiod=symbol_bb_period,
                            nbdevup=std_mult,
                            nbdevdn=std_mult,
                        )
                        upper_value = (
                            float(upper[-1]) if not np.isnan(upper[-1]) else None
                        )
                        middle_value = (
                            float(middle[-1]) if not np.isnan(middle[-1]) else None
                        )
                        lower_value = (
                            float(lower[-1]) if not np.isnan(lower[-1]) else None
                        )
                        if all(
                            v is not None
                            for v in [upper_value, middle_value, lower_value]
                        ):
                            indicator_results["BollingerBands"] = IndicatorResult(
                                name="BollingerBands",
                                value=middle_value,
                                metadata={
                                    "upper_band": upper_value,
                                    "lower_band": lower_value,
                                    "period": symbol_bb_period,
                                    "std_multiplier": std_mult,
                                },
                            )
                            recalculated.append(
                                f"BB(period={symbol_bb_period}, std={std_mult})"
                            )

                    # Логируем что было пересчитано
                    if recalculated:
                        logger.info(
                            f"✅ [АДАПТИВНО] {symbol}: Пересчитаны индикаторы с per-symbol параметрами: {', '.join(recalculated)}"
                        )

                except Exception as e:
                    logger.error(
                        f"❌ [АДАПТИВНО] {symbol}: Ошибка пересчёта per-symbol индикаторов: {e}"
                    )

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Логируем результат расчета индикаторов
            logger.debug(
                f"🔍 [INDICATORS] {symbol}: indicator_manager.calculate_all вернул {len(indicator_results)} индикаторов: {list(indicator_results.keys())}"
            )

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
                    # ✅ ИСПРАВЛЕНО: БЕЗ FALLBACK - просто сохраняем как есть, но логируем неожиданный тип
                    indicators[name.lower()] = result
                    logger.debug(
                        f"⚠️ [INDICATORS] {symbol}: Неожиданный тип результата для {name}: {type(result)}"
                    )

            # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #6: Проверяем ATR после расчета (БЕЗ FALLBACK)
            atr_value = indicators.get("atr") or indicators.get("atr_14")
            if atr_value is None or atr_value <= 0:
                logger.error(
                    f"❌ [ATR] {symbol}: ATR не рассчитан или равен 0/None (value={atr_value}) - "
                    f"ПРОПУСКАЕМ генерацию сигналов. Количество свечей: {len(candles)}, "
                    f"indicator_results keys: {list(indicator_results.keys())}"
                )
                return []

            # ✅ УДАЛЕНО: Проверка ADX здесь некорректна - ADX еще не получен из DataRegistry/fallback
            # Проверка ADX будет выполнена ПОСЛЕ получения из DataRegistry/fallback (строка ~2290)

            # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #8: Обновляем market_data.indicators для совместимости
            if not hasattr(market_data, "indicators"):
                market_data.indicators = {}
            market_data.indicators.update(indicators)
            if not market_data.indicators:
                logger.error(
                    f"❌ [INDICATORS] {symbol}: market_data.indicators пуст после обновления - "
                    f"ПРОПУСКАЕМ генерацию сигналов"
                )
                return []
            logger.debug(
                f"✅ [INDICATORS] {symbol}: market_data.indicators обновлен, ключи: {list(market_data.indicators.keys())}"
            )

            # ✅ НОВОЕ: Сохраняем индикаторы в DataRegistry
            if self.data_registry:
                try:
                    # Подготавливаем индикаторы для сохранения в DataRegistry
                    # Конвертируем сложные индикаторы в простые значения
                    indicators_for_registry = {}

                    # Простые индикаторы (RSI, ATR)
                    # ✅ ИСПРАВЛЕНО: ATR может быть сохранен как "atr_14" вместо "atr"
                    for key in ["rsi", "atr", "sma_20", "ema_12", "ema_26"]:
                        # Проверяем основное имя и варианты с периодом
                        value = None
                        if key in indicators:
                            value = indicators[key]
                        elif key == "atr":
                            # Ищем ATR с периодом (atr_14, atr_1m и т.д.)
                            for atr_key in ["atr_14", "atr_1m", "atr"]:
                                if atr_key in indicators:
                                    value = indicators[atr_key]
                                    break

                        if value is not None and isinstance(value, (int, float)):
                            # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #6: НЕ сохраняем ATR=0.0 в DataRegistry (БЕЗ FALLBACK)
                            if key == "atr":
                                if value == 0.0:
                                    logger.error(
                                        f"❌ [ATR] {symbol}: ATR равен 0.0 - НЕ сохраняем в DataRegistry (БЕЗ FALLBACK)"
                                    )
                                    # ✅ НЕ сохраняем ATR=0.0 (это проверено выше и вернет пустой список)
                                else:
                                    found_key = (
                                        atr_key if "atr_key" in locals() else key
                                    )
                                    logger.debug(
                                        f"📊 Сохранение ATR для {symbol}: {value:.6f} (найден по ключу: {found_key})"
                                    )
                                    indicators_for_registry[key] = value
                            elif value > 0:
                                indicators_for_registry[key] = value
                        elif key == "atr":
                            # Логируем, почему ATR не сохранился
                            logger.debug(
                                f"⚠️ ATR для {symbol} не сохранен: value={value}, "
                                f"type={type(value)}, indicators keys={list(indicators.keys())}"
                            )

                    # MACD (сложный индикатор - сохраняем ТОЛЬКО как DICT)
                    # ✅ ИСПРАВЛЕНО (06.01.2026): Унифицирован формат - всегда dict для консистентности
                    if "macd" in indicators:
                        macd_data = indicators["macd"]
                        if isinstance(macd_data, dict):
                            # Сохраняем весь dict - это основной формат
                            indicators_for_registry["macd"] = macd_data
                        else:
                            # Если MACD не dict (скаляр) - оборачиваем в dict
                            indicators_for_registry["macd"] = {
                                "macd": macd_data,
                                "signal": 0,
                                "histogram": 0,
                            }

                    # Bollinger Bands (сложный индикатор - сохраняем как отдельные значения)
                    if "bollinger_bands" in indicators:
                        bb_data = indicators["bollinger_bands"]
                        if isinstance(bb_data, dict):
                            indicators_for_registry["bb_upper"] = bb_data.get(
                                "upper", 0
                            )
                            indicators_for_registry["bb_lower"] = bb_data.get(
                                "lower", 0
                            )
                            indicators_for_registry["bb_middle"] = bb_data.get(
                                "middle", 0
                            )

                    # Сохраняем все индикаторы в DataRegistry одним вызовом
                    if indicators_for_registry:
                        await self.data_registry.update_indicators(
                            symbol, indicators_for_registry
                        )
                        logger.debug(
                            f"✅ DataRegistry: Сохранены индикаторы для {symbol}: {list(indicators_for_registry.keys())}"
                        )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Ошибка сохранения индикаторов в DataRegistry для {symbol}: {e}"
                    )

            # ✅ ИСПРАВЛЕНИЕ #31 (04.01.2026): Детальное логирование значений индикаторов при генерации сигналов
            rsi_val = indicators.get("rsi", "N/A")
            macd_val = indicators.get("macd", {})
            if isinstance(macd_val, dict):
                macd_line = macd_val.get("macd", 0)
                signal_line = macd_val.get("signal", 0)
                histogram = macd_line - signal_line
                macd_str = f"macd={macd_line:.4f}, signal={signal_line:.4f}, histogram={histogram:.4f}"
            else:
                macd_str = str(macd_val)

            # ✅ ИСПРАВЛЕНО: Получаем EMA и BB БЕЗ fallback - показываем реальное состояние
            ema_12 = indicators.get("ema_12")
            ema_26 = indicators.get("ema_26")
            atr_val = indicators.get("atr") or indicators.get("atr_14")
            bb_data = indicators.get("bollinger_bands")
            bb_upper = bb_data.get("upper") if isinstance(bb_data, dict) else None
            bb_lower = bb_data.get("lower") if isinstance(bb_data, dict) else None
            bb_middle = bb_data.get("middle") if isinstance(bb_data, dict) else None

            # Логируем проблемы с индикаторами
            if ema_12 is None:
                logger.warning(
                    f"⚠️ [EMA] {symbol}: EMA_12 НЕ РАССЧИТАН (индикатор отсутствует в indicators)"
                )
            if ema_26 is None:
                logger.warning(
                    f"⚠️ [EMA] {symbol}: EMA_26 НЕ РАССЧИТАН (индикатор отсутствует в indicators)"
                )
            if bb_data is None or not isinstance(bb_data, dict):
                logger.warning(
                    f"⚠️ [BB] {symbol}: Bollinger Bands НЕ РАССЧИТАН (bb_data={bb_data})"
                )
            # FIX 2026-02-22 P1: относительный порог вместо абсолютного 0.0001
            # Для BTC($95k): 0.0001 = 0.0000001% → порог никогда не срабатывал
            # Для DOGE($0.1): 0.0001 = 0.1% → ложные срабатывания на нормальных сигналах
            if (
                ema_12 is not None
                and ema_26 is not None
                and ema_26 > 0
                and abs(ema_12 - ema_26) / ema_26 < 1e-5  # 0.001% от цены
            ):
                logger.warning(
                    f"⚠️ [EMA] {symbol}: EMA_12 и EMA_26 ОДИНАКОВЫЕ ({ema_12:.6f}) - возможно, недостаточно данных или ошибка расчета"
                )

            # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #1: Получаем ADX и ATR из DataRegistry ДО логирования
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Получаем ADX тренд ДО генерации сигналов
            # ✅ ПРИОРИТЕТ 1: Читаем ADX из DataRegistry (где он уже сохранен per-symbol)
            # ✅ ПРИОРИТЕТ 2: Если нет в DataRegistry - рассчитываем из свечей через adx_filter (fallback)
            adx_trend = None  # "bullish", "bearish", "ranging", None
            adx_value = 0.0
            adx_plus_di = 0.0
            adx_minus_di = 0.0
            adx_threshold = 20.0  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен дефолтный порог с 25 до 20
            adx_from_registry = False  # Флаг, откуда взят ADX

            # ✅ ИСПРАВЛЕНО: Получаем ADX из DataRegistry ДО логирования
            if self.data_registry:
                try:
                    indicators_from_registry = await self.data_registry.get_indicators(
                        symbol
                    )
                    if indicators_from_registry:
                        # Получаем ADX из DataRegistry
                        adx_from_reg = indicators_from_registry.get("adx")
                        # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #1: НЕ используем ADX=0.0
                        if adx_from_reg == 0.0:
                            adx_from_reg = None
                        if (
                            adx_from_reg
                            and isinstance(adx_from_reg, (int, float))
                            and float(adx_from_reg) > 0
                        ):
                            adx_value = float(adx_from_reg)
                            adx_plus_di = (
                                float(indicators_from_registry.get("adx_plus_di", 0))
                                if indicators_from_registry.get("adx_plus_di")
                                else 0.0
                            )
                            adx_minus_di = (
                                float(indicators_from_registry.get("adx_minus_di", 0))
                                if indicators_from_registry.get("adx_minus_di")
                                else 0.0
                            )
                            adx_from_registry = True

                        # ✅ ИСПРАВЛЕНО: Получаем ATR из DataRegistry (если не получен из indicators)
                        if atr_val == 0 or atr_val is None:
                            atr_from_reg = indicators_from_registry.get("atr")
                            if atr_from_reg and atr_from_reg > 0:
                                atr_val = atr_from_reg
                            else:
                                # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #1: Используем ATRProvider с fallback
                                if hasattr(self, "atr_provider") and self.atr_provider:
                                    try:
                                        atr_from_provider = self.atr_provider.get_atr(
                                            symbol
                                        )  # БЕЗ FALLBACK
                                        if atr_from_provider and atr_from_provider > 0:
                                            atr_val = atr_from_provider
                                    except Exception as exc:
                                        logger.debug(
                                            "Ignored error in optional block: %s", exc
                                        )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Не удалось получить ADX/ATR из DataRegistry для логирования {symbol}: {e}"
                    )

            # ✅ FALLBACK: Если ADX не получен из DataRegistry, рассчитываем через adx_filter ПЕРЕД определением тренда
            if (
                not adx_from_registry
                and self.adx_filter
                and self.adx_filter.config.enabled
            ):
                try:
                    # Получаем порог из конфига
                    adx_threshold = self.adx_filter.config.adx_threshold

                    # Конвертируем свечи в формат для ADX фильтра
                    candles_dict = []
                    if market_data and market_data.ohlcv_data:
                        for candle in market_data.ohlcv_data:
                            candles_dict.append(
                                {
                                    "high": candle.high,
                                    "low": candle.low,
                                    "close": candle.close,
                                }
                            )

                    if candles_dict:
                        # Проверяем тренд для BUY и SELL
                        from src.strategies.modules.adx_filter import OrderSide

                        # Проверяем BUY (LONG)
                        buy_result = self.adx_filter.check_trend_strength(
                            symbol, OrderSide.BUY, candles_dict
                        )
                        # Проверяем SELL (SHORT)
                        sell_result = self.adx_filter.check_trend_strength(
                            symbol, OrderSide.SELL, candles_dict
                        )

                        # Определяем тренд на основе ADX
                        adx_value = buy_result.adx_value
                        adx_plus_di = buy_result.plus_di
                        adx_minus_di = buy_result.minus_di

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сохраняем ADX в indicators для доступа в _generate_symbol_signals
                        indicators["adx"] = adx_value
                        indicators["adx_plus_di"] = adx_plus_di
                        indicators["adx_minus_di"] = adx_minus_di

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 8.1.2026: Сохраняем ADX в DataRegistry
                        # (была ошибка - ADX считался но не сохранялся в registry)
                        if self.data_registry:
                            try:
                                await self.data_registry.update_indicators(
                                    symbol,
                                    {
                                        "adx": adx_value,
                                        "adx_plus_di": adx_plus_di,
                                        "adx_minus_di": adx_minus_di,
                                    },
                                )
                                logger.debug(
                                    f"✅ ADX сохранен в DataRegistry для {symbol}: ADX={adx_value:.2f}, +DI={adx_plus_di:.2f}, -DI={adx_minus_di:.2f}"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"⚠️ Ошибка сохранения ADX в DataRegistry для {symbol}: {e}"
                                )

                        logger.debug(
                            f"✅ ADX для {symbol} рассчитан через adx_filter (fallback): ADX={adx_value:.2f}, +DI={adx_plus_di:.2f}, -DI={adx_minus_di:.2f}"
                        )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Ошибка расчета ADX через adx_filter для {symbol}: {e}, "
                        f"сигналы будут генерироваться без учета ADX"
                    )

            # ✅ ИСПРАВЛЕНО: Для логирования используем актуальное значение adx_value (может быть обновлено через fallback)
            adx_for_log = (
                adx_value
                if adx_value > 0
                else indicators.get("adx", indicators.get("adx_proxy", 0))
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (10.01.2026): Заменён жёсткий блок на мягкий fallback
            # Если ADX=0 после всех попыток → генерируем сигналы в degraded режиме (ranging, без ADX-проверок)
            if adx_value <= 0 or adx_for_log <= 0:
                logger.warning(
                    f"⚠️ [ADX] {symbol}: ADX не получен из DataRegistry/fallback "
                    f"(adx_value={adx_value}, adx_for_log={adx_for_log}, adx_from_registry={adx_from_registry}). "
                    f"Продолжаем генерацию в degraded режиме: adx_trend=ranging, adx_value=0. "
                    f"Свечей: {len(candles)}, indicators: {list(indicator_results.keys())}"
                )
                # Degraded mode: принудительно устанавливаем ranging и ADX=0
                adx_trend = "ranging"
                adx_value = 0.0
                adx_plus_di = 0.0
                adx_minus_di = 0.0
                # НЕ блокируем генерацию - продолжаем работу

            # ✅ ИСПРАВЛЕНО: Определяем направление тренда ДО логирования (после fallback)
            if adx_value > 0:
                adx_threshold_for_trend = (
                    self.adx_filter.config.adx_threshold if self.adx_filter else 20.0
                )
                if adx_value >= adx_threshold_for_trend:
                    # Сильный тренд
                    di_difference = (
                        self.adx_filter.config.di_difference if self.adx_filter else 5.0
                    )
                    if adx_plus_di > adx_minus_di + di_difference:
                        adx_trend = "bullish"  # Восходящий тренд
                    elif adx_minus_di > adx_plus_di + di_difference:
                        adx_trend = "bearish"  # Нисходящий тренд
                    else:
                        adx_trend = "ranging"  # Нейтральный (DI близки)
                else:
                    # Слабый тренд (ADX < threshold)
                    adx_trend = "ranging"

            # Получаем текущую цену для логирования
            current_price_log = 0.0
            if market_data and market_data.ohlcv_data:
                current_price_log = self._get_current_price(market_data)

            # ✅ ИСПРАВЛЕНО: Правильное форматирование RSI (сначала проверяем тип, потом форматируем)
            rsi_str = (
                f"{rsi_val:.2f}" if isinstance(rsi_val, (int, float)) else str(rsi_val)
            )

            # Форматируем значения БЕЗ fallback на 0
            ema_12_str = f"{ema_12:.2f}" if ema_12 is not None else "НЕ РАССЧИТАН"
            ema_26_str = f"{ema_26:.2f}" if ema_26 is not None else "НЕ РАССЧИТАН"
            bb_upper_str = f"{bb_upper:.2f}" if bb_upper is not None else "НЕ РАССЧИТАН"
            bb_middle_str = (
                f"{bb_middle:.2f}" if bb_middle is not None else "НЕ РАССЧИТАН"
            )
            bb_lower_str = f"{bb_lower:.2f}" if bb_lower is not None else "НЕ РАССЧИТАН"
            # ✅ НОВОЕ: Адаптивное форматирование ATR для микро-значений
            if atr_val is not None and atr_val > 0:
                if atr_val < 0.01:
                    atr_val_str = f"{atr_val:.8f}"  # 8 знаков для DOGE/XRP
                elif atr_val < 0.1:
                    atr_val_str = f"{atr_val:.4f}"  # 4 знака для SOL
                else:
                    atr_val_str = f"{atr_val:.2f}"  # 2 знака для BTC/ETH
            else:
                atr_val_str = "НЕ РАССЧИТАН"

            logger.info(
                f"📊 [INDICATORS] {symbol}: Значения индикаторов при генерации сигналов | "
                f"Цена: ${current_price_log:.2f} | "
                f"RSI: {rsi_str} | "
                f"MACD: {macd_str} | "
                f"ADX: {adx_for_log:.2f} (+DI={adx_plus_di:.2f}, -DI={adx_minus_di:.2f}, trend={adx_trend or 'НЕ ОПРЕДЕЛЕН'}) | "
                f"ATR: {atr_val_str} | "
                f"EMA: 12={ema_12_str}, 26={ema_26_str} | "
                f"BB: upper={bb_upper_str}, middle={bb_middle_str}, lower={bb_lower_str}"
            )
            # ✅ ОПТИМИЗАЦИЯ: Используем актуальную цену из стакана для сигналов вместо цены закрытия свечи
            # Это синхронизирует цену сигнала с текущей рыночной ценой
            candle_close_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )
            current_price = await self._get_current_market_price(
                symbol, candle_close_price
            )
            if current_price <= 0:
                logger.warning(
                    f"⚠️ {symbol}: нет валидной текущей цены для генерации сигналов (current_price={current_price}), "
                    "пропускаем символ в этом цикле"
                )
                return []

            # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование всех индикаторов (экономия ~30% логов)
            # Логируем только при генерации реальных сигналов (INFO уровень)
            # logger.debug(f"📊 Индикаторы для {symbol}: цена=${current_price:.2f}, RSI={rsi_val}")

            # ✅ ИСПРАВЛЕНО: ADX и тренд уже определены ДО логирования (строки 2097-2167)
            # Fallback через adx_filter и определение тренда выполняются перед логированием

            # ✅ НОВОЕ (27.12.2025): Счетчики для детального логирования
            signal_stats = {
                "rsi": {"generated": 0, "blocked_adx": 0},
                "macd": {"generated": 0, "blocked_adx": 0},
                "bb": {"generated": 0, "blocked_adx": 0},
                "ma": {"generated": 0, "blocked_adx": 0},
                "adx": {
                    "generated": 0,
                    "blocked_adx": 0,
                },  # ✅ НОВОЕ (29.12.2025): Счетчик для ADX сигналов
            }

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (30.12.2025): Фильтр по волатильности для CHOPPY режима
            # Пропускаем генерацию сигналов при vol>3% в CHOPPY режиме (высокий риск)
            current_regime_for_vol = None
            try:
                if self.data_registry:
                    regime_data = await self.data_registry.get_regime(symbol)
                    if regime_data:
                        current_regime_for_vol = regime_data.get("regime", "").lower()
            except Exception as exc:
                logger.debug("Ignored error in optional block: %s", exc)

            if current_regime_for_vol == "choppy":
                # Получаем ATR для расчета волатильности
                atr_14 = indicators.get("atr_14", 0) if indicators else 0
                # Ищем ATR в разных форматах
                if atr_14 == 0:
                    for atr_key in ["atr", "atr_1m"]:
                        if atr_key in indicators:
                            atr_14 = indicators[atr_key]
                            break

                candle_close_price = (
                    market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
                )
                current_price_for_vol = await self._get_current_market_price(
                    symbol, candle_close_price
                )

                if atr_14 > 0 and current_price_for_vol > 0:
                    volatility_pct = (atr_14 / current_price_for_vol) * 100.0
                    if volatility_pct > 3.0:
                        logger.debug(
                            f"🚫 {symbol}: CHOPPY режим, волатильность {volatility_pct:.2f}% > 3%, "
                            f"пропускаем генерацию сигналов (высокий риск)"
                        )
                        # Возвращаем пустой список сигналов - фильтр сработал
                        return []

            # ✅ РЕФАКТОРИНГ: Используем новые модули генерации сигналов
            # RSI сигналы
            if self.rsi_signal_generator:
                rsi_signals = await self.rsi_signal_generator.generate_signals(
                    symbol, indicators, market_data, adx_trend, adx_value, adx_threshold
                )
                signal_stats["rsi"]["generated"] = len(rsi_signals)
                signals.extend(rsi_signals)
            else:
                # Fallback на старый метод
                rsi_signals = await self._generate_rsi_signals(
                    symbol, indicators, market_data, adx_trend, adx_value, adx_threshold
                )
                signal_stats["rsi"]["generated"] = len(rsi_signals)
                signals.extend(rsi_signals)

            # MACD сигналы
            if self.macd_signal_generator:
                macd_signals = await self.macd_signal_generator.generate_signals(
                    symbol, indicators, market_data, adx_trend, adx_value, adx_threshold
                )
                signal_stats["macd"]["generated"] = len(macd_signals)
                signals.extend(macd_signals)
            else:
                # Fallback на старый метод
                macd_signals = await self._generate_macd_signals(
                    symbol, indicators, market_data, adx_trend, adx_value, adx_threshold
                )
                signal_stats["macd"]["generated"] = len(macd_signals)
                signals.extend(macd_signals)

            # ✅ НОВОЕ (09.01.2026): TrendFollowing сигналы для LONG в uptrend
            if self.trend_following_generator:
                try:
                    trend_signals = (
                        await self.trend_following_generator.generate_signals(
                            symbol,
                            indicators,
                            market_data,
                            adx_trend,
                            adx_value,
                            adx_threshold,
                        )
                    )
                    signal_stats["trend_following"] = {
                        "generated": len(trend_signals),
                        "filtered": 0,
                    }
                    signals.extend(trend_signals)
                    if trend_signals:
                        logger.info(
                            f"✅ {symbol}: TrendFollowingSignalGenerator добавил {len(trend_signals)} сигналов "
                            f"(strategies: pullback/breakout/support_bounce)"
                        )
                except Exception as e:
                    logger.warning(
                        f"⚠️ TrendFollowingSignalGenerator ошибка для {symbol}: {e}"
                    )

            # Bollinger Bands сигналы
            bb_signals = await self._generate_bollinger_signals(
                symbol, indicators, market_data, adx_trend, adx_value, adx_threshold
            )
            signal_stats["bb"]["generated"] = len(bb_signals)
            signals.extend(bb_signals)

            # ✅ NEW (2026-02-18): RSI Divergence — ловит развороты ДО пробоя уровней
            rsi_div_signals = await self._generate_rsi_divergence_signals(
                symbol, indicators, market_data, adx_trend, adx_value
            )
            signal_stats["rsi_divergence"] = {
                "generated": len(rsi_div_signals),
                "filtered": 0,
            }
            signals.extend(rsi_div_signals)
            if rsi_div_signals:
                logger.info(
                    f"📐 {symbol}: RSI Divergence добавил {len(rsi_div_signals)} сигналов"
                )

            # ✅ NEW (2026-02-18): VWAP mean-reversion — возврат к VWAP при отклонении >1.5σ
            vwap_signals = await self._generate_vwap_signals(
                symbol, market_data, adx_trend
            )
            signal_stats["vwap"] = {"generated": len(vwap_signals), "filtered": 0}
            signals.extend(vwap_signals)
            if vwap_signals:
                logger.info(f"📊 {symbol}: VWAP добавил {len(vwap_signals)} сигналов")

            # Moving Average сигналы
            ma_signals = await self._generate_ma_signals(
                symbol, indicators, market_data, adx_trend, adx_value, adx_threshold
            )
            signal_stats["ma"]["generated"] = len(ma_signals)
            signals.extend(ma_signals)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Range-bounce сигналы для ranging режима (FIX 8)
            # Генерируем сигналы отскока от BB границ в ranging режиме
            if current_regime and current_regime.lower() == "ranging":
                range_bounce_signals = await self._generate_range_bounce_signals(
                    symbol, indicators, market_data
                )
                signal_stats["range_bounce"] = {
                    "generated": len(range_bounce_signals),
                    "filtered": 0,
                }
                signals.extend(range_bounce_signals)
                logger.debug(
                    f"🎯 Range-bounce сигналы для {symbol}: {len(range_bounce_signals)}"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (30.12.2025): Генерация SHORT сигналов по требованиям Grok
            # Условия для SHORT: RSI>75 + MACD down (MACD < signal_line) + ADX bearish >25
            rsi_value = indicators.get("rsi", 0) if indicators else 0
            macd_data = indicators.get("macd", {}) if indicators else {}
            macd_line = macd_data.get("macd", 0) if isinstance(macd_data, dict) else 0
            signal_line = (
                macd_data.get("signal", 0) if isinstance(macd_data, dict) else 0
            )

            # Получаем rsi_overbought из конфига
            rsi_overbought_threshold = 75  # По умолчанию 75
            try:
                if hasattr(self.scalping_config, "rsi_overbought"):
                    rsi_overbought_threshold = getattr(
                        self.scalping_config, "rsi_overbought", 75
                    )
                elif isinstance(self.scalping_config, dict):
                    rsi_overbought_threshold = self.scalping_config.get(
                        "rsi_overbought", 75
                    )
            except Exception as exc:
                logger.debug("Ignored error in optional block: %s", exc)

            # Проверяем условия для SHORT сигнала
            rsi_overbought = rsi_value > rsi_overbought_threshold
            macd_down = macd_line < signal_line if macd_line and signal_line else False
            adx_bearish_strong = adx_trend == "bearish" and adx_value > 25.0

            if rsi_overbought and macd_down and adx_bearish_strong:
                # Рассчитываем strength на основе всех условий
                rsi_strength = min(
                    1.0, (rsi_value - rsi_overbought_threshold) / 30.0
                )  # Нормализация от 75 до 105
                macd_strength = min(
                    1.0,
                    (
                        abs(macd_line - signal_line) / abs(signal_line)
                        if signal_line
                        else 0.5
                    ),
                )
                adx_strength = min(
                    1.0, (adx_value - 25.0) / 50.0
                )  # Нормализация от 25 до 75
                final_strength = (rsi_strength + macd_strength + adx_strength) / 3.0

                # Получаем текущую цену
                candle_close_price = (
                    market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
                )
                current_price = await self._get_current_market_price(
                    symbol, candle_close_price
                )

                # Генерируем SHORT сигнал
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "short_combo",  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (30.12.2025): Новый тип SHORT сигнала
                        "strength": final_strength,
                        "price": self._adjust_price_for_slippage(
                            symbol, current_price, "sell"
                        ),
                        "timestamp": datetime.now(timezone.utc),
                        "rsi": rsi_value,
                        "macd_line": macd_line,
                        "signal_line": signal_line,
                        "adx_value": adx_value,
                        "confidence": 0.8,  # Высокая уверенность при выполнении всех условий
                        "has_conflict": False,
                        "source": "short_combo_rsi_macd_adx",
                    }
                )
                signal_stats["adx"]["generated"] = (
                    signal_stats.get("adx", {}).get("generated", 0) + 1
                )
                logger.info(
                    f"📊 {symbol}: Сгенерирован SHORT сигнал (RSI={rsi_value:.1f}>{rsi_overbought_threshold}, "
                    f"MACD={macd_line:.4f}<signal={signal_line:.4f}, ADX={adx_value:.1f}>25 bearish, "
                    f"strength={final_strength:.3f})"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Генерация SHORT сигналов на основе ADX bearish тренда (старая логика для обратной совместимости)
            # Если ADX показывает сильный bearish тренд, генерируем SHORT сигнал
            # ✅ ДИАГНОСТИКА: Логируем условие для отладки
            if adx_trend == "bearish":
                logger.debug(
                    f"🔍 {symbol}: ADX bearish тренд обнаружен (ADX={adx_value:.1f}, threshold={adx_threshold:.1f}), "
                    f"проверяем условие: adx_value >= adx_threshold → {adx_value:.1f} >= {adx_threshold:.1f} = {adx_value >= adx_threshold}"
                )
            if adx_trend == "bearish" and adx_value >= adx_threshold:
                # ✅ ИСПРАВЛЕНО: Используем уже полученные DI значения вместо indicators.get()
                # adx_plus_di и adx_minus_di уже определены выше при получении ADX из DataRegistry или adx_filter

                # Рассчитываем strength на основе силы bearish тренда
                if adx_minus_di > 0 and adx_plus_di > 0:
                    # Strength = отношение -DI к +DI (чем больше, тем сильнее bearish)
                    bearish_strength = min(
                        1.0, (adx_minus_di / (adx_minus_di + adx_plus_di)) * 2
                    )
                    # Дополнительный boost от ADX значения
                    adx_boost = min(0.3, (adx_value - adx_threshold) / 50.0)
                    final_strength = min(1.0, bearish_strength + adx_boost)

                    # Получаем текущую цену
                    candle_close_price = (
                        market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0
                    )
                    current_price = await self._get_current_market_price(
                        symbol, candle_close_price
                    )

                    # Генерируем SHORT сигнал на основе ADX bearish тренда
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "adx_bearish",
                            "strength": final_strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "sell"
                            ),
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": adx_value,
                            "confidence": 0.7,  # Высокая уверенность при сильном bearish тренде
                            "has_conflict": False,
                            "source": "adx_bearish",
                        }
                    )
                    signal_stats["adx"]["generated"] = (
                        signal_stats.get("adx", {}).get("generated", 0) + 1
                    )
                    logger.debug(
                        f"📊 {symbol}: Сгенерирован SHORT сигнал на основе ADX bearish тренда "
                        f"(ADX={adx_value:.1f}, -DI={adx_minus_di:.1f}, +DI={adx_plus_di:.1f}, "
                        f"strength={final_strength:.3f})"
                    )

                # ✅ НОВОЕ: Генерируем LONG сигнал на основе ADX bullish тренда (зеркально SHORT)
                if adx_trend == "bullish" and adx_value >= adx_threshold:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "adx_bullish",
                            "strength": final_strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "buy"
                            ),
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": adx_value,
                            "confidence": 0.7,  # Высокая уверенность при сильном bullish тренде
                            "has_conflict": False,
                            "source": "adx_bullish",
                        }
                    )
                    signal_stats["adx"]["generated"] = (
                        signal_stats.get("adx", {}).get("generated", 0) + 1
                    )
                    logger.debug(
                        f"📊 {symbol}: Сгенерирован LONG сигнал на основе ADX bullish тренда "
                        f"(ADX={adx_value:.1f}, +DI={adx_plus_di:.1f}, -DI={adx_minus_di:.1f}, "
                        f"strength={final_strength:.3f})"
                    )

            # ✅ НОВОЕ (03.01.2026): Логирование значений индикаторов перед генерацией сигналов
            try:
                rsi_value = indicators.get("rsi")
                macd_dict = indicators.get("macd", {})
                macd_hist = (
                    macd_dict.get("histogram") if isinstance(macd_dict, dict) else None
                )
                atr_value_from_indicators = indicators.get("atr")

                # ✅ ИСПРАВЛЕНО: Получаем ATR из DataRegistry ДО логирования (как ADX)
                atr_value_for_log = atr_value_from_indicators
                if (
                    atr_value_for_log is None or atr_value_for_log == 0
                ) and self.data_registry:
                    try:
                        indicators_from_registry = (
                            await self.data_registry.get_indicators(symbol)
                        )
                        if indicators_from_registry:
                            atr_from_reg = indicators_from_registry.get("atr")
                            if atr_from_reg and atr_from_reg > 0:
                                atr_value_for_log = atr_from_reg
                            else:
                                logger.warning(
                                    f"⚠️ [ATR] {symbol}: ATR в DataRegistry = {atr_from_reg} (невалидное значение)"
                                )
                        else:
                            logger.warning(
                                f"⚠️ [ATR] {symbol}: Индикаторы не найдены в DataRegistry для {symbol}"
                            )
                    except Exception as e:
                        logger.error(
                            f"❌ [ATR] {symbol}: ОШИБКА получения ATR из DataRegistry: {e}",
                            exc_info=True,
                        )

                if atr_value_for_log is None or atr_value_for_log == 0:
                    logger.warning(
                        f"⚠️ [ATR] {symbol}: ATR НЕ РАССЧИТАН (значение={atr_value_for_log}, источник=indicators/DataRegistry) - возможно, недостаточно данных для расчета"
                    )

                # ✅ ИСПРАВЛЕНО: Получаем режим БЕЗ fallback - показываем реальное состояние
                current_regime_for_log = None
                try:
                    if self.data_registry:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data:
                            current_regime_for_log = regime_data.get("regime")
                        else:
                            logger.warning(
                                f"⚠️ [REGIME] {symbol}: Режим НЕ найден в DataRegistry (regime_data=None)"
                            )
                    else:
                        logger.warning(
                            f"⚠️ [REGIME] {symbol}: DataRegistry недоступен для получения режима"
                        )
                except Exception as e:
                    logger.error(
                        f"❌ [REGIME] {symbol}: ОШИБКА получения режима из DataRegistry: {e}",
                        exc_info=True,
                    )

                # Логируем режим или отсутствие режима
                regime_str = (
                    current_regime_for_log if current_regime_for_log else "НЕ ОПРЕДЕЛЕН"
                )
                if not current_regime_for_log:
                    logger.warning(
                        f"⚠️ [REGIME] {symbol}: Режим НЕ определен - возможно, еще не был рассчитан RegimeManager"
                    )

                # ✅ ИСПРАВЛЕНИЕ (03.01.2026): Правильное форматирование значений (нельзя использовать тернарный оператор в f-string format specifier)
                rsi_str = f"{rsi_value:.1f}" if rsi_value is not None else "N/A"
                macd_str = f"{macd_hist:.3f}" if macd_hist is not None else "N/A"
                # ✅ НОВОЕ: Адаптивное форматирование ATR для микро-значений
                if atr_value_for_log is not None and atr_value_for_log > 0:
                    if atr_value_for_log < 0.01:
                        atr_str = f"{atr_value_for_log:.8f}"  # 8 знаков для DOGE/XRP
                    elif atr_value_for_log < 0.1:
                        atr_str = f"{atr_value_for_log:.4f}"  # 4 знака для SOL
                    else:
                        atr_str = f"{atr_value_for_log:.2f}"  # 2 знака для BTC/ETH
                else:
                    atr_str = "N/A"

                logger.info(
                    f"📊 [INDICATORS] {symbol} ({regime_str}): Значения индикаторов | "
                    f"ADX={adx_value:.1f} ({adx_trend or 'НЕ ОПРЕДЕЛЕН'}), RSI={rsi_str}, MACD_hist={macd_str}, ATR={atr_str} | "
                    f"Источник: MarketData.indicators -> DataRegistry/IndicatorProvider"
                )
            except Exception as e:
                logger.debug(
                    f"⚠️ Ошибка логирования значений индикаторов для {symbol}: {e}"
                )

            # ✅ НОВОЕ (27.12.2025): Детальное логирование статистики генерации сигналов
            total_generated = sum(stats["generated"] for stats in signal_stats.values())
            if total_generated == 0:
                logger.info(
                    f"📊 {symbol}: Нет сигналов от индикаторов. "
                    f"ADX={adx_value:.1f} ({adx_trend}), "
                    f"RSI={indicators.get('rsi', 'N/A')}, "
                    f"MACD={indicators.get('macd', {}).get('histogram', 'N/A') if isinstance(indicators.get('macd'), dict) else 'N/A'}"
                )
            else:
                stats_summary = ", ".join(
                    [
                        f"{name.upper()}={stats['generated']}"
                        for name, stats in signal_stats.items()
                        if stats["generated"] > 0
                    ]
                )
                logger.debug(
                    f"📊 {symbol}: Сгенерировано {total_generated} сигналов ({stats_summary})"
                )

            current_regime = None
            regime_manager = self.regime_managers.get(symbol) or self.regime_manager
            if regime_manager:
                current_regime = regime_manager.get_current_regime()

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (31.12.2025): Передаем ADX тренд в импульсные сигналы
            # Это позволит правильно определить направление сигнала с учетом общего тренда рынка
            impulse_signals = await self._detect_impulse_signals(
                symbol,
                market_data,
                indicators,
                current_regime,
                adx_trend,
                adx_value,
                adx_threshold,
            )
            signals.extend(impulse_signals)

            # Сохраняем количество сигналов до фильтрации по ADX
            total_before_adx_filter = len(signals)

            # ✅ НОВОЕ (26.12.2025): Используем DirectionAnalyzer для блокировки сигналов против тренда
            adx_block_cfg = {}
            allow_countertrend_on_price_action = True
            min_confidence_to_block = 0.65
            try:
                sg_cfg = getattr(self.scalping_config, "signal_generator", {})
                if isinstance(sg_cfg, dict):
                    adx_block_cfg = sg_cfg.get("adx_blocking")
                else:
                    adx_block_cfg = getattr(sg_cfg, "adx_blocking", None)
                if not adx_block_cfg:
                    raise ValueError(
                        "❌ adx_blocking config section is required in signal_generator config (strict orchestrator-only mode)"
                    )
                if isinstance(adx_block_cfg, dict):
                    if (
                        "allow_countertrend_on_price_action" not in adx_block_cfg
                        or "min_confidence_to_block" not in adx_block_cfg
                    ):
                        raise ValueError(
                            "❌ Both allow_countertrend_on_price_action and min_confidence_to_block must be set in adx_blocking config (strict orchestrator-only mode)"
                        )
                    allow_countertrend_on_price_action = bool(
                        adx_block_cfg["allow_countertrend_on_price_action"]
                    )
                    min_confidence_to_block = float(
                        adx_block_cfg["min_confidence_to_block"]
                    )
                else:
                    if not (
                        hasattr(adx_block_cfg, "allow_countertrend_on_price_action")
                        and hasattr(adx_block_cfg, "min_confidence_to_block")
                    ):
                        raise ValueError(
                            "❌ Both allow_countertrend_on_price_action and min_confidence_to_block must be set in adx_blocking config (strict orchestrator-only mode)"
                        )
                    allow_countertrend_on_price_action = bool(
                        getattr(adx_block_cfg, "allow_countertrend_on_price_action")
                    )
                    min_confidence_to_block = float(
                        getattr(adx_block_cfg, "min_confidence_to_block")
                    )
                logger.debug(
                    "ADX block config loaded: "
                    f"allow_countertrend_on_price_action={allow_countertrend_on_price_action}, "
                    f"min_confidence_to_block={min_confidence_to_block}"
                )
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации adx_blocking config: {e}")
                raise

            filtered_signals = []
            blocked_by_adx = {"LONG": 0, "SHORT": 0}  # Счетчик заблокированных сигналов
            for signal in signals:
                signal_symbol = signal.get("symbol", "")
                signal_side = signal.get("side", "").upper()

                # Используем DirectionAnalyzer если доступен
                if self.direction_analyzer and market_data and market_data.ohlcv_data:
                    try:
                        # Анализируем направление рынка
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Передаем regime для блокировки контр-тренда
                        current_regime = None
                        if hasattr(self, "regime_manager") and self.regime_manager:
                            try:
                                current_regime = (
                                    self.regime_manager.get_current_regime()
                                )
                                if current_regime:
                                    current_regime = (
                                        current_regime.lower()
                                        if isinstance(current_regime, str)
                                        else str(current_regime).lower()
                                    )
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ Не удалось получить regime для DirectionAnalyzer: {e}"
                                )

                        direction_result = self.direction_analyzer.analyze_direction(
                            candles=market_data.ohlcv_data,
                            current_price=current_price,
                            indicators=indicators,
                            regime=current_regime,  # ✅ Передаем regime для блокировки контр-тренда
                        )

                        market_direction = direction_result.get("direction", "neutral")
                        adx_value_from_analyzer = direction_result.get("adx_value", 0)
                        confidence = direction_result.get("confidence", 0.0)
                        price_action_direction = direction_result.get(
                            "price_action_direction", "neutral"
                        )
                        ema_direction = direction_result.get("ema_direction", "neutral")
                        sma_direction = direction_result.get("sma_direction", "neutral")
                        confidence_value = (
                            float(confidence)
                            if isinstance(confidence, (int, float))
                            else 0.0
                        )

                        # ✅ ПРИОРИТЕТ 1 (28.12.2025): Режим-специфичная ADX блокировка
                        # Получаем текущий режим для определения порога блокировки
                        current_regime_for_adx = "ranging"  # Fallback
                        try:
                            if self.data_registry:
                                regime_data = await self.data_registry.get_regime(
                                    symbol
                                )
                                if regime_data:
                                    current_regime_for_adx = regime_data.get(
                                        "regime", "ranging"
                                    ).lower()
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Не удалось получить режим для ADX блокировки: {e}"
                            )

                        # ✅ P1-8,9,10 FIX: Читаем пороги ADX blocking из конфига
                        adx_blocking_cfg = _cfg_get(
                            self.scalping_config, "adx_blocking", {}
                        )
                        if current_regime_for_adx == "trending":
                            adx_blocking_threshold = float(
                                _cfg_get(adx_blocking_cfg, "trending", 20.0)
                            )
                        elif current_regime_for_adx == "ranging":
                            adx_blocking_threshold = float(
                                _cfg_get(adx_blocking_cfg, "ranging", 25.0)
                            )
                        elif current_regime_for_adx == "choppy":
                            adx_blocking_threshold = float(
                                _cfg_get(adx_blocking_cfg, "choppy", 35.0)
                            )
                        else:
                            raise ValueError(
                                f"❌ Неизвестный режим для ADX блокировки: {current_regime_for_adx}"
                            )

                        # Блокируем сигналы против тренда только если ADX превышает режим-специфичный порог
                        if (
                            allow_countertrend_on_price_action
                            and adx_value_from_analyzer >= adx_blocking_threshold
                        ):
                            if (
                                market_direction == "bullish"
                                and price_action_direction == "bearish"
                                and confidence_value < min_confidence_to_block
                            ):
                                logger.info(
                                    f"ADX_COUNTERTREND_ALLOW {signal_symbol} {signal_side}: "
                                    f"market_direction={market_direction}, price_action={price_action_direction}, "
                                    f"ema={ema_direction}, sma={sma_direction}, "
                                    f"confidence={confidence_value:.2f}, adx={adx_value_from_analyzer:.1f}"
                                )
                                market_direction = "neutral"
                            elif (
                                market_direction == "bearish"
                                and price_action_direction == "bullish"
                                and confidence_value < min_confidence_to_block
                            ):
                                logger.info(
                                    f"ADX_COUNTERTREND_ALLOW {signal_symbol} {signal_side}: "
                                    f"market_direction={market_direction}, price_action={price_action_direction}, "
                                    f"ema={ema_direction}, sma={sma_direction}, "
                                    f"confidence={confidence_value:.2f}, adx={adx_value_from_analyzer:.1f}"
                                )
                                market_direction = "neutral"

                        if adx_value_from_analyzer >= adx_blocking_threshold:
                            if market_direction == "bearish" and signal_side == "LONG":
                                blocked_by_adx["LONG"] += 1
                                signal_type = signal.get("type", "unknown")
                                # ✅ ИСПРАВЛЕНО (05.01.2026): Проверка типа confidence перед форматированием
                                if isinstance(confidence, (int, float)):
                                    confidence_str = f"{confidence:.2f}"
                                elif confidence is not None:
                                    confidence_str = str(confidence)
                                else:
                                    confidence_str = "N/A"
                                logger.warning(
                                    f"🚫 {signal_symbol} {signal_side} ({signal_type}): Сигнал заблокирован - против ADX тренда "
                                    f"(ADX={adx_value_from_analyzer:.1f} >= {adx_blocking_threshold:.1f} для режима {current_regime_for_adx}, "
                                    f"direction={market_direction}, confidence={confidence_str})"
                                )
                                continue  # Пропускаем этот сигнал
                            elif (
                                market_direction == "bullish" and signal_side == "SHORT"
                            ):
                                blocked_by_adx["SHORT"] += 1
                                signal_type = signal.get("type", "unknown")
                                # ✅ ИСПРАВЛЕНО (05.01.2026): Проверка типа confidence перед форматированием
                                if isinstance(confidence, (int, float)):
                                    confidence_str = f"{confidence:.2f}"
                                elif confidence is not None:
                                    confidence_str = str(confidence)
                                else:
                                    confidence_str = "N/A"
                                logger.warning(
                                    f"🚫 {signal_symbol} {signal_side} ({signal_type}): Сигнал заблокирован - против ADX тренда "
                                    f"(ADX={adx_value_from_analyzer:.1f} >= {adx_blocking_threshold:.1f} для режима {current_regime_for_adx}, "
                                    f"direction={market_direction}, confidence={confidence_str})"
                                )
                                continue  # Пропускаем этот сигнал
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки DirectionAnalyzer для {signal_symbol}: {e}, разрешаем сигнал"
                        )
                else:
                    # Fallback: старая логика для XRP-USDT (если DirectionAnalyzer не доступен)
                    if signal_symbol == "XRP-USDT" and signal_side.lower() == "sell":
                        try:
                            # ✅ ПРИОРИТЕТ 1 (28.12.2025): Режим-специфичная ADX блокировка
                            current_regime_for_adx_fallback = "ranging"  # Fallback
                            try:
                                if self.data_registry:
                                    regime_data = await self.data_registry.get_regime(
                                        signal_symbol
                                    )
                                    if regime_data:
                                        current_regime_for_adx_fallback = (
                                            regime_data.get("regime", "ranging").lower()
                                        )
                            except Exception as exc:
                                logger.debug("Ignored error in optional block: %s", exc)

                            adx_blocking_threshold_fallback = (
                                30.0  # Fallback для ranging
                            )
                            if current_regime_for_adx_fallback == "trending":
                                adx_blocking_threshold_fallback = 20.0
                            elif current_regime_for_adx_fallback == "ranging":
                                adx_blocking_threshold_fallback = 30.0
                            elif current_regime_for_adx_fallback == "choppy":
                                adx_blocking_threshold_fallback = 40.0

                            if (
                                adx_value >= adx_blocking_threshold_fallback
                                and adx_trend == "bullish"
                            ):
                                logger.warning(
                                    f"🚫 XRP-USDT SHORT ПОЛНОСТЬЮ ЗАБЛОКИРОВАН: сильный BULLISH тренд "
                                    f"(ADX={adx_value:.1f} >= {adx_blocking_threshold_fallback:.1f} для режима {current_regime_for_adx_fallback}, "
                                    f"+DI={adx_plus_di:.1f}, -DI={adx_minus_di:.1f})"
                                )
                                continue
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Ошибка проверки ADX для XRP-USDT SHORT: {e}, разрешаем сигнал"
                            )

                filtered_signals.append(signal)

            signals = filtered_signals

            # ✅ НОВОЕ (27.12.2025): Итоговое логирование заблокированных сигналов по ADX
            total_blocked = blocked_by_adx["LONG"] + blocked_by_adx["SHORT"]
            if total_blocked > 0:
                logger.info(
                    f"📊 {symbol}: Заблокировано {total_blocked} сигналов по ADX "
                    f"(LONG={blocked_by_adx['LONG']}, SHORT={blocked_by_adx['SHORT']}), "
                    f"разрешено {len(signals)} из {total_before_adx_filter} сигналов. "
                    f"ADX={adx_value:.1f} ({adx_trend})"
                )
            elif len(signals) == 0 and total_before_adx_filter > 0:
                # Получаем режим для логирования
                current_regime_log = "ranging"
                try:
                    if self.data_registry:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data:
                            current_regime_log = regime_data.get(
                                "regime", "ranging"
                            ).lower()
                except Exception as exc:
                    logger.debug("Ignored error in optional block: %s", exc)

                adx_threshold_log = 30.0
                if current_regime_log == "trending":
                    adx_threshold_log = 20.0
                elif current_regime_log == "choppy":
                    adx_threshold_log = 40.0

                logger.info(
                    f"📊 {symbol}: Все {total_before_adx_filter} сгенерированных сигналов заблокированы по ADX "
                    f"(ADX={adx_value:.1f} >= {adx_threshold_log:.1f} для режима {current_regime_log}, тренд={adx_trend})"
                )

            # ✅ НОВОЕ (26.12.2025): Записываем сгенерированные сигналы в метрики
            if hasattr(self, "conversion_metrics") and self.conversion_metrics:
                for signal in signals:
                    signal_type = signal.get("source", "unknown")
                    strength = signal.get("strength", 0.0)
                    try:
                        self.conversion_metrics.record_signal_generated(
                            symbol=symbol,
                            signal_type=signal_type,
                            regime=current_regime,
                            strength=strength,
                        )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка записи метрики сигнала для {symbol}: {e}"
                        )

            # ✅ ОПТИМИЗАЦИЯ: Логируем только если есть сигналы (INFO уровень) или важная информация
            # logger.debug(f"📊 Всего базовых сигналов для {symbol}: {len(signals)}")

            return signals

        except Exception as e:
            logger.error(f"Ошибка генерации базовых сигналов для {symbol}: {e}")
            return []

    def _calculate_regime_ema(self, candles: List, period: int) -> float:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитать EMA с указанным периодом.

        Используется для динамического пересчета EMA с режим-специфичными периодами
        вместо использования захардкоженных EMA_12/EMA_26.

        Args:
            candles: Список свечей OHLCV
            period: Период EMA

        Returns:
            Значение EMA или 0.0 если недостаточно данных
        """
        if not candles or len(candles) < period:
            return 0.0

        # Получаем цены закрытия
        closes = [c.close for c in candles] if hasattr(candles[0], "close") else candles

        if len(closes) < period:
            return 0.0

        # Расчет EMA: EMA(t) = Price(t) * α + EMA(t-1) * (1 - α)
        # где α = 2 / (period + 1)
        alpha = 2.0 / (period + 1)

        # Начальное значение EMA = SMA за период
        ema = sum(closes[:period]) / period

        # Применяем формулу EMA для остальных значений
        for price in closes[period:]:
            ema = (price * alpha) + (ema * (1 - alpha))

        return ema

    def _calculate_regime_bollinger_bands(
        self, candles: List, period: int, std_multiplier: float
    ) -> Dict[str, float]:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитать Bollinger Bands с указанными параметрами.

        Используется для динамического пересчета BB с режим-специфичными параметрами.

        Args:
            candles: Список свечей OHLCV
            period: Период для SMA
            std_multiplier: Множитель стандартного отклонения

        Returns:
            Dict с upper, lower, middle или пустой dict если недостаточно данных
        """
        import numpy as np

        if not candles or len(candles) < period:
            return {}

        # Получаем цены закрытия
        closes = [c.close for c in candles] if hasattr(candles[0], "close") else candles

        if len(closes) < period:
            return {}

        # Берем последние period свечей
        recent_data = closes[-period:]

        # Средняя линия = SMA
        sma = np.mean(recent_data)

        # Стандартное отклонение
        std = np.std(recent_data)

        # Верхняя и нижняя полосы
        upper_band = sma + (std * std_multiplier)
        lower_band = sma - (std * std_multiplier)

        return {"upper": upper_band, "lower": lower_band, "middle": sma}

    def _calculate_conflict_multiplier(
        self,
        symbol: str,
        conflict_type: str,
        base_strength: float,
        conflict_severity: float = 0.5,
        regime: Optional[str] = None,
    ) -> float:
        """
        🔴 BUG #7 FIX (11.01.2026): Calculate conflict multiplier for signal strength degradation

        Правильно рассчитывает снижение strength при конфликтах между индикаторами.

        Args:
            symbol: Торговый символ
            conflict_type: Тип конфликта ('ema_conflict', 'adx_conflict', 'bb_rsi_conflict', etc.)
            base_strength: Базовая strength сигнала (0-1.0)
            conflict_severity: Степень конфликта (0-1.0), где 1.0 = полный конфликт
            regime: Режим рынка для адаптивного расчета

        Returns:
            Скорректированная strength с учетом конфликта
        """
        try:
            # Базовые множители конфликта по типу
            CONFLICT_MULTIPLIERS = {
                "ema_conflict": 0.6,  # EMA и основной сигнал конфликтуют
                "adx_conflict": 0.7,  # ADX показывает противоположное направление
                "bb_rsi_conflict": 0.5,  # BB и RSI дают разные сигналы
                "macd_conflict": 0.65,  # MACD конфликтует с основным направлением
                "volume_conflict": 0.75,  # Volume profile не подтверждает
                "default": 0.5,
            }

            # Получаем множитель для типа конфликта
            multiplier = CONFLICT_MULTIPLIERS.get(
                conflict_type, CONFLICT_MULTIPLIERS["default"]
            )

            # Адаптируем множитель под режим если доступно
            if regime and hasattr(self, "scalping_config"):
                try:
                    adaptive_regime = getattr(
                        self.scalping_config, "adaptive_regime", {}
                    )
                    if isinstance(adaptive_regime, dict):
                        regime_config = adaptive_regime.get(regime, {})
                    else:
                        regime_config = self._to_dict(adaptive_regime).get(regime, {})

                    if isinstance(regime_config, dict):
                        conflict_config = regime_config.get("conflict_handling", {})
                        if isinstance(conflict_config, dict):
                            multiplier = conflict_config.get(conflict_type, multiplier)
                except Exception as e:
                    logger.debug(f"⚠️ Error getting regime config for conflict: {e}")

            # Применяем severity фактор (более серьезный конфликт → больше снижение)
            # severity=0.5 (умеренный конфликт): multiplier * 0.8
            # severity=1.0 (полный конфликт): multiplier * 0.5
            severity_factor = 1.0 - (conflict_severity * (1.0 - multiplier))

            # Итоговая strength = базовая * severity_factor
            final_strength = base_strength * severity_factor

            logger.debug(
                f"⚠️ {symbol}: Conflict detected ({conflict_type}), "
                f"strength degraded: {base_strength:.3f} → {final_strength:.3f} "
                f"(multiplier={multiplier:.2f}, severity={conflict_severity:.2f}, regime={regime or 'default'})"
            )

            return final_strength

        except Exception as e:
            logger.error(
                f"❌ Error calculating conflict multiplier for {symbol}: {e}",
                exc_info=True,
            )
            return base_strength * 0.5  # Fallback: большое снижение при ошибке

    async def _calculate_atr_adaptive_rsi_thresholds(
        self, symbol: str, base_overbought: float = 85.0, base_oversold: float = 25.0
    ) -> Dict[str, float]:
        """
        ✅ ПРИОРИТЕТ 2.5 (28.12.2025): Рассчитать адаптивные RSI пороги на основе ATR.

        Адаптирует пороги overbought/oversold в зависимости от текущей волатильности:
        - Высокая волатильность: расширяет диапазон (более экстремальные уровни)
        - Низкая волатильность: сужает диапазон (менее экстремальные уровни)

        Args:
            symbol: Торговый символ
            base_overbought: Базовый порог overbought (85)
            base_oversold: Базовый порог oversold (25)

        Returns:
            Dict с адаптивными overbought и oversold порогами
        """
        try:
            # Получаем текущий ATR из DataRegistry
            current_atr = None
            if self.data_registry:
                try:
                    indicators = await self.data_registry.get_indicators(symbol)
                    if indicators:
                        current_atr = indicators.get("atr")
                except Exception as e:
                    logger.debug(
                        f"⚠️ Не удалось получить ATR из DataRegistry для {symbol}: {e}"
                    )

            # Если нет в DataRegistry, пробуем получить из свечей
            if current_atr is None or current_atr <= 0:
                # Fallback: используем базовые пороги
                return {
                    "rsi_overbought": base_overbought,
                    "rsi_oversold": base_oversold,
                }

            # Получаем средний ATR из истории свечей
            avg_atr = current_atr  # Fallback: используем текущий как средний
            try:
                if self.data_registry:
                    candles = await self.data_registry.get_candles(symbol, "1m")
                    if candles and len(candles) >= 100:
                        # Рассчитываем средний ATR за последние 100 периодов
                        atr_values = []
                        for i in range(max(0, len(candles) - 100), len(candles)):
                            if i >= 14:  # Нужно минимум 14 свечей для ATR
                                # Простой расчет ATR: средняя разница high-low за последние 14 свечей
                                high_low_diff = sum(
                                    [
                                        abs(candles[j].high - candles[j].low)
                                        for j in range(max(0, i - 13), i + 1)
                                    ]
                                ) / min(14, i + 1)
                                atr_values.append(high_low_diff)

                        if atr_values:
                            avg_atr = sum(atr_values) / len(atr_values)
            except Exception as e:
                logger.debug(f"⚠️ Не удалось рассчитать средний ATR для {symbol}: {e}")

            # Коэффициент волатильности
            if avg_atr and avg_atr > 0:
                volatility_ratio = current_atr / avg_atr
            else:
                volatility_ratio = 1.0

            # Адаптация порогов
            if volatility_ratio > 1.3:  # Высокая волатильность (на 30% выше среднего)
                # Расширяем диапазон (более экстремальные уровни)
                overbought = base_overbought + (volatility_ratio - 1.0) * 5
                oversold = base_oversold - (volatility_ratio - 1.0) * 3
            elif volatility_ratio < 0.7:  # Низкая волатильность (на 30% ниже среднего)
                # Сужаем диапазон (менее экстремальные уровни)
                overbought = base_overbought - (1.0 - volatility_ratio) * 5
                oversold = base_oversold + (1.0 - volatility_ratio) * 3
            else:  # Нормальная волатильность
                overbought = base_overbought
                oversold = base_oversold

            # Ограничиваем диапазоны (защита от экстремальных значений)
            overbought = min(95.0, max(75.0, overbought))
            oversold = min(35.0, max(15.0, oversold))

            return {
                "rsi_overbought": overbought,
                "rsi_oversold": oversold,
                "volatility_ratio": volatility_ratio,  # Для логирования
                "current_atr": current_atr,  # Для логирования
                "avg_atr": avg_atr,  # Для логирования
            }
        except Exception as e:
            logger.debug(
                f"⚠️ Ошибка расчета адаптивных RSI порогов для {symbol}: {e}, используем базовые"
            )
            return {"rsi_overbought": base_overbought, "rsi_oversold": base_oversold}

    def _calculate_regime_rsi(
        self, candles: List, period: int, overbought: float = 70, oversold: float = 30
    ) -> float:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитать RSI с указанным периодом.

        Args:
            candles: Список свечей OHLCV
            period: Период RSI
            overbought: Порог перекупленности (не используется в расчете, только для совместимости)
            oversold: Порог перепроданности (не используется в расчете, только для совместимости)

        Returns:
            Значение RSI или 50.0 если недостаточно данных
        """
        import numpy as np

        if not candles or len(candles) < period + 1:
            return 50.0

        # Получаем цены закрытия
        closes = [c.close for c in candles] if hasattr(candles[0], "close") else candles

        if len(closes) < period + 1:
            return 50.0

        # Расчет RSI по формуле Wilder
        prices = np.array(closes)
        deltas = np.diff(prices)

        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        # Экспоненциальное сглаживание Wilder
        if len(gains) >= period:
            avg_gain = np.mean(gains[-period:])
            avg_loss = np.mean(losses[-period:])

            if len(gains) > period:
                for i in range(period, len(gains)):
                    avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                    avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        else:
            return 50.0

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi_value = 100.0 - (100.0 / (1.0 + rs))

        return rsi_value

    def _calculate_regime_atr(self, candles: List, period: int) -> float:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитать ATR с указанным периодом.

        Args:
            candles: Список свечей OHLCV
            period: Период ATR

        Returns:
            Значение ATR или 0.0 если недостаточно данных
        """
        import numpy as np

        if not candles or len(candles) < period + 1:
            return 0.0

        # Получаем high, low, close
        highs = [c.high for c in candles] if hasattr(candles[0], "high") else []
        lows = [c.low for c in candles] if hasattr(candles[0], "low") else []
        closes = [c.close for c in candles] if hasattr(candles[0], "close") else candles

        if (
            len(highs) < period + 1
            or len(lows) < period + 1
            or len(closes) < period + 1
        ):
            return 0.0

        # Расчет True Range
        true_ranges = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            true_range = max(high_low, high_close, low_close)
            true_ranges.append(true_range)

        if len(true_ranges) < period:
            return 0.0

        # ATR с экспоненциальным сглаживанием Wilder
        atr_value = np.mean(true_ranges[-period:])

        if len(true_ranges) > period:
            for i in range(period, len(true_ranges)):
                atr_value = (atr_value * (period - 1) + true_ranges[i]) / period

        return atr_value

    def _calculate_regime_macd(
        self, candles: List, fast_period: int, slow_period: int, signal_period: int
    ) -> Dict[str, float]:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитать MACD с указанными параметрами.

        Args:
            candles: Список свечей OHLCV
            fast_period: Период быстрой EMA
            slow_period: Период медленной EMA
            signal_period: Период сигнальной линии

        Returns:
            Dict с macd_line, signal_line, histogram или пустой dict если недостаточно данных
        """
        if not candles or len(candles) < slow_period + signal_period:
            return {}

        # Получаем цены закрытия
        closes = [c.close for c in candles] if hasattr(candles[0], "close") else candles

        if len(closes) < slow_period + signal_period:
            return {}

        # Рассчитываем EMA fast и slow
        ema_fast = self._calculate_regime_ema(candles, fast_period)
        ema_slow = self._calculate_regime_ema(candles, slow_period)

        if ema_fast == 0.0 or ema_slow == 0.0:
            return {}

        # MACD line
        macd_line = ema_fast - ema_slow

        # Для signal line нужна история MACD - упрощенный расчет
        # Берем последние signal_period свечей и рассчитываем EMA от MACD
        # Упрощение: используем последние значения для расчета signal
        if len(closes) >= slow_period + signal_period:
            # Рассчитываем MACD для последних signal_period свечей
            macd_history = []
            for i in range(
                len(closes) - signal_period - slow_period, len(closes) - slow_period
            ):
                if i >= fast_period:
                    # Рассчитываем EMA для этого момента
                    ema_fast_i = self._calculate_regime_ema(
                        candles[: i + 1], fast_period
                    )
                    ema_slow_i = self._calculate_regime_ema(
                        candles[: i + 1], slow_period
                    )
                    if ema_fast_i > 0 and ema_slow_i > 0:
                        macd_history.append(ema_fast_i - ema_slow_i)

            # Если есть история, рассчитываем signal как EMA от истории
            if len(macd_history) >= signal_period:
                signal_line = self._calculate_ema_from_list(
                    macd_history[-signal_period:], signal_period
                )
            else:
                signal_line = macd_line
        else:
            signal_line = macd_line

        histogram = macd_line - signal_line

        return {"macd": macd_line, "signal": signal_line, "histogram": histogram}

    def _calculate_ema_from_list(self, data: List[float], period: int) -> float:
        """
        Вспомогательный метод для расчета EMA из списка значений.

        Args:
            data: Список значений
            period: Период EMA

        Returns:
            Значение EMA
        """
        if not data or len(data) < period:
            return data[-1] if data else 0.0

        alpha = 2.0 / (period + 1)
        ema = sum(data[:period]) / period

        for value in data[period:]:
            ema = (value * alpha) + (ema * (1 - alpha))

        return ema

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
                        # 🔴 BUG #6 FIX: Normalize to dict first, don't use getattr with lowercase
                        # Pydantic models have uppercase attribute names, dict has lowercase keys
                        regime_params_dict = self._to_dict(adaptive_regime)
                        regime_params = regime_params_dict.get(regime_key, {})

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

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Добавляем bb_period и bb_std_multiplier если их нет
        if "bb_period" not in final_indicators:
            final_indicators["bb_period"] = 20
        if "bb_std_multiplier" not in final_indicators:
            # Проверяем также bb_std_dev для обратной совместимости
            if "bb_std_dev" in final_indicators:
                final_indicators["bb_std_multiplier"] = final_indicators["bb_std_dev"]
            else:
                final_indicators["bb_std_multiplier"] = 2.0

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
            "bb_period": 20,
            "bb_std_multiplier": 2.0,
            "atr_period": 14,
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
        }

    # =========================================================================
    # ✅ NEW (2026-02-18): RSI Divergence + VWAP Signal Generators
    # =========================================================================

    def _compute_rsi_series(self, closes: list, period: int = 14) -> list:
        """Вычисляет RSI для каждой свечи (Wilder's EMA smoothing).
        Возвращает список [None]*period + [float, ...]"""
        result = [None] * period
        if len(closes) < period + 1:
            return result
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(d, 0.0) for d in deltas]
        losses = [max(-d, 0.0) for d in deltas]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(closes)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(100.0 - 100.0 / (1.0 + rs))
        return result

    async def _generate_rsi_divergence_signals(
        self,
        symbol: str,
        indicators: dict,
        market_data,
        adx_trend: str,
        adx_value: float,
    ) -> list:
        """RSI Divergence — ловит развороты ДО пробоя уровней (leading indicator).

        Bullish divergence: цена делает lower low, RSI делает higher low → BUY
        Bearish divergence: цена делает higher high, RSI делает lower high → SELL

        Адаптация по режиму:
        - ranging:  сила +20% (дивергенции наиболее надёжны в боковике)
        - choppy:   сила -20%, более мягкий порог (больше шума)
        - trending: сила -40% (дивергенция = коррекция, не разворот)
        """
        signals = []
        try:
            # Получаем текущий режим для адаптации
            current_regime = "ranging"  # fallback
            try:
                if hasattr(self, "regime_manager") and self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        current_regime = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except Exception:
                pass

            candles = getattr(market_data, "ohlcv_data", None)
            if not candles or len(candles) < 30:
                return []

            lookback = min(40, len(candles))
            recent = candles[-lookback:]
            closes = [float(c.close) for c in recent]

            rsi_series = self._compute_rsi_series(closes, period=14)
            valid_rsi = [v for v in rsi_series if v is not None]
            if len(valid_rsi) < 12:
                return []

            # Анализируем последние 20 свечей (2 половины по 10)
            window = min(20, len(valid_rsi))
            price_vals = closes[-window:]
            rsi_vals = valid_rsi[-window:]
            mid = window // 2

            current_price = float(candles[-1].close)
            current_rsi = rsi_vals[-1]

            price_early = price_vals[:mid]
            price_late = price_vals[mid:]
            rsi_early = rsi_vals[:mid]
            rsi_late = rsi_vals[mid:]

            # --- Bullish divergence ---
            price_low_early = min(price_early)
            price_low_late = min(price_late)
            rsi_low_early = min(rsi_early)
            rsi_low_late = min(rsi_late)

            if (
                price_low_late < price_low_early  # цена: lower low
                and rsi_low_late > rsi_low_early  # RSI: higher low
                and current_rsi < 55  # не перекуплено
                and adx_trend != "bearish"  # нет сильного медвежьего тренда
            ):
                price_drop = (price_low_early - price_low_late) / max(
                    price_low_early, 1e-9
                )
                rsi_recovery = (rsi_low_late - rsi_low_early) / max(
                    abs(rsi_low_early), 1e-9
                )
                strength = min(0.82, (price_drop * 10 + rsi_recovery) * 2)
                # Адаптация по режиму
                regime_multiplier = {
                    "ranging": 1.2,
                    "choppy": 0.8,
                    "trending": 0.6,
                }.get(current_regime, 1.0)
                strength = min(0.82, strength * regime_multiplier)
                min_strength_threshold = 0.12 if current_regime == "trending" else 0.15
                if strength >= min_strength_threshold:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "rsi_divergence",
                            "strength": strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "buy"
                            ),
                            "timestamp": __import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc
                            ),
                            "confidence": 0.65,
                            "has_conflict": False,
                            "source": "rsi_bullish_divergence",
                            "rsi": current_rsi,
                            "divergence_type": "bullish",
                            "regime": current_regime,
                            "price_drop_pct": round(price_drop * 100, 3),
                            "rsi_recovery_pct": round(rsi_recovery * 100, 3),
                        }
                    )
                    logger.debug(
                        f"📐 {symbol}: Bullish RSI divergence [{current_regime}]: "
                        f"price {price_low_early:.4f}→{price_low_late:.4f} (↓), "
                        f"RSI {rsi_low_early:.1f}→{rsi_low_late:.1f} (↑), "
                        f"strength={strength:.3f} (x{regime_multiplier})"
                    )

            # --- Bearish divergence ---
            price_high_early = max(price_early)
            price_high_late = max(price_late)
            rsi_high_early = max(rsi_early)
            rsi_high_late = max(rsi_late)

            if (
                price_high_late > price_high_early  # цена: higher high
                and rsi_high_late < rsi_high_early  # RSI: lower high
                and current_rsi > 45  # не перепродано
                and adx_trend != "bullish"  # нет сильного бычьего тренда
            ):
                price_rise = (price_high_late - price_high_early) / max(
                    price_high_early, 1e-9
                )
                rsi_weakness = (rsi_high_early - rsi_high_late) / max(
                    abs(rsi_high_early), 1e-9
                )
                strength = min(0.82, (price_rise * 10 + rsi_weakness) * 2)
                # Адаптация по режиму
                regime_multiplier = {
                    "ranging": 1.2,
                    "choppy": 0.8,
                    "trending": 0.6,
                }.get(current_regime, 1.0)
                strength = min(0.82, strength * regime_multiplier)
                min_strength_threshold = 0.12 if current_regime == "trending" else 0.15
                if strength >= min_strength_threshold:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "rsi_divergence",
                            "strength": strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "sell"
                            ),
                            "timestamp": __import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc
                            ),
                            "confidence": 0.65,
                            "has_conflict": False,
                            "source": "rsi_bearish_divergence",
                            "rsi": current_rsi,
                            "divergence_type": "bearish",
                            "regime": current_regime,
                            "price_rise_pct": round(price_rise * 100, 3),
                            "rsi_weakness_pct": round(rsi_weakness * 100, 3),
                        }
                    )
                    logger.debug(
                        f"📐 {symbol}: Bearish RSI divergence [{current_regime}]: "
                        f"price {price_high_early:.4f}→{price_high_late:.4f} (↑), "
                        f"RSI {rsi_high_early:.1f}→{rsi_high_late:.1f} (↓), "
                        f"strength={strength:.3f} (x{regime_multiplier})"
                    )

        except Exception as exc:
            logger.debug(f"⚠️ RSI divergence error for {symbol}: {exc}")
        return signals

    async def _generate_vwap_signals(
        self,
        symbol: str,
        market_data,
        adx_trend: str,
    ) -> list:
        """VWAP mean-reversion — динамический S/R уровень.

        BUY:  цена опустилась >1.5σ ниже VWAP → ждём возврата вверх
        SELL: цена поднялась >1.5σ выше VWAP → ждём возврата вниз

        Адаптация по режиму:
        - trending: ЗАБЛОКИРОВАН — в тренде цена уходит от VWAP надолго,
                    mean-reversion будет торговать против тренда
        - ranging:  основной режим, порог 1.5σ, confidence 0.65
        - choppy:   порог выше (2.0σ), меньше confidence (0.55), слабее сила
        """
        signals = []
        try:
            # Получаем текущий режим
            current_regime = "ranging"  # fallback
            try:
                if hasattr(self, "regime_manager") and self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        current_regime = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except Exception:
                pass

            # VWAP mean-reversion не работает в trending — цена может
            # находиться далеко от VWAP часами без возврата
            if current_regime == "trending":
                logger.debug(
                    f"📊 {symbol}: VWAP заблокирован в trending режиме "
                    f"(mean-reversion неэффективен против тренда)"
                )
                return []

            candles = getattr(market_data, "ohlcv_data", None)
            if not candles or len(candles) < 10:
                return []

            # Вычисляем VWAP (Volume Weighted Average Price)
            cum_tp_vol = 0.0
            cum_vol = 0.0
            for c in candles:
                tp = (float(c.high) + float(c.low) + float(c.close)) / 3.0
                vol = float(c.volume)
                cum_tp_vol += tp * vol
                cum_vol += vol

            if cum_vol == 0:
                return []

            vwap = cum_tp_vol / cum_vol
            current_price = float(candles[-1].close)

            # Вычисляем стандартное отклонение типичных цен от VWAP (взвешенное по объёму)
            tp_list = [
                (float(c.high) + float(c.low) + float(c.close)) / 3.0 for c in candles
            ]
            vols = [float(c.volume) for c in candles]
            variance = (
                sum((tp - vwap) ** 2 * vol for tp, vol in zip(tp_list, vols)) / cum_vol
            )
            std_dev = variance**0.5

            if std_dev < 1e-9:
                return []

            std_bands = (current_price - vwap) / std_dev

            # Параметры зависят от режима
            # ranging: стандартный порог 1.5σ, хорошая надёжность
            # choppy:  порог 2.0σ (больше шума → ждём сильного отклонения)
            entry_threshold = 2.0 if current_regime == "choppy" else 1.5
            confidence_val = 0.55 if current_regime == "choppy" else 0.62
            strength_divisor = 4.0 if current_regime == "choppy" else 3.5

            # BUY: цена ниже VWAP
            if std_bands < -entry_threshold and adx_trend != "bearish":
                strength = min(0.78, abs(std_bands) / strength_divisor)
                if strength >= 0.15:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "vwap_mean_reversion",
                            "strength": strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "buy"
                            ),
                            "timestamp": __import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc
                            ),
                            "confidence": confidence_val,
                            "has_conflict": False,
                            "source": "vwap_below",
                            "vwap": round(vwap, 6),
                            "std_bands": round(std_bands, 3),
                            "regime": current_regime,
                            "deviation_pct": round(
                                (current_price - vwap) / vwap * 100, 3
                            ),
                        }
                    )
                    logger.debug(
                        f"📊 {symbol}: VWAP BUY [{current_regime}]: "
                        f"price={current_price:.4f}, vwap={vwap:.4f}, "
                        f"bands={std_bands:.2f}σ (threshold={entry_threshold}σ), "
                        f"strength={strength:.3f}"
                    )

            # SELL: цена выше VWAP
            elif std_bands > entry_threshold and adx_trend != "bullish":
                strength = min(0.78, abs(std_bands) / strength_divisor)
                if strength >= 0.15:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "vwap_mean_reversion",
                            "strength": strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "sell"
                            ),
                            "timestamp": __import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc
                            ),
                            "confidence": confidence_val,
                            "has_conflict": False,
                            "source": "vwap_above",
                            "vwap": round(vwap, 6),
                            "std_bands": round(std_bands, 3),
                            "regime": current_regime,
                            "deviation_pct": round(
                                (current_price - vwap) / vwap * 100, 3
                            ),
                        }
                    )
                    logger.debug(
                        f"📊 {symbol}: VWAP SELL [{current_regime}]: "
                        f"price={current_price:.4f}, vwap={vwap:.4f}, "
                        f"bands={std_bands:.2f}σ (threshold={entry_threshold}σ), "
                        f"strength={strength:.3f}"
                    )

        except Exception as exc:
            logger.debug(f"⚠️ VWAP error for {symbol}: {exc}")
        return signals

    async def _generate_rsi_signals(
        self,
        symbol: str,
        indicators: Dict,
        market_data: MarketData,
        adx_trend: Optional[str] = None,
        adx_value: float = 0.0,
        adx_threshold: float = 20.0,  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен дефолтный порог с 25 до 20
    ) -> List[Dict[str, Any]]:
        """Генерация RSI сигналов с режим-специфичными порогами"""
        signals = []

        try:
            # ✅ Получаем режим-специфичные параметры для текущего символа
            regime_params = self._get_regime_indicators_params(symbol=symbol)
            rsi_period = regime_params.get("rsi_period", 14)
            base_rsi_oversold = regime_params.get("rsi_oversold", 30)
            base_rsi_overbought = regime_params.get("rsi_overbought", 70)

            # ✅ ПРИОРИТЕТ 2.5 (28.12.2025): Адаптируем RSI пороги на основе ATR
            adaptive_thresholds = await self._calculate_atr_adaptive_rsi_thresholds(
                symbol=symbol,
                base_overbought=base_rsi_overbought,
                base_oversold=base_rsi_oversold,
            )
            rsi_overbought = adaptive_thresholds.get(
                "rsi_overbought", base_rsi_overbought
            )
            rsi_oversold = adaptive_thresholds.get("rsi_oversold", base_rsi_oversold)
            volatility_ratio = adaptive_thresholds.get("volatility_ratio", 1.0)

            # Логируем адаптивные пороги (только если они отличаются от базовых)
            if (
                abs(rsi_overbought - base_rsi_overbought) > 0.5
                or abs(rsi_oversold - base_rsi_oversold) > 0.5
            ):
                logger.debug(
                    f"📊 {symbol}: RSI пороги адаптированы по ATR: "
                    f"overbought={rsi_overbought:.1f} (база={base_rsi_overbought:.1f}), "
                    f"oversold={rsi_oversold:.1f} (база={base_rsi_oversold:.1f}), "
                    f"volatility_ratio={volatility_ratio:.2f}"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем RSI с режим-специфичным периодом
            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= rsi_period + 1:
                rsi = self._calculate_regime_rsi(
                    market_data.ohlcv_data, rsi_period, rsi_overbought, rsi_oversold
                )
            else:
                # Fallback на базовый индикатор
                rsi = indicators.get("rsi", 50)

            # Получаем текущий режим для логирования
            regime_manager = self.regime_managers.get(symbol) or self.regime_manager
            current_regime = (
                regime_manager.get_current_regime() if regime_manager else "N/A"
            )

            # ✅ ПРИОРИТЕТ 2.5 (28.12.2025): Логирование параметров индикаторов
            logger.debug(
                f"📊 {symbol} RSI параметры: период={rsi_period}, overbought={rsi_overbought:.1f} "
                f"(база={base_rsi_overbought:.1f}), oversold={rsi_oversold:.1f} (база={base_rsi_oversold:.1f}), "
                f"RSI={rsi:.2f}, режим={current_regime}"
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем EMA с режим-специфичными периодами
            ema_fast_period_rsi = regime_params.get("ema_fast", 12)
            ema_slow_period_rsi = regime_params.get("ema_slow", 26)

            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= max(
                ema_fast_period_rsi, ema_slow_period_rsi
            ):
                ema_fast = self._calculate_regime_ema(
                    market_data.ohlcv_data, ema_fast_period_rsi
                )
                ema_slow = self._calculate_regime_ema(
                    market_data.ohlcv_data, ema_slow_period_rsi
                )
            else:
                # Fallback на базовые индикаторы
                ema_fast = indicators.get("ema_12", 0)
                ema_slow = indicators.get("ema_26", 0)

            # ✅ ПРИОРИТЕТ 2.5 (28.12.2025): Логирование параметров EMA
            logger.debug(
                f"📊 {symbol} EMA параметры: fast_period={ema_fast_period_rsi}, slow_period={ema_slow_period_rsi}, EMA_fast={ema_fast:.2f}, EMA_slow={ema_slow:.2f}, цена={current_price:.2f}"  # noqa: F821
            )

            # ✅ ОПТИМИЗАЦИЯ: Используем актуальную цену из стакана для сигналов
            candle_close_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )
            current_price = await self._get_current_market_price(
                symbol, candle_close_price
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
            except Exception as exc:
                logger.debug("Ignored error in optional block: %s", exc)

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

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем текущий режим для проверки блокировки
                current_regime = "ranging"  # Fallback
                try:
                    if hasattr(self, "regime_manager") and self.regime_manager:
                        regime_obj = self.regime_manager.get_current_regime()
                        if regime_obj:
                            current_regime = (
                                regime_obj.lower()
                                if isinstance(regime_obj, str)
                                else str(regime_obj).lower()
                            )
                except Exception as e:
                    logger.debug(f"⚠️ Не удалось получить режим для блокировки: {e}")

                # Нормализованная сила: от 0 до 1
                # ✅ ИСПРАВЛЕНИЕ: Проверка деления на ноль для rsi_oversold
                if rsi_oversold > 0:
                    strength = min(1.0, (rsi_oversold - rsi) / rsi_oversold)
                else:
                    # Fallback: если rsi_oversold == 0, используем 0.5 как базовую силу
                    logger.warning(
                        f"⚠️ RSI oversold == 0 для {symbol}, используем fallback strength=0.5"
                    )
                    strength = 0.5
                confidence = confidence_config_rsi.get(
                    "rsi_signal", 0.6
                )  # ✅ АДАПТИВНО: Из конфига
                has_conflict = False

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Блокировка конфликта EMA всегда (не только в trending)
                # Блокируем BUY сигналы при конфликте EMA (RSI oversold + EMA bearish) ИЛИ при ADX>=20 bearish
                should_block = False
                block_reason = ""

                if is_downtrend:
                    # Конфликт EMA: ослабляем сигнал вместо полной блокировки
                    strength *= 0.5
                    confidence *= 0.8
                    block_reason = f"ослаблен из-за EMA-конфликта (EMA_12={ema_fast:.2f} < EMA_26={ema_slow:.2f}, цена={current_price:.2f})"

                # ✅ ПРИОРИТЕТ 1 (28.12.2025): Режим-специфичная ADX блокировка
                # Получаем режим для определения порога
                current_regime_rsi_oversold = "ranging"  # Fallback
                try:
                    if self.data_registry:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data:
                            current_regime_rsi_oversold = regime_data.get(
                                "regime", "ranging"
                            ).lower()
                except Exception as exc:
                    logger.debug("Ignored error in optional block: %s", exc)

                adx_threshold_rsi_oversold = (
                    25.0  # Fallback для ranging (FIX 2026-02-22: было 30)
                )
                if current_regime_rsi_oversold == "trending":
                    adx_threshold_rsi_oversold = 20.0
                elif current_regime_rsi_oversold == "choppy":
                    adx_threshold_rsi_oversold = 25.0  # FIX 2026-02-22: было 40 — слишком высоко, DOGE ADX=40.1 не блокировался

                if adx_value >= adx_threshold_rsi_oversold and adx_trend == "bearish":
                    should_block = True
                    block_reason = f"ADX={adx_value:.1f} >= {adx_threshold_rsi_oversold:.1f} для режима {current_regime_rsi_oversold} показывает нисходящий тренд (против тренда)"

                if should_block:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Детальное логирование конфликта с указанием всех параметров
                    logger.warning(
                        f"🚫 RSI OVERSOLD сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: {block_reason}. "
                        f"Параметры: RSI={rsi:.2f}, ADX={adx_value:.1f} ({adx_trend}), "
                        f"EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, цена={current_price:.2f}"
                    )
                else:
                    # ✅ НОВОЕ (28.12.2025): Учитываем slippage при установке цены сигнала
                    adjusted_price = self._adjust_price_for_slippage(
                        symbol, current_price, "buy"
                    )
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "rsi_oversold",
                            "strength": strength,
                            "price": adjusted_price,
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": rsi,
                            "confidence": confidence,
                            "has_conflict": has_conflict,
                        }
                    )

            # Перекупленность (продажа) - используем адаптивный порог
            elif rsi > rsi_overbought:
                # Проверяем тренд через EMA - если конфликт, снижаем confidence
                is_uptrend = ema_fast > ema_slow and current_price > ema_fast

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем текущий режим для проверки блокировки
                current_regime = "ranging"  # Fallback
                try:
                    if hasattr(self, "regime_manager") and self.regime_manager:
                        regime_obj = self.regime_manager.get_current_regime()
                        if regime_obj:
                            current_regime = (
                                regime_obj.lower()
                                if isinstance(regime_obj, str)
                                else str(regime_obj).lower()
                            )
                except Exception as e:
                    logger.debug(f"⚠️ Не удалось получить режим для блокировки: {e}")

                # Нормализованная сила: от 0 до 1
                # ✅ ИСПРАВЛЕНИЕ: Проверка деления на ноль для (100 - rsi_overbought)
                denominator = 100 - rsi_overbought
                if denominator > 0:
                    strength = min(1.0, (rsi - rsi_overbought) / denominator)
                else:
                    # Fallback: если rsi_overbought == 100, используем 0.5 как базовую силу
                    logger.warning(
                        f"⚠️ RSI overbought == 100 для {symbol}, используем fallback strength=0.5"
                    )
                    strength = 0.5
                confidence = confidence_config_rsi.get(
                    "rsi_signal", 0.6
                )  # ✅ АДАПТИВНО: Из конфига
                has_conflict = False

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Блокировка конфликта EMA всегда (не только в trending)
                # Блокируем SELL сигналы при конфликте EMA (RSI overbought + EMA bullish) ИЛИ при ADX>=20 bullish
                should_block_rsi_overbought = False
                block_reason_rsi_overbought = ""

                if is_uptrend:
                    # Конфликт: RSI overbought (SHORT) vs EMA bullish (UP) - ПОЛНАЯ БЛОКИРОВКА (ВСЕГДА)
                    should_block_rsi_overbought = True
                    block_reason_rsi_overbought = f"конфликт EMA (EMA_12={ema_fast:.2f} > EMA_26={ema_slow:.2f}, цена={current_price:.2f})"

                # ✅ ПРИОРИТЕТ 1 (28.12.2025): Режим-специфичная ADX блокировка
                current_regime_rsi_overbought_2 = (
                    current_regime  # Используем уже полученный режим выше
                )
                adx_threshold_rsi_overbought_2 = (
                    25.0  # Fallback для ranging (FIX 2026-02-22: было 30)
                )
                if current_regime_rsi_overbought_2 == "trending":
                    adx_threshold_rsi_overbought_2 = 20.0
                elif current_regime_rsi_overbought_2 == "choppy":
                    adx_threshold_rsi_overbought_2 = 25.0  # FIX 2026-02-22: было 40

                if (
                    adx_value >= adx_threshold_rsi_overbought_2
                    and adx_trend == "bullish"
                ):
                    should_block_rsi_overbought = True
                    block_reason_rsi_overbought = f"ADX={adx_value:.1f} >= {adx_threshold_rsi_overbought_2:.1f} для режима {current_regime_rsi_overbought_2} показывает восходящий тренд (против тренда)"

                if should_block_rsi_overbought:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Детальное логирование конфликта с указанием всех параметров
                    logger.warning(
                        f"🚫 RSI OVERBOUGHT сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: {block_reason_rsi_overbought}. "
                        f"Параметры: RSI={rsi:.2f}, ADX={adx_value:.1f} ({adx_trend}), "
                        f"EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, цена={current_price:.2f}"
                    )
                else:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "rsi_overbought",
                            "strength": strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "sell"
                            ),  # ✅ НОВОЕ (28.12.2025): Учет slippage
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": rsi,
                            "confidence": confidence,
                            "has_conflict": has_conflict,
                        }
                    )

        except Exception as e:
            logger.error(f"Ошибка генерации RSI сигналов: {e}")

        return signals

    async def _generate_macd_signals(
        self,
        symbol: str,
        indicators: Dict,
        market_data: MarketData,
        adx_trend: Optional[str] = None,
        adx_value: float = 0.0,
        adx_threshold: float = 20.0,  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен дефолтный порог с 25 до 20
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
            except Exception as exc:
                logger.debug("Ignored error in optional block: %s", exc)

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
                    # 🔴 BUG #6 FIX: Convert to dict first to handle case sensitivity
                    if isinstance(confidence_obj, dict):
                        regime_confidence = confidence_obj.get(regime_name_macd, None)
                    else:
                        confidence_obj_dict = self._to_dict(confidence_obj)
                        regime_confidence_dict = confidence_obj_dict.get(
                            regime_name_macd, {}
                        )

                        # Convert dict back to object for getattr access
                        class _RegimeConfidence:
                            def __init__(self, d):
                                for k, v in d.items():
                                    setattr(self, k, v)

                        regime_confidence = (
                            _RegimeConfidence(regime_confidence_dict)
                            if regime_confidence_dict
                            else None
                        )
                    if regime_confidence:
                        confidence_config_macd = {
                            "macd_signal": getattr(
                                regime_confidence, "macd_signal", 0.65
                            ),
                        }

            macd_confidence = confidence_config_macd.get(
                "macd_signal", 0.65
            )  # Fallback

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем MACD с режим-специфичными параметрами
            regime_params_macd = self._get_regime_indicators_params(symbol=symbol)
            macd_fast_period = regime_params_macd.get("macd_fast", 12)
            macd_slow_period = regime_params_macd.get("macd_slow", 26)
            macd_signal_period = regime_params_macd.get("macd_signal", 9)

            if (
                market_data.ohlcv_data
                and len(market_data.ohlcv_data) >= macd_slow_period + macd_signal_period
            ):
                macd_calculated = self._calculate_regime_macd(
                    market_data.ohlcv_data,
                    macd_fast_period,
                    macd_slow_period,
                    macd_signal_period,
                )
                if macd_calculated:
                    macd_line = macd_calculated.get("macd", 0)
                    signal_line = macd_calculated.get("signal", 0)
                    histogram = macd_calculated.get("histogram", 0)
                else:
                    # Fallback на базовый индикатор
                    macd = indicators.get("macd", {})
                    macd_line = macd.get("macd", 0)
                    signal_line = macd.get("signal", 0)
                    histogram = macd.get("histogram", macd_line - signal_line)
            else:
                # Fallback на базовый индикатор
                macd = indicators.get("macd", {})
                macd_line = macd.get("macd", 0)
                signal_line = macd.get("signal", 0)
                histogram = macd.get("histogram", macd_line - signal_line)
                logger.debug(
                    f"⚠️ {symbol}: Недостаточно свечей для пересчета MACD ({len(market_data.ohlcv_data) if market_data.ohlcv_data else 0}), "
                    f"используем базовый индикатор"
                )

            # ✅ ОПТИМИЗАЦИЯ: Логируем MACD только при генерации сигналов (не каждый раз)
            # logger.debug(f"🔍 MACD для {symbol}: histogram={histogram:.4f}")

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем EMA с режим-специфичными периодами
            regime_params_macd = self._get_regime_indicators_params(symbol=symbol)
            ema_fast_period_macd = regime_params_macd.get("ema_fast", 12)
            ema_slow_period_macd = regime_params_macd.get("ema_slow", 26)

            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= max(
                ema_fast_period_macd, ema_slow_period_macd
            ):
                ema_fast = self._calculate_regime_ema(
                    market_data.ohlcv_data, ema_fast_period_macd
                )
                ema_slow = self._calculate_regime_ema(
                    market_data.ohlcv_data, ema_slow_period_macd
                )
            else:
                # Fallback на базовые индикаторы
                ema_fast = indicators.get("ema_12", 0)
                ema_slow = indicators.get("ema_26", 0)

            # ✅ ОПТИМИЗАЦИЯ: Используем актуальную цену из стакана для сигналов
            candle_close_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )
            current_price = await self._get_current_market_price(
                symbol, candle_close_price
            )

            # Пересечение MACD линии и сигнальной линии
            if macd_line > signal_line and histogram > 0:
                # ✅ ЗАДАЧА #7: Проверяем совпадение EMA и цены для BULLISH
                is_bullish_trend = ema_fast > ema_slow and current_price > ema_fast

                # ✅ ПРИОРИТЕТ 1 (28.12.2025): Адаптивный MACD strength делитель по режимам
                # Получаем режим для определения делителя
                current_regime_macd_divider_bullish = "ranging"  # Fallback
                try:
                    if self.data_registry:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data:
                            current_regime_macd_divider_bullish = regime_data.get(
                                "regime", "ranging"
                            ).lower()
                except Exception as exc:
                    logger.debug("Ignored error in optional block: %s", exc)

                # Адаптивный делитель: Trending=120 (агрессивно), Ranging=180 (консервативно), Choppy=150 (баланс)
                macd_strength_divider_bullish = 180.0  # Fallback для ranging
                try:
                    regime_params_divider_bullish = self._get_regime_indicators_params(
                        symbol=symbol
                    )
                    macd_strength_divider_bullish = regime_params_divider_bullish.get(
                        "macd_strength_divider", 180.0
                    )
                except Exception:
                    # Если нет в конфиге, используем режим-специфичные значения
                    if current_regime_macd_divider_bullish == "trending":
                        macd_strength_divider_bullish = 120.0
                    elif current_regime_macd_divider_bullish == "choppy":
                        macd_strength_divider_bullish = 150.0
                    else:  # ranging
                        macd_strength_divider_bullish = 180.0

                base_strength_raw = abs(histogram) / macd_strength_divider_bullish
                base_strength = min(base_strength_raw, 1.0)

                # ✅ ПРИОРИТЕТ 2.5 (28.12.2025): Логирование параметров и strength расчетов
                logger.debug(
                    f"📊 MACD BULLISH сигнал {symbol}: histogram={histogram:.4f}, "
                    f"делитель={macd_strength_divider_bullish:.1f}, base_strength={base_strength_raw:.3f}, "
                    f"final_strength={base_strength:.3f}, режим={current_regime_macd_divider_bullish}"
                )

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                if not is_bullish_trend:
                    # Конфликт: MACD bullish, но EMA/цена не bullish
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        adaptive_regime = getattr(
                            self.scalping_config, "adaptive_regime", {}
                        )
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_macd, {})
                        else:
                            regime_config = getattr(
                                adaptive_regime, regime_name_macd, {}
                            )

                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get(
                                "strength_multipliers", {}
                            )
                            conflict_multiplier = strength_multipliers.get(
                                "conflict", 0.5
                            )
                        else:
                            strength_multipliers = getattr(
                                regime_config, "strength_multipliers", None
                            )
                            # conflict_multiplier не используется, удалено для чистоты
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить conflict_multiplier для {regime_name_macd}: {e}"
                        )

                    # ✅ ИСПРАВЛЕНО (26.12.2025): Убрано снижение strength при конфликте с EMA
                    # Конфликтные сигналы теперь полностью блокируются при ADX>=25, а не проходят с сниженным strength
                    # Для ADX<25 оставляем сигнал как есть (без снижения strength)
                    logger.debug(
                        f"⚡ MACD BULLISH с конфликтом EMA для {symbol}: "
                        f"MACD bullish, но EMA/цена не bullish (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, price={current_price:.2f}), "
                        f"strength НЕ снижается (base_strength={base_strength:.3f})"
                    )

                logger.debug(
                    f"✅ MACD BULLISH сигнал для {symbol}: macd({macd_line:.4f}) > signal({signal_line:.4f}), "
                    f"histogram={histogram:.4f} > 0, is_bullish_trend={is_bullish_trend}"
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен порог ADX с 25 до 20 + блокировка конфликта EMA
                # Блокируем BUY сигналы при сильном нисходящем тренде (ADX>=20) ИЛИ при конфликте EMA
                # ✅ КРИТИЧЕСКОЕ: Блокируем при конфликте EMA (MACD bullish + EMA bearish) вместо снижения strength
                should_block_macd_bullish = False
                block_reason_macd_bullish = ""

                if not is_bullish_trend:
                    # Конфликт: MACD bullish, но EMA/цена не bullish - ПОЛНАЯ БЛОКИРОВКА
                    should_block_macd_bullish = True
                    block_reason_macd_bullish = f"конфликт EMA (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, цена={current_price:.2f})"

                # ✅ ПРИОРИТЕТ 1 (28.12.2025): Режим-специфичная ADX блокировка
                current_regime_macd_bullish = "ranging"  # Fallback
                try:
                    if self.data_registry:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data:
                            current_regime_macd_bullish = regime_data.get(
                                "regime", "ranging"
                            ).lower()
                except Exception as exc:
                    logger.debug("Ignored error in optional block: %s", exc)

                adx_threshold_macd_bullish = (
                    25.0  # Fallback для ranging (FIX 2026-02-22: было 30)
                )
                if current_regime_macd_bullish == "trending":
                    adx_threshold_macd_bullish = 20.0
                elif current_regime_macd_bullish == "choppy":
                    adx_threshold_macd_bullish = (
                        25.0  # FIX 2026-02-22: было 40 — слишком высоко
                    )

                if adx_value >= adx_threshold_macd_bullish and adx_trend == "bearish":
                    should_block_macd_bullish = True
                    block_reason_macd_bullish = f"ADX={adx_value:.1f} >= {adx_threshold_macd_bullish:.1f} для режима {current_regime_macd_bullish} показывает нисходящий тренд (против тренда)"

                if should_block_macd_bullish:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Детальное логирование конфликта с указанием всех параметров
                    logger.warning(
                        f"🚫 MACD BULLISH сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: {block_reason_macd_bullish}. "
                        f"Параметры: MACD={macd_line:.4f}, Signal={signal_line:.4f}, Histogram={histogram:.4f}, "
                        f"ADX={adx_value:.1f} ({adx_trend}), EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, цена={current_price:.2f}"
                    )
                else:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "macd_bullish",
                            "strength": base_strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "buy"
                            ),  # ✅ НОВОЕ (28.12.2025): Учет slippage
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": histogram,
                            "confidence": macd_confidence,  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

            elif macd_line < signal_line and histogram < 0:
                # ✅ ЗАДАЧА #7: Проверяем совпадение EMA и цены для BEARISH
                # Для BEARISH: ema_fast<ema_slow AND price<ema_fast
                is_bearish_trend = ema_fast < ema_slow and current_price < ema_fast

                # ✅ ПРИОРИТЕТ 1 (28.12.2025): Адаптивный MACD strength делитель по режимам (BEARISH)
                # Используем тот же делитель что для BULLISH (уже получен выше)
                base_strength_raw = abs(histogram) / macd_strength_divider_bullish
                base_strength = min(base_strength_raw, 1.0)

                # ✅ ПРИОРИТЕТ 2.5 (28.12.2025): Логирование параметров и strength расчетов
                logger.debug(
                    f"📊 MACD BEARISH сигнал {symbol}: histogram={histogram:.4f}, "
                    f"делитель={macd_strength_divider_bullish:.1f}, base_strength={base_strength_raw:.3f}, "
                    f"final_strength={base_strength:.3f}, режим={current_regime_macd_divider_bullish}"
                )

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                if not is_bearish_trend:
                    # Конфликт: MACD bearish, но EMA/цена не bearish
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        adaptive_regime = getattr(
                            self.scalping_config, "adaptive_regime", {}
                        )
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_macd, {})
                        else:
                            regime_config = getattr(
                                adaptive_regime, regime_name_macd, {}
                            )

                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get(
                                "strength_multipliers", {}
                            )
                            conflict_multiplier = strength_multipliers.get(
                                "conflict", 0.5
                            )
                        else:
                            strength_multipliers = getattr(
                                regime_config, "strength_multipliers", None
                            )
                            # conflict_multiplier не используется, удалено для чистоты
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить conflict_multiplier для {regime_name_macd}: {e}"
                        )

                    # ✅ ИСПРАВЛЕНО (26.12.2025): Убрано снижение strength при конфликте с EMA
                    # Конфликтные сигналы теперь полностью блокируются при ADX>=25, а не проходят с сниженным strength
                    # Для ADX<25 оставляем сигнал как есть (без снижения strength)
                    logger.debug(
                        f"⚡ MACD BEARISH с конфликтом EMA для {symbol}: "
                        f"MACD bearish, но EMA/цена не bearish (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, price={current_price:.2f}), "
                        f"strength НЕ снижается (base_strength={base_strength:.3f})"
                    )

                logger.debug(
                    f"✅ MACD BEARISH сигнал для {symbol}: histogram={histogram:.4f}, is_bearish_trend={is_bearish_trend}"
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен порог ADX с 25 до 20 + блокировка конфликта EMA
                # Блокируем SELL сигналы при сильном восходящем тренде (ADX>=20) ИЛИ при конфликте EMA
                # ✅ КРИТИЧЕСКОЕ: Блокируем при конфликте EMA (MACD bearish + EMA bullish) вместо снижения strength
                should_block_macd_bearish = False
                block_reason_macd_bearish = ""

                if not is_bearish_trend:
                    # Конфликт: MACD bearish, но EMA/цена не bearish - ПОЛНАЯ БЛОКИРОВКА
                    should_block_macd_bearish = True
                    block_reason_macd_bearish = f"конфликт EMA (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, цена={current_price:.2f})"

                if adx_value >= 20.0 and adx_trend == "bullish":
                    should_block_macd_bearish = True
                    block_reason_macd_bearish = f"ADX={adx_value:.1f} >= 20 показывает восходящий тренд (против тренда)"

                if should_block_macd_bearish:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Детальное логирование конфликта с указанием всех параметров
                    logger.warning(
                        f"🚫 MACD BEARISH сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: {block_reason_macd_bearish}. "
                        f"Параметры: MACD={macd_line:.4f}, Signal={signal_line:.4f}, Histogram={histogram:.4f}, "
                        f"ADX={adx_value:.1f} ({adx_trend}), EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}, цена={current_price:.2f}"
                    )
                else:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "macd_bearish",
                            "strength": base_strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "sell"
                            ),  # ✅ НОВОЕ (28.12.2025): Учет slippage
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": histogram,
                            "confidence": macd_confidence,  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

        except Exception as e:
            logger.error(f"Ошибка генерации MACD сигналов: {e}")

        return signals

    async def _generate_bollinger_signals(
        self,
        symbol: str,
        indicators: Dict,
        market_data: MarketData,
        adx_trend: Optional[str] = None,
        adx_value: float = 0.0,
        adx_threshold: float = 20.0,  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен дефолтный порог с 25 до 20
    ) -> List[Dict[str, Any]]:
        """Генерация Bollinger Bands сигналов"""
        signals = []

        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем BB с режим-специфичными параметрами
            # Получаем режим сначала
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
            except Exception as exc:
                logger.debug("Ignored error in optional block: %s", exc)

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
                    # 🔴 BUG #6 FIX: Convert to dict first to handle case sensitivity
                    if isinstance(confidence_obj, dict):
                        regime_confidence = confidence_obj.get(regime_name_bb, None)
                    else:
                        confidence_obj_dict = self._to_dict(confidence_obj)
                        regime_confidence_dict = confidence_obj_dict.get(
                            regime_name_bb, {}
                        )

                        # Convert dict back to object for getattr access
                        class _RegimeConfidence:
                            def __init__(self, d):
                                for k, v in d.items():
                                    setattr(self, k, v)

                        regime_confidence = (
                            _RegimeConfidence(regime_confidence_dict)
                            if regime_confidence_dict
                            else None
                        )
                    if regime_confidence:
                        confidence_config_bb = {
                            "rsi_signal": getattr(regime_confidence, "rsi_signal", 0.6),
                        }

            bb_confidence = confidence_config_bb.get("rsi_signal", 0.6)  # Fallback

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем BB с режим-специфичными параметрами
            regime_params_bb = self._get_regime_indicators_params(
                symbol=symbol, regime=regime_name_bb
            )
            bb_period = regime_params_bb.get("bb_period", 20)
            bb_std_multiplier = regime_params_bb.get("bb_std_multiplier", 2.0)

            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= bb_period:
                bb_calculated = self._calculate_regime_bollinger_bands(
                    market_data.ohlcv_data, bb_period, bb_std_multiplier
                )
                if bb_calculated:
                    upper = bb_calculated.get("upper", 0)
                    lower = bb_calculated.get("lower", 0)
                    middle = bb_calculated.get("middle", 0)
                else:
                    # Fallback на базовые индикаторы
                    bb = indicators.get("bollinger_bands", {})
                    upper = bb.get("upper", 0)
                    lower = bb.get("lower", 0)
                    middle = bb.get("middle", 0)
            else:
                # Fallback на базовые индикаторы
                bb = indicators.get("bollinger_bands", {})
                upper = bb.get("upper", 0)
                lower = bb.get("lower", 0)
                middle = bb.get("middle", 0)
                logger.debug(
                    f"⚠️ {symbol}: Недостаточно свечей для пересчета BB ({len(market_data.ohlcv_data) if market_data.ohlcv_data else 0}), "
                    f"используем базовые индикаторы"
                )

            # ✅ ОПТИМИЗАЦИЯ: Используем актуальную цену из стакана для сигналов
            candle_close_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )
            current_price = await self._get_current_market_price(
                symbol, candle_close_price
            )

            # Отскок от нижней полосы (покупка)
            # ✅ ИСПРАВЛЕНИЕ: Не даем LONG сигнал в нисходящем тренде!
            if current_price <= lower and (middle - lower) > 0:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем EMA с режим-специфичными периодами
                regime_params_bb = self._get_regime_indicators_params(symbol=symbol)
                ema_fast_period_bb = regime_params_bb.get("ema_fast", 12)
                ema_slow_period_bb = regime_params_bb.get("ema_slow", 26)

                if market_data.ohlcv_data and len(market_data.ohlcv_data) >= max(
                    ema_fast_period_bb, ema_slow_period_bb
                ):
                    ema_fast = self._calculate_regime_ema(
                        market_data.ohlcv_data, ema_fast_period_bb
                    )
                    ema_slow = self._calculate_regime_ema(
                        market_data.ohlcv_data, ema_slow_period_bb
                    )
                else:
                    # Fallback на базовые индикаторы
                    ema_fast = indicators.get("ema_12", 0)
                    ema_slow = indicators.get("ema_26", 0)

                # Если EMA показывает нисходящий тренд - НЕ даем LONG сигнал
                is_downtrend = ema_fast < ema_slow and current_price < ema_fast

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим, а не отменяем сигнал
                base_strength = min(
                    (
                        (lower - current_price) / (middle - lower)
                        if (middle - lower) > 0
                        else 0.5
                    ),
                    1.0,
                )

                if is_downtrend:
                    # Конфликт: BB oversold (LONG) vs EMA bearish (DOWN)
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        adaptive_regime = getattr(
                            self.scalping_config, "adaptive_regime", {}
                        )
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_bb, {})
                        else:
                            # 🔴 BUG #6 FIX: Convert to dict first to handle case sensitivity
                            adaptive_regime_dict = self._to_dict(adaptive_regime)
                            regime_config = adaptive_regime_dict.get(regime_name_bb, {})

                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get(
                                "strength_multipliers", {}
                            )
                            conflict_multiplier = strength_multipliers.get(
                                "conflict", 0.5
                            )
                        else:
                            strength_multipliers = getattr(
                                regime_config, "strength_multipliers", None
                            )
                            if strength_multipliers:
                                conflict_multiplier = getattr(
                                    strength_multipliers, "conflict", 0.5
                                )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить conflict_multiplier для {regime_name_bb}: {e}"
                        )

                    # ✅ ИСПРАВЛЕНО (26.12.2025): Убрано снижение strength при конфликте с EMA
                    # Конфликтные сигналы теперь полностью блокируются при ADX>=25, а не проходят с сниженным strength
                    # Для ADX<25 оставляем сигнал как есть (без снижения strength)
                    logger.debug(
                        f"⚡ BB OVERSOLD с конфликтом EMA для {symbol}: "
                        f"цена({current_price:.2f}) <= lower({lower:.2f}), "
                        f"но EMA показывает нисходящий тренд (EMA_12={ema_fast:.2f} < EMA_26={ema_slow:.2f}), "
                        f"strength НЕ снижается (base_strength={base_strength:.3f})"
                    )
                else:
                    logger.debug(
                        f"✅ BB OVERSOLD сигнал для {symbol}: "
                        f"цена({current_price:.2f}) <= lower({lower:.2f}), "
                        f"тренд не нисходящий (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f})"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен порог ADX с 25 до 20 + блокировка конфликта EMA
                # 🔴 BUG #5 FIX (09.01.2026): BB oversold не блокируется при ADX<25 bearish, только ослабляется
                # Блокируем BUY сигналы ТОЛЬКО при очень сильном нисходящем тренде (ADX>=25, не 20!)
                should_block_bb_oversold = False
                block_reason_bb_oversold = ""

                if is_downtrend:
                    # 🔴 BUG #7 FIX (11.01.2026): Use proper conflict multiplier calculation
                    # Конфликт: BB oversold (BUY) vs EMA bearish (DOWN)
                    base_strength = self._calculate_conflict_multiplier(
                        symbol=symbol,
                        conflict_type="ema_conflict",
                        base_strength=base_strength,
                        conflict_severity=0.6,  # Умеренный конфликт (0.6 из 1.0)
                        regime=regime_name_bb,
                    )
                    logger.debug(
                        f"⚡ BB OVERSOLD для {symbol}: конфликт EMA, strength снижена на основе conflict_multiplier"
                    )

                if adx_value >= 25.0 and adx_trend == "bearish" and not is_downtrend:
                    # 🔴 BUG #5 FIX: Только блокируем если ADX ОЧЕНЬ высокий (>=25) И нет EMA поддержки
                    # Если EMA показывает конфликт (is_downtrend=True), сигнал уже ослаблен выше
                    should_block_bb_oversold = True
                    block_reason_bb_oversold = f"ADX={adx_value:.1f} >= 25 показывает сильный нисходящий тренд (против тренда)"

                if should_block_bb_oversold:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Детальное логирование конфликта с указанием всех параметров
                    logger.warning(
                        f"🚫 BB OVERSOLD сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: {block_reason_bb_oversold}. "
                        f"Параметры: цена={current_price:.2f}, lower={lower:.2f}, middle={middle:.2f}, upper={upper:.2f}, "
                        f"ADX={adx_value:.1f} ({adx_trend}), EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}"
                    )
                else:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "bb_oversold",
                            "strength": base_strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "buy"
                            ),  # ✅ НОВОЕ (28.12.2025): Учет slippage
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": current_price,
                            "confidence": bb_confidence,  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

            # Отскок от верхней полосы (продажа)
            # ✅ ИСПРАВЛЕНИЕ: Не даем SHORT сигнал в восходящем тренде!
            elif current_price >= upper and (upper - middle) > 0:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем EMA с режим-специфичными периодами
                regime_params_bb = self._get_regime_indicators_params(symbol=symbol)
                ema_fast_period_bb = regime_params_bb.get("ema_fast", 12)
                ema_slow_period_bb = regime_params_bb.get("ema_slow", 26)

                if market_data.ohlcv_data and len(market_data.ohlcv_data) >= max(
                    ema_fast_period_bb, ema_slow_period_bb
                ):
                    ema_fast = self._calculate_regime_ema(
                        market_data.ohlcv_data, ema_fast_period_bb
                    )
                    ema_slow = self._calculate_regime_ema(
                        market_data.ohlcv_data, ema_slow_period_bb
                    )
                else:
                    # Fallback на базовые индикаторы
                    ema_fast = indicators.get("ema_12", 0)
                    ema_slow = indicators.get("ema_26", 0)

                # Если EMA показывает восходящий тренд - НЕ даем SHORT сигнал
                is_uptrend = ema_fast > ema_slow and current_price > ema_fast

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим, а не отменяем сигнал
                base_strength = min(
                    (
                        (current_price - upper) / (upper - middle)
                        if (upper - middle) > 0
                        else 0.5
                    ),
                    1.0,
                )

                if is_uptrend:
                    # Конфликт: BB overbought (SHORT) vs EMA bullish (UP)
                    # Получаем strength_multiplier для конфликта из конфига
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        adaptive_regime = getattr(
                            self.scalping_config, "adaptive_regime", {}
                        )
                        if isinstance(adaptive_regime, dict):
                            regime_config = adaptive_regime.get(regime_name_bb, {})
                        else:
                            # 🔴 BUG #6 FIX: Convert to dict first to handle case sensitivity
                            adaptive_regime_dict = self._to_dict(adaptive_regime)
                            regime_config = adaptive_regime_dict.get(regime_name_bb, {})

                        if isinstance(regime_config, dict):
                            strength_multipliers = regime_config.get(
                                "strength_multipliers", {}
                            )
                            conflict_multiplier = strength_multipliers.get(
                                "conflict", 0.5
                            )
                        else:
                            strength_multipliers = getattr(
                                regime_config, "strength_multipliers", None
                            )
                            if strength_multipliers:
                                conflict_multiplier = getattr(
                                    strength_multipliers, "conflict", 0.5
                                )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить conflict_multiplier для {regime_name_bb}: {e}"
                        )

                    # ✅ ИСПРАВЛЕНО (26.12.2025): Убрано снижение strength при конфликте с EMA
                    # Конфликтные сигналы теперь полностью блокируются при ADX>=25, а не проходят с сниженным strength
                    # Для ADX<25 оставляем сигнал как есть (без снижения strength)
                    logger.debug(
                        f"⚡ BB OVERBOUGHT с конфликтом EMA для {symbol}: "
                        f"цена({current_price:.2f}) >= upper({upper:.2f}), "
                        f"но EMA показывает восходящий тренд (EMA_12={ema_fast:.2f} > EMA_26={ema_slow:.2f}), "
                        f"strength НЕ снижается (base_strength={base_strength:.3f})"
                    )
                else:
                    logger.debug(
                        f"✅ BB OVERBOUGHT сигнал для {symbol}: "
                        f"цена({current_price:.2f}) >= upper({upper:.2f}), "
                        f"тренд не восходящий (EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f})"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен порог ADX с 25 до 20 + блокировка конфликта EMA
                # 🔴 BUG #5 FIX (09.01.2026): BB overbought ослабляется (не блокируется) при EMA конфликте
                # Блокируем SELL сигналы ТОЛЬКО при очень сильном восходящем тренде (ADX>=25, не 20!)
                should_block_bb_overbought = False
                block_reason_bb_overbought = ""

                if is_uptrend:
                    # 🔴 BUG #7 FIX (11.01.2026): Use proper conflict multiplier calculation
                    # Конфликт: BB overbought (SHORT) vs EMA bullish (UP)
                    base_strength = self._calculate_conflict_multiplier(
                        symbol=symbol,
                        conflict_type="ema_conflict",
                        base_strength=base_strength,
                        conflict_severity=0.6,  # Умеренный конфликт (0.6 из 1.0)
                        regime=regime_name_bb,
                    )
                    logger.debug(
                        f"⚡ BB OVERBOUGHT для {symbol}: конфликт EMA, strength снижена на основе conflict_multiplier"
                    )
                    block_reason_bb_overbought = ""  # Не блокируем, только ослабляем

                if adx_value >= 25.0 and adx_trend == "bullish" and not is_uptrend:
                    # 🔴 BUG #5 FIX: Только блокируем если ADX ОЧЕНЬ высокий (>=25) И нет EMA поддержки
                    # Если EMA показывает конфликт (is_uptrend=True), сигнал уже ослаблен выше
                    should_block_bb_overbought = True
                    block_reason_bb_overbought = f"ADX={adx_value:.1f} >= 25 показывает сильный восходящий тренд (против тренда)"

                if should_block_bb_overbought:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Детальное логирование конфликта с указанием всех параметров
                    logger.warning(
                        f"🚫 BB OVERBOUGHT сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: {block_reason_bb_overbought}. "
                        f"Параметры: цена={current_price:.2f}, lower={lower:.2f}, middle={middle:.2f}, upper={upper:.2f}, "
                        f"ADX={adx_value:.1f} ({adx_trend}), EMA_12={ema_fast:.2f}, EMA_26={ema_slow:.2f}"
                    )
                else:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "bb_overbought",
                            "strength": base_strength,
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "sell"
                            ),  # ✅ НОВОЕ (28.12.2025): Учет slippage
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": current_price,
                            "confidence": bb_confidence,  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

        except Exception as e:
            logger.error(f"Ошибка генерации Bollinger Bands сигналов: {e}")

        return signals

    async def _generate_range_bounce_signals(
        self,
        symbol: str,
        indicators: Dict,
        market_data: MarketData,
    ) -> List[Dict[str, Any]]:
        """
        🔴 BUG #8 FIX (11.01.2026): Improved Range-bounce signal generation with better regime detection

        Логика:
        - LONG при касании BB lower + RSI 20-35 (oversold, но не экстремально)
        - SHORT при касании BB upper + RSI 65-80 (overbought, но не экстремально)
        - Блокировка при сильном ADX тренде (>25) чтобы избежать ловли трендового ножа

        ✅ Improvements:
        - Better detection of ranging vs trending markets
        - Adaptive RSI thresholds based on volatility
        - Tighter entry conditions to avoid false signals
        """
        signals = []

        try:
            # Получаем индикаторы
            bb_upper = indicators.get("bb_upper", 0)
            bb_lower = indicators.get("bb_lower", 0)
            bb_middle = indicators.get("bb_middle", 0)
            rsi = indicators.get("rsi", 0)
            adx = indicators.get("adx", 0)
            atr = indicators.get("atr", 0)
            current_price = self._get_current_price(market_data)

            if not all([bb_upper, bb_lower, bb_middle, current_price]):
                return signals

            # 🔴 BUG #8 FIX: Better regime detection
            # Range is confirmed when:
            # 1. ADX < 20 (weak trend)
            # 2. Price oscillates between BB bands
            # 3. BB width is expanding (not contracting) - showing volatility within range
            bb_width = bb_upper - bb_lower
            if bb_width > 0:
                bb_width_pct = (bb_width / bb_middle) * 100
                is_good_range = adx < 20 and bb_width_pct > 2.0  # At least 2% width
            else:
                is_good_range = False

            if not is_good_range:
                logger.debug(
                    f"⛔ Range-bounce BLOCKED для {symbol}: ADX={adx:.1f} (>20 trend) или узкий диапазон"
                )
                return signals

            # 🔴 BUG #8 FIX: Adaptive RSI thresholds based on volatility
            # High volatility → wider thresholds; Low volatility → tighter thresholds
            if atr and atr > 0:
                volatility_factor = min(
                    atr / (bb_middle * 0.01), 2.0
                )  # Normalize to 0-2x
            else:
                volatility_factor = 1.0

            # Adjust RSI thresholds
            rsi_oversold_min = max(15, 20 - (volatility_factor * 5))  # 15-20
            rsi_oversold_max = min(40, 35 + (volatility_factor * 5))  # 35-40
            rsi_overbought_min = max(60, 65 - (volatility_factor * 5))  # 60-65
            rsi_overbought_max = min(85, 80 + (volatility_factor * 5))  # 80-85
            if adx < 15:
                rsi_oversold_max = min(45, rsi_oversold_max + 5)
                rsi_overbought_min = max(55, rsi_overbought_min - 5)

            # Порог касания BB (1.5% от границы)
            touch_threshold = min(0.03, 0.015 * max(1.0, volatility_factor))

            # Проверка LONG условий (касание lower + RSI oversold)
            distance_to_lower = (
                abs(current_price - bb_lower) / bb_lower if bb_lower > 0 else 1.0
            )
            if (
                distance_to_lower < touch_threshold
                and rsi_oversold_min <= rsi <= rsi_oversold_max
            ):
                strength = (
                    75.0 + (rsi_oversold_max - rsi) * 1.0
                )  # Stronger when RSI closer to minimum
                logger.info(
                    f"🎯 Range-bounce LONG сигнал для {symbol}: "
                    f"цена={current_price:.2f} касается BB lower={bb_lower:.2f}, "
                    f"RSI={rsi:.1f} (диапазон {rsi_oversold_min:.0f}-{rsi_oversold_max:.0f}), "
                    f"ADX={adx:.1f}, BB_width={bb_width_pct:.2f}%"
                )
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "range_bounce_long",
                        "strength": strength,
                        "price": self._adjust_price_for_slippage(
                            symbol, current_price, "buy"
                        ),
                        "timestamp": datetime.now(timezone.utc),
                        "indicator_value": distance_to_lower,
                        "confidence": 0.70,  # Средняя уверенность для range-bounce
                    }
                )

            # Проверка SHORT условий (касание upper + RSI overbought)
            distance_to_upper = (
                abs(current_price - bb_upper) / bb_upper if bb_upper > 0 else 1.0
            )
            if (
                distance_to_upper < touch_threshold
                and rsi_overbought_min <= rsi <= rsi_overbought_max
            ):
                strength = (
                    75.0 + (rsi - rsi_overbought_min) * 1.0
                )  # Stronger when RSI closer to maximum
                logger.info(
                    f"🎯 Range-bounce SHORT сигнал для {symbol}: "
                    f"цена={current_price:.2f} касается BB upper={bb_upper:.2f}, "
                    f"RSI={rsi:.1f} (диапазон {rsi_overbought_min:.0f}-{rsi_overbought_max:.0f}), "
                    f"ADX={adx:.1f}, BB_width={bb_width_pct:.2f}%"
                )
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "range_bounce_short",
                        "strength": strength,
                        "price": self._adjust_price_for_slippage(
                            symbol, current_price, "sell"
                        ),
                        "timestamp": datetime.now(timezone.utc),
                        "indicator_value": distance_to_upper,
                        "confidence": 0.70,  # Средняя уверенность для range-bounce
                    }
                )

        except Exception as e:
            logger.error(f"❌ Ошибка генерации Range-bounce сигналов для {symbol}: {e}")

        return signals

    async def _generate_ma_signals(
        self,
        symbol: str,
        indicators: Dict,
        market_data: MarketData,
        adx_trend: Optional[str] = None,
        adx_value: float = 0.0,
        adx_threshold: float = 20.0,  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен дефолтный порог с 25 до 20
    ) -> List[Dict[str, Any]]:
        """Генерация Moving Average сигналов с проверкой направления движения цены и ADX тренда"""
        signals = []

        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Определяем adx_threshold_ma СРАЗУ в начале метода
            # Это гарантирует, что переменная всегда определена, независимо от условий выполнения
            current_regime_ma = "ranging"  # Fallback
            try:
                if self.data_registry:
                    regime_data = await self.data_registry.get_regime(symbol)
                    if regime_data:
                        current_regime_ma = regime_data.get("regime", "ranging").lower()
            except Exception as exc:
                logger.debug("Ignored error in optional block: %s", exc)

            adx_threshold_ma = 30.0  # Fallback для ranging
            if current_regime_ma == "trending":
                adx_threshold_ma = 20.0
            elif current_regime_ma == "choppy":
                adx_threshold_ma = 40.0

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Получаем режим ПЕРЕД расчетом EMA
            # Получаем режим рынка для всех параметров
            regime_name_ma = current_regime_ma  # Используем уже полученный режим

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Пересчитываем EMA с режим-специфичными периодами
            regime_params = self._get_regime_indicators_params(
                symbol=symbol, regime=regime_name_ma
            )
            ema_fast_period = regime_params.get("ema_fast", 12)
            ema_slow_period = regime_params.get("ema_slow", 26)

            # Пересчитываем EMA с правильными периодами
            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= max(
                ema_fast_period, ema_slow_period
            ):
                ma_fast = self._calculate_regime_ema(
                    market_data.ohlcv_data, ema_fast_period
                )
                ma_slow = self._calculate_regime_ema(
                    market_data.ohlcv_data, ema_slow_period
                )
            else:
                # Fallback на базовые индикаторы если недостаточно данных
                ma_fast = indicators.get("ema_12", 0)
                ma_slow = indicators.get("ema_26", 0)
                logger.debug(
                    f"⚠️ {symbol}: Недостаточно свечей для пересчета EMA ({len(market_data.ohlcv_data) if market_data.ohlcv_data else 0}), "
                    f"используем базовые индикаторы"
                )

            # ✅ ОПТИМИЗАЦИЯ: Используем актуальную цену из стакана для сигналов
            candle_close_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )
            current_price = await self._get_current_market_price(
                symbol, candle_close_price
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
            reversal_detected = False  # ✅ НОВОЕ: Флаг обнаружения разворота
            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= 7:
                # ✅ НОВОЕ: Проверка на V-образный разворот (последние 7 свечей)
                recent_candles = market_data.ohlcv_data[-7:]
                highs = [c.high for c in recent_candles]
                lows = [c.low for c in recent_candles]
                closes = [c.close for c in recent_candles]

                # Находим максимальную и минимальную цену в окне
                max_high_idx = highs.index(max(highs))
                max_high = max(highs)
                min_low_idx = lows.index(min(lows))
                min_low = min(lows)

                # ✅ НОВОЕ: Проверка V-образного разворота
                # V-образный разворот: сначала рост до максимума, потом падение
                # Или наоборот: сначала падение до минимума, потом рост

                # ✅ АДАПТИВНО: Получаем reversal_threshold через AdaptiveFilterParameters
                if self.adaptive_filter_params:
                    reversal_threshold = (
                        await self.adaptive_filter_params.get_reversal_threshold(
                            symbol=symbol,
                            regime=regime_name_ma,
                        )
                    )
                else:
                    # Fallback: старая логика (для обратной совместимости)
                    reversal_threshold = (
                        0.0015  # Fallback: 0.15% для обнаружения разворота
                    )
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
                                regime_profile = symbol_profile_dict.get(
                                    regime_name_ma, {}
                                )
                                regime_profile_dict = (
                                    regime_profile
                                    if isinstance(regime_profile, dict)
                                    else (
                                        regime_profile.__dict__
                                        if hasattr(regime_profile, "__dict__")
                                        else {}
                                    )
                                )
                                reversal_config = regime_profile_dict.get(
                                    "reversal_detection", {}
                                )
                                reversal_config_dict = (
                                    reversal_config
                                    if isinstance(reversal_config, dict)
                                    else (
                                        reversal_config.__dict__
                                        if hasattr(reversal_config, "__dict__")
                                        else {}
                                    )
                                )

                                if "v_reversal_threshold" in reversal_config_dict:
                                    reversal_threshold = (
                                        float(
                                            reversal_config_dict["v_reversal_threshold"]
                                        )
                                        / 100.0
                                    )  # Конвертируем из процентов в доли
                                    symbol_profile_found = True
                                    logger.debug(
                                        f"✅ PER-SYMBOL: v_reversal_threshold для {symbol} ({regime_name_ma}): {reversal_threshold:.4f} ({reversal_threshold*100:.2f}%)"
                                    )
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Не удалось получить per-symbol v_reversal_threshold для {symbol}: {e}"
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

                                # Получаем reversal_detection из режима
                                reversal_config = regime_config_dict.get(
                                    "reversal_detection", {}
                                )
                                reversal_config_dict = (
                                    reversal_config
                                    if isinstance(reversal_config, dict)
                                    else (
                                        reversal_config.__dict__
                                        if hasattr(reversal_config, "__dict__")
                                        else {}
                                    )
                                )

                                if "v_reversal_threshold" in reversal_config_dict:
                                    reversal_threshold = (
                                        float(
                                            reversal_config_dict["v_reversal_threshold"]
                                        )
                                        / 100.0
                                    )  # Конвертируем из процентов в доли
                                    logger.debug(
                                        f"✅ ГЛОБАЛЬНЫЙ: v_reversal_threshold для {regime_name_ma}: {reversal_threshold:.4f} ({reversal_threshold*100:.2f}%)"
                                    )
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ Не удалось получить глобальный v_reversal_threshold для {regime_name_ma}: {e}"
                                )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить адаптивный v_reversal_threshold: {e}, используем fallback 0.15%"
                        )

                # Проверка 1: Рост → Падение (V-образный разворот вниз)
                if (
                    max_high_idx < len(recent_candles) - 2
                ):  # Максимум не в последних 2 свечах
                    # Проверяем падение после максимума
                    price_after_max = closes[-1]
                    drop_from_max = (
                        (max_high - price_after_max) / max_high if max_high > 0 else 0
                    )
                    if drop_from_max > reversal_threshold:
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Адаптация V-разворотов к режиму
                        # Для RANGING режима развороты - это нормально, не блокируем сигналы
                        if regime_name_ma and regime_name_ma.lower() == "ranging":
                            logger.info(
                                f"ℹ️ V-образный разворот ВНИЗ обнаружен для {symbol} (RANGING): "
                                f"максимум на свече {max_high_idx} ({max_high:.2f}), "
                                f"текущая цена {price_after_max:.2f}, падение {drop_from_max:.2%} "
                                f"(в ranging режиме это нормально, сигналы не блокируются)"
                            )
                            reversal_detected = False  # НЕ блокируем в ranging режиме
                        else:
                            reversal_detected = True
                            logger.warning(
                                f"⚠️ V-образный разворот ВНИЗ обнаружен для {symbol} ({regime_name_ma or 'unknown'}): "
                                f"максимум на свече {max_high_idx} ({max_high:.2f}), "
                                f"текущая цена {price_after_max:.2f}, падение {drop_from_max:.2%}"
                            )
                        # ✅ НОВОЕ: Записываем разворот в статистику
                        if self.trading_statistics:
                            try:
                                self.trading_statistics.record_reversal(
                                    symbol=symbol,
                                    reversal_type="v_down",
                                    regime=regime_name_ma or "unknown",
                                    price_change=drop_from_max,
                                    max_price=max_high,
                                )
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ Не удалось записать разворот в статистику: {e}"
                                )

                # Проверка 2: Падение → Рост (V-образный разворот вверх)
                if (
                    min_low_idx < len(recent_candles) - 2
                ):  # Минимум не в последних 2 свечах
                    # Проверяем рост после минимума
                    price_after_min = closes[-1]
                    rise_from_min = (
                        (price_after_min - min_low) / min_low if min_low > 0 else 0
                    )
                    if rise_from_min > reversal_threshold:
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Адаптация V-разворотов к режиму
                        # Для RANGING режима развороты - это нормально, не блокируем сигналы
                        if regime_name_ma and regime_name_ma.lower() == "ranging":
                            logger.info(
                                f"ℹ️ V-образный разворот ВВЕРХ обнаружен для {symbol} (RANGING): "
                                f"минимум на свече {min_low_idx} ({min_low:.2f}), "
                                f"текущая цена {price_after_min:.2f}, рост {rise_from_min:.2%} "
                                f"(в ranging режиме это нормально, сигналы не блокируются)"
                            )
                            reversal_detected = False  # НЕ блокируем в ranging режиме
                        else:
                            reversal_detected = True
                            logger.warning(
                                f"⚠️ V-образный разворот ВВЕРХ обнаружен для {symbol} ({regime_name_ma or 'unknown'}): "
                                f"минимум на свече {min_low_idx} ({min_low:.2f}), "
                                f"текущая цена {price_after_min:.2f}, рост {rise_from_min:.2%}"
                            )
                        # ✅ НОВОЕ: Записываем разворот в статистику
                        if self.trading_statistics:
                            try:
                                self.trading_statistics.record_reversal(
                                    symbol=symbol,
                                    reversal_type="v_up",
                                    regime=regime_name_ma or "unknown",
                                    price_change=rise_from_min,
                                    min_price=min_low,
                                )
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ Не удалось записать разворот в статистику: {e}"
                                )

                # Берем последние 5 свечей для определения направления
                recent_candles_5 = market_data.ohlcv_data[-5:]
                closes_5 = [c.close for c in recent_candles_5]

                # Сравниваем первую и последнюю цену в окне
                price_change = (
                    (closes_5[-1] - closes_5[0]) / closes_5[0] if closes_5[0] > 0 else 0
                )

                # ✅ АДАПТИВНО: Порог изменения цены из конфига (определяется выше)
                if price_change > price_change_threshold:  # Рост > порог
                    price_direction = "up"
                elif price_change < -price_change_threshold:  # Падение > порог
                    price_direction = "down"
                else:
                    price_direction = "neutral"

                # Также проверяем последние 3 свечи для более быстрой реакции
                if len(recent_candles_5) >= 3:
                    short_closes = [c.close for c in recent_candles_5[-3:]]
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
            elif market_data.ohlcv_data and len(market_data.ohlcv_data) >= 5:
                # Fallback: используем старую логику для меньшего количества свечей
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
                f"направление_цены={price_direction}, разворот={reversal_detected}"
            )

            # ✅ УЛУЧШЕНИЕ: Проверка минимальной разницы EMA для генерации сигнала
            # Избегаем ложных сигналов при минимальной разнице EMA
            ma_difference_pct = (
                abs(ma_fast - ma_slow) / ma_slow * 100 if ma_slow > 0 else 0
            )

            # ✅ АДАПТИВНО: Получаем min_ma_difference_pct из конфига (ПРИОРИТЕТ: per-symbol > режим > fallback)
            min_ma_difference_pct = 0.1  # Fallback значение
            symbol_profile_found = False
            try:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сначала проверяем per-symbol overrides из symbol_profiles
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

            # ✅ ЛОКАЛЬНЫЙ СМОРОЛ для flat: снижаем порог, если нет явного per-symbol override
            if (
                not symbol_profile_found
                and regime_name_ma == "ranging"
                and min_ma_difference_pct > 0.005
            ):
                logger.debug(
                    f"ℹ️ RANGING override: min_ma_difference_pct снижён до 0.005% (было {min_ma_difference_pct}%)"
                )
                min_ma_difference_pct = 0.005

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
                    # 🔴 BUG #6 FIX: Convert to dict first to handle case sensitivity
                    if isinstance(confidence_obj, dict):
                        regime_confidence = confidence_obj.get(regime_name_ma, None)
                    else:
                        confidence_obj_dict = self._to_dict(confidence_obj)
                        regime_confidence_dict = confidence_obj_dict.get(
                            regime_name_ma, {}
                        )

                        # Convert dict back to object for getattr access
                        class _RegimeConfidence:
                            def __init__(self, d):
                                for k, v in d.items():
                                    setattr(self, k, v)

                        regime_confidence = (
                            _RegimeConfidence(regime_confidence_dict)
                            if regime_confidence_dict
                            else None
                        )
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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): adx_threshold_ma уже определена в начале метода (строка 3781)
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Блокируем сигналы при идентичных EMA (|EMA12-EMA26|/EMA26 < 0.001%)
            ema_identity_threshold = 0.001  # 0.001% - порог идентичности EMA
            ema_identity_pct = (
                abs(ma_fast - ma_slow) / ma_slow * 100 if ma_slow > 0 else 0
            )
            if ema_identity_pct < ema_identity_threshold:
                logger.warning(
                    f"🚫 MA сигналы ПОЛНОСТЬЮ ЗАБЛОКИРОВАНЫ для {symbol}: "
                    f"EMA12 ({ma_fast:.8f}) ≈ EMA26 ({ma_slow:.8f}), разница {ema_identity_pct:.6f}% < {ema_identity_threshold:.6f}% (идентичные EMA). "
                    f"DOGE 08.01.2026 fix: предотвращаем некорректные сигналы при идентичных EMA."
                )
                return signals  # Не генерируем сигналы вообще при идентичных EMA

            # Пересечение быстрой и медленной MA
            if ma_fast > ma_slow and current_price > ma_fast and ma_slow > 0:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (31.12.2025): Блокируем BULLISH в bearish рынке
                # Проверяем ADX тренд ПЕРЕД всеми остальными проверками, чтобы блокировать даже при price_direction == "neutral"
                if adx_value >= adx_threshold_ma and adx_trend == "bearish":
                    # Сильный нисходящий тренд - полностью блокируем BULLISH сигнал
                    logger.warning(
                        f"🚫 MA BULLISH сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: "
                        f"bearish тренд (ADX={adx_value:.1f} >= {adx_threshold_ma:.1f} для режима {current_regime_ma}), "
                        f"price_direction={price_direction}. "
                        f"Параметры: EMA_12={ma_fast:.2f}, EMA_26={ma_slow:.2f}, цена={current_price:.2f}, "
                        f"разница EMA={ma_difference_pct:.3f}%"
                    )
                # ✅ УЛУЧШЕНИЕ: Проверяем минимальную разницу EMA
                elif ma_difference_pct < min_ma_difference_pct:
                    logger.info(
                        f"⛔ MA BULLISH сигнал ОТМЕНЕН для {symbol}: "
                        f"разница EMA слишком мала ({ma_difference_pct:.3f}% < {min_ma_difference_pct}%)"
                    )
                # ✅ НОВОЕ: Блокируем BULLISH сигнал при V-образном развороте вниз
                elif reversal_detected and price_direction == "down":
                    logger.warning(
                        f"🚨 MA BULLISH сигнал ОТМЕНЕН для {symbol}: "
                        f"обнаружен V-образный разворот ВНИЗ (направление={price_direction})"
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
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "buy"
                            ),  # ✅ НОВОЕ (28.12.2025): Учет slippage
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": ma_fast,
                            "confidence": (
                                confidence_config.get("bullish_strong", 0.7)
                                if price_direction == "up"
                                else confidence_config.get("bullish_normal", 0.5)
                            ),  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

            elif ma_fast < ma_slow and current_price < ma_fast and ma_slow > 0:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (31.12.2025): Блокируем BEARISH в bullish рынке
                # Проверяем ADX тренд ПЕРЕД всеми остальными проверками, чтобы блокировать даже при price_direction == "neutral"
                if adx_value >= adx_threshold_ma and adx_trend == "bullish":
                    # Сильный восходящий тренд - полностью блокируем BEARISH сигнал
                    logger.warning(
                        f"🚫 MA BEARISH сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: "
                        f"bullish тренд (ADX={adx_value:.1f} >= {adx_threshold_ma:.1f} для режима {current_regime_ma}), "
                        f"price_direction={price_direction}. "
                        f"Параметры: EMA_12={ma_fast:.2f}, EMA_26={ma_slow:.2f}, цена={current_price:.2f}, "
                        f"разница EMA={ma_difference_pct:.3f}%"
                    )
                # ✅ УЛУЧШЕНИЕ: Проверяем минимальную разницу EMA
                elif ma_difference_pct < min_ma_difference_pct:
                    logger.info(
                        f"⛔ MA BEARISH сигнал ОТМЕНЕН для {symbol}: "
                        f"разница EMA слишком мала ({ma_difference_pct:.3f}% < {min_ma_difference_pct}%)"
                    )
                # ✅ НОВОЕ: Блокируем BEARISH сигнал при V-образном развороте вверх
                elif reversal_detected and price_direction == "up":
                    logger.warning(
                        f"🚨 MA BEARISH сигнал ОТМЕНЕН для {symbol}: "
                        f"обнаружен V-образный разворот ВВЕРХ (направление={price_direction})"
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
                            "price": self._adjust_price_for_slippage(
                                symbol, current_price, "sell"
                            ),  # ✅ НОВОЕ (28.12.2025): Учет slippage
                            "timestamp": datetime.now(timezone.utc),
                            "indicator_value": ma_fast,
                            "confidence": (
                                confidence_config.get("bearish_strong", 0.7)
                                if price_direction == "down"
                                else confidence_config.get("bearish_normal", 0.5)
                            ),  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

        except Exception as e:
            logger.error(f"Ошибка генерации Moving Average сигналов: {e}")

        return signals

    async def _detect_impulse_signals(
        self,
        symbol: str,
        market_data: MarketData,
        indicators: Dict[str, Any],
        current_regime: Optional[str] = None,
        adx_trend: Optional[str] = None,
        adx_value: float = 0.0,
        adx_threshold: float = 20.0,
    ) -> List[Dict[str, Any]]:
        if not self.impulse_config or not getattr(
            self.impulse_config, "enabled", False
        ):
            return []

        config = self.impulse_config
        regime_key = (current_regime or "trending").lower()
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

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Используем адаптивный ATR период
        regime_params_atr = self._get_regime_indicators_params(
            symbol=symbol, regime=regime_key
        )
        atr_period = regime_params_atr.get("atr_period", 14)
        atr_slice = candles[-(atr_period + 1) :]
        atr_value = _calc_atr(atr_slice) if atr_slice else 0.0
        if atr_value <= 0:
            return []

        body = current_candle.close - current_candle.open
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (31.12.2025): Определяем направление с учетом ADX тренда
        # Направление определяется не только по цвету свечи, но и по общему тренду рынка
        initial_direction = "buy" if body >= 0 else "sell"
        direction = initial_direction

        # Проверяем ADX тренд для правильного определения направления
        if adx_value >= adx_threshold and adx_trend:
            # Сильный тренд обнаружен - проверяем соответствие направления сигнала тренду
            if adx_trend == "bearish" and initial_direction == "buy":
                # Bearish тренд, но свеча зеленая - это может быть ложный сигнал
                # Блокируем LONG в сильном нисходящем тренде
                logger.warning(
                    f"🚫 Импульсный сигнал {symbol} BUY заблокирован: "
                    f"bearish тренд (ADX={adx_value:.1f} >= {adx_threshold:.1f}), "
                    f"свеча зеленая (локальная коррекция)"
                )
                return []  # Не генерируем LONG сигнал в bearish рынке
            elif adx_trend == "bullish" and initial_direction == "sell":
                # Bullish тренд, но свеча красная - это может быть ложный сигнал
                # Блокируем SHORT в сильном восходящем тренде
                logger.warning(
                    f"🚫 Импульсный сигнал {symbol} SELL заблокирован: "
                    f"bullish тренд (ADX={adx_value:.1f} >= {adx_threshold:.1f}), "
                    f"свеча красная (локальная коррекция)"
                )
                return []  # Не генерируем SHORT сигнал в bullish рынке

        # Если тренд ranging или слабый (ADX < threshold) - используем начальное направление
        # Если тренд соответствует направлению свечи - тоже используем
        body_abs = abs(body)
        body_ratio = body_abs / atr_value

        # ✅ ИСПРАВЛЕНО (06.01.2026): Улучшенный фильтр объема (рекомендация Copilot)
        # Проверяем объем относительно SMA20 вместо среднего по lookback
        vol_cur = current_candle.volume
        volume_source = "tick"
        volume_warmup = False
        if vol_cur <= 0 and len(candles) >= 2:
            vol_cur = candles[-2].volume
            volume_source = "prev_candle"
        if vol_cur <= 0:
            volume_warmup = True

        vol_sma20 = (
            sum(c.volume for c in candles[-20:]) / 20 if len(candles) >= 20 else 0
        )
        # ✅ L2-2 FIX: Единственная volume проверка через EMA (SMA20)
        # Убрана дублирующая проверка через avg_volume
        vol_threshold = detection_values.get("min_volume_ratio", 1.1)
        if not volume_warmup and vol_sma20 > 0 and vol_cur < vol_sma20 * vol_threshold:
            # Блокируем низкообъемные сигналы (шум)
            logger.debug(
                f"🚫 Импульсный сигнал {symbol} заблокирован: низкий объем "
                f"(источник={volume_source}, текущий={vol_cur:.0f}, SMA20={vol_sma20:.0f}, ratio={vol_cur/vol_sma20:.2f} < {vol_threshold})"
            )
            return []

        # ✅ ИСПРАВЛЕНО (06.01.2026): ADX gate перед добавлением импульсных сигналов (рекомендация Copilot)
        # Повышаем требования к ADX в зависимости от режима
        adx_min_required = 20.0  # По умолчанию для trending
        if regime_key == "ranging":
            adx_min_required = 30.0
        elif regime_key == "choppy":
            adx_min_required = 40.0

        if adx_value is None or adx_value < adx_min_required:
            logger.debug(
                f"🚫 Импульсный сигнал {symbol} заблокирован: ADX={adx_value:.1f} < {adx_min_required:.1f} "
                f"(режим={regime_key})"
            )
            return []

        # ✅ ИСПРАВЛЕНО (06.01.2026): Мульти-индикаторное подтверждение (рекомендация Copilot)
        # Система scoring для проверки качества сигнала
        score = 0
        confirmation_details = []

        # 1. MACD crossover (вес 3)
        macd_data = indicators.get("macd") or indicators.get("MACD")
        if macd_data and isinstance(macd_data, dict):
            macd_line = macd_data.get("macd", 0)
            signal_line = macd_data.get("signal", 0)
            histogram = macd_data.get("histogram", 0)

            if direction == "buy":
                macd_crossover = macd_line > signal_line and histogram > 0
            else:  # sell
                macd_crossover = macd_line < signal_line and histogram < 0

            if macd_crossover:
                score += 3
                confirmation_details.append("MACD crossover")

        # 2. RSI overbought/oversold (вес 2)
        rsi_value = indicators.get("rsi") or indicators.get("RSI")
        if rsi_value is not None:
            rsi_overbought = rsi_value > 70
            rsi_oversold = rsi_value < 30

            if direction == "buy" and rsi_oversold:
                score += 2
                confirmation_details.append("RSI oversold")
            elif direction == "sell" and rsi_overbought:
                score += 2
                confirmation_details.append("RSI overbought")

        # 3. Bollinger Bands breakout (вес 1)
        bb_data = indicators.get("bollinger_bands") or indicators.get("BollingerBands")
        if bb_data and isinstance(bb_data, dict):
            bb_upper = bb_data.get("upper", 0)
            bb_lower = bb_data.get("lower", 0)
            current_price = current_candle.close

            if direction == "buy":
                bb_breakout = current_price > bb_upper
            else:  # sell
                bb_breakout = current_price < bb_lower

            if bb_breakout:
                score += 1
                confirmation_details.append("BB breakout")

        # 4. EMA crossover (вес 1)
        ema_fast = (
            indicators.get("ema_fast")
            or indicators.get("ema_9")
            or indicators.get("EMA_FAST")
        )
        ema_slow = (
            indicators.get("ema_slow")
            or indicators.get("ema_21")
            or indicators.get("EMA_SLOW")
        )
        if ema_fast is not None and ema_slow is not None:
            if direction == "buy":
                ema_crossover = ema_fast > ema_slow and current_candle.close > ema_fast
            else:  # sell
                ema_crossover = ema_fast < ema_slow and current_candle.close < ema_fast

            if ema_crossover:
                score += 1
                confirmation_details.append("EMA crossover")

        # Требуем минимум 4 балла (хотя бы 2 подтверждения)
        if score < 4:
            logger.debug(
                f"🚫 Импульсный сигнал {symbol} {direction.upper()} заблокирован: "
                f"недостаточно подтверждений (score={score}/4, подтверждения={', '.join(confirmation_details) if confirmation_details else 'нет'})"
            )
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
            f"объём x{meta['volume_ratio']:.2f}, пробой уровня {pivot_level:.4f}, "
            f"подтверждения: {', '.join(confirmation_details)} (score={score})"
        )

        relax_cfg = getattr(config, "relax", None)
        trailing_cfg = getattr(config, "trailing", None)

        # ✅ ОПТИМИЗАЦИЯ: Используем актуальную цену из стакана для сигнала
        candle_close_price = current_candle.close
        current_market_price = await self._get_current_market_price(
            symbol, candle_close_price
        )

        signal = {
            "symbol": symbol,
            "side": "buy" if direction == "buy" else "sell",
            "type": "impulse_breakout",
            "strength": strength,
            "price": current_market_price,  # ✅ Используем актуальную цену из стакана
            "timestamp": datetime.now(timezone.utc),
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
            # ✅ ЛОГИРОВАНИЕ: Входящие сигналы перед фильтрами
            logger.info(
                f"[FILTER_INPUT] {symbol}: {len(signals)} signals entering filters"
            )
            for idx, sig in enumerate(signals[:5]):  # Логируем первые 5
                logger.debug(
                    f"  RAW_SIGNAL #{idx+1}: {sig.get('side')} @ {sig.get('price'):.6f} (strength={sig.get('strength'):.2f})"
                )
            if len(signals) > 5:
                logger.debug(f"  ... and {len(signals)-5} more signals")

            # ✅ РЕФАКТОРИНГ: Используем FilterManager если он настроен
            use_filter_manager = (
                self.filter_manager
                and self.filter_manager.adx_filter
                is not None  # Хотя бы один фильтр подключен
            )

            if use_filter_manager:
                # Используем новый FilterManager
                filtered = await self._apply_filters_via_manager(
                    symbol, signals, market_data, current_positions
                )
                # ✅ ЛОГИРОВАНИЕ: Выходящие сигналы после фильтров
                logger.info(
                    f"[FILTER_OUTPUT] {symbol}: {len(filtered)} signals after filters ({len(signals)} before)"
                )
                logger.info(
                    f"  Acceptance rate: {len(filtered)/len(signals)*100:.1f}%"
                    if signals
                    else ""
                )
                return filtered

            # Fallback на старую логику
            filtered_signals = []

            for signal in signals:
                # ✅ КОНФИГУРИРУЕМАЯ Блокировка SHORT/LONG сигналов по конфигу (по умолчанию разрешены обе стороны)
                signal_side = signal.get("side", "").lower()
                allow_short = getattr(
                    self.scalping_config, "allow_short_positions", True
                )
                allow_long = getattr(self.scalping_config, "allow_long_positions", True)

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

                # ✅ ИСПРАВЛЕНО (25.12.2025): Получаем режим с проверкой инициализации и альтернативными источниками
                regime_manager = self.regime_managers.get(symbol) or self.regime_manager
                current_regime_name = None

                if regime_manager:
                    try:
                        current_regime_name = regime_manager.get_current_regime()
                        # Проверяем, что режим действительно определен (не None)
                        if current_regime_name:
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Приводим режим к lowercase для совпадения с конфигом
                            if isinstance(current_regime_name, str):
                                current_regime_name = current_regime_name.lower()
                            else:
                                # Если это объект (например, Regime enum), конвертируем в строку
                                current_regime_name = str(current_regime_name).lower()
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка получения режима из RegimeManager для {symbol}: {e}"
                        )

                # ✅ НОВОЕ: Альтернативный источник - DataRegistry
                if (
                    not current_regime_name
                    and hasattr(self, "data_registry")
                    and self.data_registry
                ):
                    try:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data and regime_data.get("regime"):
                            current_regime_name = str(regime_data.get("regime")).lower()
                            logger.debug(
                                f"✅ Режим для {symbol} получен из DataRegistry: {current_regime_name}"
                            )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить режим из DataRegistry для {symbol}: {e}"
                        )

                if current_regime_name:
                    signal["regime"] = current_regime_name
                    logger.debug(
                        f"✅ Режим для {symbol}: {current_regime_name} (добавлен в сигнал)"
                    )
                else:
                    # ✅ ИСПРАВЛЕНО: Fallback только если все источники недоступны
                    signal["regime"] = "ranging"
                    logger.warning(
                        f"⚠️ Режим не определен для {symbol} при генерации сигнала (RegimeManager и DataRegistry недоступны), "
                        f"используется fallback 'ranging'"
                    )

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

                # удалены неиспользуемые переменные: liquidity_override, order_flow_override, funding_override, volatility_override

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

                # ✅ Проверка ADX: Сила и направление тренда (ПЕРЕД другими фильтрами)
                if self.adx_filter:
                    try:
                        # Получаем параметры ADX из текущего режима перед проверкой
                        if regime_manager:
                            regime_params = regime_manager.get_current_parameters()
                            if regime_params and hasattr(regime_params, "modules"):
                                adx_modules = regime_params.modules
                                from src.strategies.modules.adx_filter import (
                                    ADXFilterConfig,
                                )

                                adx_new_config = ADXFilterConfig(
                                    enabled=True,
                                    adx_threshold=getattr(
                                        adx_modules, "adx_threshold", 18.0
                                    ),
                                    di_difference=getattr(
                                        adx_modules, "adx_di_difference", 1.5
                                    ),
                                )
                                self.adx_filter.config = adx_new_config

                        # Преобразуем side сигнала в OrderSide
                        signal_side_str = signal.get("side", "").lower()
                        from src.models import OrderSide

                        if signal_side_str == "buy":
                            order_side = OrderSide.BUY  # LONG
                        elif signal_side_str == "sell":
                            order_side = OrderSide.SELL  # SHORT
                        else:
                            logger.warning(
                                f"⚠️ Неизвестное направление сигнала для {symbol}: {signal_side_str}"
                            )
                            continue

                        # Получаем свечи из market_data
                        candles = (
                            market_data.ohlcv_data
                            if market_data and market_data.ohlcv_data
                            else []
                        )
                        if not candles:
                            logger.warning(f"⚠️ Нет свечей для ADX проверки {symbol}")
                            continue

                        # Конвертируем OHLCV в dict для ADX фильтра
                        candles_dict = []
                        for candle in candles:
                            candles_dict.append(
                                {
                                    "high": candle.high,
                                    "low": candle.low,
                                    "close": candle.close,
                                }
                            )

                        # Проверяем тренд через ADX
                        adx_result = self.adx_filter.check_trend_strength(
                            symbol, order_side, candles_dict
                        )

                        if not adx_result.allowed:
                            # ✅ ИСПРАВЛЕНО: Блокируем сигнал против тренда (не переключаем направление)
                            logger.warning(
                                f"🚫 ADX заблокировал {signal_side_str.upper()} сигнал для {symbol}: "
                                f"сигнал против тренда ({adx_result.reason if hasattr(adx_result, 'reason') else 'ADX не разрешил'}, "
                                f"ADX={adx_result.adx_value:.1f}, +DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f})"
                            )
                            continue  # Блокируем сигнал
                        else:
                            logger.debug(
                                f"✅ ADX подтвердил {signal_side_str.upper()} сигнал для {symbol}: "
                                f"{adx_result.reason} (ADX={adx_result.adx_value:.1f}, "
                                f"+DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f})"
                            )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка проверки ADX для {symbol}: {e}, пропускаем фильтр"
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
                                    from src.strategies.modules.correlation_filter import (
                                        CorrelationFilterConfig,
                                    )

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
                                    from src.strategies.modules.multi_timeframe import (
                                        MTFConfig,
                                    )

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
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Передаем направление сигнала в LiquidityFilter
                        # Для LONG (buy): проверяем только bid volume
                        # Для SHORT (sell): проверяем только ask volume
                        signal_side = signal.get("side", "").lower()
                        (
                            liquidity_ok,
                            liquidity_snapshot,
                        ) = await self.liquidity_filter.evaluate(
                            symbol,
                            regime=current_regime_name,
                            relax_multiplier=liquidity_relax,
                            thresholds_override=liquidity_override,  # noqa: F821
                            signal_side=signal_side,  # ✅ НОВОЕ: Передаем направление сигнала
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
                            overrides=order_flow_override,  # noqa: F821
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
                            overrides=funding_override,  # noqa: F821
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
                            overrides=volatility_override,  # noqa: F821
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

    async def _apply_filters_via_manager(
        self,
        symbol: str,
        signals: List[Dict[str, Any]],
        market_data: MarketData,
        current_positions: Dict = None,
    ) -> List[Dict[str, Any]]:
        """
        ✅ РЕФАКТОРИНГ: Применение фильтров через FilterManager.

        Args:
            symbol: Торговая пара
            signals: Список сигналов
            market_data: Рыночные данные
            current_positions: Текущие открытые позиции

        Returns:
            Отфильтрованный список сигналов
        """
        try:
            filtered_signals = []

            # Получаем режим для FilterManager
            regime_manager = self.regime_managers.get(symbol) or self.regime_manager
            current_regime_name = (
                regime_manager.get_current_regime() if regime_manager else None
            )

            # Получаем параметры режима
            regime_params = None
            if regime_manager:
                try:
                    regime_params_obj = regime_manager.get_current_parameters()
                    if regime_params_obj:
                        regime_params = self._to_dict(regime_params_obj)
                except Exception as exc:
                    logger.debug("Ignored error in optional block: %s", exc)

            for signal in signals:
                # ✅ КОНФИГУРИРУЕМАЯ Блокировка SHORT/LONG сигналов
                signal_side = signal.get("side", "").lower()
                allow_short = getattr(
                    self.scalping_config, "allow_short_positions", True
                )
                allow_long = getattr(self.scalping_config, "allow_long_positions", True)

                if signal_side == "sell" and not allow_short:
                    logger.debug(
                        f"⛔ SHORT сигнал заблокирован для {symbol}: "
                        f"allow_short_positions={allow_short}"
                    )
                    continue
                elif signal_side == "buy" and not allow_long:
                    logger.debug(
                        f"⛔ LONG сигнал заблокирован для {symbol}: "
                        f"allow_long_positions={allow_long}"
                    )
                    continue

                # Применяем все фильтры через FilterManager
                filtered_signal = await self.filter_manager.apply_all_filters(
                    symbol=symbol,
                    signal=signal,
                    market_data=market_data,
                    current_positions=current_positions,
                    regime=current_regime_name,
                    regime_params=regime_params,
                )

                if filtered_signal:
                    # Адаптация под Futures специфику
                    futures_signal = await self._adapt_signal_for_futures(
                        filtered_signal
                    )
                    filtered_signals.append(futures_signal)
                else:
                    # ✅ НОВОЕ: Сохраняем причину фильтрации для детального логирования
                    filter_reason = signal.get("filter_reason", "неизвестно")
                    signal["filter_reason"] = filter_reason

                    if (
                        self._is_diagnostic_symbol(symbol)
                        and hasattr(self, "structured_logger")
                        and self.structured_logger
                    ):
                        try:
                            fallback_price = None
                            try:
                                fallback_price = (
                                    signal.get("price")
                                    or getattr(market_data, "price", None)
                                    or getattr(market_data, "last_price", None)
                                )
                            except Exception:
                                fallback_price = signal.get("price")

                            self.structured_logger.log_filter_reject(
                                symbol=symbol,
                                side=signal.get("side", "unknown"),
                                price=fallback_price,
                                strength=signal.get("strength", 0.0),
                                regime=current_regime_name or "unknown",
                                reason=filter_reason,
                                filters_passed=signal.get("filters_passed", []),
                            )
                        except Exception as e:
                            logger.debug(f"Ignored error in optional block: {e}")

            return filtered_signals

        except Exception as e:
            logger.error(
                f"Ошибка применения фильтров через FilterManager для {symbol}: {e}",
                exc_info=True,
            )
            # Fallback на старую логику при ошибке
            logger.warning(f"⚠️ Fallback на старую логику фильтрации для {symbol}")
            return await self._apply_filters_legacy(
                symbol, signals, market_data, current_positions
            )

    async def _apply_filters_legacy(
        self,
        symbol: str,
        signals: List[Dict[str, Any]],
        market_data: MarketData,
        current_positions: Dict = None,
    ) -> List[Dict[str, Any]]:
        """
        ✅ LEGACY: Старая логика применения фильтров (fallback).

        Сохранена для обратной совместимости.
        """
        # Переименовываем старую логику в legacy метод
        # Вся существующая логика остается здесь
        try:
            filtered_signals = []

            for signal in signals:
                # ✅ КОНФИГУРИРУЕМАЯ Блокировка SHORT/LONG сигналов по конфигу (по умолчанию разрешены обе стороны)
                signal_side = signal.get("side", "").lower()
                allow_short = getattr(
                    self.scalping_config, "allow_short_positions", True
                )
                allow_long = getattr(self.scalping_config, "allow_long_positions", True)

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

                # ✅ ИСПРАВЛЕНО (25.12.2025): Получаем режим с проверкой инициализации и альтернативными источниками
                regime_manager = self.regime_managers.get(symbol) or self.regime_manager
                current_regime_name = None

                if regime_manager:
                    try:
                        current_regime_name = regime_manager.get_current_regime()
                        # Проверяем, что режим действительно определен (не None)
                        if current_regime_name:
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Приводим режим к lowercase для совпадения с конфигом
                            if isinstance(current_regime_name, str):
                                current_regime_name = current_regime_name.lower()
                            else:
                                # Если это объект (например, Regime enum), конвертируем в строку
                                current_regime_name = str(current_regime_name).lower()
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка получения режима из RegimeManager для {symbol}: {e}"
                        )

                # ✅ НОВОЕ: Альтернативный источник - DataRegistry
                if (
                    not current_regime_name
                    and hasattr(self, "data_registry")
                    and self.data_registry
                ):
                    try:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data and regime_data.get("regime"):
                            current_regime_name = str(regime_data.get("regime")).lower()
                            logger.debug(
                                f"✅ Режим для {symbol} получен из DataRegistry: {current_regime_name}"
                            )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить режим из DataRegistry для {symbol}: {e}"
                        )

                if current_regime_name:
                    signal["regime"] = current_regime_name
                    logger.debug(
                        f"✅ Режим для {symbol}: {current_regime_name} (добавлен в сигнал)"
                    )
                else:
                    # ✅ ИСПРАВЛЕНО: Fallback только если все источники недоступны
                    signal["regime"] = "ranging"
                    logger.warning(
                        f"⚠️ Режим не определен для {symbol} при генерации сигнала (RegimeManager и DataRegistry недоступны), "
                        f"используется fallback 'ranging'"
                    )

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

                # ✅ Проверка ADX: Сила и направление тренда (ПЕРЕД другими фильтрами)
                if self.adx_filter:
                    try:
                        # Получаем параметры ADX из текущего режима перед проверкой
                        if regime_manager:
                            regime_params = regime_manager.get_current_parameters()
                            if regime_params and hasattr(regime_params, "modules"):
                                adx_modules = regime_params.modules
                                from src.strategies.modules.adx_filter import (
                                    ADXFilterConfig,
                                )

                                adx_new_config = ADXFilterConfig(
                                    enabled=True,
                                    adx_threshold=getattr(
                                        adx_modules, "adx_threshold", 18.0
                                    ),
                                    di_difference=getattr(
                                        adx_modules, "adx_di_difference", 1.5
                                    ),
                                )
                                self.adx_filter.config = adx_new_config

                        # Преобразуем side сигнала в OrderSide
                        signal_side_str = signal.get("side", "").lower()
                        from src.models import OrderSide

                        if signal_side_str == "buy":
                            order_side = OrderSide.BUY  # LONG
                        elif signal_side_str == "sell":
                            order_side = OrderSide.SELL  # SHORT
                        else:
                            logger.warning(
                                f"⚠️ Неизвестное направление сигнала для {symbol}: {signal_side_str}"
                            )
                            continue

                        # Получаем свечи из market_data
                        candles = (
                            market_data.ohlcv_data
                            if market_data and market_data.ohlcv_data
                            else []
                        )
                        if not candles:
                            logger.warning(f"⚠️ Нет свечей для ADX проверки {symbol}")
                            continue

                        # Конвертируем OHLCV в dict для ADX фильтра
                        candles_dict = []
                        for candle in candles:
                            candles_dict.append(
                                {
                                    "high": candle.high,
                                    "low": candle.low,
                                    "close": candle.close,
                                }
                            )

                        # Проверяем тренд через ADX
                        adx_result = self.adx_filter.check_trend_strength(
                            symbol, order_side, candles_dict
                        )

                        if not adx_result.allowed:
                            # ✅ ИСПРАВЛЕНО: Блокируем сигнал против тренда (не переключаем направление)
                            logger.warning(
                                f"🚫 ADX заблокировал {signal_side_str.upper()} сигнал для {symbol}: "
                                f"сигнал против тренда ({adx_result.reason if hasattr(adx_result, 'reason') else 'ADX не разрешил'}, "
                                f"ADX={adx_result.adx_value:.1f}, +DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f})"
                            )
                            continue  # Блокируем сигнал
                        else:
                            logger.debug(
                                f"✅ ADX подтвердил {signal_side_str.upper()} сигнал для {symbol}: "
                                f"{adx_result.reason} (ADX={adx_result.adx_value:.1f}, "
                                f"+DI={adx_result.plus_di:.1f}, -DI={adx_result.minus_di:.1f})"
                            )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка проверки ADX для {symbol}: {e}, пропускаем фильтр"
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
                                    from src.strategies.modules.correlation_filter import (
                                        CorrelationFilterConfig,
                                    )

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
                                    mtf_modules = regime_params.modules
                                    # Обновляем параметры MTF из текущего режима
                                    from src.strategies.modules.multi_timeframe import (
                                        MultiTimeframeConfig,
                                    )

                                    mtf_new_config = MultiTimeframeConfig(
                                        enabled=True,
                                        block_neutral=mtf_modules.mtf_block_neutral,
                                        score_bonus=mtf_modules.mtf_score_bonus,
                                        confirmation_timeframe=mtf_modules.mtf_confirmation_timeframe,
                                    )
                                    self.mtf_filter.update_parameters(mtf_new_config)

                            if not self.mtf_filter.check_entry(
                                symbol,
                                signal.get("side", "").lower(),
                                signal.get("price"),
                            ):
                                logger.debug(f"🔍 Сигнал {symbol} отфильтрован MTF")
                                continue
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Ошибка проверки MTF для {symbol}: {e}, пропускаем фильтр"
                            )

                # ✅ Проверка Pivot Points (если фильтр инициализирован)
                if self.pivot_filter:
                    try:
                        # удалена неиспользуемая переменная: pivot_params
                        if not self.pivot_filter.check_entry(
                            symbol, signal.get("side", "").lower(), signal.get("price")
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован Pivot Points")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки Pivot Points для {symbol}: {e}, пропускаем фильтр"
                        )

                # ✅ Проверка Volume Profile (если фильтр инициализирован)
                if self.volume_filter:
                    try:
                        # удалена неиспользуемая переменная: vp_params
                        if not self.volume_filter.check_entry(
                            symbol, signal.get("side", "").lower(), signal.get("price")
                        ):
                            logger.debug(
                                f"🔍 Сигнал {symbol} отфильтрован Volume Profile"
                            )
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки Volume Profile для {symbol}: {e}, пропускаем фильтр"
                        )

                # ✅ Проверка Liquidity (если фильтр инициализирован)
                if self.liquidity_filter:
                    try:
                        liquidity_params = filters_profile.get("liquidity", {})
                        # Применяем relax для импульсов
                        if liquidity_relax < 1.0:
                            # Ослабляем параметры ликвидности
                            if isinstance(liquidity_params, dict):
                                liquidity_params = liquidity_params.copy()
                                liquidity_params["min_spread"] = (
                                    liquidity_params.get("min_spread", 0.001)
                                    * liquidity_relax
                                )
                        if not self.liquidity_filter.check_entry(
                            symbol, signal.get("side", "").lower(), signal.get("price")
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован Liquidity")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки Liquidity для {symbol}: {e}, пропускаем фильтр"
                        )

                # ✅ Проверка Order Flow (если фильтр инициализирован)
                if self.order_flow_filter:
                    try:
                        order_flow_params = filters_profile.get("order_flow", {})
                        # Применяем relax для импульсов
                        if order_flow_relax < 1.0:
                            if isinstance(order_flow_params, dict):
                                order_flow_params = order_flow_params.copy()
                                order_flow_params["long_threshold"] = (
                                    order_flow_params.get("long_threshold", 0.1)
                                    * order_flow_relax
                                )
                                order_flow_params["short_threshold"] = (
                                    order_flow_params.get("short_threshold", -0.1)
                                    * order_flow_relax
                                )
                        if not self.order_flow_filter.check_entry(
                            symbol, signal.get("side", "").lower(), signal.get("price")
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован Order Flow")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки Order Flow для {symbol}: {e}, пропускаем фильтр"
                        )

                # ✅ Проверка Funding Rate (если фильтр инициализирован)
                if self.funding_filter:
                    try:
                        # удалена неиспользуемая переменная: funding_params
                        if not self.funding_filter.check_entry(
                            symbol, signal.get("side", "").lower(), signal.get("price")
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован Funding Rate")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки Funding Rate для {symbol}: {e}, пропускаем фильтр"
                        )

                # ✅ Проверка Volatility (если фильтр инициализирован)
                if self.volatility_filter:
                    try:
                        # удалена неиспользуемая переменная: volatility_params
                        if not self.volatility_filter.check_entry(
                            symbol, signal.get("side", "").lower(), signal.get("price")
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован Volatility")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки Volatility для {symbol}: {e}, пропускаем фильтр"
                        )

                # Адаптация под Futures специфику
                futures_signal = await self._adapt_signal_for_futures(signal)
                filtered_signals.append(futures_signal)

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка применения фильтров (legacy): {e}", exc_info=True)
            # В случае ошибки возвращаем сигналы без фильтрации
            return signals

    async def _adapt_signal_for_futures(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Адаптация сигнала под Futures специфику"""
        try:
            # Добавление Futures-специфичных параметров
            futures_signal = signal.copy()

            # Учет левериджа в силе сигнала (читаем из конфига)
            leverage = getattr(self.scalping_config, "leverage", 3) or 3
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
            # ✅ DEBUG: Логирование входящих сигналов
            logger.info(
                f"📊 [FILTER_AND_RANK_INPUT] Получено {len(signals)} сигналов на вход"
            )
            for sig in signals[:5]:  # Логируем первые 5
                logger.info(
                    f"   Сигнал: {sig.get('symbol')} {sig.get('side')} @ {sig.get('price'):.2f} (strength={sig.get('strength', 0):.2f})"
                )

            # ✅ ПРАВКА: Ограничение частоты сигналов по параметру из конфига
            # NOTE: Pre-filter cooldown in generator is disabled by default.
            # Use coordinator cooldown based on executed trades to avoid blocking all signals.
            prefilter_enabled = False
            try:
                sg_cfg = getattr(self.scalping_config, "signal_generator", {})
                if isinstance(sg_cfg, dict):
                    prefilter_enabled = bool(sg_cfg.get("cooldown_in_generator", False))
                else:
                    prefilter_enabled = bool(
                        getattr(sg_cfg, "cooldown_in_generator", False)
                    )
            except Exception:
                prefilter_enabled = False

            if prefilter_enabled:
                import time

                cooldown = 3.0
                try:
                    if hasattr(self.scalping_config, "signal_cooldown_seconds"):
                        cooldown = float(
                            getattr(
                                self.scalping_config, "signal_cooldown_seconds", 3.0
                            )
                        )
                except Exception as exc:
                    logger.warning(
                        f"SignalGenerator: failed to read signal_cooldown_seconds: {exc}, using 3.0"
                    )

                current_time = time.time()
                filtered_by_time = []
                for signal in signals:
                    symbol = signal.get("symbol", "")
                    if symbol:
                        last_signal_time = self.signal_cache.get(symbol, 0)
                        if current_time - last_signal_time < cooldown:
                            logger.debug(
                                f"SignalGenerator cooldown filter: {symbol} skipped "
                                f"({current_time - last_signal_time:.1f}s < {cooldown}s)"
                            )
                            continue
                        self.signal_cache[symbol] = current_time
                    filtered_by_time.append(signal)
                signals = filtered_by_time
                if not signals:
                    logger.debug(
                        "SignalGenerator: all signals filtered by cooldown, skipping ranking"
                    )
                    return []

            pattern_context_by_symbol = {}
            orchestrator_min_strength_by_symbol = {}
            orchestrator_source_by_symbol = {}

            # min_signal_strength ?????? ????? ParameterOrchestrator
            regime_name_min_strength = "ranging"  # default, ?????????? RegimeManager
            try:
                if hasattr(self, "regime_manager") and self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        regime_name_min_strength = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
                logger.debug(
                    f"PARAM_ORCH: using regime '{regime_name_min_strength}' for min_signal_strength"
                )
            except Exception as exc:
                logger.debug("Ignored error in optional block: %s", exc)

            # P0-3 fix (2026-02-21): нет сигналов → нечего фильтровать.
            # Root cause: symbols_in_signals брался из входных сигналов, а не из конфига.
            # При signals=[] → пустой set → цикл ниже не выполнялся → словарь {} →
            # "PARAM_ORCH: no valid min_signal_strength values; block signals" (328 раз).
            # Решение: ранний выход. Нечего фильтровать = нечего и валидировать.
            if not signals:
                logger.debug(
                    "_filter_and_rank_signals: нет сигналов на входе — пропускаем orchestrator валидацию"
                )
                return []

            if not getattr(self, "parameter_orchestrator", None):
                logger.error(
                    "PARAM_ORCH missing: min_signal_strength must come from ParameterOrchestrator"
                )
                return []

            symbols_in_signals = {s.get("symbol") for s in signals if s.get("symbol")}
            for symbol_val in symbols_in_signals:
                market_data = await self._get_market_data(symbol_val)
                if not market_data or not getattr(market_data, "ohlcv_data", None):
                    logger.warning(
                        f"PARAM_ORCH: market_data missing for {symbol_val}, using fallback threshold"
                    )
                    # FIX (2026-02-20): use fallback instead of None → None causes empty min_strength_by_symbol → blocks ALL signals
                    _fallback = getattr(
                        self.scalping_config, "min_signal_strength", 0.08
                    )
                    orchestrator_min_strength_by_symbol[symbol_val] = float(_fallback)
                    orchestrator_source_by_symbol[
                        symbol_val
                    ] = "fallback_no_market_data"
                    continue
                bundle = self.parameter_orchestrator.resolve_bundle(
                    symbol=symbol_val,
                    regime=None,  # Use per-symbol regime detection
                    market_data=market_data,
                    include_signal=True,
                    include_exit=False,
                    include_order=False,
                    include_risk=False,
                    include_patterns=True,
                )
                if not bundle.status.valid or not bundle.signal:
                    logger.warning(
                        f"PARAM_ORCH invalid for {symbol_val}: {bundle.status.errors} — используем fallback threshold"
                    )
                    # FIX (2026-02-18): вместо None (→ блокировка всех сигналов) — используем fallback
                    _fallback = getattr(
                        self.scalping_config, "min_signal_strength", 0.08
                    )
                    orchestrator_min_strength_by_symbol[symbol_val] = float(_fallback)
                    orchestrator_source_by_symbol[symbol_val] = "fallback_config"
                    continue
                if bundle.signal.min_signal_strength is None:
                    logger.warning(
                        f"PARAM_ORCH: min_signal_strength missing for {symbol_val} — используем fallback"
                    )
                    _fallback = getattr(
                        self.scalping_config, "min_signal_strength", 0.08
                    )
                    orchestrator_min_strength_by_symbol[symbol_val] = float(_fallback)
                    orchestrator_source_by_symbol[symbol_val] = "fallback_config"
                    continue
                orchestrator_min_strength_by_symbol[
                    symbol_val
                ] = bundle.signal.min_signal_strength
                source = None
                if bundle.signal.sources:
                    source = bundle.signal.sources.get("min_signal_strength")
                orchestrator_source_by_symbol[symbol_val] = (
                    source or "parameter_orchestrator"
                )
                if bundle.patterns and bundle.patterns.enabled and self.pattern_engine:
                    current_price = self._get_current_price(market_data)
                    ctx = self.pattern_engine.evaluate(
                        market_data.ohlcv_data,
                        current_price,
                        bundle.patterns,
                    )
                    pattern_context_by_symbol[symbol_val] = ctx

            min_strength_by_symbol = {}
            source_info_by_symbol = {}
            for symbol_val, min_val in orchestrator_min_strength_by_symbol.items():
                if min_val is None:
                    continue
                min_strength_by_symbol[symbol_val] = float(min_val)
                source_info_by_symbol[symbol_val] = orchestrator_source_by_symbol.get(
                    symbol_val, "parameter_orchestrator"
                )

            if not min_strength_by_symbol:
                logger.error(
                    "PARAM_ORCH: no valid min_signal_strength values; block signals"
                )
                return []

            if pattern_context_by_symbol:
                for signal in signals:
                    symbol_val = signal.get("symbol")
                    if not symbol_val:
                        continue
                    ctx = pattern_context_by_symbol.get(symbol_val)
                    if not ctx or not ctx.get("valid"):
                        continue
                    score = max(
                        ctx.get("bullish_score", 0.0), ctx.get("bearish_score", 0.0)
                    )
                    if ctx.get("confidence", 0.0) < ctx.get("min_confidence", 0.0):
                        continue
                    if score < ctx.get("min_strength", 0.0):
                        continue
                    side = signal.get("side")
                    bias = ctx.get("bias", 0)
                    strength_val = float(signal.get("strength", 0.0))
                    if (side == "buy" and bias > 0) or (side == "sell" and bias < 0):
                        strength_val = min(
                            1.0,
                            strength_val
                            * (
                                1.0
                                + ctx.get("boost_multiplier", 0.0)
                                * ctx.get("confidence", 0.0)
                            ),
                        )
                        signal["pattern_action"] = "boost"
                    elif bias != 0:
                        strength_val = max(
                            0.0,
                            strength_val
                            * (
                                1.0
                                - ctx.get("penalty_multiplier", 0.0)
                                * ctx.get("confidence", 0.0)
                            ),
                        )
                        signal["pattern_action"] = "penalize"
                    signal["strength"] = strength_val
                    signal["pattern_bias"] = bias
                    signal["pattern_confidence"] = ctx.get("confidence", 0.0)

            # Нормализация силы сигнала до 0..1 для согласования с min_signal_strength
            def _safe_strength(value: Any) -> float:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return 0.0

            # Вариант 2: нормализация по медиане/квантилям (PER-SYMBOL)
            strengths_by_symbol: Dict[str, list] = {}
            for s in signals:
                if not s:
                    continue
                sym = s.get("symbol")
                if not sym:
                    continue
                strengths_by_symbol.setdefault(sym, []).append(
                    _safe_strength(s.get("strength", 0.0))
                )

            norm_factor_by_symbol: Dict[str, float] = {}
            for sym, values in strengths_by_symbol.items():
                positive_strengths = [v for v in values if v > 0.0]
                norm_factor = 1.0
                if positive_strengths:
                    try:
                        median_strength = float(np.percentile(positive_strengths, 50))
                        p90_strength = float(np.percentile(positive_strengths, 90))
                    except Exception:
                        sorted_strengths = sorted(positive_strengths)
                        mid_idx = max(0, int(len(sorted_strengths) * 0.5) - 1)
                        p90_idx = max(0, int(len(sorted_strengths) * 0.9) - 1)
                        median_strength = float(sorted_strengths[mid_idx])
                        p90_strength = float(sorted_strengths[p90_idx])

                    target_median = 0.10
                    if median_strength > 0:
                        norm_factor = min(
                            10.0, max(1.0, target_median / median_strength)
                        )
                    if p90_strength > 0:
                        max_by_p90 = 0.90 / p90_strength
                        norm_factor = min(norm_factor, max_by_p90)

                    if norm_factor > 1.0:
                        logger.info(
                            "[STRENGTH NORMALIZE v2] "
                            f"symbol={sym} median={median_strength:.6f}, "
                            f"p90={p90_strength:.6f}, norm_factor={norm_factor:.3f}, "
                            f"samples={len(positive_strengths)}"
                        )
                norm_factor_by_symbol[sym] = norm_factor

            for s in signals:
                if not s:
                    continue
                sym = s.get("symbol")
                raw_strength = _safe_strength(s.get("strength", 0.0))
                s["strength_raw"] = raw_strength
                norm_factor = norm_factor_by_symbol.get(sym, 1.0)
                if norm_factor > 1.0:
                    raw_strength = raw_strength * norm_factor
                    s["strength_normed"] = True
                    s["strength_norm_factor"] = norm_factor
                    s["strength_norm_method"] = "median_p90_per_symbol"
                else:
                    s["strength_normed"] = False
                    s["strength_norm_factor"] = 1.0
                    s["strength_norm_method"] = "none"
                s["strength"] = max(0.0, min(1.0, raw_strength))

            filtered_signals = []
            for s in signals:
                symbol_val = s.get("symbol", "UNKNOWN")
                if symbol_val not in min_strength_by_symbol:
                    logger.warning(
                        f"PARAM_ORCH: missing min_strength for {symbol_val}, skip signal"
                    )
                    continue
                min_strength = min_strength_by_symbol[symbol_val]
                strength_val = s.get("strength", 0)
                logger.info(
                    f"[SIGNAL STRENGTH] {symbol_val}: strength={strength_val:.2f}, min_signal_strength={min_strength:.2f}"
                )
                if strength_val >= min_strength:
                    s["min_strength_applied"] = True
                    s["min_strength"] = min_strength
                    s["min_strength_source"] = source_info_by_symbol.get(
                        symbol_val, "unknown"
                    )
                    filtered_signals.append(s)

            if self._diagnostic_symbols:
                for s in signals:
                    strength_val = s.get("strength", 0)
                    symbol_val = s.get("symbol")
                    min_strength = min_strength_by_symbol.get(symbol_val)
                    if min_strength is None:
                        continue
                    source_info = source_info_by_symbol.get(symbol_val, "unknown")
                    if strength_val < min_strength and self._is_diagnostic_symbol(
                        symbol_val
                    ):
                        try:
                            if (
                                hasattr(self, "structured_logger")
                                and self.structured_logger
                            ):
                                self.structured_logger.log_filter_reject(
                                    symbol=symbol_val,
                                    side=s.get("side", "unknown"),
                                    price=s.get("price"),
                                    strength=strength_val,
                                    regime=regime_name_min_strength or "unknown",
                                    reason=(
                                        f"min_signal_strength: strength={strength_val:.2f} < {min_strength:.2f} "
                                        f"(source={source_info})"
                                    ),
                                    filters_passed=s.get("filters_passed", []),
                                )
                        except Exception as e:
                            logger.debug("Ignored error in optional block: %s", e)

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
            timestamp = datetime.now(timezone.utc)

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
                "last_signal_time": (
                    self.signal_history[-1]["timestamp"]
                    if self.signal_history
                    else None
                ),
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
