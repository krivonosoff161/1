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
                        PositionSide, RiskMetrics, Signal, Tick)
from src.okx_client import OKXClient
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
        self.min_close_value_usd = 15.0  # Минимум $15 для закрытия позиции
        self.min_order_value_usd = 30.0  # Минимум $30 для открытия (с запасом)

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
        self.trade_overlaps_only = False  # ✅ ИЗМЕНЕНО: Торговать во ВСЕ активные сессии, не только в пересечения
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
        # ⚠️ ОТКЛЮЧЕНО: В режиме RANGING блокирует 100% сигналов скальпинга!
        self.regime_detection_enabled = False  # ❌ Отключаем для тестирования Phase 1
        self.high_volatility_threshold = 0.02  # 2% волатильность = высокая
        self.trend_threshold = 0.05  # 5% разница SMA50/200 = тренд

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
                self.daily_start_balance = sum(b.total for b in balances)
                logger.info(f"💼 Daily start balance: ${self.daily_start_balance:.2f}")

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
        Торговля конкретным символом с опросом раз в минуту.

        Использует polling вместо websocket stream для большей надежности
        и совместимости с 1-минутным таймфреймом стратегии.
        """
        logger.info(f"🎯 Starting scalping for {symbol} (polling mode)")

        try:
            # Получаем начальные рыночные данные
            await self._update_market_data(symbol)
            logger.info(f"✅ {symbol}: Initial market data loaded")

            # Polling loop - опрос раз в минуту
            while self.active:
                try:
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

                # Ждем 60 секунд до следующего опроса
                await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"❌ Fatal error trading {symbol}: {e}")

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

        # Check minimum volatility
        if atr.value < self.config.entry.min_volatility_atr:
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
                    f"(min={self.config.entry.min_volatility_atr})"
                )
            return None

        # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА: Фильтр RANGING режима (не торговать во флэте)
        if self.regime_detection_enabled:
            market_regime = self._detect_market_regime(symbol)

            if market_regime == "RANGING":
                logger.debug(
                    f"⚪ {symbol} RANGING market detected - skipping trade "
                    f"(flat market = high risk for scalping)"
                )
                return None  # НЕ генерируем сигнал во флэте!

        # 🎯 УЛУЧШЕНИЕ 4: Scoring система вместо "всё или ничего"
        if self.scoring_enabled:
            # Long сигнал - присваиваем баллы каждому условию
            long_score = 0
            long_score += (
                2 if (current_price > sma_fast.value > sma_slow.value) else 0
            )  # Тренд (2 балла)
            long_score += 2 if ema_fast.value > ema_slow.value else 0  # EMA (2)
            long_score += 2 if 30 < rsi.value < 70 else 0  # RSI (2)
            long_score += (
                2 if current_price <= bb.metadata["lower_band"] * 1.002 else 0
            )  # BB (2)
            long_score += (
                2 if volume.value >= self.config.entry.volume_threshold else 0
            )  # Volume (2)

            # 📊 УЛУЧШЕНИЕ 7: MACD confirmation (2 балла)
            macd_line = macd.metadata.get("macd_line", 0)
            macd_signal = macd.metadata.get("signal_line", 0)
            long_score += 2 if (macd_line > macd_signal and macd_line > 0) else 0

            # Short сигнал - присваиваем баллы
            short_score = 0
            short_score += 2 if (current_price < sma_fast.value < sma_slow.value) else 0
            short_score += 2 if ema_fast.value < ema_slow.value else 0
            short_score += 2 if 30 < rsi.value < 70 else 0
            short_score += (
                2 if current_price >= bb.metadata["upper_band"] * 0.998 else 0
            )
            short_score += (
                2 if volume.value >= self.config.entry.volume_threshold else 0
            )

            # 📊 УЛУЧШЕНИЕ 7: MACD confirmation (2 балла)
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

                # PHASE 1: Volatility Modes - адаптация порога scoring
            current_score_threshold = self.min_score_threshold
            if self.volatility_adapter and atr:
                # Рассчитываем текущую волатильность
                current_volatility = self.volatility_adapter.calculate_volatility(
                    atr.value, current_price
                )
                # Получаем адаптированные параметры
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
                    # Применяем бонус к обоим score (если есть сигнал)
                    if (
                        long_score >= current_score_threshold
                        and long_score > short_score
                    ):
                        long_score += vp_result.bonus
                        long_confidence = long_score / 12.0
                        logger.info(
                            f"✅ VOLUME PROFILE BONUS: {symbol} LONG | "
                            f"Reason: {vp_result.reason} | "
                            f"Bonus: +{vp_result.bonus} | New score: {long_score}/12"
                        )
                    elif (
                        short_score >= current_score_threshold
                        and short_score > long_score
                    ):
                        short_score += vp_result.bonus
                        short_confidence = short_score / 12.0
                        logger.info(
                            f"✅ VOLUME PROFILE BONUS: {symbol} SHORT | "
                            f"Reason: {vp_result.reason} | "
                            f"Bonus: +{vp_result.bonus} | New score: {short_score}/12"
                        )

            # PHASE 1: Pivot Points
            # Проверяем Pivot уровни (до MTF, так как может дать бонус к score)
            if self.pivot_filter:
                if long_score >= current_score_threshold and long_score > short_score:
                    # Проверяем LONG около Pivot уровней
                    pivot_result = await self.pivot_filter.check_entry(
                        symbol, current_price, "LONG"
                    )
                    if pivot_result.near_level and pivot_result.bonus > 0:
                        long_score += pivot_result.bonus
                        long_confidence = long_score / 12.0
                        logger.info(
                            f"✅ PIVOT BONUS: {symbol} LONG near {pivot_result.level_name} | "
                            f"Bonus: +{pivot_result.bonus} | New score: {long_score}/12"
                        )
                elif (
                    short_score >= current_score_threshold and short_score > long_score
                ):
                    # Проверяем SHORT около Pivot уровней
                    pivot_result = await self.pivot_filter.check_entry(
                        symbol, current_price, "SHORT"
                    )
                    if pivot_result.near_level and pivot_result.bonus > 0:
                        short_score += pivot_result.bonus
                        short_confidence = short_score / 12.0
                        logger.info(
                            f"✅ PIVOT BONUS: {symbol} SHORT near {pivot_result.level_name} | "
                            f"Bonus: +{pivot_result.bonus} | New score: {short_score}/12"
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

        # Check hourly trade limit
        if self.trade_count_hourly >= self.config.max_trades_per_hour:
            logger.debug(
                f"🚫 {symbol}: Hourly trade limit reached "
                f"({self.trade_count_hourly}/{self.config.max_trades_per_hour})"
            )
            return False

        # Check cooldown after loss
        if symbol in self.last_loss_time:
            cooldown_end = self.last_loss_time[symbol] + timedelta(
                minutes=self.config.cooldown_after_loss_minutes
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

            # Calculate stop loss and take profit
            atr_value = self.market_data_cache[signal.symbol]
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

            # Place order
            order = await self.client.place_order(
                symbol=signal.symbol,
                side=signal.side,
                order_type=OrderType.MARKET,
                quantity=position_size,
            )

            if order:
                self.pending_orders[order.id] = signal.symbol
                self.trade_count_hourly += 1
                self.last_trade_time[signal.symbol] = datetime.utcnow()

                # Create position with SL/TP levels
                position = Position(
                    id=order.id,
                    symbol=signal.symbol,
                    side=PositionSide.LONG
                    if signal.side == OrderSide.BUY
                    else PositionSide.SHORT,
                    entry_price=signal.price,
                    current_price=signal.price,
                    size=position_size,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    timestamp=datetime.utcnow(),
                )
                self.positions[signal.symbol] = position

                logger.info(
                    f"✅ Order placed: {signal.side.value} {position_size} "
                    f"{signal.symbol} @ {signal.price:.6f} "
                    f"(SL: {stop_loss:.6f}, TP: {take_profit:.6f})"
                )

        except Exception as e:
            logger.error(f"Error executing signal: {e}")

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

            # Calculate stop loss distance
            stop_distance = atr_result.value * self.config.exit.stop_loss_atr_multiplier

            # Position size = risk amount / stop distance
            position_size = risk_amount / stop_distance

            # Apply maximum position size limit
            max_position_value = base_balance * (
                self.risk_config.max_position_size_percent / 100
            )
            max_position_size = max_position_value / price

            final_position_size = min(position_size, max_position_size)

            # 🌊 УЛУЧШЕНИЕ 9: Корректировка размера по market regime
            if self.regime_detection_enabled:
                regime = self._detect_market_regime(symbol)

                # Мультипликаторы для разных режимов
                if regime == "HIGH_VOLATILITY":
                    final_position_size *= 0.7  # Уменьшаем на 30% в волатильности
                    logger.info(f"🌊 HIGH VOLATILITY detected, reducing size by 30%")
                elif regime == "TRENDING":
                    final_position_size *= 1.2  # Увеличиваем на 20% на тренде
                    logger.info(f"🌊 TRENDING market detected, increasing size by 20%")
                # RANGING - без изменений (1.0)

            # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА: Проверка минимального размера ордера
            # OKX минимум ~$10, берем $30 с запасом +2% (учитываем комиссии и движение цены)
            position_value_usd = final_position_size * price
            logger.info(
                f"📊 Final position size: {final_position_size:.6f} = ${position_value_usd:.2f} (min: ${self.min_order_value_usd})"
            )

            if position_value_usd < self.min_order_value_usd:
                # Увеличиваем размер до минимума $30 + 2% запас
                final_position_size = (self.min_order_value_usd * 1.02) / price
                final_value = final_position_size * price
                logger.info(
                    f"⬆️ {symbol} Position size increased to meet ${self.min_order_value_usd} minimum: "
                    f"{final_position_size:.6f} (${final_value:.2f} with 2% buffer)"
                )

            return final_position_size

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
        мультипликаторами из конфигурации.

        Args:
            entry_price: Цена входа в позицию
            side: Направление сделки (BUY/SELL)
            atr: Значение ATR для расчета расстояния

        Returns:
            tuple: (stop_loss_price, take_profit_price)
        """
        stop_distance = atr * self.config.exit.stop_loss_atr_multiplier
        profit_distance = atr * self.config.exit.take_profit_atr_multiplier

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

        # Check time-based exit
        holding_time = datetime.utcnow() - position.timestamp
        if holding_time.seconds / 60 > self.config.exit.max_holding_minutes:
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
                current_price = tick.last

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

            # 🛡️ ЗАЩИТА #4: Проверка баланса для закрытия SHORT
            if position.side == PositionSide.SHORT:
                # Для закрытия SHORT нужно купить обратно - проверяем USDT
                required_usdt = position.size * current_price * 1.01  # +1% запас
                base_currency = "USDT"
                base_balance = await self.client.get_balance(base_currency)

                if base_balance < required_usdt:
                    logger.error(
                        f"❌ Insufficient USDT to close SHORT {symbol}: "
                        f"Need ${required_usdt:.2f}, have ${base_balance:.2f} - cannot close!"
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

                # Remove position
                del self.positions[symbol]

                # 🎯 Очистка partial TP info
                if symbol in self.position_partial_info:
                    del self.position_partial_info[symbol]

                # 📊 УЛУЧШЕННОЕ ЛОГИРОВАНИЕ: Детали закрытия с комиссиями
                win_rate = (
                    (self.winning_trades / self.total_trades * 100)
                    if self.total_trades > 0
                    else 0.0
                )
                logger.info(
                    f"✅ Position closed: {symbol} {reason} | "
                    f"Gross PnL: ${position.unrealized_pnl:.4f} | "
                    f"Commission: -${total_commission:.4f} | "
                    f"NET PnL: ${net_pnl:.4f} | "
                    f"Win rate: {win_rate:.1f}%"
                )

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
                await asyncio.sleep(60)  # Wait longer on error

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

            # 🌊 УЛУЧШЕНИЕ 9: Определение режима рынка для отображения
            market_regime = "N/A"
            if self.regime_detection_enabled:
                market_regime = self._detect_market_regime(symbol)

            # Красивый вывод столбцом с новыми метриками
            logger.info(f"\n{'='*60}")
            logger.info(f"📈 ПАРА: {symbol}")
            logger.info(f"💵 ЦЕНА: ${tick.price:,.2f}")
            logger.info(f"💼 БАЛАНС: {balance_str}")
            logger.info(f"📋 ОТКРЫТЫЕ ОРДЕРА: {len(open_orders)}")
            logger.info(f"{position_emoji} ПОЗИЦИЯ: {position_info}")
            logger.info(f"📊 СДЕЛКИ: {self.total_trades} (Успешных: {win_rate:.1f}%)")
            logger.info(f"{pnl_emoji} ДНЕВНОЙ PnL: ${self.daily_pnl:.2f}")
            logger.info(f"🛡️ CONSECUTIVE LOSSES: {self.consecutive_losses}")
            logger.info(f"🌊 MARKET REGIME: {market_regime}")
            logger.info(f"{'='*60}\n")

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
        market_regime: bool = True,
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
            market_regime: Адаптация размера по режиму рынка
            spread_filter: Фильтр по спреду
        """
        self.scoring_enabled = scoring
        self.max_consecutive_losses = max_consecutive_losses
        self.daily_profit_target_percent = daily_profit_lock
        self.profit_lock_enabled = daily_profit_lock > 0
        self.breakeven_enabled = breakeven
        self.trailing_stop_enabled = trailing_stop
        self.partial_tp_enabled = partial_tp
        self.session_filtering_enabled = session_filtering
        self.regime_detection_enabled = market_regime
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
                "market_regime": self.regime_detection_enabled,
                "spread_filter": self.spread_filter_enabled,
            },
        }
