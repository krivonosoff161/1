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

from src.config import RiskConfig, ScalpingConfig
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
        self, client: OKXClient, config: ScalpingConfig, risk_config: RiskConfig
    ):
        """
        Инициализация оркестратора.

        Args:
            client: OKX клиент
            config: Scalping конфигурация
            risk_config: Risk конфигурация
        """
        self.client = client
        self.config = config
        self.risk_config = risk_config
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
        """Создание конфигурации ARM из config.yaml"""
        # TODO: Реализовать полную загрузку из config
        # Пока используем дефолтные значения
        from src.strategies.modules.adaptive_regime_manager import RegimeType

        # Загружаем параметры из config.adaptive_regime
        arm_settings = self.config.adaptive_regime

        # Создаем параметры для каждого режима
        # (Это упрощенная версия - полная логика в старом scalping.py)

        trending_params = RegimeParameters(
            min_score_threshold=arm_settings.get("trending", {}).get(
                "min_score_threshold", 6
            ),
            max_trades_per_hour=arm_settings.get("trending", {}).get(
                "max_trades_per_hour", 20
            ),
            position_size_multiplier=arm_settings.get("trending", {}).get(
                "position_size_multiplier", 1.2
            ),
            tp_atr_multiplier=arm_settings.get("trending", {}).get(
                "tp_atr_multiplier", 1.5
            ),
            sl_atr_multiplier=arm_settings.get("trending", {}).get(
                "sl_atr_multiplier", 1.25
            ),
            max_holding_minutes=arm_settings.get("trending", {}).get(
                "max_holding_minutes", 10
            ),
            cooldown_after_loss_minutes=arm_settings.get("trending", {}).get(
                "cooldown_after_loss_minutes", 2
            ),
            pivot_bonus_multiplier=arm_settings.get("trending", {}).get(
                "pivot_bonus_multiplier", 1.5
            ),
            volume_profile_bonus_multiplier=arm_settings.get("trending", {}).get(
                "volume_profile_bonus_multiplier", 1.0
            ),
            indicators=IndicatorParameters(
                rsi_overbought=70,
                rsi_oversold=30,
                volume_threshold=1.05,
                sma_fast=8,
                sma_slow=25,
                ema_fast=8,
                ema_slow=21,
                atr_period=14,
                min_volatility_atr=0.0003,
            ),
            modules=ModuleParameters(
                mtf_block_opposite=False,
                mtf_score_bonus=1,
                mtf_confirmation_timeframe="30m",
                correlation_threshold=0.8,
                max_correlated_positions=3,
                block_same_direction_only=False,
                prefer_overlaps=True,
                avoid_low_liquidity_hours=False,
                pivot_level_tolerance_percent=0.4,
                pivot_score_bonus_near_level=1,
                pivot_use_last_n_days=3,
                vp_score_bonus_in_value_area=1,
                vp_score_bonus_near_poc=1,
                vp_poc_tolerance_percent=0.4,
                vp_lookback_candles=100,
                avoid_weekends=True,
            ),
        )

        ranging_params = RegimeParameters(
            min_score_threshold=arm_settings.get("ranging", {}).get(
                "min_score_threshold", 3
            ),
            max_trades_per_hour=arm_settings.get("ranging", {}).get(
                "max_trades_per_hour", 10
            ),
            position_size_multiplier=arm_settings.get("ranging", {}).get(
                "position_size_multiplier", 1.0
            ),
            tp_atr_multiplier=arm_settings.get("ranging", {}).get(
                "tp_atr_multiplier", 1.25
            ),
            sl_atr_multiplier=arm_settings.get("ranging", {}).get(
                "sl_atr_multiplier", 1.0
            ),
            max_holding_minutes=arm_settings.get("ranging", {}).get(
                "max_holding_minutes", 5
            ),
            cooldown_after_loss_minutes=arm_settings.get("ranging", {}).get(
                "cooldown_after_loss_minutes", 5
            ),
            pivot_bonus_multiplier=arm_settings.get("ranging", {}).get(
                "pivot_bonus_multiplier", 1.5
            ),
            volume_profile_bonus_multiplier=arm_settings.get("ranging", {}).get(
                "volume_profile_bonus_multiplier", 1.5
            ),
            indicators=IndicatorParameters(
                rsi_overbought=70,
                rsi_oversold=30,
                volume_threshold=1.1,
                sma_fast=10,
                sma_slow=30,
                ema_fast=10,
                ema_slow=30,
                atr_period=14,
                min_volatility_atr=0.0005,
            ),
            modules=ModuleParameters(
                mtf_block_opposite=True,
                mtf_score_bonus=2,
                mtf_confirmation_timeframe="15m",
                correlation_threshold=0.7,
                max_correlated_positions=2,
                block_same_direction_only=True,
                prefer_overlaps=True,
                avoid_low_liquidity_hours=True,
                pivot_level_tolerance_percent=0.25,
                pivot_score_bonus_near_level=2,
                pivot_use_last_n_days=5,
                vp_score_bonus_in_value_area=2,
                vp_score_bonus_near_poc=2,
                vp_poc_tolerance_percent=0.25,
                vp_lookback_candles=200,
                avoid_weekends=True,
            ),
        )

        choppy_params = RegimeParameters(
            min_score_threshold=arm_settings.get("choppy", {}).get(
                "min_score_threshold", 5
            ),
            max_trades_per_hour=arm_settings.get("choppy", {}).get(
                "max_trades_per_hour", 4
            ),
            position_size_multiplier=arm_settings.get("choppy", {}).get(
                "position_size_multiplier", 0.6
            ),
            tp_atr_multiplier=arm_settings.get("choppy", {}).get(
                "tp_atr_multiplier", 1.0
            ),
            sl_atr_multiplier=arm_settings.get("choppy", {}).get(
                "sl_atr_multiplier", 0.75
            ),
            max_holding_minutes=arm_settings.get("choppy", {}).get(
                "max_holding_minutes", 3
            ),
            cooldown_after_loss_minutes=arm_settings.get("choppy", {}).get(
                "cooldown_after_loss_minutes", 15
            ),
            pivot_bonus_multiplier=arm_settings.get("choppy", {}).get(
                "pivot_bonus_multiplier", 2.0
            ),
            volume_profile_bonus_multiplier=arm_settings.get("choppy", {}).get(
                "volume_profile_bonus_multiplier", 2.0
            ),
            indicators=IndicatorParameters(
                rsi_overbought=65,
                rsi_oversold=35,
                volume_threshold=1.25,
                sma_fast=8,
                sma_slow=25,
                ema_fast=8,
                ema_slow=21,
                atr_period=14,
                min_volatility_atr=0.0004,
            ),
            modules=ModuleParameters(
                mtf_block_opposite=False,
                mtf_score_bonus=2,
                mtf_confirmation_timeframe="15m",
                correlation_threshold=0.6,
                max_correlated_positions=1,
                block_same_direction_only=True,
                prefer_overlaps=True,
                avoid_low_liquidity_hours=True,
                pivot_level_tolerance_percent=0.2,
                pivot_score_bonus_near_level=3,
                pivot_use_last_n_days=5,
                vp_score_bonus_in_value_area=3,
                vp_score_bonus_near_poc=3,
                vp_poc_tolerance_percent=0.15,
                vp_lookback_candles=300,
                avoid_weekends=True,
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
        # 1. Rate limit
        await self._check_rate_limit()

        # 2. Обновление рыночных данных
        await self._update_market_data(symbol)

        # 3. Получение текущей цены
        try:
            ticker = await self.client.get_ticker(symbol)
            current_price = float(ticker.get("last", 0))
        except Exception as e:
            logger.error(f"Failed to get ticker for {symbol}: {e}")
            return

        # 4. Мониторинг существующих позиций
        if symbol in self.positions:
            current_prices = {symbol: current_price}
            to_close = await self.position_manager.monitor_positions(
                {symbol: self.positions[symbol]}, current_prices
            )

            for close_symbol, reason in to_close:
                await self._close_position(close_symbol, current_price, reason)

            return  # Если есть позиция - не открываем новую

        # 5. Проверка можно ли торговать
        stats = self.performance_tracker.get_stats()
        can_trade, reason = self.risk_controller.can_trade(
            symbol, self.positions, stats
        )

        if not can_trade:
            logger.debug(f"🚫 {symbol}: Cannot trade - {reason}")
            return

        # 6. Генерация сигнала
        market_data = self.market_data_cache.get(symbol)
        if not market_data:
            return

        indicators = self.indicators.calculate_all(market_data)

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
            await self.signal_generator.update_regime_parameters(
                market_data.ohlcv_data, current_price
            )

        signal = await self.signal_generator.generate_signal(
            symbol, indicators, tick, self.positions
        )

        if not signal:
            return

        # 7. Исполнение сигнала
        position = await self.order_executor.execute_signal(signal, market_data)

        if position:
            self.positions[symbol] = position
            self.risk_controller.record_trade_opened(symbol)
            logger.info(f"✅ Position added to tracking: {symbol}")

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
                f"⚠️ API rate limit reached ({self.api_requests_count}/{self.max_requests_per_minute}) - "
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
