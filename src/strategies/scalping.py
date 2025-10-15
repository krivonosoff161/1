"""
Scalping trading strategy implementation
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
from loguru import logger

from src.config import RiskConfig, ScalpingConfig
# PHASE 1: Time-Based Filter
from src.filters.time_session_manager import (TimeFilterConfig,
                                              TimeSessionManager)
from src.indicators import (ATR, MACD, RSI, BollingerBands,
                            ExponentialMovingAverage, IndicatorManager,
                            SimpleMovingAverage, VolumeIndicator)
from src.models import (MarketData, OrderSide, OrderType, Position,
                        PositionSide, Signal, Tick)
from src.okx_client import OKXClient
# PHASE 1.5: Adaptive Regime Manager
from src.strategies.modules.adaptive_regime_manager import (
    AdaptiveRegimeManager, IndicatorParameters, ModuleParameters, RegimeConfig,
    RegimeParameters, RegimeType)
# PHASE 1: Balance Checker
from src.strategies.modules.balance_checker import (BalanceCheckConfig,
                                                    BalanceChecker)
# PHASE 1: Correlation Filter
from src.strategies.modules.correlation_filter import (CorrelationFilter,
                                                       CorrelationFilterConfig)
# PHASE 1: Multi-Timeframe Confirmation
from src.strategies.modules.multi_timeframe import (MTFConfig,
                                                    MultiTimeframeFilter)
# PHASE 1: Pivot Points
from src.strategies.modules.pivot_points import (PivotPointsConfig,
                                                 PivotPointsFilter)
# PHASE 1: Volatility Modes
from src.strategies.modules.volatility_adapter import (VolatilityAdapter,
                                                       VolatilityModeConfig)
# PHASE 1: Volume Profile
from src.strategies.modules.volume_profile_filter import (VolumeProfileConfig,
                                                          VolumeProfileFilter)


class ScalpingStrategy:
    """High-frequency scalping strategy"""

    def __init__(
        self, client: OKXClient, config: ScalpingConfig, risk_config: RiskConfig
    ) -> None:
        self.client = client
        self.config = config
        self.risk_config = risk_config
        self.strategy_id = "scalping_v1"

        # Strategy state
        self.active = config.enabled
        self.positions: Dict[str, Position] = {}
        self.pending_orders: Dict[str, str] = {}  # order_id -> symbol
        self.trade_count_hourly = 0
        self.last_trade_time = {}  # symbol -> datetime
        self.last_loss_time = {}  # symbol -> datetime

        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.daily_pnl = 0.0

        # 📊 История сделок для детального логирования
        self.trade_history = []  # Список завершенных сделок
        self.max_history_size = 50  # Храним последние 50 сделок

        # API Rate Limiting (защита от превышения лимитов)
        self.api_requests_count = 0
        self.api_requests_window_start = datetime.utcnow()
        self.max_requests_per_minute = 100  # Безопасный лимит (у нас 30-120/мин)
        self.max_drawdown = 0.0

        # 🛡️ УЛУЧШЕНИЕ 1: Max consecutive losses защита
        self.consecutive_losses = 0
        self.max_consecutive_losses = 3  # Остановка после 3 убытков подряд

        # 💰 УЛУЧШЕНИЕ 2: Daily profit lock
        self.daily_profit_target_percent = 5.0  # 5% от баланса
        self.profit_lock_enabled = True
        self.daily_start_balance = 0.0  # Будет установлен при старте

        # 🚨 КРИТИЧЕСКАЯ ЗАЩИТА: Флаг emergency close (против рекурсии)
        self._emergency_in_progress = False

        # 💰 ЗАЩИТА: Минимальные размеры для операций
        # ВАЖНО: Каждая пара на OKX имеет свой minSz!
        # TODO: Получать реальные minSz через get_instruments()
        self.min_close_value_usd = 70.0  # Минимум $70 для закрытия
        self.min_order_value_usd = 70.0  # Минимум $70 (BTC/ETH пары)

        # 🔒 УЛУЧШЕНИЕ 3: Break-even stop
        self.breakeven_enabled = True
        self.breakeven_trigger_atr = 1.0  # Переводим SL в безубыток после 1 ATR прибыли

        # 🎯 УЛУЧШЕНИЕ 4: Scoring система
        self.scoring_enabled = True
        self.min_score_threshold = (
            7  # ✅ Было: 9 - Минимум 7 баллов из 12 для входа (больше сигналов)
        )

        # 📈 УЛУЧШЕНИЕ 5: Trailing Stop
        self.trailing_stop_enabled = True
        self.trailing_stop_activation_atr = 1.5  # Активация после 1.5 ATR прибыли
        self.trailing_stop_distance_atr = 0.8  # Дистанция trailing SL (0.8 ATR)

        # ⏰ УЛУЧШЕНИЕ 8: Session filtering
        self.session_filtering_enabled = True
        # ✅ ИЗМЕНЕНО: Торговать во ВСЕ активные сессии
        self.trade_overlaps_only = False
        self.trading_sessions = {
            "asian": (0, 9),  # UTC 00:00-09:00
            "european": (7, 16),  # UTC 07:00-16:00
            "american": (13, 22),  # UTC 13:00-22:00
        }
        self.session_overlaps = [
            (7, 9),  # EUR-ASIA overlap (высокая ликвидность)
            (13, 16),  # EUR-USA overlap (максимальная ликвидность)
        ]

        # 🌊 УЛУЧШЕНИЕ 9: Market Regime Detection
        # ✅ ЗАМЕНЕНО НА ARM (Adaptive Regime Manager) - см. adaptive_regime выше

        # 💸 УЛУЧШЕНИЕ 10 (БОНУС): Spread filter
        self.spread_filter_enabled = True
        self.max_spread_percent = 0.1  # Максимум 0.1% спред

        # 🎯 УЛУЧШЕНИЕ 6: Partial Take Profit (многоуровневый выход)
        self.partial_tp_enabled = True
        self.tp_levels = [
            {"percent": 0.5, "atr_multiplier": 1.5},  # 50% позиции на 1.5 ATR
            {"percent": 0.3, "atr_multiplier": 2.5},  # 30% позиции на 2.5 ATR
            {"percent": 0.2, "atr_multiplier": 4.0},  # 20% позиции на 4.0 ATR
        ]
        self.position_partial_info: Dict[str, List[dict]] = {}  # Трекинг частей

        # Setup indicators
        self.indicators = self._setup_indicators()

        # Market data cache
        self.market_data_cache: Dict[str, MarketData] = {}

        # PHASE 1: Multi-Timeframe Confirmation Filter
        self.mtf_filter: Optional[MultiTimeframeFilter] = None
        if (
            hasattr(config, "multi_timeframe_enabled")
            and config.multi_timeframe_enabled
        ):
            mtf_config = MTFConfig(
                confirmation_timeframe=config.multi_timeframe.get(
                    "confirmation_timeframe", "5m"
                ),
                score_bonus=config.multi_timeframe.get("score_bonus", 2),
                block_opposite=config.multi_timeframe.get("block_opposite", True),
                ema_fast_period=config.multi_timeframe.get("ema_fast_period", 8),
                ema_slow_period=config.multi_timeframe.get("ema_slow_period", 21),
                cache_ttl_seconds=config.multi_timeframe.get("cache_ttl_seconds", 30),
            )
            self.mtf_filter = MultiTimeframeFilter(client, mtf_config)
            logger.info("🎯 MTF Filter enabled!")
        else:
            logger.info("⚪ MTF Filter disabled (enable in config.yaml)")

        # PHASE 1: Correlation Filter
        self.correlation_filter: Optional[CorrelationFilter] = None
        if (
            hasattr(config, "correlation_filter_enabled")
            and config.correlation_filter_enabled
        ):
            corr_filter_config = CorrelationFilterConfig(
                enabled=True,
                max_correlated_positions=config.correlation_filter.get(
                    "max_correlated_positions", 1
                ),
                correlation_threshold=config.correlation_filter.get(
                    "correlation_threshold", 0.7
                ),
                block_same_direction_only=config.correlation_filter.get(
                    "block_same_direction_only", True
                ),
            )
            self.correlation_filter = CorrelationFilter(
                client, corr_filter_config, config.symbols
            )
            logger.info("🔗 Correlation Filter enabled!")
        else:
            logger.info("⚪ Correlation Filter disabled (enable in config.yaml)")

        # PHASE 1: Time-Based Filter
        self.time_filter: Optional[TimeSessionManager] = None
        if hasattr(config, "time_filter_enabled") and config.time_filter_enabled:
            time_filter_config = TimeFilterConfig(
                enabled=True,
                trade_asian_session=config.time_filter.get("trade_asian_session", True),
                trade_european_session=config.time_filter.get(
                    "trade_european_session", True
                ),
                trade_american_session=config.time_filter.get(
                    "trade_american_session", True
                ),
                prefer_overlaps=config.time_filter.get("prefer_overlaps", False),
                avoid_low_liquidity_hours=config.time_filter.get(
                    "avoid_low_liquidity_hours", True
                ),
                avoid_weekends=config.time_filter.get("avoid_weekends", True),
            )
            self.time_filter = TimeSessionManager(time_filter_config)
            logger.info("⏰ Time Filter enabled!")
        else:
            logger.info("⚪ Time Filter disabled (enable in config.yaml)")

        # PHASE 1: Volatility Modes
        self.volatility_adapter: Optional[VolatilityAdapter] = None
        if (
            hasattr(config, "volatility_modes_enabled")
            and config.volatility_modes_enabled
        ):
            vol_config = VolatilityModeConfig(
                enabled=True,
                low_volatility_threshold=config.volatility_modes.get(
                    "low_volatility_threshold", 0.01
                ),
                high_volatility_threshold=config.volatility_modes.get(
                    "high_volatility_threshold", 0.02
                ),
                low_vol_sl_multiplier=config.volatility_modes.get(
                    "low_vol_sl_multiplier", 1.5
                ),
                low_vol_tp_multiplier=config.volatility_modes.get(
                    "low_vol_tp_multiplier", 1.0
                ),
                low_vol_score_threshold=config.volatility_modes.get(
                    "low_vol_score_threshold", 6
                ),
                low_vol_position_size_multiplier=config.volatility_modes.get(
                    "low_vol_position_size_multiplier", 1.2
                ),
                normal_vol_sl_multiplier=config.volatility_modes.get(
                    "normal_vol_sl_multiplier", 2.5
                ),
                normal_vol_tp_multiplier=config.volatility_modes.get(
                    "normal_vol_tp_multiplier", 1.5
                ),
                normal_vol_score_threshold=config.volatility_modes.get(
                    "normal_vol_score_threshold", 7
                ),
                normal_vol_position_size_multiplier=config.volatility_modes.get(
                    "normal_vol_position_size_multiplier", 1.0
                ),
                high_vol_sl_multiplier=config.volatility_modes.get(
                    "high_vol_sl_multiplier", 3.5
                ),
                high_vol_tp_multiplier=config.volatility_modes.get(
                    "high_vol_tp_multiplier", 2.5
                ),
                high_vol_score_threshold=config.volatility_modes.get(
                    "high_vol_score_threshold", 8
                ),
                high_vol_position_size_multiplier=config.volatility_modes.get(
                    "high_vol_position_size_multiplier", 0.7
                ),
            )
            self.volatility_adapter = VolatilityAdapter(vol_config)
            logger.info("📊 Volatility Adapter enabled!")
        else:
            logger.info("⚪ Volatility Adapter disabled (enable in config.yaml)")

        # PHASE 1: Pivot Points
        self.pivot_filter: Optional[PivotPointsFilter] = None
        if hasattr(config, "pivot_points_enabled") and config.pivot_points_enabled:
            pivot_config = PivotPointsConfig(
                enabled=True,
                daily_timeframe=config.pivot_points.get("daily_timeframe", "1D"),
                use_last_n_days=config.pivot_points.get("use_last_n_days", 1),
                level_tolerance_percent=config.pivot_points.get(
                    "level_tolerance_percent", 0.003
                ),
                score_bonus_near_level=config.pivot_points.get(
                    "score_bonus_near_level", 1
                ),
                cache_ttl_seconds=config.pivot_points.get("cache_ttl_seconds", 3600),
            )
            self.pivot_filter = PivotPointsFilter(client, pivot_config)
            logger.info("📍 Pivot Points Filter enabled!")
        else:
            logger.info("⚪ Pivot Points Filter disabled (enable in config.yaml)")

        # PHASE 1: Volume Profile
        self.volume_profile_filter: Optional[VolumeProfileFilter] = None
        if hasattr(config, "volume_profile_enabled") and config.volume_profile_enabled:
            vp_config = VolumeProfileConfig(
                enabled=True,
                lookback_timeframe=config.volume_profile.get(
                    "lookback_timeframe", "1H"
                ),
                lookback_candles=config.volume_profile.get("lookback_candles", 100),
                price_buckets=config.volume_profile.get("price_buckets", 50),
                value_area_percent=config.volume_profile.get(
                    "value_area_percent", 70.0
                ),
                score_bonus_in_value_area=config.volume_profile.get(
                    "score_bonus_in_value_area", 1
                ),
                score_bonus_near_poc=config.volume_profile.get(
                    "score_bonus_near_poc", 1
                ),
                poc_tolerance_percent=config.volume_profile.get(
                    "poc_tolerance_percent", 0.005
                ),
                cache_ttl_seconds=config.volume_profile.get("cache_ttl_seconds", 600),
            )
            self.volume_profile_filter = VolumeProfileFilter(client, vp_config)
            logger.info("📊 Volume Profile Filter enabled!")
        else:
            logger.info("⚪ Volume Profile Filter disabled (enable in config.yaml)")

        # PHASE 1: Balance Checker
        self.balance_checker: Optional[BalanceChecker] = None
        if (
            hasattr(config, "balance_checker_enabled")
            and config.balance_checker_enabled
        ):
            balance_config = BalanceCheckConfig(
                enabled=True,
                usdt_reserve_percent=config.balance_checker.get(
                    "usdt_reserve_percent", 10.0
                ),
                min_asset_balance_usd=config.balance_checker.get(
                    "min_asset_balance_usd", 30.0
                ),
                min_usdt_balance=config.balance_checker.get("min_usdt_balance", 30.0),
                log_all_checks=config.balance_checker.get("log_all_checks", False),
            )
            self.balance_checker = BalanceChecker(balance_config)
            logger.info("💰 Balance Checker enabled!")
        else:
            logger.info("⚪ Balance Checker disabled (enable in config.yaml)")

        # PHASE 1.5: Adaptive Regime Manager
        self.adaptive_regime: Optional[AdaptiveRegimeManager] = None
        if (
            hasattr(config, "adaptive_regime_enabled")
            and config.adaptive_regime_enabled
        ):
            # Создаем параметры для каждого режима
            # Параметры индикаторов для TRENDING режима
            trending_indicators = IndicatorParameters(
                rsi_overbought=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("rsi_overbought", 70.0),  # СКАЛЬП: четкие сигналы
                rsi_oversold=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("rsi_oversold", 30.0),  # СКАЛЬП: четкие сигналы
                volume_threshold=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("volume_threshold", 1.05),
                sma_fast=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("sma_fast", 8),
                sma_slow=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("sma_slow", 25),
                ema_fast=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("ema_fast", 8),
                ema_slow=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("ema_slow", 21),
                atr_period=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("atr_period", 14),
                min_volatility_atr=config.adaptive_regime.get("trending", {})
                .get("indicators", {})
                .get("min_volatility_atr", 0.0003),
            )

            # Параметры модулей для TRENDING режима
            trending_modules = ModuleParameters(
                mtf_block_opposite=config.adaptive_regime.get("trending", {})
                .get("modules", {})
                .get("multi_timeframe", {})
                .get("block_opposite", False),
                mtf_score_bonus=config.adaptive_regime["trending"]["modules"][
                    "multi_timeframe"
                ].get("score_bonus", 1),
                mtf_confirmation_timeframe=config.adaptive_regime["trending"][
                    "modules"
                ]["multi_timeframe"].get("confirmation_timeframe", "5m"),
                correlation_threshold=config.adaptive_regime["trending"]["modules"][
                    "correlation_filter"
                ].get("correlation_threshold", 0.8),
                max_correlated_positions=config.adaptive_regime["trending"]["modules"][
                    "correlation_filter"
                ].get("max_correlated_positions", 3),
                block_same_direction_only=config.adaptive_regime["trending"]["modules"][
                    "correlation_filter"
                ].get("block_same_direction_only", False),
                prefer_overlaps=config.adaptive_regime["trending"]["modules"][
                    "time_filter"
                ].get("prefer_overlaps", True),
                avoid_low_liquidity_hours=config.adaptive_regime["trending"]["modules"][
                    "time_filter"
                ].get("avoid_low_liquidity_hours", False),
                avoid_weekends=config.adaptive_regime["trending"]["modules"][
                    "time_filter"
                ].get("avoid_weekends", True),
                pivot_level_tolerance_percent=config.adaptive_regime["trending"][
                    "modules"
                ]["pivot_points"].get("level_tolerance_percent", 0.4),
                pivot_score_bonus_near_level=config.adaptive_regime["trending"][
                    "modules"
                ]["pivot_points"].get("score_bonus_near_level", 1),
                pivot_use_last_n_days=config.adaptive_regime["trending"]["modules"][
                    "pivot_points"
                ].get("use_last_n_days", 3),
                vp_score_bonus_in_value_area=config.adaptive_regime["trending"][
                    "modules"
                ]["volume_profile"].get("score_bonus_in_value_area", 1),
                vp_score_bonus_near_poc=config.adaptive_regime["trending"]["modules"][
                    "volume_profile"
                ].get("score_bonus_near_poc", 1),
                vp_poc_tolerance_percent=config.adaptive_regime["trending"]["modules"][
                    "volume_profile"
                ].get("poc_tolerance_percent", 0.4),
                vp_lookback_candles=config.adaptive_regime["trending"]["modules"][
                    "volume_profile"
                ].get("lookback_candles", 100),
            )

            trending_params = RegimeParameters(
                min_score_threshold=config.adaptive_regime["trending"].get(
                    "min_score_threshold", 6
                ),
                max_trades_per_hour=config.adaptive_regime["trending"].get(
                    "max_trades_per_hour", 20
                ),
                position_size_multiplier=config.adaptive_regime["trending"].get(
                    "position_size_multiplier", 1.2
                ),
                tp_atr_multiplier=config.adaptive_regime["trending"].get(
                    "tp_atr_multiplier", 0.3
                ),
                sl_atr_multiplier=config.adaptive_regime["trending"].get(
                    "sl_atr_multiplier", 0.25
                ),
                max_holding_minutes=config.adaptive_regime["trending"].get(
                    "max_holding_minutes", 5
                ),
                cooldown_after_loss_minutes=config.adaptive_regime["trending"].get(
                    "cooldown_after_loss_minutes", 2
                ),
                pivot_bonus_multiplier=config.adaptive_regime["trending"].get(
                    "pivot_bonus_multiplier", 1.0
                ),
                volume_profile_bonus_multiplier=config.adaptive_regime["trending"].get(
                    "volume_profile_bonus_multiplier", 1.0
                ),
                indicators=trending_indicators,
                modules=trending_modules,
            )

            # Параметры индикаторов для RANGING режима
            ranging_indicators = IndicatorParameters(
                rsi_overbought=config.adaptive_regime["ranging"]["indicators"].get(
                    "rsi_overbought", 70.0
                ),
                rsi_oversold=config.adaptive_regime["ranging"]["indicators"].get(
                    "rsi_oversold", 30.0
                ),
                volume_threshold=config.adaptive_regime["ranging"]["indicators"].get(
                    "volume_threshold", 1.1
                ),
                sma_fast=config.adaptive_regime["ranging"]["indicators"].get(
                    "sma_fast", 10
                ),
                sma_slow=config.adaptive_regime["ranging"]["indicators"].get(
                    "sma_slow", 30
                ),
                ema_fast=config.adaptive_regime["ranging"]["indicators"].get(
                    "ema_fast", 10
                ),
                ema_slow=config.adaptive_regime["ranging"]["indicators"].get(
                    "ema_slow", 30
                ),
                atr_period=config.adaptive_regime["ranging"]["indicators"].get(
                    "atr_period", 14
                ),
                min_volatility_atr=config.adaptive_regime["ranging"]["indicators"].get(
                    "min_volatility_atr", 0.0005
                ),
            )

            # Параметры модулей для RANGING режима
            ranging_modules = ModuleParameters(
                mtf_block_opposite=config.adaptive_regime["ranging"]["modules"][
                    "multi_timeframe"
                ].get("block_opposite", True),
                mtf_score_bonus=config.adaptive_regime["ranging"]["modules"][
                    "multi_timeframe"
                ].get("score_bonus", 2),
                mtf_confirmation_timeframe=config.adaptive_regime["ranging"]["modules"][
                    "multi_timeframe"
                ].get("confirmation_timeframe", "5m"),
                correlation_threshold=config.adaptive_regime["ranging"]["modules"][
                    "correlation_filter"
                ].get("correlation_threshold", 0.7),
                max_correlated_positions=config.adaptive_regime["ranging"]["modules"][
                    "correlation_filter"
                ].get("max_correlated_positions", 2),
                block_same_direction_only=config.adaptive_regime["ranging"]["modules"][
                    "correlation_filter"
                ].get("block_same_direction_only", True),
                prefer_overlaps=config.adaptive_regime["ranging"]["modules"][
                    "time_filter"
                ].get("prefer_overlaps", True),
                avoid_low_liquidity_hours=config.adaptive_regime["ranging"]["modules"][
                    "time_filter"
                ].get("avoid_low_liquidity_hours", True),
                avoid_weekends=config.adaptive_regime["ranging"]["modules"][
                    "time_filter"
                ].get("avoid_weekends", True),
                pivot_level_tolerance_percent=config.adaptive_regime["ranging"][
                    "modules"
                ]["pivot_points"].get("level_tolerance_percent", 0.25),
                pivot_score_bonus_near_level=config.adaptive_regime["ranging"][
                    "modules"
                ]["pivot_points"].get("score_bonus_near_level", 2),
                pivot_use_last_n_days=config.adaptive_regime["ranging"]["modules"][
                    "pivot_points"
                ].get("use_last_n_days", 5),
                vp_score_bonus_in_value_area=config.adaptive_regime["ranging"][
                    "modules"
                ]["volume_profile"].get("score_bonus_in_value_area", 2),
                vp_score_bonus_near_poc=config.adaptive_regime["ranging"]["modules"][
                    "volume_profile"
                ].get("score_bonus_near_poc", 2),
                vp_poc_tolerance_percent=config.adaptive_regime["ranging"]["modules"][
                    "volume_profile"
                ].get("poc_tolerance_percent", 0.25),
                vp_lookback_candles=config.adaptive_regime["ranging"]["modules"][
                    "volume_profile"
                ].get("lookback_candles", 200),
            )

            ranging_params = RegimeParameters(
                min_score_threshold=config.adaptive_regime["ranging"].get(
                    "min_score_threshold", 8
                ),
                max_trades_per_hour=config.adaptive_regime["ranging"].get(
                    "max_trades_per_hour", 10
                ),
                position_size_multiplier=config.adaptive_regime["ranging"].get(
                    "position_size_multiplier", 1.0
                ),
                tp_atr_multiplier=config.adaptive_regime["ranging"].get(
                    "tp_atr_multiplier", 0.25
                ),
                sl_atr_multiplier=config.adaptive_regime["ranging"].get(
                    "sl_atr_multiplier", 0.2
                ),
                max_holding_minutes=config.adaptive_regime["ranging"].get(
                    "max_holding_minutes", 3
                ),
                cooldown_after_loss_minutes=config.adaptive_regime["ranging"].get(
                    "cooldown_after_loss_minutes", 5
                ),
                pivot_bonus_multiplier=config.adaptive_regime["ranging"].get(
                    "pivot_bonus_multiplier", 1.5
                ),
                volume_profile_bonus_multiplier=config.adaptive_regime["ranging"].get(
                    "volume_profile_bonus_multiplier", 1.5
                ),
                indicators=ranging_indicators,
                modules=ranging_modules,
            )

            # Параметры индикаторов для CHOPPY режима
            choppy_indicators = IndicatorParameters(
                rsi_overbought=config.adaptive_regime["choppy"]["indicators"].get(
                    "rsi_overbought", 65.0
                ),
                rsi_oversold=config.adaptive_regime["choppy"]["indicators"].get(
                    "rsi_oversold", 35.0
                ),
                volume_threshold=config.adaptive_regime["choppy"]["indicators"].get(
                    "volume_threshold", 1.25
                ),
                sma_fast=config.adaptive_regime["choppy"]["indicators"].get(
                    "sma_fast", 8
                ),
                sma_slow=config.adaptive_regime["choppy"]["indicators"].get(
                    "sma_slow", 25
                ),
                ema_fast=config.adaptive_regime["choppy"]["indicators"].get(
                    "ema_fast", 8
                ),
                ema_slow=config.adaptive_regime["choppy"]["indicators"].get(
                    "ema_slow", 21
                ),
                atr_period=config.adaptive_regime["choppy"]["indicators"].get(
                    "atr_period", 14
                ),
                min_volatility_atr=config.adaptive_regime["choppy"]["indicators"].get(
                    "min_volatility_atr", 0.0004
                ),
            )

            # Параметры модулей для CHOPPY режима
            choppy_modules = ModuleParameters(
                mtf_block_opposite=config.adaptive_regime["choppy"]["modules"][
                    "multi_timeframe"
                ].get("block_opposite", True),
                mtf_score_bonus=config.adaptive_regime["choppy"]["modules"][
                    "multi_timeframe"
                ].get("score_bonus", 3),
                mtf_confirmation_timeframe=config.adaptive_regime["choppy"]["modules"][
                    "multi_timeframe"
                ].get(
                    "confirmation_timeframe", "15m"
                ),  # 15m для скальпа
                correlation_threshold=config.adaptive_regime["choppy"]["modules"][
                    "correlation_filter"
                ].get("correlation_threshold", 0.6),
                max_correlated_positions=config.adaptive_regime["choppy"]["modules"][
                    "correlation_filter"
                ].get("max_correlated_positions", 1),
                block_same_direction_only=config.adaptive_regime["choppy"]["modules"][
                    "correlation_filter"
                ].get("block_same_direction_only", True),
                prefer_overlaps=config.adaptive_regime["choppy"]["modules"][
                    "time_filter"
                ].get("prefer_overlaps", True),
                avoid_low_liquidity_hours=config.adaptive_regime["choppy"]["modules"][
                    "time_filter"
                ].get("avoid_low_liquidity_hours", True),
                avoid_weekends=config.adaptive_regime["choppy"]["modules"][
                    "time_filter"
                ].get("avoid_weekends", True),
                pivot_level_tolerance_percent=config.adaptive_regime["choppy"][
                    "modules"
                ]["pivot_points"].get(
                    "level_tolerance_percent", 0.2
                ),  # СКАЛЬП: не слишком узко
                pivot_score_bonus_near_level=config.adaptive_regime["choppy"][
                    "modules"
                ]["pivot_points"].get("score_bonus_near_level", 3),
                pivot_use_last_n_days=config.adaptive_regime["choppy"]["modules"][
                    "pivot_points"
                ].get(
                    "use_last_n_days", 5
                ),  # СКАЛЬП: средний период
                vp_score_bonus_in_value_area=config.adaptive_regime["choppy"][
                    "modules"
                ]["volume_profile"].get("score_bonus_in_value_area", 3),
                vp_score_bonus_near_poc=config.adaptive_regime["choppy"]["modules"][
                    "volume_profile"
                ].get("score_bonus_near_poc", 3),
                vp_poc_tolerance_percent=config.adaptive_regime["choppy"]["modules"][
                    "volume_profile"
                ].get("poc_tolerance_percent", 0.15),
                vp_lookback_candles=config.adaptive_regime["choppy"]["modules"][
                    "volume_profile"
                ].get("lookback_candles", 300),
            )

            choppy_params = RegimeParameters(
                min_score_threshold=config.adaptive_regime["choppy"].get(
                    "min_score_threshold", 10
                ),
                max_trades_per_hour=config.adaptive_regime["choppy"].get(
                    "max_trades_per_hour", 4
                ),
                position_size_multiplier=config.adaptive_regime["choppy"].get(
                    "position_size_multiplier", 0.5
                ),
                tp_atr_multiplier=config.adaptive_regime["choppy"].get(
                    "tp_atr_multiplier", 0.2
                ),
                sl_atr_multiplier=config.adaptive_regime["choppy"].get(
                    "sl_atr_multiplier", 0.15
                ),
                max_holding_minutes=config.adaptive_regime["choppy"].get(
                    "max_holding_minutes", 2
                ),
                cooldown_after_loss_minutes=config.adaptive_regime["choppy"].get(
                    "cooldown_after_loss_minutes", 15
                ),
                pivot_bonus_multiplier=config.adaptive_regime["choppy"].get(
                    "pivot_bonus_multiplier", 2.0
                ),
                volume_profile_bonus_multiplier=config.adaptive_regime["choppy"].get(
                    "volume_profile_bonus_multiplier", 2.0
                ),
                indicators=choppy_indicators,
                modules=choppy_modules,
            )

            arm_config = RegimeConfig(
                enabled=True,
                trending_adx_threshold=config.adaptive_regime.get(
                    "trending_adx_threshold", 25.0
                ),
                ranging_adx_threshold=config.adaptive_regime.get(
                    "ranging_adx_threshold", 20.0
                ),
                high_volatility_threshold=config.adaptive_regime.get(
                    "high_volatility_threshold", 0.05
                ),
                low_volatility_threshold=config.adaptive_regime.get(
                    "low_volatility_threshold", 0.02
                ),
                trend_strength_percent=config.adaptive_regime.get(
                    "trend_strength_percent", 2.0
                ),
                min_regime_duration_minutes=config.adaptive_regime.get(
                    "min_regime_duration_minutes", 15
                ),
                required_confirmations=config.adaptive_regime.get(
                    "required_confirmations", 3
                ),
                trending_params=trending_params,
                ranging_params=ranging_params,
                choppy_params=choppy_params,
            )
            self.adaptive_regime = AdaptiveRegimeManager(arm_config)
            logger.info("🧠 Adaptive Regime Manager enabled!")

            # Инициализируем параметры для текущего режима
            initial_regime_params = self.adaptive_regime.get_current_parameters()
            self.current_indicator_params = initial_regime_params.indicators
            self.current_module_params = initial_regime_params.modules
            self.current_regime_type = self.adaptive_regime.current_regime
            regime_name = self.current_regime_type.value.upper()
            logger.info(f"📊 Initial regime parameters loaded: {regime_name}")
        else:
            logger.info("⚪ ARM disabled (enable in config.yaml)")

        # Загружаем Partial TP конфигурацию
        if hasattr(config, "partial_tp_enabled") and config.partial_tp_enabled:
            self.partial_tp_enabled = True
            if hasattr(config, "partial_tp_levels"):
                self.tp_levels = [
                    {
                        "percent": level.get("percent", 50) / 100.0,
                        "atr_multiplier": level.get("atr_multiplier", 1.5),
                    }
                    for level in config.partial_tp_levels
                ]
            logger.info(
                f"📊 Partial TP enabled: {len(self.tp_levels)} levels configured"
            )

        # Инициализируем переменные для отслеживания текущих параметров
        self.current_indicator_params = None
        self.current_module_params = None
        self.current_regime_type = None
        self.regime_switches = {}  # Статистика переключений режимов

        logger.info(f"Scalping strategy initialized for symbols: {config.symbols}")

    def _setup_indicators(self) -> IndicatorManager:
        """
        Настройка технических индикаторов для скальпинговой стратегии.

        Инициализирует набор технических индикаторов, включая:
        - Скользящие средние (SMA и EMA)
        - RSI для определения перекупленности/перепроданности
        - ATR для измерения волатильности
        - Bollinger Bands для определения границ цены
        - Volume индикатор для подтверждения силы движения

        Returns:
            IndicatorManager: Менеджер с инициализированными индикаторами
        """
        manager = IndicatorManager()

        # Moving Averages
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

        # Momentum indicators
        manager.add_indicator(
            "RSI",
            RSI(
                self.config.indicators.rsi_period,
                self.config.entry.rsi_overbought,
                self.config.entry.rsi_oversold,
            ),
        )

        # Volatility indicators
        manager.add_indicator("ATR", ATR(self.config.indicators.atr_period))
        manager.add_indicator(
            "BB",
            BollingerBands(
                self.config.indicators.bollinger_period,
                self.config.indicators.bollinger_std,
            ),
        )

        # Volume indicator
        manager.add_indicator(
            "VOLUME", VolumeIndicator(20, self.config.entry.volume_threshold)
        )

        # 📊 УЛУЧШЕНИЕ 7: MACD индикатор
        manager.add_indicator(
            "MACD", MACD(fast_period=12, slow_period=26, signal_period=9)
        )

        return manager

    async def update_indicator_parameters(
        self, indicator_params: IndicatorParameters
    ) -> None:
        """
        Динамически обновляет параметры индикаторов для текущего режима рынка.

        Args:
            indicator_params: Новые параметры индикаторов
        """
        try:
            logger.info("🔄 Updating indicator parameters...")

            # Обновляем RSI параметры
            if (
                hasattr(self.indicators, "indicators")
                and "RSI" in self.indicators.indicators
            ):
                rsi_indicator = self.indicators.indicators["RSI"]
                rsi_indicator.overbought_level = indicator_params.rsi_overbought
                rsi_indicator.oversold_level = indicator_params.rsi_oversold
                rsi_os = indicator_params.rsi_oversold
                rsi_ob = indicator_params.rsi_overbought
                logger.debug(f"   RSI levels: {rsi_os}/{rsi_ob}")

            # Обновляем Volume threshold
            if (
                hasattr(self.indicators, "indicators")
                and "VOLUME" in self.indicators.indicators
            ):
                volume_indicator = self.indicators.indicators["VOLUME"]
                volume_indicator.threshold = indicator_params.volume_threshold
                logger.debug(
                    f"   Volume threshold: {indicator_params.volume_threshold}"
                )

            # Обновляем ATR период (требует пересоздания индикатора)
            if (
                hasattr(self.indicators, "indicators")
                and "ATR" in self.indicators.indicators
            ):
                current_atr = self.indicators.indicators["ATR"]
                if current_atr.period != indicator_params.atr_period:
                    # Создаем новый ATR с новым периодом
                    old_period = current_atr.period
                    new_period = indicator_params.atr_period
                    new_atr = ATR(new_period)
                    self.indicators.indicators["ATR"] = new_atr
                    logger.debug(
                        f"   ✅ ATR period updated: {old_period} → {new_period}"
                    )

            # Обновляем SMA периоды (требует пересоздания индикаторов)
            if hasattr(self.indicators, "indicators"):
                # SMA Fast
                if "SMA_FAST" in self.indicators.indicators:
                    current_sma = self.indicators.indicators["SMA_FAST"]
                    if current_sma.period != indicator_params.sma_fast:
                        old_p = current_sma.period
                        new_p = indicator_params.sma_fast
                        new_sma = SimpleMovingAverage(new_p)
                        self.indicators.indicators["SMA_FAST"] = new_sma
                        logger.debug(f"   ✅ SMA Fast period updated: {old_p} → {new_p}")

                # SMA Slow
                if "SMA_SLOW" in self.indicators.indicators:
                    current_sma = self.indicators.indicators["SMA_SLOW"]
                    if current_sma.period != indicator_params.sma_slow:
                        old_p = current_sma.period
                        new_p = indicator_params.sma_slow
                        new_sma = SimpleMovingAverage(new_p)
                        self.indicators.indicators["SMA_SLOW"] = new_sma
                        logger.debug(f"   ✅ SMA Slow period updated: {old_p} → {new_p}")

                # EMA Fast
                if "EMA_FAST" in self.indicators.indicators:
                    current_ema = self.indicators.indicators["EMA_FAST"]
                    if current_ema.period != indicator_params.ema_fast:
                        old_p = current_ema.period
                        new_p = indicator_params.ema_fast
                        new_ema = ExponentialMovingAverage(new_p)
                        self.indicators.indicators["EMA_FAST"] = new_ema
                        logger.debug(f"   ✅ EMA Fast period updated: {old_p} → {new_p}")

                # EMA Slow
                if "EMA_SLOW" in self.indicators.indicators:
                    current_ema = self.indicators.indicators["EMA_SLOW"]
                    if current_ema.period != indicator_params.ema_slow:
                        old_p = current_ema.period
                        new_p = indicator_params.ema_slow
                        new_ema = ExponentialMovingAverage(new_p)
                        self.indicators.indicators["EMA_SLOW"] = new_ema
                        logger.debug(f"   ✅ EMA Slow period updated: {old_p} → {new_p}")

            # Сохраняем текущие параметры для использования в скоринге
            self.current_indicator_params = indicator_params

            logger.info("✅ Indicator parameters updated successfully")

        except Exception as e:
            logger.error(f"❌ Error updating indicator parameters: {e}")
            raise

    async def update_module_parameters(self, module_params: ModuleParameters) -> None:
        """
        Динамически обновляет параметры модулей для текущего режима рынка.

        Args:
            module_params: Новые параметры модулей
        """
        try:
            logger.info("🔄 Updating module parameters...")

            # Обновляем MTF параметры
            if hasattr(self, "mtf_filter") and self.mtf_filter:
                self.mtf_filter.config.block_opposite = module_params.mtf_block_opposite
                self.mtf_filter.config.score_bonus = module_params.mtf_score_bonus
                self.mtf_filter.config.confirmation_timeframe = (
                    module_params.mtf_confirmation_timeframe
                )
                block_opp = module_params.mtf_block_opposite
                bonus = module_params.mtf_score_bonus
                logger.debug(f"   MTF: block_opposite={block_opp}, bonus={bonus}")

            # Обновляем Correlation Filter параметры
            if hasattr(self, "correlation_filter") and self.correlation_filter:
                self.correlation_filter.config.correlation_threshold = (
                    module_params.correlation_threshold
                )
                self.correlation_filter.config.max_correlated_positions = (
                    module_params.max_correlated_positions
                )
                self.correlation_filter.config.block_same_direction_only = (
                    module_params.block_same_direction_only
                )
                thresh = module_params.correlation_threshold
                max_pos = module_params.max_correlated_positions
                logger.debug(
                    f"   Correlation: threshold={thresh}, max_positions={max_pos}"
                )

            # Обновляем Time Filter параметры
            if hasattr(self, "time_filter") and self.time_filter:
                self.time_filter.config.prefer_overlaps = module_params.prefer_overlaps
                self.time_filter.config.avoid_low_liquidity_hours = (
                    module_params.avoid_low_liquidity_hours
                )
                if hasattr(module_params, "avoid_weekends"):
                    self.time_filter.config.avoid_weekends = (
                        module_params.avoid_weekends
                    )
                pref_ovr = module_params.prefer_overlaps
                avoid_low = module_params.avoid_low_liquidity_hours
                logger.debug(
                    f"   Time Filter: prefer_overlaps={pref_ovr}, "
                    f"avoid_low_liquidity={avoid_low}"
                )

            # Обновляем Pivot Points параметры
            if hasattr(self, "pivot_filter") and self.pivot_filter:
                self.pivot_filter.config.level_tolerance_percent = (
                    module_params.pivot_level_tolerance_percent
                )
                self.pivot_filter.config.score_bonus_near_level = (
                    module_params.pivot_score_bonus_near_level
                )
                self.pivot_filter.config.use_last_n_days = (
                    module_params.pivot_use_last_n_days
                )
                tol = module_params.pivot_level_tolerance_percent
                bonus = module_params.pivot_score_bonus_near_level
                logger.debug(f"   Pivot Points: tolerance={tol}%, bonus={bonus}")

            # Обновляем Volume Profile параметры
            if hasattr(self, "volume_profile_filter") and self.volume_profile_filter:
                self.volume_profile_filter.config.score_bonus_in_value_area = (
                    module_params.vp_score_bonus_in_value_area
                )
                self.volume_profile_filter.config.score_bonus_near_poc = (
                    module_params.vp_score_bonus_near_poc
                )
                self.volume_profile_filter.config.poc_tolerance_percent = (
                    module_params.vp_poc_tolerance_percent
                )
                self.volume_profile_filter.config.lookback_candles = (
                    module_params.vp_lookback_candles
                )
                va_bonus = module_params.vp_score_bonus_in_value_area
                poc_bonus = module_params.vp_score_bonus_near_poc
                logger.debug(
                    f"   Volume Profile: value_area_bonus={va_bonus}, "
                    f"poc_bonus={poc_bonus}"
                )

            # Сохраняем текущие параметры
            self.current_module_params = module_params

            logger.info("✅ Module parameters updated successfully")

        except Exception as e:
            logger.error(f"❌ Error updating module parameters: {e}")
            raise

    async def switch_regime_parameters(self, regime_type: RegimeType) -> None:
        """
        Переключает параметры на новый режим рынка.

        Управляет переходными состояниями при смене режима.

        Args:
            regime_type: Новый тип режима рынка
        """
        try:
            if not hasattr(self, "adaptive_regime") or not self.adaptive_regime:
                logger.warning("⚠️ ARM not available, cannot switch regime parameters")
                return

            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info("🔄 REGIME TRANSITION STARTED")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            old_name = (
                self.current_regime_type.value.upper()
                if self.current_regime_type
                else "N/A"
            )
            logger.info(f"   Old regime: {old_name}")
            logger.info(f"   New regime: {regime_type.value.upper()}")

            # ЭТАП 1: Анализ текущих позиций
            open_positions_count = len(self.positions)
            if open_positions_count > 0:
                logger.info(f"📊 Found {open_positions_count} open positions:")
                for symbol, position in self.positions.items():
                    side = position.side
                    size = position.size
                    entry = position.entry_price
                    logger.info(
                        f"   {symbol}: {side} | Size: {size} | Entry: ${entry:.2f}"
                    )
                logger.info(
                    "   ✅ Keeping existing positions with current TP/SL "
                    "(no changes on the fly)"
                )
            else:
                logger.info("📊 No open positions found")

            # ЭТАП 2: Получаем параметры для нового режима
            regime_params = self.adaptive_regime.get_current_parameters()

            logger.info(f"⚙️ Loading {regime_type.value.upper()} regime parameters...")

            # ЭТАП 3: Обновляем параметры индикаторов
            logger.info("   🔧 Updating indicator parameters...")
            await self.update_indicator_parameters(regime_params.indicators)

            # ЭТАП 4: Обновляем параметры модулей
            logger.info("   🔧 Updating module parameters...")
            await self.update_module_parameters(regime_params.modules)

            # ЭТАП 5: Обновляем торговые параметры
            logger.info("   🔧 Updating trading parameters...")
            old_regime_type = self.current_regime_type
            self.current_regime_type = regime_type

            # ЭТАП 6: Логируем изменения ключевых параметров
            logger.info("📋 Parameter changes:")
            if old_regime_type and hasattr(
                self.adaptive_regime.config, f"{old_regime_type.value}_params"
            ):
                old_params = getattr(
                    self.adaptive_regime.config, f"{old_regime_type.value}_params"
                )
                logger.info(
                    f"   Score threshold: {old_params.min_score_threshold} → "
                    f"{regime_params.min_score_threshold}"
                )
                logger.info(
                    f"   Max trades/hour: {old_params.max_trades_per_hour} → "
                    f"{regime_params.max_trades_per_hour}"
                )
                old_mult = old_params.position_size_multiplier
                new_mult = regime_params.position_size_multiplier
                logger.info(f"   Position multiplier: {old_mult}x → {new_mult}x")
                logger.info(
                    f"   TP multiplier: {old_params.tp_atr_multiplier} → "
                    f"{regime_params.tp_atr_multiplier} ATR"
                )
                logger.info(
                    f"   SL multiplier: {old_params.sl_atr_multiplier} → "
                    f"{regime_params.sl_atr_multiplier} ATR"
                )

                # Индикаторы
                if hasattr(old_params, "indicators"):
                    old_rsi = f"{old_params.indicators.rsi_oversold}/{old_params.indicators.rsi_overbought}"
                    new_rsi = f"{regime_params.indicators.rsi_oversold}/{regime_params.indicators.rsi_overbought}"
                    logger.info(f"   RSI levels: {old_rsi} → {new_rsi}")

                    old_vol = old_params.indicators.volume_threshold
                    new_vol = regime_params.indicators.volume_threshold
                    logger.info(f"   Volume threshold: {old_vol} → {new_vol}")

                    old_sma = f"{old_params.indicators.sma_fast}/{old_params.indicators.sma_slow}"
                    new_sma = f"{regime_params.indicators.sma_fast}/{regime_params.indicators.sma_slow}"
                    logger.info(f"   SMA periods: {old_sma} → {new_sma}")

            # ЭТАП 7: Переходные состояния для новых ордеров
            logger.info("🔄 Transition state management:")
            logger.info("   ✅ Existing positions: Keep current TP/SL")
            logger.info("   ✅ New positions: Use new regime parameters")
            logger.info("   ✅ Cooldowns: Preserved from previous regime")

            # ЭТАП 8: Обновляем статистику переключений
            if not hasattr(self, "regime_switches"):
                self.regime_switches = {}

            old_val = old_regime_type.value if old_regime_type else "initial"
            transition_key = f"{old_val}_to_{regime_type.value}"
            self.regime_switches[transition_key] = (
                self.regime_switches.get(transition_key, 0) + 1
            )

            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"✅ REGIME TRANSITION COMPLETED: {regime_type.value.upper()}")
            logger.info(
                f"   Transition count: {self.regime_switches.get(transition_key, 1)}"
            )
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        except Exception as e:
            logger.error(f"❌ Error during regime transition: {e}")
            # В случае ошибки, сохраняем старый режим
            if hasattr(self, "current_regime_type") and old_regime_type:
                self.current_regime_type = old_regime_type
                logger.error(
                    f"🔄 Reverted to previous regime: {old_regime_type.value.upper()}"
                )
            raise

    def log_regime_statistics(self) -> None:
        """Логирует статистику переключений режимов."""
        if not hasattr(self, "regime_switches") or not self.regime_switches:
            logger.info("📊 No regime switches recorded")
            return

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("📊 REGIME SWITCHING STATISTICS")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        total_switches = sum(self.regime_switches.values())
        logger.info(f"   Total regime switches: {total_switches}")

        for transition, count in sorted(self.regime_switches.items()):
            percentage = (count / total_switches) * 100 if total_switches > 0 else 0
            logger.info(f"   {transition}: {count} times ({percentage:.1f}%)")

        # Анализ наиболее частых переходов
        if self.regime_switches:
            most_common = max(self.regime_switches.items(), key=lambda x: x[1])
            logger.info(
                f"   Most common transition: {most_common[0]} ({most_common[1]} times)"
            )

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    async def run(self) -> None:
        """Main strategy execution loop"""
        logger.info("Starting scalping strategy")

        try:
            # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА: Проверка режима торговли (SPOT только!)
            try:
                account_config = await self.client.get_account_config()
                acct_level = account_config.get("acctLv", "1")

                if acct_level != "1":  # '1' = Simple (SPOT only)
                    logger.error(
                        f"⛔ MARGIN MODE DETECTED (acctLv={acct_level})! "
                        f"This bot is designed for SPOT trading ONLY!"
                    )
                    logger.error(
                        "📋 INSTRUCTIONS TO FIX:"
                        "\n  1. Go to OKX → Settings → Trading Preferences"
                        "\n  2. Set Portfolio Mode to 'Simple' or 'SPOT'"
                        "\n  3. Repay all borrowed funds (if any)"
                        "\n  4. Restart bot"
                    )
                    raise ValueError("Bot cannot start in MARGIN mode! Switch to SPOT!")

                logger.info("✅ Trading mode verified: SPOT (Simple)")
            except ValueError:
                raise  # Пробрасываем ошибку режима дальше
            except Exception as e:
                logger.warning(f"⚠️ Could not verify trading mode: {e}")
                logger.warning("⚠️ Assuming SPOT mode - VERIFY MANUALLY on exchange!")

            # 💰 УЛУЧШЕНИЕ 2: Установка начального баланса для daily profit lock
            balances = await self.client.get_account_balance()
            if balances:
                # ТОЛЬКО USDT баланс для контроля прибыли/убытков
                usdt_balance = next((b for b in balances if b.currency == "USDT"), None)
                if usdt_balance:
                    self.daily_start_balance = usdt_balance.total
                    balance = self.daily_start_balance
                    logger.info(f"💼 Daily start balance (USDT only): ${balance:.2f}")
                else:
                    logger.warning(
                        "⚠️ USDT balance not found, daily profit lock disabled"
                    )
                    self.daily_start_balance = 0.0

            # Create tasks for each symbol
            tasks = []
            for symbol in self.config.symbols:
                task = asyncio.create_task(self._trade_symbol(symbol))
                tasks.append(task)

            # Add monitoring task
            monitor_task = asyncio.create_task(self._monitor_positions())
            tasks.append(monitor_task)

            # Wait for all tasks
            await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Strategy execution error: {e}")
            await self._emergency_close_all()

    async def _trade_symbol(self, symbol: str) -> None:
        """
        Торговля конкретным символом с опросом каждые 15 секунд.

        Использует polling с rate limiting для защиты от превышения API лимитов.
        Обеспечивает быструю реакцию на изменения рынка (4x быстрее).
        """
        logger.info(f"🎯 Starting scalping for {symbol} (polling mode, 5s intervals)")

        try:
            # Получаем начальные рыночные данные
            await self._update_market_data(symbol)
            logger.info(f"✅ {symbol}: Initial market data loaded")

            # Polling loop - опрос каждые 5 секунд (реалистичный скальпинг)
            while self.active:
                try:
                    # Проверяем API rate limiting
                    await self._check_rate_limit()

                    # Обновляем рыночные данные (свечи)
                    await self._update_market_data(symbol)

                    # Получаем текущую цену (тикер)
                    ticker = await self.client.get_ticker(symbol)
                    current_price = float(ticker["last"])

                    # Создаем tick объект
                    tick = Tick(
                        symbol=symbol,
                        price=current_price,
                        volume=float(ticker.get("vol24h", 0)),
                        timestamp=datetime.utcnow(),
                    )

                    # Обрабатываем тик
                    await self._process_tick(symbol, tick)

                except Exception as e:
                    logger.error(f"❌ Error processing {symbol}: {e}")

                # Ждем 5 секунд до следующего опроса (реалистичный скальпинг)
                await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"❌ Fatal error trading {symbol}: {e}")

    async def _check_rate_limit(self) -> None:
        """
        Проверка и контроль API rate limiting.

        Защищает от превышения лимитов OKX API:
        - Public endpoints: 120 запросов/секунда
        - Private endpoints: 20 запросов/секунда
        """
        current_time = datetime.utcnow()

        # Сброс счетчика каждую минуту
        if (current_time - self.api_requests_window_start).seconds >= 60:
            self.api_requests_count = 0
            self.api_requests_window_start = current_time

        # Проверка лимита
        if self.api_requests_count >= self.max_requests_per_minute:
            wait_seconds = 60 - (current_time - self.api_requests_window_start).seconds
            if wait_seconds > 0:
                logger.warning(
                    f"⏰ Rate limit reached ({self.api_requests_count}/{self.max_requests_per_minute}). Waiting {wait_seconds}s..."
                )
                await asyncio.sleep(wait_seconds)
                self.api_requests_count = 0
                self.api_requests_window_start = datetime.utcnow()

        # Увеличиваем счетчик
        self.api_requests_count += 1

    async def _update_market_data(self, symbol: str) -> None:
        """
        Обновление рыночных данных для торгового символа.

        Загружает последние OHLCV данные с биржи и обновляет кэш
        рыночных данных для использования в индикаторах и генерации сигналов.

        Args:
            symbol: Торговый символ (например, "BTC-USDT")

        Raises:
            Exception: При ошибках получения данных с биржи
        """
        try:
            ohlcv_data = await self.client.get_market_data(
                symbol, self.config.timeframe, 100  # Get enough data for indicators
            )

            # Create MarketData object
            market_data = MarketData(
                symbol=symbol, timeframe=self.config.timeframe, ohlcv_data=ohlcv_data
            )

            self.market_data_cache[symbol] = market_data

        except Exception as e:
            logger.error(f"Error updating market data for {symbol}: {e}")

    async def _process_tick(self, symbol: str, tick) -> None:
        """
        Обработка входящего тика рыночных данных.

        Анализирует текущий тик, вычисляет технические индикаторы,
        генерирует торговые сигналы и обновляет существующие позиции.

        Args:
            symbol: Торговый символ
            tick: Объект тика с текущими рыночными данными

        Raises:
            Exception: При критических ошибках обработки
        """
        try:
            # Check if we have enough market data
            if symbol not in self.market_data_cache:
                return

            market_data = self.market_data_cache[symbol]
            market_data.current_tick = tick

            # 💸 УЛУЧШЕНИЕ 10: Spread filter
            if self.spread_filter_enabled and tick.bid and tick.ask:
                spread = (tick.ask - tick.bid) / tick.bid
                spread_percent = spread * 100

                if spread_percent > self.max_spread_percent:
                    logger.debug(
                        f"Spread too wide for {symbol}: {spread_percent:.3f}% "
                        f"(max: {self.max_spread_percent}%)"
                    )
                    return  # Пропускаем этот тик

            # Периодический вывод статистики (каждые 30 секунд)
            current_time = datetime.utcnow()
            if not hasattr(self, "_last_status_time"):
                self._last_status_time = {}

            if (
                symbol not in self._last_status_time
                or (current_time - self._last_status_time[symbol]).total_seconds() >= 30
            ):
                await self._log_trading_status(symbol, tick)
                self._last_status_time[symbol] = current_time

            # Calculate indicators
            indicator_results = self.indicators.calculate_all(market_data)

            # Debug: показываем ключевые индикаторы
            rsi = indicator_results.get("RSI")
            atr = indicator_results.get("ATR")
            if rsi and atr:
                logger.debug(
                    f"📈 {symbol} Indicators: RSI={rsi.value:.2f}, ATR={atr.value:.6f}"
                )

            # Check for trading opportunity
            signal = await self._generate_signal(symbol, indicator_results, tick)

            if signal:
                await self._execute_signal(signal)

            # Update existing positions
            await self._update_position_prices(symbol, tick.price)

        except Exception as e:
            logger.error(f"Error processing tick for {symbol}: {e}")

    async def _generate_signal(
        self, symbol: str, indicators: Dict, tick
    ) -> Optional[Signal]:
        """Generate trading signal based on indicators"""

        # Check rate limiting
        if not self._can_trade(symbol):
            logger.debug(f"🚫 {symbol}: Cannot trade (rate limit or restrictions)")
            return None

        # Get indicator values
        sma_fast = indicators.get("SMA_FAST")
        sma_slow = indicators.get("SMA_SLOW")
        ema_fast = indicators.get("EMA_FAST")
        ema_slow = indicators.get("EMA_SLOW")
        rsi = indicators.get("RSI")
        atr = indicators.get("ATR")
        bb = indicators.get("BB")
        volume = indicators.get("VOLUME")
        macd = indicators.get("MACD")  # 📊 УЛУЧШЕНИЕ 7

        # Проверка наличия всех индикаторов
        required_indicators = [
            sma_fast,
            sma_slow,
            ema_fast,
            ema_slow,
            rsi,
            atr,
            bb,
            volume,
            macd,
        ]
        if not all(required_indicators):
            missing = []
            if not sma_fast:
                missing.append("SMA_FAST")
            if not sma_slow:
                missing.append("SMA_SLOW")
            if not ema_fast:
                missing.append("EMA_FAST")
            if not ema_slow:
                missing.append("EMA_SLOW")
            if not rsi:
                missing.append("RSI")
            if not atr:
                missing.append("ATR")
            if not bb:
                missing.append("BB")
            if not volume:
                missing.append("VOLUME")
            if not macd:
                missing.append("MACD")
            logger.debug(f"🚫 {symbol}: Missing indicators: {', '.join(missing)}")
            return None

        current_price = tick.price

        # Check minimum volatility (ARM может перекрыть!)
        min_volatility = self.config.entry.min_volatility_atr
        if self.current_indicator_params:
            min_volatility = self.current_indicator_params.min_volatility_atr

        if atr.value < min_volatility:
            # Детальная диагностика для ATR = 0
            if atr.value == 0.0:
                error_info = atr.metadata.get("error", "Unknown reason")
                warning_info = atr.metadata.get("warning", "")
                logger.warning(f"🚫 {symbol}: ATR is ZERO! {error_info} {warning_info}")
                if "sample_prices" in atr.metadata:
                    logger.debug(f"   Sample prices: {atr.metadata['sample_prices']}")
            else:
                logger.debug(
                    f"🚫 {symbol}: Low volatility: ATR={atr.value:.6f} "
                    f"(min={min_volatility})"
                )
            return None

        # 🛡️ Market Regime контролируется ARM (Adaptive Regime Manager)
        # ARM автоматически переключает min_score_threshold и другие параметры

        # 🎯 УЛУЧШЕНИЕ 4: Scoring система с взвешенными баллами
        if self.scoring_enabled:
            # Long сигнал - присваиваем баллы с разными весами
            long_score = 0

            # SMA Trend (1 балл - быстрая, может быть шумной)
            long_score += 1 if (current_price > sma_fast.value > sma_slow.value) else 0

            # EMA Trend (2 балла - стабильнее чем SMA)
            long_score += 2 if ema_fast.value > ema_slow.value else 0

            # RSI (3-4 балла - ВАЖНЫЙ индикатор! + confluence bonus)
            # Используем динамические параметры RSI если доступны
            rsi_oversold = (
                self.current_indicator_params.rsi_oversold
                if self.current_indicator_params
                else self.config.entry.rsi_oversold
            )
            rsi_overbought = (
                self.current_indicator_params.rsi_overbought
                if self.current_indicator_params
                else self.config.entry.rsi_overbought
            )

            # 🎯 ГАРМОНИЗАЦИЯ: Зональная логика RSI
            # Extreme zone (очень сильный сигнал)
            if rsi.value <= (rsi_oversold - 5):  # Например <25 для RANGING
                long_score += 4  # EXTREME! +1 bonus
            # Strong zone (сильный сигнал)
            elif rsi.value <= rsi_oversold:  # Перепродано
                long_score += 3  # Стандарт
            # Weak zone (слабый сигнал)
            elif rsi.value <= (rsi_oversold + 10):
                long_score += 2
            # Neutral-bullish
            elif rsi.value <= (rsi_oversold + 20):
                long_score += 1

            # Bollinger Bands (2 балла - хорошее подтверждение)
            long_score += 2 if current_price <= bb.metadata["lower_band"] * 1.002 else 0

            # Volume (2 балла - важное подтверждение силы)
            volume_threshold = (
                self.current_indicator_params.volume_threshold
                if self.current_indicator_params
                else self.config.entry.volume_threshold
            )
            long_score += 2 if volume.value >= volume_threshold else 0

            # MACD (2 балла - надежный индикатор)
            macd_line = macd.metadata.get("macd_line", 0)
            macd_signal = macd.metadata.get("signal_line", 0)
            long_score += 2 if (macd_line > macd_signal and macd_line > 0) else 0

            # Short сигнал - присваиваем баллы с разными весами
            short_score = 0

            # SMA Trend (1 балл)
            short_score += 1 if (current_price < sma_fast.value < sma_slow.value) else 0

            # EMA Trend (2 балла)
            short_score += 2 if ema_fast.value < ema_slow.value else 0

            # RSI (3-4 балла - ВАЖНЫЙ! + confluence bonus)
            # Используем те же динамические параметры RSI
            # 🎯 ГАРМОНИЗАЦИЯ: Зональная логика RSI для SHORT
            if rsi.value >= (rsi_overbought + 5):  # Extreme overbought
                short_score += 4  # EXTREME! +1 bonus
            elif rsi.value >= rsi_overbought:  # Strong overbought
                short_score += 3  # Стандарт
            elif rsi.value >= (rsi_overbought - 10):  # Weak overbought
                short_score += 2
            elif rsi.value >= (rsi_overbought - 20):  # Neutral-bearish
                short_score += 1

            # Bollinger Bands (2 балла)
            short_score += (
                2 if current_price >= bb.metadata["upper_band"] * 0.998 else 0
            )

            # Volume (2 балла)
            short_score += 2 if volume.value >= volume_threshold else 0

            # MACD (2 балла)
            short_score += 2 if (macd_line < macd_signal and macd_line < 0) else 0

            # Расчёт confidence (0.0 - 1.0)
            long_confidence = long_score / 12.0  # Максимум 12 баллов (с MACD)
            short_confidence = short_score / 12.0

            # Проверка существующей позиции
            existing_position = self.positions.get(symbol)
            if existing_position:
                if existing_position.side == PositionSide.LONG and short_score > 0:
                    return None
                if existing_position.side == PositionSide.SHORT and long_score > 0:
                    return None

            # PHASE 1.5: ARM - адаптация порога на основе режима рынка
            current_score_threshold = self.min_score_threshold

            if self.adaptive_regime:
                # Обновляем режим рынка
                candles = self.market_data_cache[symbol].ohlcv_data
                new_regime = self.adaptive_regime.update_regime(candles, current_price)

                # Проверяем, изменился ли режим
                if new_regime and new_regime != self.current_regime_type:
                    logger.info(
                        f"🔄 Regime changed: {self.current_regime_type} → {new_regime}"
                    )
                    # Переключаем параметры на новый режим
                    await self.switch_regime_parameters(new_regime)

                # Получаем параметры для текущего режима
                regime_params = self.adaptive_regime.get_current_parameters()
                current_score_threshold = regime_params.min_score_threshold

                logger.debug(
                    f"🧠 Market Regime: {self.adaptive_regime.current_regime.value.upper()} | "
                    f"Threshold: {current_score_threshold}/12"
                )
            elif self.volatility_adapter and atr:
                # Fallback: используем Volatility Adapter если ARM отключен
                current_volatility = self.volatility_adapter.calculate_volatility(
                    atr.value, current_price
                )
                vol_params = self.volatility_adapter.get_parameters(current_volatility)
                current_score_threshold = vol_params.score_threshold

                logger.debug(
                    f"📊 Volatility: {current_volatility:.2%} → Regime: {vol_params.regime.value} | "
                    f"Threshold: {current_score_threshold}/12"
                )

            # Логируем scoring ВСЕГДА (для понимания почему нет сигналов)
            logger.info(
                f"📊 {symbol} Scoring: LONG {long_score}/12 ({long_confidence:.1%}) | "
                f"SHORT {short_score}/12 ({short_confidence:.1%}) | "
                f"Threshold: {current_score_threshold}/12"
            )

            # PHASE 1: Time-Based Filter
            # Проверяем СНАЧАЛА время (самая быстрая проверка)
            if self.time_filter:
                if not self.time_filter.is_trading_allowed():
                    next_time = self.time_filter.get_next_trading_time()
                    logger.info(
                        f"⏰ TIME FILTER BLOCKED: {symbol} | "
                        f"Reason: Outside trading hours | "
                        f"{next_time}"
                    )
                    return None

            # PHASE 1: Correlation Filter
            # Проверяем корреляцию ПЕРЕД MTF (чтобы не тратить ресурсы)
            if self.correlation_filter:
                # Определяем направление сигнала (используем адаптированный порог)
                signal_direction = None
                if long_score >= current_score_threshold and long_score > short_score:
                    signal_direction = "LONG"
                elif (
                    short_score >= current_score_threshold and short_score > long_score
                ):
                    signal_direction = "SHORT"

                if signal_direction:
                    corr_result = await self.correlation_filter.check_entry(
                        symbol, signal_direction, self.positions
                    )
                    if corr_result.blocked:
                        logger.warning(
                            f"🚫 CORRELATION BLOCKED: {symbol} {signal_direction} | "
                            f"Reason: {corr_result.reason} | "
                            f"Correlated: {corr_result.correlated_positions}"
                        )
                        return None

            # PHASE 1: Volume Profile
            # Проверяем Volume Profile первым (общий бонус для обоих направлений)
            if self.volume_profile_filter:
                vp_result = await self.volume_profile_filter.check_entry(
                    symbol, current_price
                )
                if vp_result.bonus > 0:
                    # Получаем multiplier для текущего режима
                    vp_multiplier = 1.0
                    if self.adaptive_regime:
                        regime_params = self.adaptive_regime.get_current_parameters()
                        vp_multiplier = regime_params.volume_profile_bonus_multiplier

                    # Применяем multiplier к бонусу
                    base_bonus = vp_result.bonus
                    adjusted_bonus = int(round(base_bonus * vp_multiplier))

                    # Применяем бонус к обоим score (если есть сигнал)
                    if (
                        long_score >= current_score_threshold
                        and long_score > short_score
                    ):
                        long_score += adjusted_bonus
                        long_confidence = long_score / 12.0
                        logger.info(
                            f"✅ VOLUME PROFILE BONUS: {symbol} LONG | "
                            f"Reason: {vp_result.reason} | "
                            f"Base bonus: +{base_bonus} | Multiplier: {vp_multiplier}x | "
                            f"Adjusted bonus: +{adjusted_bonus} | New score: {long_score}/12"
                        )
                    elif (
                        short_score >= current_score_threshold
                        and short_score > long_score
                    ):
                        short_score += adjusted_bonus
                        short_confidence = short_score / 12.0
                        logger.info(
                            f"✅ VOLUME PROFILE BONUS: {symbol} SHORT | "
                            f"Reason: {vp_result.reason} | "
                            f"Base bonus: +{base_bonus} | Multiplier: {vp_multiplier}x | "
                            f"Adjusted bonus: +{adjusted_bonus} | New score: {short_score}/12"
                        )

            # PHASE 1: Pivot Points
            # Проверяем Pivot уровни (до MTF, так как может дать бонус к score)
            if self.pivot_filter:
                # Получаем multiplier для текущего режима
                pivot_multiplier = 1.0
                if self.adaptive_regime:
                    regime_params = self.adaptive_regime.get_current_parameters()
                    pivot_multiplier = regime_params.pivot_bonus_multiplier

                if long_score >= current_score_threshold and long_score > short_score:
                    # Проверяем LONG около Pivot уровней
                    pivot_result = await self.pivot_filter.check_entry(
                        symbol, current_price, "LONG"
                    )
                    if pivot_result.near_level and pivot_result.bonus > 0:
                        # Применяем multiplier к бонусу
                        base_bonus = pivot_result.bonus
                        adjusted_bonus = int(round(base_bonus * pivot_multiplier))

                        long_score += adjusted_bonus
                        long_confidence = long_score / 12.0
                        logger.info(
                            f"✅ PIVOT BONUS: {symbol} LONG near {pivot_result.level_name} | "
                            f"Base bonus: +{base_bonus} | Multiplier: {pivot_multiplier}x | "
                            f"Adjusted bonus: +{adjusted_bonus} | New score: {long_score}/12"
                        )
                elif (
                    short_score >= current_score_threshold and short_score > long_score
                ):
                    # Проверяем SHORT около Pivot уровней
                    pivot_result = await self.pivot_filter.check_entry(
                        symbol, current_price, "SHORT"
                    )
                    if pivot_result.near_level and pivot_result.bonus > 0:
                        # Применяем multiplier к бонусу
                        base_bonus = pivot_result.bonus
                        adjusted_bonus = int(round(base_bonus * pivot_multiplier))

                        short_score += adjusted_bonus
                        short_confidence = short_score / 12.0
                        logger.info(
                            f"✅ PIVOT BONUS: {symbol} SHORT near {pivot_result.level_name} | "
                            f"Base bonus: +{base_bonus} | Multiplier: {pivot_multiplier}x | "
                            f"Adjusted bonus: +{adjusted_bonus} | New score: {short_score}/12"
                        )

            # PHASE 1: Multi-Timeframe Confirmation
            # Применяем MTF фильтр ДО генерации сигнала (если включен)
            if self.mtf_filter:
                # Определяем какой сигнал сильнее (используем адаптированный порог)
                if long_score >= current_score_threshold and long_score > short_score:
                    # Проверяем LONG сигнал
                    mtf_result = await self.mtf_filter.check_confirmation(
                        symbol, "LONG"
                    )
                    if mtf_result.blocked:
                        logger.warning(
                            f"🚫 MTF BLOCKED: {symbol} LONG signal blocked | "
                            f"Reason: {mtf_result.reason}"
                        )
                        return None
                    if mtf_result.confirmed:
                        # Добавляем бонус к score
                        long_score += mtf_result.bonus
                        long_confidence = long_score / 12.0
                        logger.info(
                            f"✅ MTF CONFIRMED: {symbol} LONG | "
                            f"Bonus: +{mtf_result.bonus} | New score: {long_score}/12"
                        )
                elif (
                    short_score >= current_score_threshold and short_score > long_score
                ):
                    # Проверяем SHORT сигнал
                    mtf_result = await self.mtf_filter.check_confirmation(
                        symbol, "SHORT"
                    )
                    if mtf_result.blocked:
                        logger.warning(
                            f"🚫 MTF BLOCKED: {symbol} SHORT signal blocked | "
                            f"Reason: {mtf_result.reason}"
                        )
                        return None
                    if mtf_result.confirmed:
                        # Добавляем бонус к score
                        short_score += mtf_result.bonus
                        short_confidence = short_score / 12.0
                        logger.info(
                            f"✅ MTF CONFIRMED: {symbol} SHORT | "
                            f"Bonus: +{mtf_result.bonus} | New score: {short_score}/12"
                        )

            # Long сигнал: минимум current_score_threshold баллов и больше чем short
            if long_score >= current_score_threshold and long_score > short_score:
                logger.info(
                    f"🎯 SIGNAL GENERATED: {symbol} LONG | "
                    f"Score: {long_score}/12 | Confidence: {long_confidence:.1%} | "
                    f"Price: ${current_price:,.2f}"
                )
                return Signal(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    strength=long_confidence,
                    price=current_price,
                    timestamp=datetime.utcnow(),
                    strategy_id=self.strategy_id,
                    indicators={k: v.value for k, v in indicators.items()},
                    confidence=long_confidence,
                )

            # Short сигнал: минимум current_score_threshold баллов и больше чем long
            if short_score >= current_score_threshold and short_score > long_score:
                logger.info(
                    f"🎯 SIGNAL GENERATED: {symbol} SHORT | "
                    f"Score: {short_score}/12 | Confidence: {short_confidence:.1%} | "
                    f"Price: ${current_price:,.2f}"
                )
                return Signal(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    strength=short_confidence,
                    price=current_price,
                    timestamp=datetime.utcnow(),
                    strategy_id=self.strategy_id,
                    indicators={k: v.value for k, v in indicators.items()},
                    confidence=short_confidence,
                )

            # Если нет сигнала - логируем почему
            if (
                long_score < current_score_threshold
                and short_score < current_score_threshold
            ):
                logger.info(
                    f"⚪ {symbol} No signal: Both scores too low "
                    f"(L:{long_score}/12, S:{short_score}/12, need {current_score_threshold})"
                )
            elif long_score == short_score:
                logger.info(
                    f"⚪ {symbol} No signal: Equal scores "
                    f"(L:{long_score}/12, S:{short_score}/12)"
                )

            return None

        else:
            # Старая логика "всё или ничего" (если scoring отключен)
            long_conditions = [
                current_price > sma_fast.value > sma_slow.value,
                ema_fast.value > ema_slow.value,
                30 < rsi.value < 70,
                current_price <= bb.metadata["lower_band"] * 1.002,
                volume.value >= self.config.entry.volume_threshold,
            ]

            short_conditions = [
                current_price < sma_fast.value < sma_slow.value,
                ema_fast.value < ema_slow.value,
                30 < rsi.value < 70,
                current_price >= bb.metadata["upper_band"] * 0.998,
                volume.value >= self.config.entry.volume_threshold,
            ]

            existing_position = self.positions.get(symbol)
            if existing_position:
                if existing_position.side == PositionSide.LONG and any(
                    short_conditions
                ):
                    return None
                if existing_position.side == PositionSide.SHORT and any(
                    long_conditions
                ):
                    return None

            if all(long_conditions):
                return Signal(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    strength=0.8,
                    price=current_price,
                    timestamp=datetime.utcnow(),
                    strategy_id=self.strategy_id,
                    indicators={k: v.value for k, v in indicators.items()},
                    confidence=1.0,
                )

            elif all(short_conditions):
                return Signal(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    strength=0.8,
                    price=current_price,
                    timestamp=datetime.utcnow(),
                    strategy_id=self.strategy_id,
                    indicators={k: v.value for k, v in indicators.items()},
                    confidence=1.0,
                )

            return None

    def _detect_market_regime(self, symbol: str) -> str:
        """
        Определение текущего режима рынка (простая версия).

        Классифицирует рынок в одну из категорий:
        - HIGH_VOLATILITY: высокая волатильность (>2%)
        - TRENDING: явный тренд (SMA50 vs SMA200)
        - RANGING: боковое движение

        Args:
            symbol: Торговый символ

        Returns:
            str: Режим рынка ("HIGH_VOLATILITY", "TRENDING", "RANGING")
        """
        market_data = self.market_data_cache.get(symbol)
        if not market_data:
            return "RANGING"  # По умолчанию

        closes = market_data.get_closes()
        if len(closes) < 200:
            return "RANGING"

        # Расчёт волатильности (стандартное отклонение доходностей)
        returns = np.diff(closes[-20:]) / closes[-21:-1]  # Последние 20 свечей
        volatility = np.std(returns)

        # Расчёт тренда (SMA50 vs SMA200)
        sma_50 = np.mean(closes[-50:])
        sma_200 = np.mean(closes[-200:])
        trend_diff = abs(sma_50 - sma_200) / sma_200

        # Классификация
        if volatility > self.high_volatility_threshold:
            return "HIGH_VOLATILITY"
        elif trend_diff > self.trend_threshold:
            return "TRENDING"
        else:
            return "RANGING"

    def _can_trade(self, symbol: str) -> bool:
        """
        Проверка возможности открытия новой сделки по символу.

        Проверяет различные ограничения и условия:
        - Активность стратегии
        - Лимит сделок в час
        - Период охлаждения после убытка
        - Максимальное количество открытых позиций
        - 🛡️ Лимит consecutive losses (НОВОЕ)

        Args:
            symbol: Торговый символ для проверки

        Returns:
            bool: True если торговля разрешена, False иначе
        """
        # Check if strategy is active
        if not self.active:
            logger.debug(f"🚫 {symbol}: Strategy not active")
            return False

        # 🛡️ УЛУЧШЕНИЕ 1: Проверка consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            logger.warning(
                f"Cannot trade: max consecutive losses reached "
                f"({self.consecutive_losses})"
            )
            return False

        # 💰 УЛУЧШЕНИЕ 2: Проверка daily profit lock
        if self.profit_lock_enabled and self.daily_start_balance > 0:
            profit_pct = (self.daily_pnl / self.daily_start_balance) * 100
            if profit_pct >= self.daily_profit_target_percent:
                logger.info(
                    f"🎯 Daily profit target reached: {profit_pct:.2f}%. "
                    f"Stopping trading for today."
                )
                return False

        # ⏰ УЛУЧШЕНИЕ 8: Session filtering - ЗАМЕНЕНО НА TimeSessionManager
        # Теперь проверка времени выполняется через TimeSessionManager в _generate_signal()
        # Старая логика отключена, чтобы избежать конфликтов
        # if self.session_filtering_enabled:
        #     ... старый код удален

        # Check hourly trade limit (ARM может перекрыть!)
        max_trades = self.config.max_trades_per_hour
        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            max_trades = regime_params.max_trades_per_hour

        if self.trade_count_hourly >= max_trades:
            logger.debug(
                f"🚫 {symbol}: Hourly trade limit reached "
                f"({self.trade_count_hourly}/{max_trades})"
            )
            return False

        # Check cooldown after loss (ARM может перекрыть!)
        cooldown_minutes = self.config.cooldown_after_loss_minutes
        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            cooldown_minutes = regime_params.cooldown_after_loss_minutes

        if symbol in self.last_loss_time:
            cooldown_end = self.last_loss_time[symbol] + timedelta(
                minutes=cooldown_minutes
            )
            if datetime.utcnow() < cooldown_end:
                remaining = (cooldown_end - datetime.utcnow()).total_seconds() / 60
                logger.debug(
                    f"🚫 {symbol}: Cooldown active, {remaining:.1f} min remaining"
                )
                return False

        # 🛡️ ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА: Увеличенный cooldown после 2+ убытков
        if self.consecutive_losses >= 2:
            extended_cooldown_minutes = 15  # 15 минут пауза после серии убытков

            # Ищем время последнего убытка по любому символу
            if self.last_loss_time:
                latest_loss_time = max(self.last_loss_time.values())
                time_since_loss = (
                    datetime.utcnow() - latest_loss_time
                ).total_seconds() / 60

                if time_since_loss < extended_cooldown_minutes:
                    logger.debug(
                        f"🛡️ {symbol} Extended cooldown active after {self.consecutive_losses} losses: "
                        f"{extended_cooldown_minutes - time_since_loss:.1f} min remaining"
                    )
                return False

        # Check max positions
        if len(self.positions) >= self.risk_config.max_open_positions:
            logger.debug(
                f"🚫 {symbol}: Max positions reached "
                f"({len(self.positions)}/{self.risk_config.max_open_positions})"
            )
            return False

        logger.debug(f"✅ {symbol}: All checks passed, can trade")
        return True

    async def _execute_signal(self, signal: Signal) -> None:
        """
        Исполнение торгового сигнала (открытие позиции).

        Рассчитывает размер позиции на основе риск-менеджмента,
        определяет уровни stop-loss и take-profit, и размещает
        рыночный ордер на бирже.

        Args:
            signal: Торговый сигнал с параметрами сделки

        Raises:
            Exception: При ошибках размещения ордера
        """
        try:
            # Calculate position size
            position_size = await self._calculate_position_size(
                signal.symbol, signal.price
            )

            if position_size <= 0:
                logger.warning(f"Invalid position size for {signal.symbol}")
                return

            # PHASE 1: Balance Checker - проверяем баланс перед входом
            if self.balance_checker:
                balances = await self.client.get_account_balance()

                # 🛡️ КРИТИЧЕСКАЯ ПРОВЕРКА: Блокируем торговлю если есть займы
                base_asset = signal.symbol.split("-")[0]
                quote_asset = signal.symbol.split("-")[1]

                try:
                    borrowed_base = await self.client.get_borrowed_balance(base_asset)
                    borrowed_quote = await self.client.get_borrowed_balance(quote_asset)

                    if borrowed_base > 0 or borrowed_quote > 0:
                        logger.error(
                            f"⛔ {signal.symbol} {signal.side.value} BLOCKED: "
                            f"BORROWED FUNDS DETECTED! "
                            f"{base_asset}: {borrowed_base:.6f} | "
                            f"{quote_asset}: {borrowed_quote:.6f}"
                        )
                        logger.error(
                            "🚨 TRADING SUSPENDED! "
                            "Repay all loans and switch to SPOT mode!"
                        )
                        return
                except Exception as e:
                    logger.error(f"Failed to check borrowed balance: {e}")
                    # В случае ошибки проверки - блокируем торговлю!
                    logger.error(
                        "⛔ Trade blocked due to borrowed balance check failure"
                    )
                    return

                balance_check = self.balance_checker.check_balance(
                    symbol=signal.symbol,
                    side=signal.side,
                    required_amount=position_size,
                    current_price=signal.price,
                    balances=balances,
                )

                if not balance_check.allowed:
                    logger.warning(
                        f"⛔ {signal.symbol} {signal.side.value} BLOCKED by Balance Checker: "
                        f"{balance_check.reason}"
                    )
                    return

            # 🛡️ ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА: Блокировка SHORT без актива (предотвращение займов)
            if signal.side == OrderSide.SELL:
                base_asset = signal.symbol.split("-")[
                    0
                ]  # Извлекаем актив (SOL, DOGE, etc)
                asset_balance = await self.client.get_balance(base_asset)

                if asset_balance < position_size:
                    logger.error(
                        f"🚨 {signal.symbol} SHORT BLOCKED: No {base_asset} on balance! "
                        f"Have: {asset_balance:.8f}, Need: {position_size:.8f} - "
                        f"Preventing automatic borrowing in SPOT mode!"
                    )
                    return  # ❌ НЕ открываем SHORT без актива!

            # Calculate stop loss and take profit
            indicators = self.indicators.calculate_all(
                self.market_data_cache[signal.symbol]
            )
            atr_result = indicators.get("ATR")

            if not atr_result:
                logger.warning(f"No ATR data for {signal.symbol}")
                return

            stop_loss, take_profit = self._calculate_exit_levels(
                signal.price, signal.side, atr_result.value
            )

            # 🛡️ КРИТИЧНО! Проверка минимума для OCO MARKET orders
            # OCO объединяет TP и SL в один ордер - при срабатывании одного
            # второй автоматически отменяется
            #
            # Минимумы найдены тестами на реальной бирже OKX:
            # LONG: entry $30 → TP $30.45 ✅, SL $29.25 ✅
            # SHORT: entry $43 → TP $42.35 ✅, SL $44.07 ✅
            #
            # Для SHORT нужно больше т.к. TP (ниже entry) должен быть >= $40

            MIN_LONG_OCO = 70.0  # Минимум для LONG OCO ордера (BTC/ETH)
            MIN_SHORT_OCO = 70.0  # Минимум для SHORT OCO ордера

            # Определяем минимум в зависимости от направления
            if signal.side == OrderSide.BUY:  # LONG
                min_position_value = MIN_LONG_OCO
            else:  # SHORT
                min_position_value = MIN_SHORT_OCO

            # Проверяем минимум entry (с буфером +5%)
            position_value = position_size * signal.price

            if position_value < min_position_value:
                # Увеличиваем размер до минимума + 5% буфер
                required_value = min_position_value * 1.05
                old_size = position_size
                position_size = round(required_value / signal.price, 8)
                new_value = position_size * signal.price

                logger.info(
                    f"⬆️ Position size increased for OCO order: "
                    f"{old_size:.6f} → {position_size:.6f} "
                    f"(${position_value:.2f} → ${new_value:.2f}, "
                    f"min ${min_position_value} + 5% buffer)"
                )

                position_value = new_value

            # 🎯 Шаг 1: Открываем основной ордер (БЕЗ TP/SL)
            if signal.side == OrderSide.BUY:
                # LONG: передаем сумму в USDT (tgtCcy='quote_ccy' - безопасно)
                logger.info(
                    f"📤 Placing LONG order: BUY ${position_value:.2f} USDT "
                    f"{signal.symbol} @ ${signal.price:.2f}"
                )
                logger.info(f"   📊 TP/SL: TP=${take_profit:.2f}, SL=${stop_loss:.2f}")

                order = await self.client.place_order(
                    symbol=signal.symbol,
                    side=signal.side,
                    order_type=OrderType.MARKET,
                    quantity=position_value,  # Сумма в USDT
                )
            else:
                # SHORT: передаем количество монет (как раньше)
                logger.info(
                    f"📤 Placing SHORT order: SELL {position_size} "
                    f"{signal.symbol} @ ${signal.price:.2f}"
                )
                logger.info(f"   📊 TP/SL: TP=${take_profit:.2f}, SL=${stop_loss:.2f}")

                order = await self.client.place_order(
                    symbol=signal.symbol,
                    side=signal.side,
                    order_type=OrderType.MARKET,
                    quantity=position_size,  # Количество монет
                )

            if order:
                self.pending_orders[order.id] = signal.symbol
                self.trade_count_hourly += 1
                self.last_trade_time[signal.symbol] = datetime.utcnow()

                # 🎯 Для BUY ордеров получаем фактически купленное количество
                actual_position_size = position_size
                if signal.side == OrderSide.BUY:
                    try:
                        # 🔧 Инициализируем словарь для отслеживания балансов
                        if not hasattr(self, "previous_balances"):
                            self.previous_balances = {}

                        # Получаем баланс базовой валюты
                        base_currency = signal.symbol.split("-")[0]

                        # 🔧 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если НЕТ в кэше - используем ожидаемый размер!
                        # При первой покупке мы НЕ ЗНАЕМ баланс ДО, поэтому используем расчетный
                        if base_currency not in self.previous_balances:
                            logger.info(
                                f"📊 BUY completed (first trade for {base_currency}): "
                                f"using expected size {position_size:.8f}"
                            )
                            actual_position_size = position_size
                            
                            # Сохраняем текущий баланс для СЛЕДУЮЩЕЙ сделки
                            current_balance = await self.client.get_balance(base_currency)
                            self.previous_balances[base_currency] = current_balance
                        else:
                            # 🔧 Для ПОСЛЕДУЮЩИХ сделок: вычисляем разницу
                            previous_balance = self.previous_balances[base_currency]

                            # Ждем секунду для обновления баланса
                            await asyncio.sleep(1)

                            # Получаем текущий баланс ПОСЛЕ покупки
                            current_balance = await self.client.get_balance(base_currency)

                            # 🔧 Вычисляем разницу (только купленное!)
                            actual_position_size = current_balance - previous_balance

                            # 🛡️ Защита от отрицательных значений
                            if actual_position_size < 0 or actual_position_size > position_size * 5:
                                logger.warning(
                                    f"⚠️ Suspicious position size detected! Using expected value. "
                                    f"Previous: {previous_balance:.8f}, Current: {current_balance:.8f}, "
                                    f"Calculated: {actual_position_size:.8f}, Expected: {position_size:.8f}"
                                )
                                actual_position_size = position_size

                            # 🔧 Обновляем кэш баланса для следующей сделки
                            self.previous_balances[base_currency] = current_balance

                            logger.info(
                                f"📊 BUY completed: expected ~{position_size:.8f}, "
                                f"previous balance {previous_balance:.8f}, "
                                f"current balance {current_balance:.8f}, "
                                f"actual bought {actual_position_size:.8f} {base_currency}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Could not get actual position size for BUY: {e}"
                        )
                        # Используем расчетное значение
                        actual_position_size = position_value / signal.price

                # Create position with SL/TP levels
                # TP/SL мониторятся ботом (SPOT не поддерживает автоматические)
                position = Position(
                    id=order.id,
                    symbol=signal.symbol,
                    side=(
                        PositionSide.LONG
                        if signal.side == OrderSide.BUY
                        else PositionSide.SHORT
                    ),
                    entry_price=signal.price,
                    current_price=signal.price,
                    size=actual_position_size,  # Используем фактический размер
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    timestamp=datetime.utcnow(),
                )
                self.positions[signal.symbol] = position

                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                logger.info(
                    f"✅ POSITION OPENED: {signal.symbol} {position.side.value.upper()}"
                )
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                logger.info(f"   Order ID: {order.id}")
                logger.info(f"   Side: {signal.side.value.upper()}")
                logger.info(
                    f"   Size: {actual_position_size:.8f} {signal.symbol.split('-')[0]}"
                )
                logger.info(f"   Entry: ${signal.price:.2f}")
                logger.info(f"   Take Profit: ${take_profit:.2f}")
                logger.info(f"   Stop Loss: ${stop_loss:.2f}")
                logger.info(
                    f"   Risk/Reward: 1:{abs(take_profit-signal.price)/abs(signal.price-stop_loss):.2f}"
                )
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

                # 🎯 Шаг 2: Выставляем OCO ордер (TP + SL в одном!)
                try:
                    # Определяем сторону закрытия
                    close_side = (
                        OrderSide.SELL
                        if signal.side == OrderSide.BUY
                        else OrderSide.BUY
                    )

                    oco_order_id = await self.client.place_oco_order(
                        symbol=signal.symbol,
                        side=close_side,
                        quantity=actual_position_size,  # Используем фактический размер
                        tp_trigger_price=take_profit,
                        sl_trigger_price=stop_loss,
                    )

                    if oco_order_id:
                        # Сохраняем OCO ID в позиции для отслеживания
                        position.algo_order_id = oco_order_id

                        logger.info(
                            f"✅ OCO order placed: ID={oco_order_id} | "
                            f"TP @ ${take_profit:.2f}, SL @ ${stop_loss:.2f}"
                        )
                    else:
                        logger.warning(
                            f"⚠️ OCO order FAILED for {signal.symbol} - "
                            f"position without automatic TP/SL protection!"
                        )
                except Exception as e:
                    logger.error(f"❌ Error placing OCO order: {e}")

                # Добавляем Partial TP
                await self._check_partial_take_profit(
                    signal.symbol, signal.price, position
                )
            else:
                logger.error(
                    f"❌ Order placement FAILED: {signal.side.value} "
                    f"{signal.symbol} - No order returned from exchange"
                )

        except Exception as e:
            logger.error(
                f"❌ Error executing signal {signal.symbol}: {e}", exc_info=True
            )

    async def _calculate_position_size(self, symbol: str, price: float) -> float:
        """
        Расчет размера позиции на основе риск-менеджмента.

        Использует метод фиксированного риска на сделку (обычно 1% от баланса).
        Учитывает ATR для определения расстояния до stop-loss и
        применяет ограничения на максимальный размер позиции.

        Args:
            symbol: Торговый символ
            price: Текущая цена для расчета количества

        Returns:
            float: Размер позиции в базовой валюте (0 при ошибках)

        Raises:
            Exception: При критических ошибках расчета
        """
        logger.info(f"🔍 CALCULATING POSITION SIZE for {symbol} @ ${price:.2f}")
        try:
            # Get account balance
            balances = await self.client.get_account_balance()
            # Используем USDT как базовую валюту для всех пар
            base_balance = next(
                (b.free for b in balances if b.currency == "USDT"),
                0.0,
            )

            logger.info(f"💰 USDT Balance: ${base_balance:.2f}")

            if base_balance <= 0:
                logger.warning(f"❌ No USDT balance for {symbol}")
                return 0.0

            # Calculate risk amount (1% of balance)
            risk_amount = base_balance * (self.risk_config.risk_per_trade_percent / 100)
            logger.info(
                f"🎯 Risk amount: ${risk_amount:.2f} ({self.risk_config.risk_per_trade_percent}%)"
            )

            # Get ATR for stop loss calculation
            market_data = self.market_data_cache.get(symbol)
            if not market_data:
                return 0.0

            indicators = self.indicators.calculate_all(market_data)
            atr_result = indicators.get("ATR")

            if not atr_result or atr_result.value <= 0:
                return 0.0

            # Calculate stop loss distance (ARM может перекрыть!)
            sl_multiplier = self.config.exit.stop_loss_atr_multiplier
            if self.adaptive_regime:
                regime_params = self.adaptive_regime.get_current_parameters()
                sl_multiplier = regime_params.sl_atr_multiplier

            stop_distance = atr_result.value * sl_multiplier

            # Position size = risk amount / stop distance
            position_size = risk_amount / stop_distance

            # Apply maximum position size limit
            max_position_value = base_balance * (
                self.risk_config.max_position_size_percent / 100
            )
            max_position_size = max_position_value / price

            final_position_size = min(position_size, max_position_size)

            # PHASE 1.5: ARM - корректировка размера по режиму рынка
            if self.adaptive_regime:
                regime_params = self.adaptive_regime.get_current_parameters()
                multiplier = regime_params.position_size_multiplier
                final_position_size *= multiplier
                logger.debug(
                    f"🧠 ARM: {self.adaptive_regime.current_regime.value.upper()} "
                    f"mode → size multiplier {multiplier}x"
                )

            # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА: Проверка минимального размера ордера
            # OKX минимум ~$10, берем $30 с запасом +2% (учитываем комиссии и движение цены)
            position_value_usd = final_position_size * price
            logger.info(
                f"📊 Final position size: {final_position_size:.6f} = ${position_value_usd:.2f} (min: ${self.min_order_value_usd})"
            )

            if position_value_usd < self.min_order_value_usd:
                # Увеличиваем размер до минимума + 2% запас
                final_position_size = (self.min_order_value_usd * 1.02) / price
                final_value = final_position_size * price
                logger.info(
                    f"⬆️ {symbol} Position size increased to meet ${self.min_order_value_usd} minimum: "
                    f"{final_position_size:.6f} (${final_value:.2f} with 2% buffer)"
                )

                # 🛡️ КРИТИЧНО! Проверяем баланс ПОСЛЕ увеличения до минимума
                if self.balance_checker:
                    # Определяем направление для проверки баланса
                    # (нужно смотреть на signal, но у нас его тут нет, поэтому проверим оба)
                    # Используем эвристику: для большинства пар нужен USDT (LONG)
                    balances_check = await self.client.get_account_balance()

                    # Проверяем USDT баланс (для LONG) - основной случай
                    balance_result = self.balance_checker._check_usdt_balance(
                        symbol, final_position_size, price, balances_check
                    )

                    if not balance_result.allowed:
                        logger.error(
                            f"⛔ {symbol}: Insufficient balance after increasing to minimum! "
                            f"{balance_result.reason} - SKIPPING TRADE to prevent automatic borrowing"
                        )
                        return 0.0  # ❌ Отменяем сделку полностью!

            # Округляем до 8 знаков после запятой (OKX requirement)
            rounded_size = round(final_position_size, 8)
            logger.debug(
                f"📐 {symbol} Position size rounded: {final_position_size:.15f} → {rounded_size:.8f}"
            )

            return rounded_size

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0.0

    def _calculate_exit_levels(
        self, entry_price: float, side: OrderSide, atr: float
    ) -> tuple:
        """
        Расчет уровней выхода из позиции (stop-loss и take-profit).

        Использует ATR (Average True Range) для динамического определения
        расстояния до уровней выхода. Расстояния масштабируются
        мультипликаторами из конфигурации или ARM.

        Args:
            entry_price: Цена входа в позицию
            side: Направление сделки (BUY/SELL)
            atr: Значение ATR для расчета расстояния

        Returns:
            tuple: (stop_loss_price, take_profit_price)
        """
        # PHASE 1.5: Используем параметры ARM если включен
        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            sl_multiplier = regime_params.sl_atr_multiplier
            tp_multiplier = regime_params.tp_atr_multiplier
        else:
            # Fallback: используем конфигурацию по умолчанию
            sl_multiplier = self.config.exit.stop_loss_atr_multiplier
            tp_multiplier = self.config.exit.take_profit_atr_multiplier

        stop_distance = atr * sl_multiplier
        profit_distance = atr * tp_multiplier

        if side == OrderSide.BUY:
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + profit_distance
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - profit_distance

        return stop_loss, take_profit

    async def _update_position_prices(self, symbol: str, current_price: float) -> None:
        """
        Обновление цены позиции и проверка условий выхода.

        Проверяет следующие условия выхода:
        - Достижение stop-loss уровня
        - Достижение take-profit уровня
        - Превышение максимального времени удержания позиции

        Args:
            symbol: Торговый символ
            current_price: Текущая рыночная цена

        Raises:
            Exception: При ошибках закрытия позиции
        """
        position = self.positions.get(symbol)
        if not position:
            return

        # 🔧 ОТКЛЮЧЕНО: Проверка статуса OCO (вызывает Invalid Sign!)
        # OCO ордера работают автоматически на бирже
        # Закрытие определяем по изменению баланса
        if False and position.algo_order_id:
            try:
                oco_status = await self.client.get_algo_order_status(
                    position.algo_order_id
                )

                if oco_status:
                    state = oco_status.get("state")

                    # state: "live" - активен, "filled" - исполнен, "canceled" - отменен
                    if state == "filled":
                        # OCO сработал! Определяем TP или SL
                        actual_px = float(oco_status.get("actualPx", current_price))

                        # Определяем что сработало
                        if position.side == PositionSide.LONG:
                            if actual_px >= position.take_profit * 0.99:
                                reason = "take_profit_oco"
                            else:
                                reason = "stop_loss_oco"
                        else:
                            if actual_px <= position.take_profit * 1.01:
                                reason = "take_profit_oco"
                            else:
                                reason = "stop_loss_oco"

                        logger.info(
                            f"🎯 OCO executed! {symbol} {reason.upper()} @ ${actual_px:.2f}"
                        )

                        # Обновляем статистику и удаляем позицию
                        await self._record_trade_completion(symbol, actual_px, reason)
                        return  # Позиция закрыта

                    elif state == "canceled":
                        logger.warning(
                            f"⚠️ OCO canceled for {symbol}, position unprotected!"
                        )
                        position.algo_order_id = None  # Больше не отслеживаем

            except Exception as e:
                logger.debug(f"Could not check OCO status for {symbol}: {e}")

        # Update position price
        position.update_price(current_price)

        # 🔒 УЛУЧШЕНИЕ 3: Break-even stop
        if self.breakeven_enabled:
            # Получаем текущий ATR
            market_data = self.market_data_cache.get(symbol)
            if market_data:
                indicators = self.indicators.calculate_all(market_data)
                atr_result = indicators.get("ATR")

                if atr_result and atr_result.value > 0:
                    # Расчёт прибыли
                    if position.side == PositionSide.LONG:
                        profit = current_price - position.entry_price
                        # Если прибыль >= 1 ATR и SL ещё не в безубытке
                        if (
                            profit >= atr_result.value * self.breakeven_trigger_atr
                            and position.stop_loss < position.entry_price
                        ):
                            # Переводим SL в безубыток + небольшой буфер
                            position.stop_loss = position.entry_price + (
                                atr_result.value * 0.1
                            )
                            logger.info(
                                f"🔒 Break-even activated for {symbol}: "
                                f"SL moved to {position.stop_loss:.6f}"
                            )
                    else:  # SHORT
                        profit = position.entry_price - current_price
                        if (
                            profit >= atr_result.value * self.breakeven_trigger_atr
                            and position.stop_loss > position.entry_price
                        ):
                            position.stop_loss = position.entry_price - (
                                atr_result.value * 0.1
                            )
                            logger.info(
                                f"🔒 Break-even activated for {symbol}: "
                                f"SL moved to {position.stop_loss:.6f}"
                            )

        # 📈 УЛУЧШЕНИЕ 5: Trailing Stop
        if self.trailing_stop_enabled:
            market_data = self.market_data_cache.get(symbol)
            if market_data:
                indicators = self.indicators.calculate_all(market_data)
                atr_result = indicators.get("ATR")

                if atr_result and atr_result.value > 0:
                    if position.side == PositionSide.LONG:
                        profit = current_price - position.entry_price
                        # Активируем trailing после 1.5 ATR прибыли
                        activation_level = (
                            atr_result.value * self.trailing_stop_activation_atr
                        )

                        if profit >= activation_level:
                            # Новый trailing SL на 0.8 ATR ниже текущей цены
                            new_trailing_sl = current_price - (
                                atr_result.value * self.trailing_stop_distance_atr
                            )
                            # Поднимаем SL только вверх (не опускаем)
                            if new_trailing_sl > position.stop_loss:
                                position.stop_loss = new_trailing_sl
                                logger.info(
                                    f"📈 Trailing SL updated for {symbol}: "
                                    f"{position.stop_loss:.6f} "
                                    f"(distance: {self.trailing_stop_distance_atr} ATR)"
                                )
                    else:  # SHORT
                        profit = position.entry_price - current_price
                        activation_level = (
                            atr_result.value * self.trailing_stop_activation_atr
                        )

                        if profit >= activation_level:
                            # Новый trailing SL на 0.8 ATR выше текущей цены
                            new_trailing_sl = current_price + (
                                atr_result.value * self.trailing_stop_distance_atr
                            )
                            # Опускаем SL только вниз (не поднимаем)
                            if new_trailing_sl < position.stop_loss:
                                position.stop_loss = new_trailing_sl
                                logger.info(
                                    f"📈 Trailing SL updated for {symbol}: "
                                    f"{position.stop_loss:.6f}"
                                )

        # 🎯 УЛУЧШЕНИЕ 6: Partial Take Profit
        if self.partial_tp_enabled:
            await self._check_partial_take_profit(symbol, current_price, position)

        # Check time-based exit (ARM может перекрыть!)
        max_holding = self.config.exit.max_holding_minutes
        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            max_holding = regime_params.max_holding_minutes

        holding_time = datetime.utcnow() - position.timestamp
        if holding_time.seconds / 60 > max_holding:
            await self._close_position(symbol, "time_limit")
            return

        # Check stop loss / take profit
        if position.side == PositionSide.LONG:
            if current_price <= position.stop_loss:
                await self._close_position(symbol, "stop_loss")
            elif current_price >= position.take_profit:
                await self._close_position(symbol, "take_profit")
        else:
            if current_price >= position.stop_loss:
                await self._close_position(symbol, "stop_loss")
            elif current_price <= position.take_profit:
                await self._close_position(symbol, "take_profit")

    async def _check_partial_take_profit(
        self, symbol: str, current_price: float, position: Position
    ) -> None:
        """
        Проверка и исполнение частичного закрытия позиции (Partial TP).

        Закрывает части позиции на разных уровнях прибыли:
        - 50% на первом уровне (1.5 ATR)
        - 30% на втором уровне (2.5 ATR)
        - 20% на третьем уровне (4.0 ATR)

        Args:
            symbol: Торговый символ
            current_price: Текущая рыночная цена
            position: Объект позиции

        Raises:
            Exception: При ошибках частичного закрытия
        """
        try:
            # Инициализация уровней TP для новой позиции
            if symbol not in self.position_partial_info:
                market_data = self.market_data_cache.get(symbol)
                if not market_data:
                    return

                indicators = self.indicators.calculate_all(market_data)
                atr_result = indicators.get("ATR")

                if not atr_result or atr_result.value <= 0:
                    return

                # Создаём уровни TP на основе ATR
                self.position_partial_info[symbol] = []
                for level in self.tp_levels:
                    if position.side == PositionSide.LONG:
                        tp_price = position.entry_price + (
                            atr_result.value * level["atr_multiplier"]
                        )
                    else:  # SHORT
                        tp_price = position.entry_price - (
                            atr_result.value * level["atr_multiplier"]
                        )

                    self.position_partial_info[symbol].append(
                        {
                            "price": tp_price,
                            "percent": level["percent"],
                            "executed": False,
                        }
                    )

                logger.info(
                    f"🎯 Partial TP levels set for {symbol}: "
                    f"{len(self.tp_levels)} levels"
                )

            # Проверка достижения уровней TP
            partial_levels = self.position_partial_info.get(symbol, [])

            for i, level in enumerate(partial_levels):
                if level["executed"]:
                    continue  # Уже исполнен

                # Проверка достижения уровня
                level_reached = False
                if position.side == PositionSide.LONG:
                    level_reached = current_price >= level["price"]
                else:  # SHORT
                    level_reached = current_price <= level["price"]

                if level_reached:
                    # Закрываем часть позиции
                    close_size = position.size * level["percent"]
                    close_value = close_size * current_price

                    # 🛡️ ЗАЩИТА: Проверка минимального размера для частичного закрытия
                    if close_value < self.min_close_value_usd:
                        logger.debug(
                            f"⚠️ Partial TP #{i+1} for {symbol} too small: "
                            f"${close_value:.2f} < ${self.min_close_value_usd} - skipping this level"
                        )
                        continue  # Пропускаем этот уровень TP

                    # Размещаем ордер на частичное закрытие
                    order_side = (
                        OrderSide.SELL
                        if position.side == PositionSide.LONG
                        else OrderSide.BUY
                    )

                    order = await self.client.place_order(
                        symbol=symbol,
                        side=order_side,
                        order_type=OrderType.MARKET,
                        quantity=close_size,
                    )

                    if order:
                        # Обновляем размер позиции
                        position.size -= close_size
                        level["executed"] = True

                        # Рассчитываем PnL от частичного закрытия
                        if position.side == PositionSide.LONG:
                            partial_pnl = (
                                current_price - position.entry_price
                            ) * close_size
                        else:
                            partial_pnl = (
                                position.entry_price - current_price
                            ) * close_size

                        self.daily_pnl += partial_pnl

                        logger.info(
                            f"🎯 Partial TP #{i+1} hit for {symbol}: "
                            f"Closed {level['percent']:.0%} at "
                            f"${current_price:.6f}, "
                            f"PnL: ${partial_pnl:.2f}, "
                            f"Remaining: {position.size:.6f}"
                        )

                        # Если закрыли всю позицию (все уровни достигнуты)
                        if all(lvl["executed"] for lvl in partial_levels):
                            del self.positions[symbol]
                            del self.position_partial_info[symbol]
                            logger.info(
                                f"✅ All partial TP levels executed for " f"{symbol}"
                            )
                            return

        except Exception as e:
            logger.error(f"Error in partial take profit for {symbol}: {e}")

    async def _close_position(self, symbol: str, reason: str) -> None:
        """
        Закрытие открытой позиции по рыночной цене.

        Размещает рыночный ордер в противоположном направлении,
        обновляет статистику торговли и удаляет позицию из трекинга.

        Args:
            symbol: Торговый символ
            reason: Причина закрытия (stop_loss, take_profit, time_limit)

        Raises:
            Exception: При ошибках размещения ордера закрытия
        """
        # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА #1: Проверка лимита consecutive losses ДО закрытия
        if self.consecutive_losses >= self.max_consecutive_losses:
            logger.error(
                f"🛑 MAX CONSECUTIVE LOSSES ALREADY REACHED ({self.consecutive_losses})! "
                f"Bot stopped. NOT closing more positions to prevent emergency loop!"
            )
            self.active = False
            return  # НЕ закрываем позицию, НЕ вызываем emergency!

        # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА #2: Проверка активности бота
        if not self.active:
            logger.warning(f"🛑 Bot is not active, skipping position close for {symbol}")
            return

        position = self.positions.get(symbol)
        if not position:
            return

        try:
            # Получить текущую цену
            current_price = position.current_price
            tick = await self.client.get_ticker(symbol)
            if tick:
                # ✅ ИСПРАВЛЕНО: get_ticker возвращает dict, не объект Tick
                current_price = float(
                    tick.get("last", tick.get("lastPx", current_price))
                )

            # 🛡️ ЗАЩИТА #3: Проверка минимального размера для закрытия
            position_value = position.size * current_price

            if position_value < self.min_close_value_usd:
                logger.warning(
                    f"⚠️ {symbol} position too small to close: "
                    f"${position_value:.2f} < ${self.min_close_value_usd} - keeping open until grows or time limit"
                )
                return

            # Determine order side (opposite of position)
            order_side = (
                OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
            )

            # 🛡️ ЗАЩИТА #4: Проверка баланса ПЕРЕД закрытием (КРИТИЧНО!)
            base_currency = symbol.split("-")[0]  # BTC, ETH, и т.д.
            quote_currency = symbol.split("-")[1]  # USDT

            if position.side == PositionSide.LONG:
                # Для закрытия LONG нужно продать - проверяем базовую валюту (BTC/ETH)
                actual_balance = await self.client.get_balance(base_currency)

                if actual_balance < position.size * 0.99:  # -1% допуск на округление
                    # 🔧 ИСПРАВЛЕНИЕ: Проверяем время позиции перед удалением
                    time_since_open = (
                        datetime.utcnow() - position.timestamp
                    ).total_seconds()

                    if time_since_open < 300:  # Менее 5 минут
                        logger.warning(
                            f"⚠️ {symbol} LONG closed on exchange! "
                            f"Have {actual_balance:.8f} {base_currency}, "
                            f"was {position.size:.8f}. "
                            f"Age: {time_since_open:.0f}s - OCO TP/SL likely"
                        )
                        # Записываем как успешное закрытие
                        await self._record_trade_completion(
                            symbol, current_price, "oco_closed"
                        )
                        del self.positions[symbol]
                        return
                    else:
                        logger.error(
                            f"❌ {symbol} LONG is PHANTOM! "
                            f"Have {actual_balance:.8f}, shows {position.size:.8f}. "
                            f"Age: {time_since_open:.0f}s - removing!"
                        )
                        del self.positions[symbol]
                        return
            else:
                # Для закрытия SHORT нужно купить обратно - проверяем USDT
                required_usdt = position.size * current_price * 1.01  # +1% запас
                usdt_balance = await self.client.get_balance(quote_currency)

                if usdt_balance < required_usdt:
                    logger.error(
                        f"❌ Insufficient USDT to close SHORT {symbol}: "
                        f"Need ${required_usdt:.2f}, have ${usdt_balance:.2f} - cannot close!"
                    )
                    return  # НЕ пытаемся закрыть без средств!

            # 📊 УЛУЧШЕННОЕ ЛОГИРОВАНИЕ: Ордер на закрытие
            logger.info(
                f"🔴 CLOSING ORDER: {order_side.value} {position.size:.6f} {symbol} "
                f"@ ${current_price:.2f} (Reason: {reason})"
            )

            # Place market order to close position
            order = await self.client.place_order(
                symbol=symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=position.size,
            )

            if order:
                # 💰 УЧЁТ КОМИССИЙ: Рассчитываем реальный PnL с комиссиями
                commission_rate = 0.001  # 0.1% taker fee на OKX

                # Комиссия при открытии позиции
                open_commission = position.size * position.entry_price * commission_rate

                # Комиссия при закрытии позиции
                close_commission = position.size * current_price * commission_rate

                # Общая комиссия за сделку (туда-обратно)
                total_commission = open_commission + close_commission

                # PnL с учётом комиссий
                net_pnl = position.unrealized_pnl - total_commission

                # Update statistics
                self.total_trades += 1

                # 🛡️ УЛУЧШЕНИЕ 1: Отслеживание consecutive losses (с учётом комиссий!)
                if net_pnl > 0:
                    self.winning_trades += 1
                    self.consecutive_losses = 0  # Сброс при выигрыше
                    logger.info(f"✅ Win streak reset, consecutive losses: 0")
                else:
                    self.last_loss_time[symbol] = datetime.utcnow()
                    self.consecutive_losses += 1

                    # 🛡️ ЗАЩИТА: Ограничить максимум
                    if self.consecutive_losses > self.max_consecutive_losses:
                        self.consecutive_losses = self.max_consecutive_losses

                    logger.warning(
                        f"❌ Loss #{self.consecutive_losses} of "
                        f"{self.max_consecutive_losses}"
                    )

                    # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА #5: НЕ вызываем emergency при лимите!
                    if self.consecutive_losses >= self.max_consecutive_losses:
                        logger.error(
                            f"🛑 MAX CONSECUTIVE LOSSES REACHED: {self.consecutive_losses}! "
                            f"Bot will stop accepting new signals. Open positions will close naturally."
                        )
                        self.active = False
                        # УБРАНО: await self._emergency_close_all()  ← ЭТО ВЫЗЫВАЛО РЕКУРСИЮ!
                        # Вместо этого просто останавливаем новые сделки

                # Обновляем PnL с учётом комиссий
                self.daily_pnl += net_pnl

                # 📊 ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ РЕЗУЛЬТАТА СДЕЛКИ
                win_rate = (
                    (self.winning_trades / self.total_trades * 100)
                    if self.total_trades > 0
                    else 0
                )

                # Вычисляем время удержания
                holding_time = datetime.utcnow() - position.timestamp

                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                if net_pnl > 0:
                    logger.info(
                        f"✅ TRADE COMPLETED: {symbol} {position.side.value.upper()} | WIN"
                    )
                else:
                    logger.info(
                        f"❌ TRADE COMPLETED: {symbol} {position.side.value.upper()} | LOSS"
                    )
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                logger.info(f"   Reason: {reason.upper()}")
                logger.info(f"   Entry: ${position.entry_price:.2f}")
                logger.info(f"   Exit: ${current_price:.2f}")
                logger.info(f"   Size: {position.size:.8f} {symbol.split('-')[0]}")
                logger.info(f"   Holding time: {holding_time}")
                logger.info(f"   Gross PnL: ${position.unrealized_pnl:.2f}")
                logger.info(f"   Commission: ${total_commission:.2f}")
                logger.info(
                    f"   Net PnL: ${net_pnl:.2f} ({(net_pnl/position.entry_price/position.size)*100:.2f}%)"
                )
                logger.info(f"   Daily PnL: ${self.daily_pnl:.2f}")
                logger.info(
                    f"   Total trades: {self.total_trades} (Win rate: {win_rate:.1f}%)"
                )
                logger.info(f"   Consecutive losses: {self.consecutive_losses}")
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

                # 📊 Сохраняем сделку в историю
                trade_record = {
                    "timestamp": datetime.utcnow(),
                    "symbol": symbol,
                    "side": position.side.value.upper(),
                    "entry_price": position.entry_price,
                    "exit_price": current_price,
                    "size": position.size,
                    "holding_time": str(holding_time),
                    "gross_pnl": position.unrealized_pnl,
                    "commission": total_commission,
                    "net_pnl": net_pnl,
                    "reason": reason.upper(),
                    "result": "WIN" if net_pnl > 0 else "LOSS",
                }

                self.trade_history.append(trade_record)

                # Ограничиваем размер истории
                if len(self.trade_history) > self.max_history_size:
                    self.trade_history = self.trade_history[-self.max_history_size :]

                # Remove position
                del self.positions[symbol]

                # 🎯 Очистка partial TP info
                if symbol in self.position_partial_info:
                    del self.position_partial_info[symbol]

        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}")

    async def _monitor_positions(self) -> None:
        """Monitor positions and orders"""
        while self.active:
            try:
                # SPOT MODE: Не синхронизируем позиции с биржей
                # Позиции управляются только программно в памяти
                # exchange_positions = await self.client.get_positions()

                # НЕ синхронизируем - позиции остаются в памяти до закрытия по SL/TP
                # for pos in exchange_positions:
                #     if pos.symbol in self.config.symbols:
                #         self.positions[pos.symbol] = pos
                #
                # НЕ удаляем позиции - они закрываются только через _close_position
                # active_symbols = {pos.symbol for pos in exchange_positions}
                # closed_symbols = set(self.positions.keys()) - active_symbols
                # for symbol in closed_symbols:
                #     del self.positions[symbol]

                # Reset hourly trade count
                current_hour = datetime.utcnow().hour
                if not hasattr(self, "_last_hour") or self._last_hour != current_hour:
                    self.trade_count_hourly = 0
                    self._last_hour = current_hour

                await asyncio.sleep(30)  # Check every 30 seconds

            except Exception as e:
                logger.error(f"Error monitoring positions: {e}")
                await asyncio.sleep(15)  # Wait 15 seconds on error

    async def _emergency_close_all(self) -> None:
        """
        Emergency close all positions (WITHOUT recursion protection).

        🛡️ КРИТИЧЕСКАЯ ЗАЩИТА: Использует флаг _emergency_in_progress
        для предотвращения бесконечной рекурсии.
        """
        # 🛡️ ЗАЩИТА: Проверка на повторный вызов
        if self._emergency_in_progress:
            logger.warning(
                "⚠️ Emergency close already in progress - skipping duplicate call"
            )
            return

        self._emergency_in_progress = True
        logger.error("🚨 EMERGENCY CLOSE ALL POSITIONS INITIATED!")

        try:
            # Закрываем все позиции через отдельный метод БЕЗ обновления статистики
            for symbol in list(self.positions.keys()):
                await self._close_position_silent(symbol, "emergency")
        finally:
            self._emergency_in_progress = False
            logger.info("🚨 Emergency close completed")

    async def _record_trade_completion(
        self, symbol: str, exit_price: float, reason: str
    ) -> None:
        """
        Записать завершение сделки (когда OCO уже закрыл позицию на бирже).

        Обновляет статистику торговли без размещения ордера закрытия.

        Args:
            symbol: Торговая пара
            exit_price: Цена закрытия
            reason: Причина (take_profit_oco, stop_loss_oco)
        """
        position = self.positions.get(symbol)
        if not position:
            return

        try:
            base_currency = symbol.split("-")[0]

            # Расчет PnL
            if position.side == PositionSide.LONG:
                gross_pnl = (exit_price - position.entry_price) * position.size
            else:
                gross_pnl = (position.entry_price - exit_price) * position.size

            # Комиссии
            commission_rate = 0.001
            open_commission = position.size * position.entry_price * commission_rate
            close_commission = position.size * exit_price * commission_rate
            total_commission = open_commission + close_commission

            net_pnl = gross_pnl - total_commission

            # Update statistics
            self.total_trades += 1

            if net_pnl > 0:
                self.winning_trades += 1
                self.consecutive_losses = 0
                logger.info(f"✅ Win streak reset, consecutive losses: 0")
            else:
                self.last_loss_time[symbol] = datetime.utcnow()
                self.consecutive_losses += 1

                if self.consecutive_losses > self.max_consecutive_losses:
                    self.consecutive_losses = self.max_consecutive_losses

                logger.warning(
                    f"❌ Loss #{self.consecutive_losses} of {self.max_consecutive_losses}"
                )

                if self.consecutive_losses >= self.max_consecutive_losses:
                    logger.error(
                        f"🛑 MAX CONSECUTIVE LOSSES REACHED: {self.consecutive_losses}!"
                    )
                    self.active = False

            self.daily_pnl += net_pnl

            # Статистика по символу
            if symbol not in self.trade_stats_per_symbol:
                self.trade_stats_per_symbol[symbol] = {
                    "total": 0,
                    "wins": 0,
                    "losses": 0,
                    "pnl": 0.0,
                }

            self.trade_stats_per_symbol[symbol]["total"] += 1
            self.trade_stats_per_symbol[symbol]["pnl"] += net_pnl

            if net_pnl > 0:
                self.trade_stats_per_symbol[symbol]["wins"] += 1
            else:
                self.trade_stats_per_symbol[symbol]["losses"] += 1

            # Время удержания
            holding_time = datetime.utcnow() - position.timestamp
            win_rate = (
                (self.winning_trades / self.total_trades * 100)
                if self.total_trades > 0
                else 0
            )

            # Логирование
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            if net_pnl > 0:
                logger.info(
                    f"✅ TRADE COMPLETED: {symbol} {position.side.value.upper()} | WIN"
                )
            else:
                logger.info(
                    f"❌ TRADE COMPLETED: {symbol} {position.side.value.upper()} | LOSS"
                )
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"   Reason: {reason.upper()}")
            logger.info(f"   Entry: ${position.entry_price:.2f}")
            logger.info(f"   Exit: ${exit_price:.2f}")
            logger.info(f"   Size: {position.size:.8f} {base_currency}")
            logger.info(f"   Holding time: {holding_time}")
            logger.info(f"   Gross PnL: ${gross_pnl:.2f}")
            logger.info(f"   Commission: ${total_commission:.2f}")
            logger.info(
                f"   Net PnL: ${net_pnl:.2f} ({(net_pnl/position.entry_price/position.size*100):.2f}%)"
            )
            logger.info(f"   Daily PnL: ${self.daily_pnl:.2f}")
            logger.info(
                f"   Total trades: {self.total_trades} (Win rate: {win_rate:.1f}%)"
            )
            logger.info(f"   Consecutive losses: {self.consecutive_losses}")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # Сохраняем в историю
            self.trade_history.append(
                {
                    "symbol": symbol,
                    "side": position.side.value,
                    "entry_price": position.entry_price,
                    "exit_price": exit_price,
                    "size": position.size,
                    "pnl": net_pnl,
                    "timestamp": datetime.utcnow(),
                    "reason": reason,
                }
            )

            if len(self.trade_history) > self.max_history_size:
                self.trade_history = self.trade_history[-self.max_history_size :]

            # Remove position
            del self.positions[symbol]

            # Очистка partial TP info
            if symbol in self.position_partial_info:
                del self.position_partial_info[symbol]

        except Exception as e:
            logger.error(f"Error recording trade completion for {symbol}: {e}")

    async def _close_position_silent(self, symbol: str, reason: str) -> None:
        """
        Закрытие позиции БЕЗ обновления consecutive_losses (для emergency).

        Это предотвращает рекурсивный вызов _emergency_close_all().
        """
        position = self.positions.get(symbol)
        if not position:
            return

        try:
            # Получить текущую цену
            current_price = position.current_price
            tick = await self.client.get_ticker(symbol)
            if tick:
                current_price = tick.last

            # Определить направление ордера
            order_side = (
                OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
            )

            # 🛡️ ЗАЩИТА: Проверка баланса ПЕРЕД закрытием (даже в emergency!)
            base_currency = symbol.split("-")[0]
            quote_currency = symbol.split("-")[1]

            if position.side == PositionSide.LONG:
                # Для SELL нужен BTC/ETH
                actual_balance = await self.client.get_balance(base_currency)

                if actual_balance < position.size * 0.99:
                    logger.error(
                        f"❌ {symbol} PHANTOM LONG position in emergency! "
                        f"Cannot SELL: have {actual_balance:.8f} {base_currency}, "
                        f"need {position.size:.8f}. Removing phantom position!"
                    )
                    del self.positions[symbol]
                    return
            else:
                # Для BUY нужен USDT
                required_usdt = position.size * current_price * 1.01
                usdt_balance = await self.client.get_balance(quote_currency)

                if usdt_balance < required_usdt:
                    logger.error(
                        f"❌ Insufficient USDT to close SHORT {symbol} in emergency: "
                        f"Need ${required_usdt:.2f}, have ${usdt_balance:.2f}"
                    )
                    return

            logger.warning(
                f"🔇 SILENT CLOSE: {order_side.value} {position.size:.6f} {symbol} "
                f"@ ${current_price:.2f} (Reason: {reason})"
            )

            # Разместить ордер
            order = await self.client.place_order(
                symbol=symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=position.size,
            )

            if order:
                # НЕ обновляем consecutive_losses!
                # НЕ обновляем статистику!
                # Просто удаляем позицию
                del self.positions[symbol]

                if symbol in self.position_partial_info:
                    del self.position_partial_info[symbol]

                logger.info(f"🔇 Silent close completed: {symbol}")

        except Exception as e:
            logger.error(f"Error in silent close {symbol}: {e}")

    async def _log_trading_status(self, symbol: str, tick) -> None:
        """
        Вывод детальной статистики торговли в лог.

        Отображает текущее состояние:
        - Цену и торговый символ
        - Баланс аккаунта
        - Открытые ордера и позиции
        - Статистику сделок и win rate
        - Дневной PnL

        Args:
            symbol: Торговый символ
            tick: Текущий тик с рыночными данными

        Raises:
            Exception: При ошибках получения данных (логируется, не останавливает бота)
        """
        try:
            # Получаем баланс - показываем только USDT и монету из пары
            balances = await self.client.get_account_balance()

            # Извлекаем базовую валюту из пары (например BTC из BTC-USDT)
            base_currency = symbol.split("-")[0]  # BTC, ETH, SOL
            quote_currency = symbol.split("-")[1]  # USDT

            # Ищем нужные балансы
            balance_parts = []
            for b in balances:
                if b.currency == quote_currency:  # USDT
                    balance_parts.append(f"💵 {b.currency}: ${b.total:,.2f}")
                elif b.currency == base_currency:  # BTC, ETH, SOL
                    balance_parts.append(f"🪙 {b.currency}: {b.total:.6f}")

            balance_str = " | ".join(balance_parts) if balance_parts else "N/A"

            # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА: Проверка заёмных средств (MARGIN mode detection)
            try:
                borrowed_base = await self.client.get_borrowed_balance(base_currency)
                borrowed_quote = await self.client.get_borrowed_balance(quote_currency)

                if borrowed_base > 0 or borrowed_quote > 0:
                    logger.error(
                        f"🚨 BORROWED FUNDS DETECTED! "
                        f"{base_currency}: {borrowed_base:.6f} | {quote_currency}: ${borrowed_quote:.2f}"
                    )
                    logger.error(
                        "⛔ THIS SHOULD NOT HAPPEN IN SPOT MODE! "
                        "Switch Portfolio Mode to SPOT and repay loans IMMEDIATELY!"
                    )
                    # Останавливаем бота для безопасности
                    self.active = False
            except Exception as e:
                logger.debug(f"Could not check borrowed balance: {e}")

            # Получаем открытые ордера (опционально - требует Trade права)
            try:
                open_orders = await self.client.get_open_orders(symbol)
            except Exception as e:
                logger.debug(
                    f"Cannot fetch open orders (requires Trade permission): {e}"
                )
                open_orders = []

            # Текущие позиции
            position_info = "Нет позиций"
            position_emoji = "⚪"
            if symbol in self.positions:
                pos = self.positions[symbol]
                position_emoji = "🟢" if pos.side == PositionSide.LONG else "🔴"
                position_info = (
                    f"{pos.side.value} {pos.size:.6f} @ ${pos.entry_price:.2f}"
                )

            # Статистика стратегии
            win_rate = (
                (self.winning_trades / self.total_trades * 100)
                if self.total_trades > 0
                else 0
            )

            # Эмодзи для PnL
            pnl_emoji = (
                "💰" if self.daily_pnl > 0 else "📉" if self.daily_pnl < 0 else "➖"
            )

            # 🌊 Определение режима рынка для отображения
            market_regime = "N/A"
            if self.adaptive_regime:
                market_regime = self.adaptive_regime.current_regime.value.upper()

            # Подсчёт сделок по текущей паре
            symbol_trades = [t for t in self.trade_history if t["symbol"] == symbol]
            symbol_trades_count = len(symbol_trades)
            symbol_wins = len([t for t in symbol_trades if t["result"] == "WIN"])
            symbol_win_rate = (
                (symbol_wins / symbol_trades_count * 100)
                if symbol_trades_count > 0
                else 0
            )

            # Красивый вывод столбцом с новыми метриками
            logger.info(f"\n{'='*60}")
            logger.info(f"📈 ПАРА: {symbol}")
            logger.info(f"💵 ЦЕНА: ${tick.price:,.2f}")
            logger.info(f"💼 БАЛАНС: {balance_str}")
            logger.info(f"📋 ОТКРЫТЫЕ ОРДЕРА: {len(open_orders)}")
            logger.info(f"{position_emoji} ПОЗИЦИЯ: {position_info}")
            logger.info(
                f"📊 ВСЕГО СДЕЛОК: {self.total_trades} (Успешных: {win_rate:.1f}%)"
            )
            logger.info(
                f"🎯 СДЕЛОК ПО {symbol}: {symbol_trades_count} (Успешных: {symbol_win_rate:.1f}%)"
            )
            logger.info(f"{pnl_emoji} ДНЕВНОЙ PnL: ${self.daily_pnl:.2f}")
            logger.info(f"🛡️ CONSECUTIVE LOSSES: {self.consecutive_losses}")
            logger.info(f"🌊 MARKET REGIME: {market_regime}")
            logger.info(f"{'='*60}")

            # 📊 ТАБЛИЦА ПОСЛЕДНИХ СДЕЛОК (по этому символу)
            symbol_trades = [t for t in self.trade_history if t["symbol"] == symbol]
            if symbol_trades:
                logger.info(f"\n📋 ПОСЛЕДНИЕ СДЕЛКИ {symbol}:")
                logger.info(f"{'─'*60}")
                for trade in symbol_trades[-5:]:  # Последние 5 сделок по паре
                    result_emoji = "✅" if trade["result"] == "WIN" else "❌"
                    time_str = trade["timestamp"].strftime("%H:%M:%S")
                    logger.info(
                        f"{result_emoji} {time_str} | {trade['side']:5} | "
                        f"Entry ${trade['entry_price']:>10,.2f} → Exit ${trade['exit_price']:>10,.2f} | "
                        f"PnL ${trade['net_pnl']:>7.2f} | {trade['reason']}"
                    )
                logger.info(f"{'─'*60}\n")
            else:
                logger.info(f"\n📋 Нет завершенных сделок для {symbol}\n")

        except Exception as e:
            logger.error(f"Error logging trading status for {symbol}: {e}")

    def configure_enhancements(
        self,
        scoring: bool = True,
        max_consecutive_losses: int = 3,
        daily_profit_lock: float = 5.0,
        breakeven: bool = True,
        trailing_stop: bool = True,
        partial_tp: bool = True,
        session_filtering: bool = True,
        spread_filter: bool = True,
    ) -> None:
        """
        Настройка всех улучшений стратегии.

        Позволяет гибко включать/выключать различные улучшения
        и настраивать их параметры.

        Args:
            scoring: Включить scoring систему (рекомендуется)
            max_consecutive_losses: Максимум consecutive losses (0 = отключено)
            daily_profit_lock: Целевая дневная прибыль % (0 = отключено)
            breakeven: Включить break-even stop
            trailing_stop: Включить trailing stop
            partial_tp: Включить partial take profit (многоуровневый выход)
            session_filtering: Фильтр по торговым сессиям
            spread_filter: Фильтр по спреду

        Note:
            Market regime адаптация теперь управляется ARM (Adaptive Regime Manager)
        """
        self.scoring_enabled = scoring
        self.max_consecutive_losses = max_consecutive_losses
        self.daily_profit_target_percent = daily_profit_lock
        self.profit_lock_enabled = daily_profit_lock > 0
        self.breakeven_enabled = breakeven
        self.trailing_stop_enabled = trailing_stop
        self.partial_tp_enabled = partial_tp
        self.session_filtering_enabled = session_filtering
        self.spread_filter_enabled = spread_filter

        logger.info(
            f"✨ Strategy enhancements configured: "
            f"Scoring={scoring}, ConsecLoss={max_consecutive_losses}, "
            f"ProfitLock={daily_profit_lock}%, Trailing={trailing_stop}, "
            f"PartialTP={partial_tp}"
        )

    def stop(self) -> None:
        """Stop the strategy"""
        self.active = False

        # Log Balance Checker statistics
        if self.balance_checker:
            self.balance_checker.log_statistics()

        # Log ARM statistics
        if self.adaptive_regime:
            self.adaptive_regime.log_statistics()

        # Log regime switching statistics
        self.log_regime_statistics()

        logger.info("Scalping strategy stopped")

    def get_performance_stats(self) -> dict:
        """
        Получение расширенной статистики производительности.

        Включает базовые метрики и информацию о включённых улучшениях.

        Returns:
            dict: Словарь с метриками производительности
        """
        win_rate = (
            (self.winning_trades / self.total_trades * 100)
            if self.total_trades > 0
            else 0
        )

        # Расчёт profit factor
        if self.total_trades > 0:
            avg_win = (
                self.daily_pnl / self.winning_trades if self.winning_trades > 0 else 0
            )
            losing_trades = self.total_trades - self.winning_trades
            avg_loss = abs(self.daily_pnl) / losing_trades if losing_trades > 0 else 1
            profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        else:
            profit_factor = 0

        return {
            "strategy_id": self.strategy_id,
            "active": self.active,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": win_rate,
            "daily_pnl": self.daily_pnl,
            "open_positions": len(self.positions),
            "hourly_trade_count": self.trade_count_hourly,
            # 📊 Новые метрики от улучшений
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "profit_factor": profit_factor,
            "enhancements": {
                "scoring": self.scoring_enabled,
                "trailing_stop": self.trailing_stop_enabled,
                "partial_tp": self.partial_tp_enabled,
                "breakeven": self.breakeven_enabled,
                "session_filtering": self.session_filtering_enabled,
                "adaptive_regime_manager": self.adaptive_regime is not None,
                "spread_filter": self.spread_filter_enabled,
            },
        }
