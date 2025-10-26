"""
WebSocket Orchestrator для OKX Trading Bot
Real-time скальпинг стратегия с WebSocket подключением
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.balance import (AdaptiveBalanceManager, BalanceProfileConfig,
                         BalanceUpdateEvent)
from src.clients.spot_client import OKXClient
from src.config import BotConfig
from src.indicators import TechnicalIndicators
from src.risk.risk_controller import RiskController
from src.strategies.modules.adaptive_regime_manager import \
    AdaptiveRegimeManager
from src.strategies.modules.adx_filter import ADXFilter
from src.strategies.modules.balance_checker import BalanceChecker
from src.strategies.modules.correlation_filter import CorrelationFilter
from src.strategies.modules.multi_timeframe import MultiTimeframeFilter
from src.strategies.modules.pivot_points import PivotPointsFilter
from src.strategies.modules.volume_profile_filter import VolumeProfileFilter
from src.websocket_manager import (PriceData, WebSocketConfig,
                                   WebSocketPriceManager, get_latency_monitor,
                                   get_websocket_manager, initialize_websocket)

from .order_executor import OrderExecutor
from .performance_tracker import PerformanceTracker
from .position_manager import PositionManager
from .signal_generator import SignalGenerator

logger = logging.getLogger(__name__)


@dataclass
class WebSocketTradingState:
    """Состояние торговли для WebSocket режима"""

    current_prices: Dict[str, float] = None
    last_update_time: Dict[str, float] = None
    is_processing: bool = False
    last_signal_time: float = 0
    signal_cooldown: float = 1.0  # Минимальная задержка между сигналами

    def __post_init__(self):
        if self.current_prices is None:
            self.current_prices = {}
        if self.last_update_time is None:
            self.last_update_time = {}


class WebSocketScalpingOrchestrator:
    """WebSocket Orchestrator для скальпинг стратегии"""

    def __init__(self, config: BotConfig, okx_client: OKXClient):
        self.config = config
        self.okx_client = okx_client
        self.is_running = False
        self.test_mode = False
        self.trading_state = WebSocketTradingState()

        # WebSocket компоненты
        self.websocket_manager: Optional[WebSocketPriceManager] = None
        self.latency_monitor = None

        # Адаптивный баланс
        self.balance_manager: Optional[AdaptiveBalanceManager] = None

        # Торговые модули
        self.indicators = None
        self.arm = None
        self.signal_generator = None
        self.order_executor = None
        self.position_manager = None
        self.performance_tracker = None
        self.risk_controller = None

        # Фильтры
        self.mtf_filter = None
        self.correlation_filter = None
        self.adx_filter = None
        self.pivot_filter = None
        self.volume_filter = None
        self.balance_checker = None

        # Статистика
        self.stats = {
            "signals_generated": 0,
            "signals_processed": 0,
            "signals_rejected": 0,
            "websocket_errors": 0,
            "last_price_update": 0,
            "avg_latency": 0.0,
        }

        self._setup_components()

    def _setup_components(self):
        """Настройка всех компонентов"""
        logger.info("🔧 Setting up WebSocket components...")

        # Инициализация WebSocket
        websocket_config = WebSocketConfig(
            url="wss://ws.okx.com:8443/ws/v5/public",
            ping_interval=20,
            ping_timeout=10,
            close_timeout=10,
            max_size=2**20,
            reconnect_interval=5,
            max_reconnect_attempts=10,
        )

        # Создаем WebSocket Manager напрямую
        from src.websocket_manager import WebSocketPriceManager

        self.websocket_manager = WebSocketPriceManager(websocket_config)
        self.latency_monitor = None  # Пока отключаем

        # Настройка callbacks
        self.websocket_manager.add_price_callback(self._on_price_update)
        self.websocket_manager.add_error_callback(self._on_websocket_error)

        if self.latency_monitor:
            self.latency_monitor.add_warning_callback(self._on_latency_warning)
            self.latency_monitor.add_critical_callback(self._on_latency_critical)

        # Инициализация адаптивного баланса
        self._init_balance_manager()

        # Инициализация торговых модулей
        self._init_trading_modules()

        logger.info("✅ WebSocket components setup complete")

    def _init_balance_manager(self):
        """Инициализация адаптивного баланс менеджера"""
        logger.info("💰 Initializing Adaptive Balance Manager...")

        try:
            # Загружаем профили из конфигурации
            if self.config.balance_profiles:
                profiles = {}
                for name, profile_config in self.config.balance_profiles.items():
                    # Проверяем тип profile_config
                    if isinstance(profile_config, dict):
                        profiles[name] = BalanceProfileConfig(
                            threshold=profile_config["threshold"],
                            base_position_size=profile_config["base_position_size"],
                            min_position_size=profile_config["min_position_size"],
                            max_position_size=profile_config["max_position_size"],
                            max_open_positions=profile_config["max_open_positions"],
                            max_position_percent=profile_config["max_position_percent"],
                            trending_boost=profile_config["trending_boost"],
                            ranging_boost=profile_config["ranging_boost"],
                            choppy_boost=profile_config["choppy_boost"],
                        )
                    else:
                        # Уже BalanceProfileConfig объект
                        profiles[name] = profile_config

                self.balance_manager = AdaptiveBalanceManager(profiles)
                logger.info(
                    "✅ Adaptive Balance Manager initialized with config profiles"
                )
            else:
                # Используем профили по умолчанию
                from src.balance import create_default_profiles

                profiles = create_default_profiles()
                self.balance_manager = AdaptiveBalanceManager(profiles)
                logger.info(
                    "✅ Adaptive Balance Manager initialized with default profiles"
                )

        except Exception as e:
            logger.error(f"❌ Failed to initialize Balance Manager: {e}")
            # Fallback к профилям по умолчанию
            from src.balance import create_default_profiles

            profiles = create_default_profiles()
            self.balance_manager = AdaptiveBalanceManager(profiles)
            logger.info("✅ Adaptive Balance Manager initialized with fallback profiles")

    def _init_trading_modules(self):
        """Инициализация торговых модулей"""
        logger.info("🔧 Initializing trading modules...")

        # Индикаторы
        self.indicators = TechnicalIndicators()

        # ARM (Adaptive Regime Manager) - создаем конфигурацию по умолчанию
        from src.strategies.modules.adaptive_regime_manager import RegimeConfig

        regime_config = RegimeConfig()
        self.arm = AdaptiveRegimeManager(regime_config)

        # Передаем balance_manager в ARM для адаптации параметров
        self.arm.balance_manager = self.balance_manager

        # Фильтры - создаем с правильными конфигурациями
        from src.strategies.modules.adx_filter import (ADXFilter,
                                                       ADXFilterConfig)
        from src.strategies.modules.balance_checker import (BalanceCheckConfig,
                                                            BalanceChecker)
        from src.strategies.modules.correlation_filter import (
            CorrelationFilter, CorrelationFilterConfig)
        from src.strategies.modules.multi_timeframe import (
            MTFConfig, MultiTimeframeFilter)
        from src.strategies.modules.pivot_points import (PivotPointsConfig,
                                                         PivotPointsFilter)
        from src.strategies.modules.volume_profile_filter import (
            VolumeProfileConfig, VolumeProfileFilter)

        self.mtf_filter = MultiTimeframeFilter(self.okx_client, MTFConfig())
        self.correlation_filter = CorrelationFilter(
            self.okx_client, CorrelationFilterConfig(), self.config.trading.symbols
        )
        self.adx_filter = ADXFilter(ADXFilterConfig())
        self.pivot_filter = PivotPointsFilter(self.okx_client, PivotPointsConfig())
        self.volume_filter = VolumeProfileFilter(self.okx_client, VolumeProfileConfig())
        self.balance_checker = BalanceChecker(BalanceCheckConfig())

        # Торговые модули - создаем с правильными конфигурациями
        from src.risk.risk_controller import RiskController
        from src.risk.risk_controller_config import RiskControllerConfig

        from .order_executor import OrderExecutor
        from .order_executor_config import OrderExecutorConfig
        from .position_manager import PositionManager
        from .position_manager_config import PositionManagerConfig
        from .signal_generator import SignalGenerator
        from .signal_generator_config import SignalGeneratorConfig

        # Создаем модули для SignalGenerator
        modules = {
            "mtf": self.mtf_filter,
            "correlation": self.correlation_filter,
            "adx": self.adx_filter,
            "pivot": self.pivot_filter,
            "volume_profile": self.volume_filter,
            "balance": self.balance_checker,
            "arm": self.arm,
        }

        self.signal_generator = SignalGenerator(
            self.okx_client,
            SignalGeneratorConfig(),
            self.config.risk,
            modules,
            self.indicators,
        )

        self.order_executor = OrderExecutor(
            self.okx_client,
            OrderExecutorConfig(),
            self.config.risk,
            self.balance_checker,
            self.arm,
        )

        self.position_manager = PositionManager(
            self.okx_client, PositionManagerConfig(), self.arm
        )

        self.performance_tracker = PerformanceTracker()
        self.risk_controller = RiskController(
            RiskControllerConfig(), self.config.risk, self.arm
        )

        logger.info("✅ Trading modules initialized")

    async def start(self):
        """Запуск WebSocket оркестратора"""
        logger.info("🚀 Starting WebSocket Scalping Orchestrator...")

        try:
            # Подключение к WebSocket
            logger.info("🔌 Attempting WebSocket connection...")
            if not await self.websocket_manager.connect():
                logger.error("❌ Failed to connect to WebSocket")
                return False
            logger.info("✅ WebSocket connected successfully")

            # Подписка на символы
            for symbol in self.config.trading.symbols:
                await self.websocket_manager.subscribe_ticker(symbol)
                for interval in self.config.scalping.candle_intervals:
                    await self.websocket_manager.subscribe_candles(symbol, interval)

            self.is_running = True
            logger.info("✅ WebSocket Orchestrator started")

            # Запуск прослушивания WebSocket
            logger.info("🎧 Starting WebSocket listener...")

            # В тестовом режиме не запускаем бесконечный цикл
            if self.test_mode:
                logger.info(
                    "🧪 Test mode: WebSocket listener ready (not starting infinite loop)"
                )
                return True
            else:
                await self.websocket_manager.start_listening()

        except Exception as e:
            logger.error(f"❌ WebSocket Orchestrator start failed: {e}")
            self.is_running = False
            return False

    async def shutdown(self):
        """Корректное завершение работы WebSocket оркестратора"""
        logger.info("🛑 Shutting down WebSocket Orchestrator...")

        try:
            self.is_running = False

            # Отключение от WebSocket
            if self.websocket_manager:
                await self.websocket_manager.disconnect()

            logger.info("✅ WebSocket Orchestrator shutdown complete")

        except Exception as e:
            logger.error(f"❌ Error during shutdown: {e}")

    async def stop(self):
        """Остановка WebSocket оркестратора"""
        logger.info("🛑 Stopping WebSocket Orchestrator...")

        self.is_running = False

        if self.websocket_manager:
            await self.websocket_manager.disconnect()

        logger.info("✅ WebSocket Orchestrator stopped")

    async def _trading_loop(self):
        """Основной торговый цикл"""
        logger.info("🔄 Starting trading loop...")

        while self.is_running:
            try:
                # Проверка состояния
                if not self.websocket_manager.is_connected:
                    logger.warning(
                        "⚠️ WebSocket disconnected, waiting for reconnect..."
                    )
                    await asyncio.sleep(1)
                    continue

                # Обработка каждого символа
                for symbol in self.config.trading.symbols:
                    if not self.is_running:
                        break

                    await self._process_symbol(symbol)

                # Обновление статистики
                self._update_stats()

                # Небольшая задержка для предотвращения перегрузки
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"❌ Trading loop error: {e}")
                await asyncio.sleep(1)

    async def _process_symbol(self, symbol: str):
        """Обработка символа"""
        try:
            # Проверка наличия актуальных данных
            if symbol not in self.trading_state.current_prices:
                return

            current_price = self.trading_state.current_prices[symbol]
            last_update = self.trading_state.last_update_time.get(symbol, 0)

            # Проверка актуальности данных (не старше 5 секунд)
            if time.time() - last_update > 5:
                logger.warning(f"⚠️ Stale data for {symbol}")
                return

            # Проверка блокировки обработки
            if self.trading_state.is_processing:
                return

            self.trading_state.is_processing = True

            try:
                # Получение исторических данных для индикаторов
                candles = await self._get_historical_data(symbol)
                if not candles:
                    return

                # Расчет индикаторов
                indicators_data = self._calculate_indicators(symbol, candles)

                # Обновление ARM
                self.arm.detect_regime(
                    indicators_data.get("adx", 0.0), indicators_data.get("atr", 0.0)
                )
                state.current_regime[symbol] = self.arm.current_regime

                # Получаем параметры с учетом адаптивного баланса
                regime_params = self.arm.get_current_parameters(self.balance_manager)

                # Генерация сигнала
                signal = await self._generate_signal(
                    symbol, current_price, indicators_data, regime_params
                )

                if signal:
                    await self._process_signal(signal)

            finally:
                self.trading_state.is_processing = False

        except Exception as e:
            logger.error(f"❌ Symbol processing error for {symbol}: {e}")
            self.trading_state.is_processing = False

    async def _get_historical_data(self, symbol: str) -> Optional[List[Dict]]:
        """Получение исторических данных"""
        try:
            # Используем REST API для получения исторических данных
            candles = await self.okx_client.get_candles(symbol, "5m", 200)
            return candles
        except Exception as e:
            logger.error(f"❌ Failed to get historical data for {symbol}: {e}")
            return None

    def _calculate_indicators(self, symbol: str, candles: List[Dict]) -> Dict[str, Any]:
        """Расчет технических индикаторов"""
        try:
            if not candles or len(candles) < 50:
                return {}

            # Подготовка данных
            closes = [float(candle[4]) for candle in candles]
            highs = [float(candle[2]) for candle in candles]
            lows = [float(candle[3]) for candle in candles]
            volumes = [float(candle[5]) for candle in candles]

            # Расчет индикаторов
            indicators = {
                "sma_fast": self.indicators.sma(closes, 20),
                "sma_slow": self.indicators.sma(closes, 50),
                "ema_fast": self.indicators.ema(closes, 20),
                "ema_slow": self.indicators.ema(closes, 50),
                "rsi": self.indicators.rsi(closes, 14),
                "bb_upper": self.indicators.bollinger_upper(closes, 20, 2),
                "bb_lower": self.indicators.bollinger_lower(closes, 20, 2),
                "macd": self.indicators.macd(closes),
                "atr": self.indicators.atr(highs, lows, closes, 14),
                "volume_ratio": self.indicators.volume_ratio(volumes, 20),
            }

            return indicators

        except Exception as e:
            logger.error(f"❌ Indicator calculation error for {symbol}: {e}")
            return {}

    async def _generate_signal(
        self, symbol: str, price: float, indicators: Dict[str, Any], regime_params: Dict
    ) -> Optional[Dict]:
        """Генерация торгового сигнала"""
        try:
            # Проверка cooldown
            current_time = time.time()
            if (
                current_time - self.trading_state.last_signal_time
                < self.trading_state.signal_cooldown
            ):
                return None

            # Генерация сигнала
            signal = self.signal_generator.generate_signal(
                symbol=symbol,
                price=price,
                indicators=indicators,
                regime_params=regime_params,
            )

            if signal:
                self.trading_state.last_signal_time = current_time
                self.stats["signals_generated"] += 1
                logger.info(
                    f"📊 Signal generated for {symbol}: {signal['side']} at {price}"
                )

            return signal

        except Exception as e:
            logger.error(f"❌ Signal generation error for {symbol}: {e}")
            return None

    async def _process_signal(self, signal: Dict):
        """Обработка торгового сигнала"""
        try:
            symbol = signal["symbol"]
            side = signal["side"]
            price = signal["price"]

            # Применение фильтров
            if not await self._apply_filters(signal):
                self.stats["signals_rejected"] += 1
                logger.info(f"🚫 Signal rejected by filters: {symbol} {side}")
                return

            # Проверка рисков
            if not self.risk_controller.can_trade(signal):
                self.stats["signals_rejected"] += 1
                logger.info(f"🚫 Signal rejected by risk controller: {symbol} {side}")
                return

            # Выполнение ордера
            order_result = await self.order_executor.execute_signal(signal)

            if order_result["success"]:
                self.stats["signals_processed"] += 1
                logger.info(f"✅ Order executed: {symbol} {side} at {price}")

                # Обновляем баланс менеджер
                if self.balance_manager:
                    self.balance_manager.check_and_update_balance(
                        event="position_opened", symbol=symbol, side=side, amount=price
                    )
            else:
                logger.error(f"❌ Order execution failed: {order_result['error']}")

        except Exception as e:
            logger.error(f"❌ Signal processing error: {e}")

    async def _apply_filters(self, signal: Dict) -> bool:
        """Применение фильтров к сигналу"""
        try:
            symbol = signal["symbol"]
            side = signal["side"]
            price = signal["price"]

            # Multi-timeframe фильтр
            if self.mtf_filter and not self.mtf_filter.check_entry(symbol, side, price):
                return False

            # Correlation фильтр
            if self.correlation_filter and not self.correlation_filter.check_entry(
                signal
            ):
                return False

            # ADX фильтр
            if self.adx_filter and not self.adx_filter.check_entry(symbol, side, price):
                return False

            # Pivot Points фильтр
            if self.pivot_filter and not self.pivot_filter.check_entry(
                symbol, side, price
            ):
                return False

            # Volume Profile фильтр
            if self.volume_filter and not self.volume_filter.check_entry(
                symbol, side, price
            ):
                return False

            # Balance Checker
            if self.balance_checker and not self.balance_checker.check_entry(
                symbol, side, price
            ):
                return False

            return True

        except Exception as e:
            logger.error(f"❌ Filter application error: {e}")
            return False

    def _on_price_update(self, price_data: PriceData):
        """Callback для обновления цены"""
        try:
            symbol = price_data.symbol
            price = price_data.price
            timestamp = price_data.timestamp

            # Обновление состояния
            self.trading_state.current_prices[symbol] = price
            self.trading_state.last_update_time[symbol] = time.time()

            # Обновление статистики
            self.stats["last_price_update"] = timestamp

            logger.debug(f"💰 Price update: {symbol} = ${price:.2f}")

        except Exception as e:
            logger.error(f"❌ Price update callback error: {e}")

    def _on_websocket_error(self, error: Exception):
        """Callback для ошибок WebSocket"""
        logger.error(f"❌ WebSocket error: {error}")
        self.stats["websocket_errors"] += 1

    def _on_latency_warning(self, latency: float):
        """Callback для предупреждения о латентности"""
        logger.warning(f"⚠️ High latency detected: {latency:.2f}ms")

    def _on_latency_critical(self, latency: float):
        """Callback для критической латентности"""
        logger.error(f"🚨 CRITICAL LATENCY: {latency:.2f}ms")
        # Можно добавить логику для приостановки торговли при критической латентности

    def _update_stats(self):
        """Обновление статистики"""
        if self.latency_monitor:
            self.stats["avg_latency"] = self.latency_monitor.get_average_latency()

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        stats = {
            **self.stats,
            "websocket_status": self.websocket_manager.get_connection_status()
            if self.websocket_manager
            else {},
            "latency_stats": self.latency_monitor.get_latency_stats()
            if self.latency_monitor
            else {},
            "trading_state": {
                "is_processing": self.trading_state.is_processing,
                "active_symbols": len(self.trading_state.current_prices),
                "last_signal_time": self.trading_state.last_signal_time,
            },
        }

        # Добавляем статистику баланса
        if self.balance_manager:
            stats["balance_stats"] = self.balance_manager.get_balance_stats()

        return stats
