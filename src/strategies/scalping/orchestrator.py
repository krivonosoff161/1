"""
Оркестратор скальпинг стратегии.

Координирует все модули:
- SignalGenerator
- OrderExecutor
- PositionManager
- RiskController
- PerformanceTracker
- Phase 1 модули (MTF, Correlation, Pivot, VP, ARM, Balance, Time)
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional

from loguru import logger

from src.config import BotConfig, RiskConfig, ScalpingConfig
# Phase 1 модули
from src.filters.time_session_manager import (TimeFilterConfig,
                                              TimeSessionManager)
from src.indicators import IndicatorManager
from src.models import MarketData, Position
from src.okx_client import OKXClient
from src.risk.risk_controller import RiskController
from src.strategies.modules.adaptive_regime_manager import (
    AdaptiveRegimeManager, IndicatorParameters, ModuleParameters, RegimeConfig,
    RegimeParameters)
from src.strategies.modules.balance_checker import (BalanceCheckConfig,
                                                    BalanceChecker)
from src.strategies.modules.correlation_filter import (CorrelationFilter,
                                                       CorrelationFilterConfig)
from src.strategies.modules.multi_timeframe import (MTFConfig,
                                                    MultiTimeframeFilter)
from src.strategies.modules.pivot_points import (PivotPointsConfig,
                                                 PivotPointsFilter)
from src.strategies.modules.volume_profile_filter import (VolumeProfileConfig,
                                                          VolumeProfileFilter)

from .order_executor import OrderExecutor
from .performance_tracker import PerformanceTracker
from .position_manager import PositionManager
# Core модули
from .signal_generator import SignalGenerator


class ScalpingOrchestrator:
    """
    Оркестратор скальпинг стратегии.

    Главный координатор всех модулей стратегии.
    """

    def __init__(
        self,
        client: OKXClient,
        config: ScalpingConfig,
        risk_config: RiskConfig,
        full_config: BotConfig,
    ):
        """
        Инициализация оркестратора.

        Args:
            client: OKX клиент
            config: Scalping конфигурация
            risk_config: Risk конфигурация
            full_config: Полный конфиг бота (для доступа к manual_pools)
        """
        self.client = client
        self.config = config
        self.risk_config = risk_config
        self.full_config = full_config
        self.strategy_id = "scalping_modular_v2"

        # Состояние
        self.active = config.enabled
        self.positions: Dict[str, Position] = {}
        self.market_data_cache: Dict[str, MarketData] = {}

        # Rate limiting
        self.api_requests_count = 0
        self.api_requests_window_start = datetime.utcnow()
        self.max_requests_per_minute = 100

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🎯 SCALPING ORCHESTRATOR INITIALIZATION")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # 1. Инициализация индикаторов
        self.indicators = self._setup_indicators()

        # 2. Инициализация Phase 1 модулей
        self.modules = self._init_phase1_modules()

        # 3. Инициализация Telegram (если включен)
        self.telegram = self._init_telegram()

        # 4. Инициализация Core модулей
        self.signal_generator = SignalGenerator(
            client, config, risk_config, self.modules, self.indicators
        )

        self.order_executor = OrderExecutor(
            client,
            config,
            risk_config,
            balance_checker=self.modules.get("balance"),
            adaptive_regime=self.modules.get("arm"),
        )

        # Инициализация WebSocket для быстрых входов
        self.ws_initialized = False

        self.position_manager = PositionManager(
            client, config, adaptive_regime=self.modules.get("arm")
        )

        self.risk_controller = RiskController(
            config,
            risk_config,
            adaptive_regime=self.modules.get("arm"),
            telegram_notifier=self.telegram,
        )

        self.performance_tracker = PerformanceTracker()

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("✅ SCALPING ORCHESTRATOR READY")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    async def initialize_websocket(self):
        """Инициализация WebSocket для быстрых входов"""
        try:
            logger.info("🚀 Initializing WebSocket Order Executor...")
            await self.order_executor.initialize_websocket()
            self.ws_initialized = True
            logger.info("✅ WebSocket Order Executor ready for fast entries")
        except Exception as e:
            logger.error(f"❌ WebSocket initialization failed: {e}")
            logger.warning("⚠️ Will use REST API for order placement")
            self.ws_initialized = False

    async def cleanup_websocket(self):
        """Очистка WebSocket соединения"""
        if self.ws_initialized:
            try:
                await self.order_executor.cleanup_websocket()
                self.ws_initialized = False
                logger.info("🔌 WebSocket Order Executor disconnected")
            except Exception as e:
                logger.error(f"❌ WebSocket cleanup error: {e}")

    def _setup_indicators(self) -> IndicatorManager:
        """Настройка индикаторов"""
        from src.indicators import (ATR, MACD, RSI, BollingerBands,
                                    ExponentialMovingAverage,
                                    SimpleMovingAverage, VolumeIndicator)

        manager = IndicatorManager()

        # Добавляем индикаторы с параметрами из конфига
        manager.add_indicator(
            "SMA_FAST", SimpleMovingAverage(self.config.indicators.sma_fast)
        )
        manager.add_indicator(
            "SMA_SLOW", SimpleMovingAverage(self.config.indicators.sma_slow)
        )
        manager.add_indicator(
            "EMA_FAST", ExponentialMovingAverage(self.config.indicators.ema_fast)
        )
        manager.add_indicator(
            "EMA_SLOW", ExponentialMovingAverage(self.config.indicators.ema_slow)
        )
        manager.add_indicator("RSI", RSI(self.config.indicators.rsi_period))
        manager.add_indicator("ATR", ATR(self.config.indicators.atr_period))
        manager.add_indicator(
            "BB",
            BollingerBands(
                self.config.indicators.bollinger_period,
                self.config.indicators.bollinger_std,
            ),
        )
        manager.add_indicator("VOLUME", VolumeIndicator())
        manager.add_indicator("MACD", MACD())

        logger.info("✅ Indicators initialized")
        return manager

    def _init_phase1_modules(self) -> Dict:
        """
        Инициализация Phase 1 модулей.

        Returns:
            Dict с модулями
        """
        modules = {}

        # Multi-Timeframe
        if (
            hasattr(self.config, "multi_timeframe_enabled")
            and self.config.multi_timeframe_enabled
        ):
            mtf_config = MTFConfig(
                confirmation_timeframe=self.config.multi_timeframe.get(
                    "confirmation_timeframe", "15m"
                ),
                score_bonus=self.config.multi_timeframe.get("score_bonus", 2),
                block_opposite=self.config.multi_timeframe.get("block_opposite", True),
                ema_fast_period=self.config.multi_timeframe.get("ema_fast_period", 8),
                ema_slow_period=self.config.multi_timeframe.get("ema_slow_period", 21),
                cache_ttl_seconds=self.config.multi_timeframe.get(
                    "cache_ttl_seconds", 30
                ),
            )
            modules["mtf"] = MultiTimeframeFilter(self.client, mtf_config)
            logger.info("✅ Multi-Timeframe Filter enabled")
        else:
            logger.info("⚪ Multi-Timeframe Filter disabled")

        # Correlation Filter
        if (
            hasattr(self.config, "correlation_filter_enabled")
            and self.config.correlation_filter_enabled
        ):
            corr_config = CorrelationFilterConfig(
                enabled=True,
                max_correlated_positions=self.config.correlation_filter.get(
                    "max_correlated_positions", 1
                ),
                correlation_threshold=self.config.correlation_filter.get(
                    "correlation_threshold", 0.7
                ),
                block_same_direction_only=self.config.correlation_filter.get(
                    "block_same_direction_only", True
                ),
            )
            modules["correlation"] = CorrelationFilter(
                self.client, corr_config, self.config.symbols
            )
            logger.info("✅ Correlation Filter enabled")
        else:
            logger.info("⚪ Correlation Filter disabled")

        # 🆕 ADX Filter (сила тренда)
        if (
            hasattr(self.config, "adx_filter_enabled")
            and self.config.adx_filter_enabled
        ):
            from src.strategies.modules.adx_filter import (ADXFilter,
                                                           ADXFilterConfig)

            adx_config = ADXFilterConfig(
                enabled=True,
                adx_threshold=self.config.adx_filter.get("adx_threshold", 25.0),
                di_difference=self.config.adx_filter.get(
                    "di_difference", 1.5
                ),  # 🔥 ИЗМЕНЕНО: 5.0→1.5 (начальный RANGING!)
                adx_period=self.config.adx_filter.get("adx_period", 14),
                timeframe=self.config.adx_filter.get("timeframe", "15m"),
            )
            modules["adx"] = ADXFilter(adx_config)
            logger.info("✅ ADX Filter enabled")
        else:
            logger.info("⚪ ADX Filter disabled")

        # Pivot Points
        if (
            hasattr(self.config, "pivot_points_enabled")
            and self.config.pivot_points_enabled
        ):
            pivot_config = PivotPointsConfig(
                enabled=True,
                daily_timeframe=self.config.pivot_points.get("daily_timeframe", "1D"),
                use_last_n_days=self.config.pivot_points.get("use_last_n_days", 1),
                level_tolerance_percent=self.config.pivot_points.get(
                    "level_tolerance_percent", 0.003
                ),
                score_bonus_near_level=self.config.pivot_points.get(
                    "score_bonus_near_level", 1
                ),
                cache_ttl_seconds=self.config.pivot_points.get(
                    "cache_ttl_seconds", 3600
                ),
            )
            modules["pivot"] = PivotPointsFilter(self.client, pivot_config)
            logger.info("✅ Pivot Points Filter enabled")
        else:
            logger.info("⚪ Pivot Points Filter disabled")

        # Volume Profile
        if (
            hasattr(self.config, "volume_profile_enabled")
            and self.config.volume_profile_enabled
        ):
            vp_config = VolumeProfileConfig(
                enabled=True,
                lookback_timeframe=self.config.volume_profile.get(
                    "lookback_timeframe", "1H"
                ),
                lookback_candles=self.config.volume_profile.get(
                    "lookback_candles", 100
                ),
                price_buckets=self.config.volume_profile.get("price_buckets", 50),
                value_area_percent=self.config.volume_profile.get(
                    "value_area_percent", 70.0
                ),
                score_bonus_in_value_area=self.config.volume_profile.get(
                    "score_bonus_in_value_area", 1
                ),
                score_bonus_near_poc=self.config.volume_profile.get(
                    "score_bonus_near_poc", 1
                ),
                poc_tolerance_percent=self.config.volume_profile.get(
                    "poc_tolerance_percent", 0.005
                ),
                cache_ttl_seconds=self.config.volume_profile.get(
                    "cache_ttl_seconds", 600
                ),
            )
            modules["vp"] = VolumeProfileFilter(self.client, vp_config)
            logger.info("✅ Volume Profile Filter enabled")
        else:
            logger.info("⚪ Volume Profile Filter disabled")

        # Balance Checker
        if (
            hasattr(self.config, "balance_checker_enabled")
            and self.config.balance_checker_enabled
        ):
            balance_config = BalanceCheckConfig(
                enabled=True,
                usdt_reserve_percent=self.config.balance_checker.get(
                    "usdt_reserve_percent", 10.0
                ),
                min_asset_balance_usd=self.config.balance_checker.get(
                    "min_asset_balance_usd", 50.0
                ),
                min_usdt_balance=self.config.balance_checker.get(
                    "min_usdt_balance", 15.0
                ),
                log_all_checks=self.config.balance_checker.get("log_all_checks", False),
            )
            modules["balance"] = BalanceChecker(balance_config)
            logger.info("✅ Balance Checker enabled")
        else:
            logger.info("⚪ Balance Checker disabled")

        # Time Filter
        if (
            hasattr(self.config, "time_filter_enabled")
            and self.config.time_filter_enabled
        ):
            time_config = TimeFilterConfig(
                enabled=True,
                trade_asian_session=self.config.time_filter.get(
                    "trade_asian_session", True
                ),
                trade_european_session=self.config.time_filter.get(
                    "trade_european_session", True
                ),
                trade_american_session=self.config.time_filter.get(
                    "trade_american_session", True
                ),
                prefer_overlaps=self.config.time_filter.get("prefer_overlaps", False),
                avoid_low_liquidity_hours=self.config.time_filter.get(
                    "avoid_low_liquidity_hours", True
                ),
                avoid_weekends=self.config.time_filter.get("avoid_weekends", True),
            )
            modules["time"] = TimeSessionManager(time_config)
            logger.info("✅ Time Filter enabled")
        else:
            logger.info("⚪ Time Filter disabled")

        # ARM - Adaptive Regime Manager
        if (
            hasattr(self.config, "adaptive_regime_enabled")
            and self.config.adaptive_regime_enabled
        ):
            # Создаем параметры для каждого режима из config
            arm_config = self._create_arm_config()
            modules["arm"] = AdaptiveRegimeManager(arm_config)
            logger.info("✅ Adaptive Regime Manager enabled")
        else:
            logger.info("⚪ Adaptive Regime Manager disabled")

        return modules

    def _create_arm_config(self) -> RegimeConfig:
        """
        Создание конфигурации ARM из config.yaml.

        ✅ ВСЕ ПАРАМЕТРЫ загружаются из config.yaml!
        ✅ Fallback значения обновлены на актуальные (19.10.2025)
        """
        # Загружаем параметры из config.adaptive_regime
        arm_settings = self.config.adaptive_regime

        # Извлекаем настройки для каждого режима
        trending_cfg = arm_settings.get("trending", {})
        trending_indicators = trending_cfg.get("indicators", {})
        trending_modules = trending_cfg.get("modules", {})

        trending_params = RegimeParameters(
            # Основные параметры
            min_score_threshold=trending_cfg.get(
                "min_score_threshold", 5
            ),  # 🔥 ОБНОВЛЕНО: 6→5
            max_trades_per_hour=trending_cfg.get("max_trades_per_hour", 20),
            position_size_multiplier=trending_cfg.get("position_size_multiplier", 1.2),
            tp_atr_multiplier=trending_cfg.get(
                "tp_atr_multiplier", 1.2
            ),  # 🔥 ОБНОВЛЕНО: 1.5→1.2
            sl_atr_multiplier=trending_cfg.get(
                "sl_atr_multiplier", 0.9
            ),  # 🔥 ОБНОВЛЕНО: 1.25→0.9
            max_holding_minutes=trending_cfg.get(
                "max_holding_minutes", 60
            ),  # 🔥 ОБНОВЛЕНО: 10→60
            cooldown_after_loss_minutes=trending_cfg.get(
                "cooldown_after_loss_minutes", 2
            ),
            pivot_bonus_multiplier=trending_cfg.get("pivot_bonus_multiplier", 1.5),
            volume_profile_bonus_multiplier=trending_cfg.get(
                "volume_profile_bonus_multiplier", 1.0
            ),
            # ✅ Profit Harvesting (теперь берётся из config!)
            ph_enabled=trending_cfg.get("ph_enabled", True),
            ph_threshold=trending_cfg.get(
                "ph_threshold", 0.35
            ),  # 🔥 ОБНОВЛЕНО: 0.20→0.35
            ph_time_limit=trending_cfg.get(
                "ph_time_limit", 300
            ),  # 🔥 ОБНОВЛЕНО: 120→300
            # ✅ Индикаторы (теперь берутся из config!)
            indicators=IndicatorParameters(
                rsi_overbought=trending_indicators.get("rsi_overbought", 70),
                rsi_oversold=trending_indicators.get("rsi_oversold", 30),
                volume_threshold=trending_indicators.get(
                    "volume_threshold", 1.10
                ),  # 🔥 ОБНОВЛЕНО: 1.05→1.10
                sma_fast=trending_indicators.get("sma_fast", 8),
                sma_slow=trending_indicators.get("sma_slow", 25),
                ema_fast=trending_indicators.get("ema_fast", 8),
                ema_slow=trending_indicators.get("ema_slow", 21),
                atr_period=trending_indicators.get("atr_period", 14),
                min_volatility_atr=trending_indicators.get(
                    "min_volatility_atr", 0.0003
                ),
            ),
            # ✅ Модули (теперь берутся из config!)
            modules=ModuleParameters(
                mtf_block_opposite=trending_modules.get("multi_timeframe", {}).get(
                    "block_opposite", False
                ),
                mtf_score_bonus=trending_modules.get("multi_timeframe", {}).get(
                    "score_bonus", 1
                ),
                mtf_confirmation_timeframe=trending_modules.get(
                    "multi_timeframe", {}
                ).get("confirmation_timeframe", "30m"),
                correlation_threshold=trending_modules.get(
                    "correlation_filter", {}
                ).get("correlation_threshold", 0.8),
                max_correlated_positions=trending_modules.get(
                    "correlation_filter", {}
                ).get("max_correlated_positions", 3),
                block_same_direction_only=trending_modules.get(
                    "correlation_filter", {}
                ).get("block_same_direction_only", False),
                prefer_overlaps=trending_modules.get("time_filter", {}).get(
                    "prefer_overlaps", True
                ),
                avoid_low_liquidity_hours=trending_modules.get("time_filter", {}).get(
                    "avoid_low_liquidity_hours", False
                ),
                pivot_level_tolerance_percent=trending_modules.get(
                    "pivot_points", {}
                ).get("level_tolerance_percent", 0.4),
                pivot_score_bonus_near_level=trending_modules.get(
                    "pivot_points", {}
                ).get("score_bonus_near_level", 1),
                pivot_use_last_n_days=trending_modules.get("pivot_points", {}).get(
                    "use_last_n_days", 3
                ),
                adx_threshold=trending_modules.get("adx_filter", {}).get(
                    "adx_threshold", 22.0
                ),  # 🔥 ОБНОВЛЕНО: 25.0→22.0
                adx_di_difference=trending_modules.get("adx_filter", {}).get(
                    "adx_di_difference", 4.0
                ),  # 🔥 ОБНОВЛЕНО: 7.0→4.0
                vp_score_bonus_in_value_area=trending_modules.get(
                    "volume_profile", {}
                ).get("score_bonus_in_value_area", 1),
                vp_score_bonus_near_poc=trending_modules.get("volume_profile", {}).get(
                    "score_bonus_near_poc", 1
                ),
                vp_poc_tolerance_percent=trending_modules.get("volume_profile", {}).get(
                    "poc_tolerance_percent", 0.4
                ),
                vp_lookback_candles=trending_modules.get("volume_profile", {}).get(
                    "lookback_candles", 100
                ),
                avoid_weekends=trending_modules.get("time_filter", {}).get(
                    "avoid_weekends", True
                ),
            ),
        )

        # RANGING РЕЖИМ
        ranging_cfg = arm_settings.get("ranging", {})
        ranging_indicators = ranging_cfg.get("indicators", {})
        ranging_modules = ranging_cfg.get("modules", {})

        ranging_params = RegimeParameters(
            # Основные параметры
            min_score_threshold=ranging_cfg.get(
                "min_score_threshold", 4
            ),  # 🔥 ОБНОВЛЕНО: 3→4
            max_trades_per_hour=ranging_cfg.get("max_trades_per_hour", 10),
            position_size_multiplier=ranging_cfg.get("position_size_multiplier", 1.0),
            tp_atr_multiplier=ranging_cfg.get(
                "tp_atr_multiplier", 0.9
            ),  # 🔥 ОБНОВЛЕНО: 1.25→0.9
            sl_atr_multiplier=ranging_cfg.get(
                "sl_atr_multiplier", 0.7
            ),  # 🔥 ОБНОВЛЕНО: 1.0→0.7
            max_holding_minutes=ranging_cfg.get(
                "max_holding_minutes", 60
            ),  # 🔥 ОБНОВЛЕНО: 5→60
            cooldown_after_loss_minutes=ranging_cfg.get(
                "cooldown_after_loss_minutes", 5
            ),
            pivot_bonus_multiplier=ranging_cfg.get("pivot_bonus_multiplier", 1.5),
            volume_profile_bonus_multiplier=ranging_cfg.get(
                "volume_profile_bonus_multiplier", 1.5
            ),
            # ✅ Profit Harvesting
            ph_enabled=ranging_cfg.get("ph_enabled", True),
            ph_threshold=ranging_cfg.get(
                "ph_threshold", 0.28
            ),  # 🔥 ОБНОВЛЕНО: 0.20→0.28
            ph_time_limit=ranging_cfg.get("ph_time_limit", 300),  # 🔥 ОБНОВЛЕНО: 120→300
            # ✅ Индикаторы
            indicators=IndicatorParameters(
                rsi_overbought=ranging_indicators.get(
                    "rsi_overbought", 65
                ),  # 🔥 ОБНОВЛЕНО: 70→65
                rsi_oversold=ranging_indicators.get(
                    "rsi_oversold", 35
                ),  # 🔥 ОБНОВЛЕНО: 30→35
                volume_threshold=ranging_indicators.get(
                    "volume_threshold", 1.10
                ),  # 🔥 ОБНОВЛЕНО: 1.1→1.10
                sma_fast=ranging_indicators.get("sma_fast", 10),
                sma_slow=ranging_indicators.get("sma_slow", 30),
                ema_fast=ranging_indicators.get("ema_fast", 10),
                ema_slow=ranging_indicators.get("ema_slow", 30),
                atr_period=ranging_indicators.get("atr_period", 14),
                min_volatility_atr=ranging_indicators.get("min_volatility_atr", 0.0005),
            ),
            # ✅ Модули
            modules=ModuleParameters(
                mtf_block_opposite=ranging_modules.get("multi_timeframe", {}).get(
                    "block_opposite", False
                ),  # 🔥 ОБНОВЛЕНО: True→False
                mtf_score_bonus=ranging_modules.get("multi_timeframe", {}).get(
                    "score_bonus", 2
                ),
                mtf_confirmation_timeframe=ranging_modules.get(
                    "multi_timeframe", {}
                ).get("confirmation_timeframe", "15m"),
                correlation_threshold=ranging_modules.get("correlation_filter", {}).get(
                    "correlation_threshold", 0.7
                ),
                max_correlated_positions=ranging_modules.get(
                    "correlation_filter", {}
                ).get("max_correlated_positions", 2),
                block_same_direction_only=ranging_modules.get(
                    "correlation_filter", {}
                ).get("block_same_direction_only", True),
                prefer_overlaps=ranging_modules.get("time_filter", {}).get(
                    "prefer_overlaps", True
                ),
                avoid_low_liquidity_hours=ranging_modules.get("time_filter", {}).get(
                    "avoid_low_liquidity_hours", True
                ),
                pivot_level_tolerance_percent=ranging_modules.get(
                    "pivot_points", {}
                ).get("level_tolerance_percent", 0.25),
                pivot_score_bonus_near_level=ranging_modules.get(
                    "pivot_points", {}
                ).get("score_bonus_near_level", 2),
                pivot_use_last_n_days=ranging_modules.get("pivot_points", {}).get(
                    "use_last_n_days", 5
                ),
                adx_threshold=ranging_modules.get("adx_filter", {}).get(
                    "adx_threshold", 15.0
                ),
                adx_di_difference=ranging_modules.get("adx_filter", {}).get(
                    "adx_di_difference", 1.5
                ),
                vp_score_bonus_in_value_area=ranging_modules.get(
                    "volume_profile", {}
                ).get("score_bonus_in_value_area", 2),
                vp_score_bonus_near_poc=ranging_modules.get("volume_profile", {}).get(
                    "score_bonus_near_poc", 2
                ),
                vp_poc_tolerance_percent=ranging_modules.get("volume_profile", {}).get(
                    "poc_tolerance_percent", 0.25
                ),
                vp_lookback_candles=ranging_modules.get("volume_profile", {}).get(
                    "lookback_candles", 200
                ),
                avoid_weekends=ranging_modules.get("time_filter", {}).get(
                    "avoid_weekends", True
                ),
            ),
        )

        # CHOPPY РЕЖИМ
        choppy_cfg = arm_settings.get("choppy", {})
        choppy_indicators = choppy_cfg.get("indicators", {})
        choppy_modules = choppy_cfg.get("modules", {})

        choppy_params = RegimeParameters(
            # Основные параметры
            min_score_threshold=choppy_cfg.get(
                "min_score_threshold", 7
            ),  # 🔥 ОБНОВЛЕНО: 5→7
            max_trades_per_hour=choppy_cfg.get("max_trades_per_hour", 4),
            position_size_multiplier=choppy_cfg.get(
                "position_size_multiplier", 0.8
            ),  # 🔥 ОБНОВЛЕНО: 0.6→0.8
            tp_atr_multiplier=choppy_cfg.get(
                "tp_atr_multiplier", 0.7
            ),  # 🔥 ОБНОВЛЕНО: 1.0→0.7
            sl_atr_multiplier=choppy_cfg.get(
                "sl_atr_multiplier", 0.5
            ),  # 🔥 ОБНОВЛЕНО: 0.75→0.5
            max_holding_minutes=choppy_cfg.get(
                "max_holding_minutes", 30
            ),  # 🔥 ОБНОВЛЕНО: 3→30
            cooldown_after_loss_minutes=choppy_cfg.get(
                "cooldown_after_loss_minutes", 10
            ),  # 🔥 ОБНОВЛЕНО: 15→10
            pivot_bonus_multiplier=choppy_cfg.get("pivot_bonus_multiplier", 2.0),
            volume_profile_bonus_multiplier=choppy_cfg.get(
                "volume_profile_bonus_multiplier", 2.0
            ),
            # ✅ Profit Harvesting
            ph_enabled=choppy_cfg.get("ph_enabled", True),
            ph_threshold=choppy_cfg.get("ph_threshold", 0.35),  # 🔥 ОБНОВЛЕНО: 0.20→0.35
            ph_time_limit=choppy_cfg.get("ph_time_limit", 150),  # 🔥 ОБНОВЛЕНО: 120→150
            # ✅ Индикаторы
            indicators=IndicatorParameters(
                rsi_overbought=choppy_indicators.get("rsi_overbought", 65),
                rsi_oversold=choppy_indicators.get("rsi_oversold", 35),
                volume_threshold=choppy_indicators.get("volume_threshold", 1.25),
                sma_fast=choppy_indicators.get("sma_fast", 10),  # 🔥 ОБНОВЛЕНО: 8→10
                sma_slow=choppy_indicators.get("sma_slow", 30),  # 🔥 ОБНОВЛЕНО: 25→30
                ema_fast=choppy_indicators.get("ema_fast", 10),  # 🔥 ОБНОВЛЕНО: 8→10
                ema_slow=choppy_indicators.get("ema_slow", 30),  # 🔥 ОБНОВЛЕНО: 21→30
                atr_period=choppy_indicators.get("atr_period", 14),
                min_volatility_atr=choppy_indicators.get("min_volatility_atr", 0.0004),
            ),
            # ✅ Модули
            modules=ModuleParameters(
                mtf_block_opposite=choppy_modules.get("multi_timeframe", {}).get(
                    "block_opposite", False
                ),
                mtf_score_bonus=choppy_modules.get("multi_timeframe", {}).get(
                    "score_bonus", 2
                ),
                mtf_confirmation_timeframe=choppy_modules.get(
                    "multi_timeframe", {}
                ).get("confirmation_timeframe", "15m"),
                correlation_threshold=choppy_modules.get("correlation_filter", {}).get(
                    "correlation_threshold", 0.6
                ),
                max_correlated_positions=choppy_modules.get(
                    "correlation_filter", {}
                ).get("max_correlated_positions", 1),
                block_same_direction_only=choppy_modules.get(
                    "correlation_filter", {}
                ).get("block_same_direction_only", True),
                prefer_overlaps=choppy_modules.get("time_filter", {}).get(
                    "prefer_overlaps", True
                ),
                avoid_low_liquidity_hours=choppy_modules.get("time_filter", {}).get(
                    "avoid_low_liquidity_hours", True
                ),
                pivot_level_tolerance_percent=choppy_modules.get(
                    "pivot_points", {}
                ).get("level_tolerance_percent", 0.2),
                pivot_score_bonus_near_level=choppy_modules.get("pivot_points", {}).get(
                    "score_bonus_near_level", 3
                ),
                pivot_use_last_n_days=choppy_modules.get("pivot_points", {}).get(
                    "use_last_n_days", 5
                ),
                adx_threshold=choppy_modules.get("adx_filter", {}).get(
                    "adx_threshold", 10.0
                ),
                adx_di_difference=choppy_modules.get("adx_filter", {}).get(
                    "adx_di_difference", 1.0
                ),
                vp_score_bonus_in_value_area=choppy_modules.get(
                    "volume_profile", {}
                ).get("score_bonus_in_value_area", 3),
                vp_score_bonus_near_poc=choppy_modules.get("volume_profile", {}).get(
                    "score_bonus_near_poc", 3
                ),
                vp_poc_tolerance_percent=choppy_modules.get("volume_profile", {}).get(
                    "poc_tolerance_percent", 0.15
                ),
                vp_lookback_candles=choppy_modules.get("volume_profile", {}).get(
                    "lookback_candles", 300
                ),
                avoid_weekends=choppy_modules.get("time_filter", {}).get(
                    "avoid_weekends", True
                ),
            ),
        )

        arm_config = RegimeConfig(
            enabled=True,
            trending_adx_threshold=arm_settings.get("trending_adx_threshold", 20.0),
            ranging_adx_threshold=arm_settings.get("ranging_adx_threshold", 15.0),
            high_volatility_threshold=arm_settings.get(
                "high_volatility_threshold", 0.03
            ),
            low_volatility_threshold=arm_settings.get("low_volatility_threshold", 0.01),
            trend_strength_percent=arm_settings.get("trend_strength_percent", 1.0),
            min_regime_duration_minutes=arm_settings.get(
                "min_regime_duration_minutes", 5
            ),
            required_confirmations=arm_settings.get("required_confirmations", 2),
            trending_params=trending_params,
            ranging_params=ranging_params,
            choppy_params=choppy_params,
        )

        return arm_config

    def _init_telegram(self) -> Optional["TelegramNotifier"]:
        """
        Инициализация Telegram уведомлений.

        Returns:
            TelegramNotifier или None
        """
        telegram_enabled = self.config.__dict__.get("telegram_enabled", False)

        if not telegram_enabled:
            logger.info("⚪ Telegram notifications disabled")
            return None

        try:
            from src.utils.telegram_notifier import TelegramNotifier

            telegram = TelegramNotifier()

            if telegram.enabled:
                logger.info("✅ Telegram notifications enabled")
                return telegram
            else:
                logger.warning("⚠️ Telegram configured but credentials missing")
                return None

        except ImportError:
            logger.warning("⚠️ Telegram module not found - install aiohttp")
            return None
        except Exception as e:
            logger.error(f"❌ Failed to init Telegram: {e}")
            return None

    async def run(self):
        """
        Главный цикл торговли.

        Порядок выполнения:
        1. Проверка rate limit
        2. Обновление рыночных данных
        3. Мониторинг существующих позиций
        4. Генерация новых сигналов (если can_trade)
        5. Исполнение сигналов
        6. Статистика (каждые 60 сек)
        """
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🚀 SCALPING ORCHESTRATOR STARTED")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Получаем стартовый баланс
        await self._init_start_balance()

        while self.active:
            try:
                for symbol in self.config.symbols:
                    await self._process_symbol(symbol)

                # Статистика каждые 60 сек
                await self._log_periodic_stats()

                # Polling interval: 5 секунд
                await asyncio.sleep(5)

            except KeyboardInterrupt:
                logger.info("⚠️ Keyboard interrupt - stopping orchestrator")
                break
            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}", exc_info=True)
                await asyncio.sleep(5)

        logger.info("🛑 Scalping orchestrator stopped")

    async def _init_start_balance(self):
        """Инициализация стартового баланса дня"""
        try:
            balances = await self.client.get_account_balance()
            usdt_balance = next((b.free for b in balances if b.currency == "USDT"), 0.0)
            self.performance_tracker.set_start_balance(usdt_balance)
        except Exception as e:
            logger.error(f"Failed to get start balance: {e}")

    async def _process_symbol(self, symbol: str):
        """
        Обработка одного символа за тик.

        Args:
            symbol: Торговый символ
        """
        logger.debug(f"🔄 TICK START: {symbol}")

        # 1. Rate limit
        await self._check_rate_limit()
        logger.debug(f"   ✔ Rate limit OK")

        # 2. Обновление рыночных данных
        await self._update_market_data(symbol)
        logger.debug(f"   ✔ Market data updated")

        # 3. Получение текущей цены
        try:
            ticker = await self.client.get_ticker(symbol)
            current_price = float(ticker.get("last", 0))
            logger.debug(f"   ✔ Current price: ${current_price:.2f}")
        except Exception as e:
            logger.error(f"Failed to get ticker for {symbol}: {e}")
            return

        # 4. Мониторинг существующих позиций
        if symbol in self.positions:
            logger.debug(f"   ↻ Monitoring existing position...")
            current_prices = {symbol: current_price}
            to_close = await self.position_manager.monitor_positions(
                {symbol: self.positions[symbol]}, current_prices
            )

            for close_symbol, reason in to_close:
                logger.debug(f"   ⚠ Closing position: {reason}")
                await self._close_position(close_symbol, current_price, reason)

                # 🔥 КРИТИЧНО: Удаляем позицию после закрытия!
                if close_symbol in self.positions:
                    del self.positions[close_symbol]
                    logger.info(f"✅ Position removed from tracking: {close_symbol}")

            return  # Если есть позиция - не открываем новую

        # 5. Проверка можно ли торговать
        stats = self.performance_tracker.get_stats()
        can_trade, reason = self.risk_controller.can_trade(
            symbol, self.positions, stats
        )

        if not can_trade:
            logger.debug(f"   🚫 Cannot trade: {reason}")
            return

        logger.debug(f"   ✔ Can trade: {reason}")

        # 6. Генерация сигнала
        market_data = self.market_data_cache.get(symbol)
        if not market_data:
            logger.debug(f"   ⚠ No market data in cache")
            return

        indicators = self.indicators.calculate_all(market_data)
        logger.debug(f"   ✔ Indicators calculated: {len(indicators)} items")

        # Создаем tick объект
        from src.models import Tick

        tick = Tick(
            timestamp=datetime.utcnow(),
            symbol=symbol,
            price=current_price,
            volume=0.0,  # TODO: получать реальный volume
        )

        # ARM обновление (внутри signal_generator)
        if self.modules.get("arm"):
            logger.debug(f"   🧠 Updating ARM regime...")
            await self.signal_generator.update_regime_parameters(
                market_data.ohlcv_data, current_price
            )

        logger.debug(f"   🎯 Generating signal...")
        signal = await self.signal_generator.generate_signal(
            symbol,
            indicators,
            tick,
            self.positions,
            market_data,  # 🆕 Передаем market_data для ADX
        )

        if not signal:
            logger.debug(f"   ⚪ No signal generated")
            return

        logger.info(
            f"   🔔 SIGNAL: {signal.side.value.upper()} | Score: {signal.confidence:.1f}"
        )

        # 7. Исполнение сигнала
        logger.debug(f"   💼 Executing signal...")
        position = await self.order_executor.execute_signal(signal, market_data)

        if position:
            self.positions[symbol] = position
            self.risk_controller.record_trade_opened(symbol)
            logger.info(f"   ✅ Position opened and tracking started")

    async def _close_position(self, symbol: str, current_price: float, reason: str):
        """
        Закрытие позиции.

        Args:
            symbol: Торговый символ
            current_price: Текущая цена
            reason: Причина закрытия
        """
        position = self.positions.get(symbol)
        if not position:
            return

        # Закрываем через PositionManager
        trade_result = await self.position_manager.close_position(
            symbol, position, current_price, reason
        )

        if trade_result:
            # Записываем в статистику
            self.performance_tracker.record_trade(trade_result)

            # Обновляем риск-контроллер
            self.risk_controller.record_trade_closed(trade_result.net_pnl)

            # Удаляем позицию
            del self.positions[symbol]

            logger.info(f"✅ Position removed from tracking: {symbol}")
        else:
            # PHANTOM или ошибка - просто удаляем
            del self.positions[symbol]
            logger.warning(f"⚠️ Position removed without trade result: {symbol}")

    async def _update_market_data(self, symbol: str):
        """Обновление рыночных данных"""
        try:
            candles = await self.client.get_candles(
                symbol, self.config.timeframe, limit=200
            )
            self.market_data_cache[symbol] = MarketData(
                symbol=symbol, timeframe=self.config.timeframe, ohlcv_data=candles
            )
        except Exception as e:
            logger.error(f"Failed to update market data for {symbol}: {e}")

    async def _check_rate_limit(self):
        """Проверка API rate limit"""
        self.api_requests_count += 1

        elapsed = (datetime.utcnow() - self.api_requests_window_start).total_seconds()

        if elapsed >= 60:
            self.api_requests_count = 0
            self.api_requests_window_start = datetime.utcnow()

        elif self.api_requests_count >= self.max_requests_per_minute:
            wait_time = 60 - elapsed
            logger.warning(
                f"⚠️ API rate limit reached "
                f"({self.api_requests_count}/{self.max_requests_per_minute}) - "
                f"waiting {wait_time:.1f}s"
            )
            await asyncio.sleep(wait_time)
            self.api_requests_count = 0
            self.api_requests_window_start = datetime.utcnow()

    async def _log_periodic_stats(self):
        """Периодическое логирование статистики (каждые 60 сек)"""
        # TODO: Добавить периодическое логирование
        pass

    async def emergency_close_all(self):
        """
        🚨 РУЧНОЕ ЗАКРЫТИЕ ВСЕХ ПОЗИЦИЙ

        Использование:
        1. Останови бота (Ctrl+C или stop_bot.bat)
        2. В консоли Python:
           >>> from src.main import BotRunner
           >>> bot = BotRunner(...)
           >>> await bot.strategy.emergency_close_all()

        Или через отдельный скрипт emergency_close.py
        """
        logger.error("🚨 EMERGENCY CLOSE ALL INITIATED!")

        try:
            positions_to_close = list(self.positions.items())

            if not positions_to_close:
                logger.info("⚪ No open positions to close")
                return

            logger.info(f"📊 Closing {len(positions_to_close)} positions...")

            for symbol, position in positions_to_close:
                try:
                    # Получаем текущую цену
                    ticker = await self.client.get_ticker(symbol)
                    current_price = float(ticker.get("last", position.current_price))

                    # Закрываем через PositionManager
                    trade_result = await self.position_manager.close_position(
                        symbol, position, current_price, "emergency_manual"
                    )

                    if trade_result:
                        self.performance_tracker.record_trade(trade_result)
                        logger.info(
                            f"✅ {symbol} closed: NET ${trade_result.net_pnl:.2f}"
                        )

                    # Удаляем из трекинга
                    if symbol in self.positions:
                        del self.positions[symbol]

                except Exception as e:
                    logger.error(f"❌ Failed to close {symbol}: {e}")

            logger.info("🚨 Emergency close completed!")

        except Exception as e:
            logger.critical(f"🚨 Critical error in emergency close: {e}")

    def stop(self):
        """Остановка стратегии"""
        logger.warning("🛑 Stopping Scalping Orchestrator...")
        self.active = False

    def get_performance_stats(self) -> Dict:
        """Получить статистику производительности"""
        return self.performance_tracker.get_stats()
