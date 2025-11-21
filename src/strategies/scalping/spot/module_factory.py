"""
Фабрика модулей для Spot стратегии.

Ответственность:
- Инициализация Phase 1 модулей (MTF, Correlation, ADX, Pivot, VP, Balance, Time, ARM)
- Создание конфигураций модулей
- Централизация логики инициализации
"""

from typing import Dict

from loguru import logger

from src.filters.time_session_manager import (TimeFilterConfig,
                                              TimeSessionManager)
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


class ModuleFactory:
    """
    Фабрика для создания и инициализации модулей стратегии.

    Централизует логику инициализации всех Phase 1 модулей.
    """

    def __init__(self, client, config):
        """
        Args:
            client: OKX клиент
            config: Scalping конфигурация
        """
        self.client = client
        self.config = config

    def create_phase1_modules(self) -> Dict:
        """
        Инициализация Phase 1 модулей.

        Returns:
            Dict с модулями
        """
        modules = {}

        # Multi-Timeframe
        modules["mtf"] = self._create_mtf_module()

        # Correlation Filter
        modules["correlation"] = self._create_correlation_module()

        # ADX Filter
        modules["adx"] = self._create_adx_module()

        # Pivot Points
        modules["pivot"] = self._create_pivot_module()

        # Volume Profile
        modules["vp"] = self._create_volume_profile_module()

        # Balance Checker
        modules["balance"] = self._create_balance_module()

        # Time Filter
        modules["time"] = self._create_time_module()

        # ARM - Adaptive Regime Manager
        modules["arm"] = self._create_arm_module()

        return modules

    def _create_mtf_module(self):
        """Создание Multi-Timeframe Filter"""
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
            logger.info("✅ Multi-Timeframe Filter enabled")
            return MultiTimeframeFilter(self.client, mtf_config)
        else:
            logger.info("⚪ Multi-Timeframe Filter disabled")
            return None

    def _create_correlation_module(self):
        """Создание Correlation Filter"""
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
            logger.info("✅ Correlation Filter enabled")
            return CorrelationFilter(self.client, corr_config, self.config.symbols)
        else:
            logger.info("⚪ Correlation Filter disabled")
            return None

    def _create_adx_module(self):
        """Создание ADX Filter"""
        if (
            hasattr(self.config, "adx_filter_enabled")
            and self.config.adx_filter_enabled
        ):
            from src.strategies.modules.adx_filter import (ADXFilter,
                                                           ADXFilterConfig)

            adx_config = ADXFilterConfig(
                enabled=True,
                adx_threshold=self.config.adx_filter.get("adx_threshold", 25.0),
                di_difference=self.config.adx_filter.get("di_difference", 1.5),
                adx_period=self.config.adx_filter.get("adx_period", 14),
                timeframe=self.config.adx_filter.get("timeframe", "15m"),
            )
            logger.info("✅ ADX Filter enabled")
            return ADXFilter(adx_config)
        else:
            logger.info("⚪ ADX Filter disabled")
            return None

    def _create_pivot_module(self):
        """Создание Pivot Points Filter"""
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
            logger.info("✅ Pivot Points Filter enabled")
            return PivotPointsFilter(self.client, pivot_config)
        else:
            logger.info("⚪ Pivot Points Filter disabled")
            return None

    def _create_volume_profile_module(self):
        """Создание Volume Profile Filter"""
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
            logger.info("✅ Volume Profile Filter enabled")
            return VolumeProfileFilter(self.client, vp_config)
        else:
            logger.info("⚪ Volume Profile Filter disabled")
            return None

    def _create_balance_module(self):
        """Создание Balance Checker"""
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
            logger.info("✅ Balance Checker enabled")
            return BalanceChecker(balance_config)
        else:
            logger.info("⚪ Balance Checker disabled")
            return None

    def _create_time_module(self):
        """Создание Time Filter"""
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
            logger.info("✅ Time Filter enabled")
            return TimeSessionManager(time_config)
        else:
            logger.info("⚪ Time Filter disabled")
            return None

    def _create_arm_module(self):
        """Создание ARM - Adaptive Regime Manager"""
        if (
            hasattr(self.config, "adaptive_regime_enabled")
            and self.config.adaptive_regime_enabled
        ):
            # Создаем параметры для каждого режима из config
            arm_config = self._create_arm_config()
            logger.info("✅ Adaptive Regime Manager enabled")
            return AdaptiveRegimeManager(arm_config)
        else:
            logger.info("⚪ Adaptive Regime Manager disabled")
            return None

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

        ranging_cfg = arm_settings.get("ranging", {})
        ranging_indicators = ranging_cfg.get("indicators", {})
        ranging_modules = ranging_cfg.get("modules", {})

        choppy_cfg = arm_settings.get("choppy", {})
        choppy_indicators = choppy_cfg.get("indicators", {})
        choppy_modules = choppy_cfg.get("modules", {})

        # Создаем RegimeParameters для каждого режима
        trending = RegimeParameters(
            name="TRENDING",
            indicators=IndicatorParameters(
                rsi_period=trending_indicators.get("rsi_period", 14),
                rsi_overbought=trending_indicators.get("rsi_overbought", 70),
                rsi_oversold=trending_indicators.get("rsi_oversold", 30),
                sma_fast=trending_indicators.get("sma_fast", 8),
                sma_slow=trending_indicators.get("sma_slow", 21),
                ema_fast=trending_indicators.get("ema_fast", 8),
                ema_slow=trending_indicators.get("ema_slow", 21),
                bollinger_period=trending_indicators.get("bollinger_period", 20),
                bollinger_std=trending_indicators.get("bollinger_std", 2.0),
                atr_period=trending_indicators.get("atr_period", 14),
            ),
            modules=ModuleParameters(
                mtf_enabled=trending_modules.get("mtf_enabled", True),
                mtf_score_bonus=trending_modules.get("mtf_score_bonus", 3),
                correlation_enabled=trending_modules.get("correlation_enabled", True),
                correlation_max_positions=trending_modules.get(
                    "correlation_max_positions", 1
                ),
                pivot_enabled=trending_modules.get("pivot_enabled", True),
                pivot_score_bonus=trending_modules.get("pivot_score_bonus", 2),
                vp_enabled=trending_modules.get("vp_enabled", True),
                vp_score_bonus=trending_modules.get("vp_score_bonus", 2),
            ),
            min_signal_strength=trending_cfg.get("min_signal_strength", 8.0),
            tp_atr_multiplier=trending_cfg.get("tp_atr_multiplier", 3.0),
            sl_atr_multiplier=trending_cfg.get("sl_atr_multiplier", 1.5),
            max_holding_minutes=trending_cfg.get("max_holding_minutes", 30),
            ph_enabled=trending_cfg.get("ph_enabled", True),
            ph_threshold=trending_cfg.get("ph_threshold", 0.16),
            ph_time_limit=trending_cfg.get("ph_time_limit", 60),
            hourly_trade_limit=trending_cfg.get("hourly_trade_limit", 4),
        )

        ranging = RegimeParameters(
            name="RANGING",
            indicators=IndicatorParameters(
                rsi_period=ranging_indicators.get("rsi_period", 14),
                rsi_overbought=ranging_indicators.get("rsi_overbought", 65),
                rsi_oversold=ranging_indicators.get("rsi_oversold", 35),
                sma_fast=ranging_indicators.get("sma_fast", 10),
                sma_slow=ranging_indicators.get("sma_slow", 30),
                ema_fast=ranging_indicators.get("ema_fast", 10),
                ema_slow=ranging_indicators.get("ema_slow", 30),
                bollinger_period=ranging_indicators.get("bollinger_period", 20),
                bollinger_std=ranging_indicators.get("bollinger_std", 2.0),
                atr_period=ranging_indicators.get("atr_period", 14),
            ),
            modules=ModuleParameters(
                mtf_enabled=ranging_modules.get("mtf_enabled", True),
                mtf_score_bonus=ranging_modules.get("mtf_score_bonus", 2),
                correlation_enabled=ranging_modules.get("correlation_enabled", True),
                correlation_max_positions=ranging_modules.get(
                    "correlation_max_positions", 2
                ),
                pivot_enabled=ranging_modules.get("pivot_enabled", True),
                pivot_score_bonus=ranging_modules.get("pivot_score_bonus", 2),
                vp_enabled=ranging_modules.get("vp_enabled", True),
                vp_score_bonus=ranging_modules.get("vp_score_bonus", 2),
            ),
            min_signal_strength=ranging_cfg.get("min_signal_strength", 6.0),
            tp_atr_multiplier=ranging_cfg.get("tp_atr_multiplier", 2.0),
            sl_atr_multiplier=ranging_cfg.get("sl_atr_multiplier", 1.5),
            max_holding_minutes=ranging_cfg.get("max_holding_minutes", 20),
            ph_enabled=ranging_cfg.get("ph_enabled", True),
            ph_threshold=ranging_cfg.get("ph_threshold", 0.20),
            ph_time_limit=ranging_cfg.get("ph_time_limit", 120),
            hourly_trade_limit=ranging_cfg.get("hourly_trade_limit", 6),
        )

        choppy = RegimeParameters(
            name="CHOPPY",
            indicators=IndicatorParameters(
                rsi_period=choppy_indicators.get("rsi_period", 14),
                rsi_overbought=choppy_indicators.get("rsi_overbought", 60),
                rsi_oversold=choppy_indicators.get("rsi_oversold", 40),
                sma_fast=choppy_indicators.get("sma_fast", 12),
                sma_slow=choppy_indicators.get("sma_slow", 40),
                ema_fast=choppy_indicators.get("ema_fast", 12),
                ema_slow=choppy_indicators.get("ema_slow", 40),
                bollinger_period=choppy_indicators.get("bollinger_period", 20),
                bollinger_std=choppy_indicators.get("bollinger_std", 2.5),
                atr_period=choppy_indicators.get("atr_period", 14),
            ),
            modules=ModuleParameters(
                mtf_enabled=choppy_modules.get("mtf_enabled", True),
                mtf_score_bonus=choppy_modules.get("mtf_score_bonus", 3),
                correlation_enabled=choppy_modules.get("correlation_enabled", True),
                correlation_max_positions=choppy_modules.get(
                    "correlation_max_positions", 1
                ),
                pivot_enabled=choppy_modules.get("pivot_enabled", True),
                pivot_score_bonus=choppy_modules.get("pivot_score_bonus", 3),
                vp_enabled=choppy_modules.get("vp_enabled", True),
                vp_score_bonus=choppy_modules.get("vp_score_bonus", 3),
            ),
            min_signal_strength=choppy_cfg.get("min_signal_strength", 10.0),
            tp_atr_multiplier=choppy_cfg.get("tp_atr_multiplier", 1.5),
            sl_atr_multiplier=choppy_cfg.get("sl_atr_multiplier", 1.0),
            max_holding_minutes=choppy_cfg.get("max_holding_minutes", 15),
            ph_enabled=choppy_cfg.get("ph_enabled", True),
            ph_threshold=choppy_cfg.get("ph_threshold", 0.25),
            ph_time_limit=choppy_cfg.get("ph_time_limit", 180),
            hourly_trade_limit=choppy_cfg.get("hourly_trade_limit", 3),
        )

        # Создаем RegimeConfig
        config = RegimeConfig(
            trending=trending,
            ranging=ranging,
            choppy=choppy,
            volatility_lookback=arm_settings.get("volatility_lookback", 100),
            regime_switch_threshold=arm_settings.get("regime_switch_threshold", 0.15),
        )

        logger.info("✅ ARM Config created from config.yaml")
        return config
