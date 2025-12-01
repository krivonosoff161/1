"""
Futures Orchestrator для скальпинг стратегии.

Координирует все модули для Futures торговли:
- FuturesSignalGenerator
- FuturesOrderExecutor
- FuturesPositionManager
- MarginCalculator
- LiquidationGuard
- SlippageGuard
- PerformanceTracker
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig
# Futures-специфичные модули безопасности
from src.strategies.modules.liquidation_guard import LiquidationGuard
from src.strategies.modules.slippage_guard import SlippageGuard
from src.strategies.modules.trading_statistics import TradingStatistics

from ..spot.performance_tracker import PerformanceTracker
# ✅ РЕФАКТОРИНГ: Импортируем новые модули
from .calculations.margin_calculator import MarginCalculator
from .config.config_manager import ConfigManager
from .coordinators.order_coordinator import OrderCoordinator
from .coordinators.signal_coordinator import SignalCoordinator
from .coordinators.smart_exit_coordinator import SmartExitCoordinator
from .coordinators.trailing_sl_coordinator import TrailingSLCoordinator
from .coordinators.websocket_coordinator import WebSocketCoordinator
from .core.data_registry import DataRegistry
from .core.position_registry import PositionRegistry
from .core.trading_control_center import TradingControlCenter
from .indicators.fast_adx import FastADX
from .indicators.funding_rate_monitor import FundingRateMonitor
from .indicators.order_flow_indicator import OrderFlowIndicator
from .logging.logger_factory import LoggerFactory
from .logging.structured_logger import StructuredLogger
from .order_executor import FuturesOrderExecutor
from .position_manager import FuturesPositionManager
from .positions.entry_manager import \
    EntryManager  # ✅ НОВОЕ: EntryManager для централизованного открытия позиций
from .positions.exit_analyzer import \
    ExitAnalyzer  # ✅ НОВОЕ: ExitAnalyzer для анализа закрытия
from .positions.position_monitor import \
    PositionMonitor  # ✅ НОВОЕ: PositionMonitor для периодического мониторинга позиций
from .private_websocket_manager import PrivateWebSocketManager
from .risk.max_size_limiter import MaxSizeLimiter
from .risk_manager import FuturesRiskManager
from .signal_generator import FuturesSignalGenerator
from .websocket_manager import FuturesWebSocketManager


class FuturesScalpingOrchestrator:
    """
    Оркестратор Futures скальпинг стратегии.

    Основные функции:
    - Координация всех модулей Futures торговли
    - Управление жизненным циклом позиций
    - Мониторинг безопасности маржи
    - Интеграция с модулями безопасности
    """

    def __init__(self, config: BotConfig):
        """
        Инициализация Futures Orchestrator

        Args:
            config: Конфигурация бота
        """
        self.config = config
        self.scalping_config = config.scalping
        self.risk_config = config.risk

        # ✅ ЭТАП 1: Config Manager для работы с конфигурацией
        self.config_manager = ConfigManager(config)

        # ✅ РЕФАКТОРИНГ: Настройка логирования через LoggerFactory
        LoggerFactory.setup_futures_logging(
            log_dir="logs/futures",
            log_level="DEBUG",
        )

        # ✅ РЕФАКТОРИНГ: DEBUG LOGGER из нового модуля
        from .logging.debug_logger import DebugLogger

        self.debug_logger = DebugLogger(
            enabled=True,  # Включить для диагностики
            csv_export=True,  # Экспортировать в logs/futures/debug/
            csv_dir="logs/futures/debug",  # ✅ Папка внутри futures (как основные логи)
            verbose=True,  # DEBUG уровень логирования
        )

        # ✅ РЕФАКТОРИНГ: StructuredLogger для структурированных логов
        self.structured_logger = StructuredLogger(log_dir="logs/futures/structured")

        # ✅ РЕФАКТОРИНГ: Инициализация Core модулей
        self.position_registry = PositionRegistry()
        self.data_registry = DataRegistry()

        # 🛡️ Защиты риска
        self.initial_balance = None  # Для drawdown расчета
        # ✅ НОВОЕ: total_margin_used теперь читается из DataRegistry, оставляем для обратной совместимости
        self.total_margin_used = (
            0.0  # DEPRECATED: Используйте data_registry.get_margin_used() вместо этого
        )
        # ✅ МОДЕРНИЗАЦИЯ: Параметры риска теперь адаптивные, читаются из конфига динамически
        # Используем fallback значения только для инициализации (будут переопределены при первом использовании)
        self.max_loss_per_trade = 0.02  # Fallback: 2% макс потеря на сделку
        self.max_margin_percent = 0.80  # Fallback: 80% макс маржа
        self.max_drawdown_percent = 0.05  # Fallback: 5% макс просадка

        # Получение API конфигурации
        okx_config = config.get_okx_config()

        # Клиент
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: leverage ОБЯЗАТЕЛЕН в конфиге (без fallback)
        leverage = getattr(self.scalping_config, "leverage", None)
        if leverage is None or leverage <= 0:
            raise ValueError(
                "❌ КРИТИЧЕСКАЯ ОШИБКА: leverage не указан в конфиге или <= 0! "
                "Добавьте в config_futures.yaml: scalping.leverage (например, 5)"
            )

        self.client = OKXFuturesClient(
            api_key=okx_config.api_key,
            secret_key=okx_config.api_secret,
            passphrase=okx_config.passphrase,
            sandbox=okx_config.sandbox,
            leverage=leverage,  # ✅ АДАПТИВНО: Из конфига
        )

        # Модули безопасности - берем параметры из futures_modules или defaults
        futures_modules = config.futures_modules if config.futures_modules else {}
        slippage_config = (
            futures_modules.slippage_guard if futures_modules.slippage_guard else {}
        )

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Параметры маржи из futures_modules.margin (НЕ из scalping_config)
        # futures_modules.margin содержит by_regime с safety_threshold для всех режимов
        if hasattr(futures_modules, "margin") and futures_modules.margin:
            margin_config = futures_modules.margin
        elif isinstance(futures_modules, dict) and "margin" in futures_modules:
            margin_config = futures_modules["margin"]
        else:
            # ✅ ИСПРАВЛЕНО: Ошибка вместо fallback - margin_config ОБЯЗАТЕЛЕН в конфиге
            raise ValueError(
                "❌ КРИТИЧЕСКАЯ ОШИБКА: futures_modules.margin не найден в конфиге! "
                "Добавьте в config_futures.yaml: futures_modules.margin.by_regime.{trending|ranging|choppy}.safety_threshold"
            )

        if isinstance(margin_config, dict):
            maintenance_margin_ratio = margin_config.get("maintenance_margin_ratio")
            initial_margin_ratio = margin_config.get("initial_margin_ratio")
            if maintenance_margin_ratio is None or initial_margin_ratio is None:
                raise ValueError(
                    "❌ КРИТИЧЕСКАЯ ОШИБКА: maintenance_margin_ratio или initial_margin_ratio не найдены в futures_modules.margin! "
                    "Добавьте в config_futures.yaml: futures_modules.margin.maintenance_margin_ratio и initial_margin_ratio"
                )
        else:
            maintenance_margin_ratio = getattr(
                margin_config, "maintenance_margin_ratio", None
            )
            initial_margin_ratio = getattr(margin_config, "initial_margin_ratio", None)
            if maintenance_margin_ratio is None or initial_margin_ratio is None:
                raise ValueError(
                    "❌ КРИТИЧЕСКАЯ ОШИБКА: maintenance_margin_ratio или initial_margin_ratio не найдены в futures_modules.margin! "
                    "Добавьте в config_futures.yaml: futures_modules.margin.maintenance_margin_ratio и initial_margin_ratio"
                )

        self.margin_calculator = MarginCalculator(
            default_leverage=leverage,  # ✅ АДАПТИВНО: Из конфига
            maintenance_margin_ratio=maintenance_margin_ratio,
            initial_margin_ratio=initial_margin_ratio,
        )
        # ✅ АДАПТИВНО: Сохраняем ссылку на margin_config для адаптивных параметров
        # ✅ ИСПРАВЛЕНО: Конвертируем Pydantic объект в dict для универсальной обработки
        if hasattr(margin_config, "dict"):
            try:
                margin_config_dict = margin_config.dict()
                self.margin_calculator.margin_config = margin_config_dict
            except:
                # Если не удалось конвертировать, сохраняем как есть
                self.margin_calculator.margin_config = margin_config
        elif isinstance(margin_config, dict):
            self.margin_calculator.margin_config = margin_config
        else:
            # Пробуем конвертировать через __dict__
            try:
                margin_config_dict = dict(margin_config.__dict__)
                self.margin_calculator.margin_config = margin_config_dict
            except:
                self.margin_calculator.margin_config = margin_config

        # ✅ АДАПТИВНО: Liquidation Guard параметры из конфига
        liquidation_config = getattr(self.scalping_config, "liquidation_guard", {})
        if isinstance(liquidation_config, dict):
            warning_threshold = liquidation_config.get("warning_threshold", 1.8)
            danger_threshold = liquidation_config.get("danger_threshold", 1.3)
            critical_threshold = liquidation_config.get("critical_threshold", 1.1)
            auto_close_threshold = liquidation_config.get("auto_close_threshold", 1.05)
        else:
            warning_threshold = getattr(liquidation_config, "warning_threshold", 1.8)
            danger_threshold = getattr(liquidation_config, "danger_threshold", 1.3)
            critical_threshold = getattr(liquidation_config, "critical_threshold", 1.1)
            auto_close_threshold = getattr(
                liquidation_config, "auto_close_threshold", 1.05
            )

        self.liquidation_guard = LiquidationGuard(
            margin_calculator=self.margin_calculator,
            warning_threshold=warning_threshold,
            danger_threshold=danger_threshold,
            critical_threshold=critical_threshold,
            auto_close_threshold=auto_close_threshold,
        )
        # ✅ АДАПТИВНО: Сохраняем ссылку на liquidation_config для адаптивных параметров
        self.liquidation_guard.liquidation_config = liquidation_config

        # ✅ АДАПТИВНО: Slippage Guard параметры из конфига
        slippage_config_full = getattr(self.scalping_config, "slippage_guard", {})
        if isinstance(slippage_config_full, dict):
            max_slippage_percent = slippage_config_full.get("max_slippage_percent", 0.1)
            max_spread_percent = slippage_config_full.get("max_spread_percent", 0.05)
            order_timeout = slippage_config_full.get("order_timeout", 30.0)
        else:
            max_slippage_percent = getattr(
                slippage_config_full, "max_slippage_percent", 0.1
            )
            max_spread_percent = getattr(
                slippage_config_full, "max_spread_percent", 0.05
            )
            order_timeout = getattr(slippage_config_full, "order_timeout", 30.0)

        # Fallback на futures_modules.slippage_guard если нет в scalping.slippage_guard
        if not slippage_config_full or (
            isinstance(slippage_config_full, dict) and not slippage_config_full
        ):
            max_slippage_percent = slippage_config.get("max_slippage_percent", 0.1)
            max_spread_percent = slippage_config.get("max_spread_percent", 0.05)
            order_timeout = slippage_config.get("order_timeout", 30.0)

        self.slippage_guard = SlippageGuard(
            max_slippage_percent=max_slippage_percent,
            max_spread_percent=max_spread_percent,
            order_timeout=order_timeout,
        )
        # ✅ АДАПТИВНО: Сохраняем ссылку на slippage_config для адаптивных параметров
        self.slippage_guard.slippage_config = (
            slippage_config_full if slippage_config_full else slippage_config
        )

        # ✅ НОВОЕ: Модуль статистики для динамической адаптации
        self.trading_statistics = TradingStatistics(lookback_hours=24)

        # Торговые модули
        # ✅ Передаем клиент в signal_generator для инициализации фильтров
        self.signal_generator = FuturesSignalGenerator(config, client=self.client)
        # ✅ НОВОЕ: Передаем trading_statistics в signal_generator для ARM
        if hasattr(self.signal_generator, "set_trading_statistics"):
            self.signal_generator.set_trading_statistics(self.trading_statistics)
        # ✅ НОВОЕ: Передаем data_registry в signal_generator для сохранения индикаторов
        if hasattr(self.signal_generator, "set_data_registry"):
            self.signal_generator.set_data_registry(self.data_registry)
        # ✅ НОВОЕ: Передаем structured_logger в signal_generator для логирования свечей
        if hasattr(self.signal_generator, "set_structured_logger"):
            self.signal_generator.set_structured_logger(self.structured_logger)
        self.order_executor = FuturesOrderExecutor(
            config, self.client, self.slippage_guard
        )
        self.position_manager = FuturesPositionManager(
            config, self.client, self.margin_calculator
        )
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Передаем ссылку на orchestrator в position_manager
        # для доступа к trailing_sl_by_symbol при проверке TP
        if hasattr(self.position_manager, "set_orchestrator"):
            self.position_manager.set_orchestrator(self)

        # ✅ РЕФАКТОРИНГ: Устанавливаем PositionRegistry и DataRegistry в position_manager
        if hasattr(self.position_manager, "set_position_registry"):
            self.position_manager.set_position_registry(self.position_registry)
        if hasattr(self.position_manager, "set_data_registry"):
            self.position_manager.set_data_registry(self.data_registry)

        # ✅ НОВОЕ: Инициализация EntryManager для централизованного открытия позиций
        # EntryManager будет использоваться в signal_coordinator вместо прямого вызова order_executor
        self.entry_manager = EntryManager(
            position_registry=self.position_registry,
            order_executor=self.order_executor,
            position_sizer=None,  # PositionSizer будет добавлен позже, пока используем риск-менеджер
        )
        logger.info("✅ EntryManager инициализирован в orchestrator")

        # ✅ НОВОЕ: Передаем symbol_profiles в position_manager для per-symbol TP
        # (инициализируем после создания symbol_profiles)
        self.performance_tracker = PerformanceTracker()

        # ✅ ЭТАП 1: Используем symbol_profiles из ConfigManager
        self.symbol_profiles: Dict[
            str, Dict[str, Any]
        ] = self.config_manager.get_symbol_profiles()

        # ✅ НОВОЕ: Передаем symbol_profiles в position_manager для per-symbol TP
        if hasattr(self.position_manager, "set_symbol_profiles"):
            self.position_manager.set_symbol_profiles(self.symbol_profiles)

        # ✅ АДАПТИВНО: FastADX параметры из конфига
        fast_adx_config = getattr(self.scalping_config, "fast_adx", {})
        if isinstance(fast_adx_config, dict):
            fast_adx_period = fast_adx_config.get("period", 9)
            fast_adx_threshold = fast_adx_config.get("threshold", 20.0)
        else:
            fast_adx_period = getattr(fast_adx_config, "period", 9)
            fast_adx_threshold = getattr(fast_adx_config, "threshold", 20.0)
        self.fast_adx = FastADX(period=fast_adx_period, threshold=fast_adx_threshold)
        # ✅ АДАПТИВНО: Сохраняем ссылку на fast_adx_config для адаптивных параметров
        self.fast_adx.fast_adx_config = fast_adx_config

        # ✅ АДАПТИВНО: OrderFlowIndicator параметры из конфига
        order_flow_params = None
        if getattr(config, "futures_modules", None):
            order_flow_params = getattr(config.futures_modules, "order_flow", None)
        if isinstance(order_flow_params, dict):
            of_window = order_flow_params.get("window", 100)
            of_long = order_flow_params.get("long_threshold", 0.1)
            of_short = order_flow_params.get("short_threshold", -0.1)
        else:
            of_window = (
                getattr(order_flow_params, "window", 100) if order_flow_params else 100
            )
            of_long = (
                getattr(order_flow_params, "long_threshold", 0.1)
                if order_flow_params
                else 0.1
            )
            of_short = (
                getattr(order_flow_params, "short_threshold", -0.1)
                if order_flow_params
                else -0.1
            )
        self.order_flow = OrderFlowIndicator(
            window=of_window,
            long_threshold=of_long,
            short_threshold=of_short,
        )

        # ✅ FIX: Создаём signal_locks раньше для ExitAnalyzer (предотвращение race condition)
        self.signal_locks = {}  # Будет создаваться по требованию

        # ✅ НОВОЕ: Инициализация ExitAnalyzer после создания fast_adx и order_flow
        # (position_registry и data_registry уже созданы выше)
        # ✅ НОВОЕ: ExitAnalyzer для анализа закрытия позиций
        self.exit_analyzer = ExitAnalyzer(
            position_registry=self.position_registry,
            data_registry=self.data_registry,
            exit_decision_logger=None,  # Можно добавить позже
            orchestrator=self,  # Передаем orchestrator для доступа к модулям
            config_manager=self.config_manager,
            signal_generator=self.signal_generator,
            signal_locks_ref=self.signal_locks,  # ✅ FIX: Передаём signal_locks для race condition
        )
        logger.info("✅ ExitAnalyzer инициализирован в orchestrator")

        # ✅ НОВОЕ: Инициализация PositionMonitor для периодического мониторинга позиций
        # PositionMonitor будет вызывать ExitAnalyzer для всех открытых позиций
        self.position_monitor = PositionMonitor(
            position_registry=self.position_registry,
            data_registry=self.data_registry,
            exit_analyzer=self.exit_analyzer,  # Передаем ExitAnalyzer для анализа
            check_interval=5.0,  # Проверка каждые 5 секунд
            close_position_callback=self._close_position,  # ✅ НОВОЕ: Callback для закрытия
            position_manager=self.position_manager,  # ✅ НОВОЕ: PositionManager для частичного закрытия
        )
        logger.info("✅ PositionMonitor инициализирован в orchestrator")

        # ✅ АДАПТИВНО: FundingRateMonitor параметры из конфига
        funding_config = getattr(config, "futures_modules", {})
        if funding_config:
            funding_monitor_config = getattr(funding_config, "funding_monitor", None)
            if funding_monitor_config:
                if isinstance(funding_monitor_config, dict):
                    max_funding_rate = funding_monitor_config.get(
                        "max_funding_rate", 0.05
                    )
                else:
                    max_funding_rate = getattr(
                        funding_monitor_config, "max_funding_rate", 0.05
                    )
            else:
                max_funding_rate = 0.05  # Fallback
        else:
            max_funding_rate = 0.05  # Fallback
        self.funding_monitor = FundingRateMonitor(max_funding_rate=max_funding_rate)

        # MaxSizeLimiter для защиты от больших позиций
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Загружаем параметры из конфига
        futures_modules = getattr(config, "futures_modules", None)
        max_size_limiter_config = None
        if futures_modules:
            max_size_limiter_config = getattr(futures_modules, "max_size_limiter", None)

        if max_size_limiter_config:
            max_single_size_usd = getattr(
                max_size_limiter_config, "max_single_size_usd", 150.0
            )
            max_total_size_usd = getattr(
                max_size_limiter_config, "max_total_size_usd", 600.0
            )
            max_positions = getattr(max_size_limiter_config, "max_positions", 5)
            logger.info(
                f"✅ MaxSizeLimiter инициализирован из конфига: "
                f"max_single=${max_single_size_usd:.2f}, "
                f"max_total=${max_total_size_usd:.2f}, "
                f"max_positions={max_positions}"
            )
        else:
            # Fallback значения (для обратной совместимости)
            max_single_size_usd = 150.0
            max_total_size_usd = 600.0
            max_positions = 5
            logger.warning(
                f"⚠️ MaxSizeLimiter config не найден в конфиге, используем fallback значения: "
                f"max_single=${max_single_size_usd:.2f}, "
                f"max_total=${max_total_size_usd:.2f}, "
                f"max_positions={max_positions}"
            )

        self.max_size_limiter = MaxSizeLimiter(
            max_single_size_usd=max_single_size_usd,
            max_total_size_usd=max_total_size_usd,
            max_positions=max_positions,
        )

        # ✅ РЕФАКТОРИНГ: Инициализируем RiskManager для расчета размера позиций
        # Передаем ссылку на orchestrator для доступа к методам (_get_used_margin, _check_drawdown_protection и т.д.)
        self.risk_manager = FuturesRiskManager(
            config=config,
            client=self.client,
            config_manager=self.config_manager,
            liquidation_protector=None,  # Можно добавить позже
            margin_monitor=None,  # Можно добавить позже
            max_size_limiter=self.max_size_limiter,
            orchestrator=self,  # ✅ РЕФАКТОРИНГ: Передаем ссылку на orchestrator
            data_registry=self.data_registry,  # ✅ НОВОЕ: DataRegistry для чтения баланса
        )
        logger.info("✅ FuturesRiskManager инициализирован")

        # WebSocket Manager
        # ✅ ИСПРАВЛЕНИЕ: Используем правильный WebSocket URL в зависимости от sandbox режима
        # OKX Sandbox WebSocket: wss://wspap.okx.com:8443/ws/v5/public (демо)
        # OKX Production WebSocket: wss://ws.okx.com:8443/ws/v5/public
        # Используем уже полученный okx_config из строки 69
        if okx_config.sandbox:
            ws_url = "wss://wspap.okx.com:8443/ws/v5/public"  # Sandbox WebSocket
            logger.info("📡 Используется SANDBOX WebSocket для тестирования")
        else:
            ws_url = "wss://ws.okx.com:8443/ws/v5/public"  # Production WebSocket
            logger.info("📡 Используется PRODUCTION WebSocket")

        self.ws_manager = FuturesWebSocketManager(ws_url=ws_url)

        # ✅ МОДЕРНИЗАЦИЯ #2: Private WebSocket для мониторинга позиций/ордеров
        self.private_ws_manager: Optional[PrivateWebSocketManager] = None
        try:
            self.private_ws_manager = PrivateWebSocketManager(
                api_key=okx_config.api_key,
                secret_key=okx_config.api_secret,
                passphrase=okx_config.passphrase,
                sandbox=okx_config.sandbox,
            )
            logger.info("✅ Private WebSocket Manager инициализирован")
        except Exception as e:
            logger.warning(
                f"⚠️ Не удалось инициализировать Private WebSocket Manager: {e}"
            )

        # Состояние
        self.is_running = False
        # ✅ ПРОКСИ: active_positions теперь прокси к PositionRegistry для обратной совместимости
        # Чтения через property автоматически получают данные из реестра
        # Записи должны идти через position_registry.register_position()
        self.trading_session = None
        self._closing_positions: set = set()  # ✅ Защита от множественных закрытий
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Флаги для автоматической разблокировки после emergency stop
        self._emergency_stop_active: bool = False
        self._emergency_stop_time: float = 0.0
        self._emergency_stop_balance: float = 0.0

        # Trailing SL coordinator
        self.trailing_sl_coordinator = TrailingSLCoordinator(
            config_manager=self.config_manager,
            debug_logger=self.debug_logger,
            signal_generator=self.signal_generator,
            client=self.client,
            scalping_config=self.scalping_config,
            get_position_callback=lambda sym: self.active_positions.get(sym, {}),
            close_position_callback=self._close_position,
            get_current_price_callback=self._get_current_price_fallback,
            active_positions_ref=self.active_positions,
            fast_adx=self.fast_adx,
            position_manager=self.position_manager,
            order_flow=self.order_flow,  # ✅ ЭТАП 1.1: Передаем OrderFlowIndicator для анализа разворота
            exit_analyzer=self.exit_analyzer,  # ✅ НОВОЕ: Передаем ExitAnalyzer для анализа закрытия
        )
        # Для совместимости с существующими модулями (PositionManager)
        self.trailing_sl_by_symbol = self.trailing_sl_coordinator.trailing_sl_by_symbol

        # ✅ АДАПТИВНО: Задержки из конфига
        delays_config = getattr(self.scalping_config, "delays", {})
        if isinstance(delays_config, dict):
            self._api_request_delay_ms = delays_config.get("api_request_delay_ms", 300)
            self._symbol_switch_delay_ms = delays_config.get(
                "symbol_switch_delay_ms", 200
            )
            self._position_sync_delay_ms = delays_config.get(
                "position_sync_delay_ms", 500
            )
        else:
            self._api_request_delay_ms = getattr(
                delays_config, "api_request_delay_ms", 300
            )
            self._symbol_switch_delay_ms = getattr(
                delays_config, "symbol_switch_delay_ms", 200
            )
            self._position_sync_delay_ms = getattr(
                delays_config, "position_sync_delay_ms", 500
            )
        self._delays_config = delays_config  # Сохраняем для адаптации по режимам

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Кэш последних ордеров и задержки между сигналами
        # Кэш последних ордеров: {symbol: {order_id, timestamp, status}}
        self.last_orders_cache = {}

        # Order coordinator
        self.order_coordinator = OrderCoordinator(
            client=self.client,
            order_executor=self.order_executor,
            scalping_config=self.scalping_config,
            signal_generator=self.signal_generator,
            last_orders_cache_ref=self.last_orders_cache,
        )

        # Время последнего сигнала по символу: {symbol: timestamp}
        self.last_signal_time = {}
        # Минимальная задержка между сигналами для одного символа (секунды)
        self.signal_cooldown_seconds = float(
            getattr(self.scalping_config, "signal_cooldown_seconds", 0.0) or 0.0
        )
        # Кэш активных ордеров: {symbol: {order_ids, timestamp}}
        self.active_orders_cache = {}
        # Время последней проверки активных ордеров
        self.last_orders_check_time = {}
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Блокировки для предотвращения race condition
        # Блокировка обработки сигналов по символам: {symbol: asyncio.Lock}
        # (signal_locks уже создан выше для ExitAnalyzer)

        # ✅ МОДЕРНИЗАЦИЯ: Параметры синхронизации состояния с биржей (адаптивные)
        check_interval = getattr(self.scalping_config, "check_interval", 5.0) or 5.0
        # ✅ МОДЕРНИЗАЦИЯ: Читаем параметры синхронизации из конфига (будет обновляться динамически)
        positions_sync_config = getattr(self.scalping_config, "positions_sync", None)
        if positions_sync_config:
            base_interval_min = (
                getattr(positions_sync_config, "base_interval_min", 5.0) or 5.0
            )
            base_interval_multiplier = (
                getattr(positions_sync_config, "base_interval_multiplier", 1.0) or 1.0
            )
            # Базовый интервал: base_interval_min * base_interval_multiplier
            self.positions_sync_interval = base_interval_min * base_interval_multiplier
        else:
            # Fallback: используем старое поведение (будет обновляться динамически)
            self.positions_sync_interval = max(
                5.0, check_interval * 1.0
            )  # ✅ МОДЕРНИЗАЦИЯ: 5 секунд вместо 15
        self._last_positions_sync = 0.0

        # Signal Coordinator (создаем ПЕРЕД WebSocketCoordinator, т.к. он нужен для callback)
        # Используем список для total_margin_used_ref, чтобы можно было изменять значение
        total_margin_used_ref = [self.total_margin_used]

        # Callback методы для SignalCoordinator
        def _get_position_for_tsl_callback(symbol: str) -> Dict[str, Any]:
            """Callback для получения позиции по символу"""
            return self.active_positions.get(symbol, {})

        async def _close_position_for_tsl_callback(symbol: str, reason: str) -> None:
            """Callback для закрытия позиции"""
            await self._close_position(symbol, reason)

        self.signal_coordinator = SignalCoordinator(
            client=self.client,
            scalping_config=self.scalping_config,
            signal_generator=self.signal_generator,
            config_manager=self.config_manager,
            order_executor=self.order_executor,
            position_manager=self.position_manager,
            margin_calculator=self.margin_calculator,
            slippage_guard=self.slippage_guard,
            max_size_limiter=self.max_size_limiter,
            trading_statistics=self.trading_statistics,
            risk_manager=self.risk_manager,
            debug_logger=self.debug_logger,
            active_positions_ref=self.active_positions,
            last_orders_cache_ref=self.last_orders_cache,
            active_orders_cache_ref=self.active_orders_cache,
            last_orders_check_time_ref=self.last_orders_check_time,
            signal_locks_ref=self.signal_locks,
            funding_monitor=self.funding_monitor,
            config=self.config,
            trailing_sl_coordinator=self.trailing_sl_coordinator,
            total_margin_used_ref=total_margin_used_ref,
            get_used_margin_callback=self._get_used_margin,
            get_position_callback=_get_position_for_tsl_callback,
            close_position_callback=_close_position_for_tsl_callback,
            normalize_symbol_callback=self.config_manager.normalize_symbol,
            initialize_trailing_stop_callback=self.trailing_sl_coordinator.initialize_trailing_stop,
            entry_manager=self.entry_manager,  # ✅ НОВОЕ: EntryManager для централизованного открытия
            data_registry=self.data_registry,  # ✅ НОВОЕ: DataRegistry для централизованного чтения данных
        )
        # Обновляем ссылку на total_margin_used для синхронизации
        self._total_margin_used_ref = total_margin_used_ref

        # Callback для обновления кэша ордеров из WebSocket
        def _update_orders_cache_from_ws(
            symbol: str, order_id: str, order_cache_data: Dict[str, Any]
        ) -> None:
            """Callback для обновления кэша ордеров из WebSocket"""
            if symbol not in self.active_orders_cache:
                self.active_orders_cache[symbol] = {}
            if "order_ids" not in self.active_orders_cache[symbol]:
                self.active_orders_cache[symbol]["order_ids"] = set()
            if order_id not in self.active_orders_cache[symbol]["order_ids"]:
                self.active_orders_cache[symbol]["order_ids"].add(order_id)
            self.active_orders_cache[symbol][order_id] = order_cache_data
            self.active_orders_cache[symbol]["timestamp"] = time.time()

        # ✅ НОВОЕ: SmartExitCoordinator для умного закрытия позиций через индикаторы
        self.smart_exit_coordinator = SmartExitCoordinator(
            position_registry=self.position_registry,
            data_registry=self.data_registry,
            close_position_callback=self._close_position,
            enabled=True,  # Можно отключить через конфиг
        )
        logger.info("✅ SmartExitCoordinator инициализирован")

        # ✅ РЕФАКТОРИНГ: Инициализация TradingControlCenter для координации торговой логики
        # Создаем ПОСЛЕ всех модулей, чтобы передать все зависимости
        self.trading_control_center = TradingControlCenter(
            client=self.client,
            signal_generator=self.signal_generator,
            signal_coordinator=self.signal_coordinator,
            position_manager=self.position_manager,
            position_registry=self.position_registry,
            data_registry=self.data_registry,
            order_coordinator=self.order_coordinator,
            trailing_sl_coordinator=self.trailing_sl_coordinator,
            performance_tracker=self.performance_tracker,
            trading_statistics=self.trading_statistics,
            liquidation_guard=self.liquidation_guard,
            config_manager=self.config_manager,
            scalping_config=self.scalping_config,
            active_positions=self.active_positions,  # Прокси к position_registry
            normalize_symbol=self._normalize_symbol,
            sync_positions_with_exchange=self._sync_positions_with_exchange,
        )
        logger.info("✅ TradingControlCenter инициализирован в orchestrator")

        # WebSocket Coordinator (создаем ПОСЛЕ SignalCoordinator, т.к. используем его callback)
        self.websocket_coordinator = WebSocketCoordinator(
            ws_manager=self.ws_manager,
            private_ws_manager=self.private_ws_manager,
            scalping_config=self.scalping_config,
            active_positions_ref=self.active_positions,
            fast_adx=self.fast_adx,
            position_manager=self.position_manager,
            trailing_sl_coordinator=self.trailing_sl_coordinator,
            debug_logger=self.debug_logger,
            client=self.client,
            handle_ticker_callback=None,  # Используем прямые вызовы методов
            update_trailing_sl_callback=self._update_trailing_stop_loss,
            check_signals_callback=self.signal_coordinator.check_for_signals,
            handle_position_closed_callback=None,  # Используем прямую ссылку
            update_active_positions_callback=None,  # Используем прямую ссылку
            update_active_orders_cache_callback=_update_orders_cache_from_ws,
            data_registry=self.data_registry,  # ✅ НОВОЕ: DataRegistry для централизованного хранения данных
            structured_logger=self.structured_logger,  # ✅ НОВОЕ: StructuredLogger для логирования свечей
            smart_exit_coordinator=self.smart_exit_coordinator,  # ✅ НОВОЕ: SmartExitCoordinator для умного закрытия
        )

        logger.info("FuturesScalpingOrchestrator инициализирован")

    async def start(self):
        """Запуск Futures торгового бота"""
        try:
            logger.info("🚀 Запуск Futures торгового бота...")

            # Инициализация клиента
            await self._initialize_client()

            # Подключение WebSocket
            await self.websocket_coordinator.initialize_websocket()

            # Запуск модулей безопасности
            await self._start_safety_modules()

            # Запуск торговых модулей
            await self._start_trading_modules()

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Очищаем все состояния после инициализации модулей
            # Это гарантирует, что не останется "призрачных" данных из предыдущих сессий
            # Важно: вызываем ПОСЛЕ инициализации модулей, чтобы фильтры были созданы
            self._reset_all_states()

            # ✅ НОВОЕ: Инициализация буферов свечей для всех символов (перед загрузкой позиций)
            await self._initialize_candle_buffers()

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Загружаем существующие позиции и инициализируем TrailingStopLoss
            await self._load_existing_positions()

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Синхронизируем позиции с биржей и обновляем MaxSizeLimiter
            # Это очистит старые данные из MaxSizeLimiter, если позиций на бирже нет
            await self._sync_positions_with_exchange(force=True)

            # ✅ НОВОЕ: Запуск PositionMonitor как фоновой задачи для периодического мониторинга
            await self.position_monitor.start()
            logger.info("✅ PositionMonitor запущен (фоновая задача)")

            # ✅ РЕФАКТОРИНГ: Основной торговый цикл делегирован в TradingControlCenter
            self.is_running = True
            await self.trading_control_center.run_main_loop()

        except Exception as e:
            logger.error(f"❌ Критическая ошибка в Futures Orchestrator: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Остановка Futures торгового бота"""
        logger.info("🛑 Остановка Futures торгового бота...")

        self.is_running = False

        # ✅ РЕФАКТОРИНГ: Остановка TradingControlCenter
        if hasattr(self, "trading_control_center") and self.trading_control_center:
            await self.trading_control_center.stop()
            logger.info("✅ TradingControlCenter остановлен")

        # Остановка модулей безопасности
        await self.liquidation_guard.stop_monitoring()
        await self.slippage_guard.stop_monitoring()

        # ✅ НОВОЕ: Остановка PositionMonitor
        if hasattr(self, "position_monitor") and self.position_monitor:
            await self.position_monitor.stop()
            logger.info("✅ PositionMonitor остановлен")

        # Отключение WebSocket
        await self.ws_manager.disconnect()

        # ✅ МОДЕРНИЗАЦИЯ #2: Отключение Private WebSocket
        if self.private_ws_manager:
            try:
                await self.private_ws_manager.disconnect()
                logger.info("✅ Private WebSocket отключен")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка отключения Private WebSocket: {e}")

        # Закрытие клиента
        await self.client.close()

        logger.info("✅ Futures торговый бот остановлен")

    async def _initialize_client(self):
        """Инициализация клиента"""
        try:
            # Проверка баланса
            balance = await self.client.get_balance()
            logger.info(f"💰 Доступный баланс: {balance:.2f} USDT")

            # ✅ НОВОЕ: Обновляем баланс в DataRegistry
            if self.data_registry:
                try:
                    balance_profile = self.config_manager.get_balance_profile(balance)
                    profile_name = (
                        balance_profile.get("name", "small")
                        if balance_profile
                        else None
                    )
                    await self.data_registry.update_balance(balance, profile_name)
                    logger.debug(
                        f"✅ DataRegistry: Обновлен баланс: ${balance:.2f} USDT (profile={profile_name})"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка обновления баланса в DataRegistry: {e}")

            # 🛡️ Инициализация начального баланса для drawdown
            if self.initial_balance is None:
                self.initial_balance = balance
                logger.info(f"📊 Начальный баланс: ${self.initial_balance:.2f}")

            if balance < 100:  # Минимальный баланс
                raise ValueError(f"Недостаточный баланс: {balance:.2f} USDT")

            # ✅ Установка leverage для торговых пар
            # Пробуем установить leverage даже в sandbox mode (может работать с правильными параметрами)
            leverage_config = getattr(self.scalping_config, "leverage", None)
            if leverage_config is None or leverage_config <= 0:
                logger.warning(
                    f"⚠️ leverage не указан в конфиге, используем 3 (fallback)"
                )
                leverage_config = 3

            # ✅ НОВОЕ: Проверяем режим позиций на бирже
            try:
                account_config = await self.client.get_account_config()
                pos_mode = None
                if account_config.get("code") == "0" and account_config.get("data"):
                    config = account_config["data"][0]
                    pos_mode = config.get("posMode", "")
                    logger.info(f"📊 Режим позиций на бирже: {pos_mode}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось получить режим позиций: {e}")

            # ✅ Устанавливаем leverage для каждого символа
            for symbol in self.scalping_config.symbols:
                leverage_set = False

                # Если режим long_short_mode (hedge), устанавливаем leverage для обоих направлений
                if pos_mode == "long_short_mode":
                    try:
                        # Устанавливаем leverage для long позиций
                        await self.client.set_leverage(
                            symbol, leverage_config, pos_side="long"
                        )
                        logger.info(
                            f"✅ Плечо {leverage_config}x установлено для {symbol} (long) "
                            f"(hedge mode, sandbox={self.client.sandbox})"
                        )
                        leverage_set = True
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Не удалось установить leverage для {symbol} (long): {e}"
                        )

                    # ✅ ИСПРАВЛЕНИЕ: Задержка для избежания rate limit (429)
                    # ✅ АДАПТИВНО: Задержка из конфига (адаптивная по режиму)
                    delay_ms = self.config_manager.get_adaptive_delay(
                        "api_request_delay_ms",
                        300,
                        self._delays_config,
                        self.signal_generator,
                    )
                    await asyncio.sleep(delay_ms / 1000.0)

                    try:
                        # Устанавливаем leverage для short позиций
                        await self.client.set_leverage(
                            symbol, leverage_config, pos_side="short"
                        )
                        logger.info(
                            f"✅ Плечо {leverage_config}x установлено для {symbol} (short) "
                            f"(hedge mode, sandbox={self.client.sandbox})"
                        )
                        leverage_set = True
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Не удалось установить leverage для {symbol} (short): {e}"
                        )
                else:
                    # Для net mode пробуем установить без posSide, затем с posSide
                    try:
                        # ✅ Попытка 1: Без posSide (для net mode)
                        await self.client.set_leverage(symbol, leverage_config)
                        logger.info(
                            f"✅ Плечо {leverage_config}x установлено для {symbol} "
                            f"(net mode, sandbox={self.client.sandbox})"
                        )
                        leverage_set = True
                    except Exception as e:
                        # ✅ ИСПРАВЛЕНИЕ: Задержка перед повторной попыткой
                        # ✅ АДАПТИВНО: Задержка из конфига (адаптивная по режиму)
                        delay_ms = self.config_manager.get_adaptive_delay(
                            "api_request_delay_ms",
                            300,
                            self._delays_config,
                            self.signal_generator,
                        )
                        await asyncio.sleep(delay_ms / 1000.0)
                        # ✅ Попытка 2: С posSide="long" (может потребоваться в некоторых случаях)
                        try:
                            logger.debug(
                                f"⚠️ Попытка 1 не удалась для {symbol}, пробуем с posSide='long': {e}"
                            )
                            await self.client.set_leverage(
                                symbol, leverage_config, pos_side="long"
                            )
                            logger.info(
                                f"✅ Плечо {leverage_config}x установлено для {symbol} с posSide='long' "
                                f"(sandbox={self.client.sandbox})"
                            )
                            leverage_set = True
                        except Exception as e2:
                            # ✅ ИСПРАВЛЕНИЕ: Задержка перед следующей попыткой
                            # ✅ АДАПТИВНО: Задержка из конфига (адаптивная по режиму)
                            delay_ms = self._get_adaptive_delay(
                                "api_request_delay_ms", 300
                            )
                            await asyncio.sleep(delay_ms / 1000.0)
                            # ✅ Попытка 3: С posSide="short"
                            try:
                                await self.client.set_leverage(
                                    symbol, leverage_config, pos_side="short"
                                )
                                logger.info(
                                    f"✅ Плечо {leverage_config}x установлено для {symbol} с posSide='short' "
                                    f"(sandbox={self.client.sandbox})"
                                )
                                leverage_set = True
                            except Exception as e3:
                                logger.warning(
                                    f"⚠️ Не удалось установить плечо {leverage_config}x для {symbol}: {e3}"
                                )

                # ✅ ИСПРАВЛЕНИЕ: Задержка между символами для избежания rate limit
                # ✅ АДАПТИВНО: Задержка из конфига (адаптивная по режиму)
                delay_ms = self.config_manager.get_adaptive_delay(
                    "symbol_switch_delay_ms",
                    200,
                    self._delays_config,
                    self.signal_generator,
                )
                await asyncio.sleep(delay_ms / 1000.0)

                if not leverage_set:
                    if self.client.sandbox:
                        logger.info(
                            f"⚠️ Sandbox mode: leverage не установлен на бирже через API для {symbol}, "
                            f"но расчеты используют leverage={leverage_config}x из конфига. "
                            f"Возможно, нужно установить leverage вручную на бирже."
                        )

        except Exception as e:
            logger.error(f"Ошибка инициализации клиента: {e}")
            raise

    async def _initialize_websocket(self):
        """Совместимость: делегирует инициализацию WebSocket координатору."""
        await self.websocket_coordinator.initialize_websocket()

    async def _start_safety_modules(self):
        """Запуск модулей безопасности"""
        try:
            # Запуск Liquidation Guard
            await self.liquidation_guard.start_monitoring(
                client=self.client,
                check_interval=5.0,
                callback=self._on_liquidation_warning,
            )

            # Запуск Slippage Guard
            await self.slippage_guard.start_monitoring(self.client)

            logger.info("✅ Модули безопасности запущены")

        except Exception as e:
            logger.error(f"Ошибка запуска модулей безопасности: {e}")
            raise

    async def _start_trading_modules(self):
        """Запуск торговых модулей"""
        try:
            # Инициализация торговых модулей
            await self.signal_generator.initialize()
            await self.order_executor.initialize()
            await self.position_manager.initialize()

            logger.info("✅ Торговые модули инициализированы")

        except Exception as e:
            logger.error(f"Ошибка инициализации торговых модулей: {e}")
            raise

    async def _initialize_candle_buffers(self):
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Инициализация буферов свечей для всех символов и всех таймфреймов при старте бота.

        Загружает свечи для всех нужных таймфреймов:
        - 1m: 200 свечей (для основных индикаторов и режимов)
        - 5m: 200 свечей (для Multi-Timeframe и Correlation фильтров)
        - 1H: 100 свечей (для Volume Profile фильтра)
        - 1D: 10 свечей (для Pivot Points фильтра)

        После этого свечи будут обновляться инкрементально через WebSocket.
        """
        try:
            logger.info(
                "📊 Инициализация буферов свечей для всех символов и таймфреймов..."
            )

            if not self.data_registry:
                logger.warning(
                    "⚠️ DataRegistry не доступен, пропускаем инициализацию свечей"
                )
                return

            symbols = self.scalping_config.symbols
            if not symbols:
                logger.warning("⚠️ Нет символов для инициализации свечей")
                return

            import aiohttp

            from src.models import OHLCV

            # ✅ КРИТИЧЕСКОЕ: Определяем все нужные таймфреймы и их параметры
            timeframes_config = [
                {
                    "timeframe": "1m",
                    "limit": 200,
                    "max_size": 200,
                    "description": "основные индикаторы",
                },
                {
                    "timeframe": "5m",
                    "limit": 200,
                    "max_size": 200,
                    "description": "Multi-Timeframe и Correlation",
                },
                {
                    "timeframe": "1H",
                    "limit": 100,
                    "max_size": 100,
                    "description": "Volume Profile",
                },
                {
                    "timeframe": "1D",
                    "limit": 10,
                    "max_size": 10,
                    "description": "Pivot Points",
                },
            ]

            total_initialized = 0
            for symbol in symbols:
                symbol_initialized = 0
                for tf_config in timeframes_config:
                    timeframe = tf_config["timeframe"]
                    limit = tf_config["limit"]
                    max_size = tf_config["max_size"]
                    description = tf_config["description"]

                    try:
                        # Получаем свечи через API
                        inst_id = f"{symbol}-SWAP"
                        url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar={timeframe}&limit={limit}"

                        async with aiohttp.ClientSession() as session:
                            async with session.get(url) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    if data.get("code") == "0" and data.get("data"):
                                        candles = data["data"]

                                        # Конвертируем свечи из формата OKX в OHLCV
                                        ohlcv_data = []
                                        for candle in candles:
                                            if len(candle) >= 6:
                                                ohlcv_item = OHLCV(
                                                    timestamp=int(candle[0])
                                                    // 1000,  # OKX в миллисекундах
                                                    symbol=symbol,
                                                    open=float(candle[1]),
                                                    high=float(candle[2]),
                                                    low=float(candle[3]),
                                                    close=float(candle[4]),
                                                    volume=float(candle[5]),
                                                    timeframe=timeframe,
                                                )
                                                ohlcv_data.append(ohlcv_item)

                                        if ohlcv_data:
                                            # Сортируем по timestamp (старые -> новые)
                                            ohlcv_data.sort(key=lambda x: x.timestamp)

                                            # Инициализируем буфер в DataRegistry
                                            await self.data_registry.initialize_candles(
                                                symbol=symbol,
                                                timeframe=timeframe,
                                                candles=ohlcv_data,
                                                max_size=max_size,
                                            )

                                            symbol_initialized += 1
                                            total_initialized += 1
                                            logger.info(
                                                f"✅ Инициализирован буфер свечей {timeframe} для {symbol} "
                                                f"({len(ohlcv_data)} свечей, {description})"
                                            )

                                            # ✅ НОВОЕ: Логируем в StructuredLogger
                                            if self.structured_logger:
                                                try:
                                                    self.structured_logger.log_candle_init(
                                                        symbol=symbol,
                                                        timeframe=timeframe,
                                                        candles_count=len(ohlcv_data),
                                                        status="success",
                                                    )
                                                except Exception as e:
                                                    logger.debug(
                                                        f"⚠️ Ошибка логирования инициализации свечей в StructuredLogger: {e}"
                                                    )
                                    else:
                                        error_msg = data.get(
                                            "msg", "Неизвестная ошибка"
                                        )
                                        logger.warning(
                                            f"⚠️ Не удалось получить свечи {timeframe} для {symbol}: {error_msg}"
                                        )
                                        # ✅ НОВОЕ: Логируем ошибку в StructuredLogger
                                        if self.structured_logger:
                                            try:
                                                self.structured_logger.log_candle_init(
                                                    symbol=symbol,
                                                    timeframe=timeframe,
                                                    candles_count=0,
                                                    status="error",
                                                    error=error_msg,
                                                )
                                            except Exception as e:
                                                logger.debug(
                                                    f"⚠️ Ошибка логирования ошибки инициализации свечей: {e}"
                                                )
                                else:
                                    logger.warning(
                                        f"⚠️ HTTP ошибка при получении свечей {timeframe} для {symbol}: {resp.status}"
                                    )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка инициализации буфера свечей {timeframe} для {symbol}: {e}"
                        )

                if symbol_initialized > 0:
                    logger.info(
                        f"📊 Символ {symbol}: инициализировано {symbol_initialized}/{len(timeframes_config)} таймфреймов"
                    )

            logger.info(
                f"📊 Инициализация буферов свечей завершена: "
                f"{total_initialized} буферов для {len(symbols)} символов"
            )

            # ✅ НОВОЕ: Логируем итоговую статистику в StructuredLogger
            if self.structured_logger:
                try:
                    self.structured_logger.log_candle_init(
                        symbol="ALL",
                        timeframe="ALL",
                        candles_count=total_initialized,
                        status="completed",
                    )
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка логирования итоговой статистики: {e}")

        except Exception as e:
            logger.error(
                f"❌ Критическая ошибка инициализации буферов свечей: {e}", exc_info=True
            )

    def _reset_all_states(self):
        """Очистка всех состояний при старте бота"""
        try:
            logger.info("🧹 Очистка состояний перед стартом...")

            # Очищаем MaxSizeLimiter
            self.max_size_limiter.reset()
            logger.debug("✅ MaxSizeLimiter очищен")

            # Очищаем active_positions
            self.active_positions.clear()
            logger.debug("✅ active_positions очищен")

            # Очищаем trailing SL
            cleared = self.trailing_sl_coordinator.clear_all_tsl()
            logger.debug(f"✅ Trailing SL очищен ({cleared} записей)")

            # Очищаем кэш последних ордеров
            self.last_orders_cache.clear()
            self.active_orders_cache.clear()

            # Очищаем состояние фильтров в signal_generator (если есть методы reset)
            if (
                hasattr(self.signal_generator, "liquidity_filter")
                and self.signal_generator.liquidity_filter
            ):
                if hasattr(self.signal_generator.liquidity_filter, "_relax_state"):
                    self.signal_generator.liquidity_filter._relax_state.clear()
                    logger.debug("✅ LiquidityFilter _relax_state очищен")
                if hasattr(self.signal_generator.liquidity_filter, "_cache"):
                    self.signal_generator.liquidity_filter._cache.clear()
                    logger.debug("✅ LiquidityFilter _cache очищен")

            if (
                hasattr(self.signal_generator, "order_flow_filter")
                and self.signal_generator.order_flow_filter
            ):
                if hasattr(self.signal_generator.order_flow_filter, "_relax_state"):
                    self.signal_generator.order_flow_filter._relax_state.clear()
                    logger.debug("✅ OrderFlowFilter _relax_state очищен")
                if hasattr(self.signal_generator.order_flow_filter, "_cache"):
                    self.signal_generator.order_flow_filter._cache.clear()
                    logger.debug("✅ OrderFlowFilter _cache очищен")

            logger.info("✅ Все состояния очищены")

        except Exception as e:
            logger.warning(f"⚠️ Ошибка при очистке состояний: {e}")

    async def _load_existing_positions(self):
        """✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Загружаем существующие позиции и инициализируем TrailingStopLoss"""
        try:
            logger.info("📊 Загрузка существующих позиций с биржи...")

            # Получаем все позиции с биржи
            all_positions = await self.client.get_positions()

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #1: Группируем позиции по символам для проверки противоположных
            positions_by_symbol = {}
            for pos in all_positions:
                pos_size = float(pos.get("pos", "0"))
                if abs(pos_size) < 0.000001:
                    continue  # Пропускаем нулевые позиции

                inst_id = pos.get("instId", "")
                symbol = inst_id.replace("-SWAP", "")

                if symbol not in positions_by_symbol:
                    positions_by_symbol[symbol] = []

                pos_side_raw = pos.get("posSide", "").lower()
                if pos_side_raw in ["long", "short"]:
                    position_side = pos_side_raw
                else:
                    position_side = "long" if pos_size > 0 else "short"

                positions_by_symbol[symbol].append(
                    {
                        "pos": pos,
                        "position_side": position_side,
                        "pos_size": abs(pos_size),
                    }
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #1: Проверяем противоположные позиции
            allow_concurrent = getattr(
                self.scalping_config,
                "allow_concurrent_positions",
                False,
            )

            for symbol, symbol_positions in positions_by_symbol.items():
                if len(symbol_positions) < 2:
                    continue  # Нет противоположных позиций

                # Проверяем, есть ли и LONG и SHORT
                has_long = any(p["position_side"] == "long" for p in symbol_positions)
                has_short = any(p["position_side"] == "short" for p in symbol_positions)

                if has_long and has_short and not allow_concurrent:
                    # ✅ КРИТИЧЕСКОЕ: Найдены противоположные позиции, закрываем одну из них
                    logger.warning(
                        f"🚨 Найдены противоположные позиции для {symbol} при загрузке: "
                        f"{len(symbol_positions)} позиций (LONG и SHORT). "
                        f"allow_concurrent=false, закрываем противоположную позицию..."
                    )

                    # Выбираем какую закрывать (с меньшим PnL или более позднюю)
                    # Сначала пробуем по PnL
                    positions_to_close = []
                    for p_info in symbol_positions:
                        pos = p_info["pos"]
                        try:
                            upl = float(pos.get("upl", "0"))
                            positions_to_close.append(
                                {
                                    "pos": pos,
                                    "position_side": p_info["position_side"],
                                    "upl": upl,
                                }
                            )
                        except:
                            positions_to_close.append(
                                {
                                    "pos": pos,
                                    "position_side": p_info["position_side"],
                                    "upl": 0,
                                }
                            )

                    # Сортируем: сначала с меньшим PnL (более убыточные)
                    positions_to_close.sort(key=lambda x: x["upl"])

                    # Закрываем первую (с наименьшим PnL или случайную)
                    position_to_close = positions_to_close[0]
                    pos_to_close = position_to_close["pos"]
                    side_to_close = position_to_close["position_side"]

                    try:
                        logger.warning(
                            f"🛑 Закрываем противоположную позицию {symbol} {side_to_close.upper()} "
                            f"(PnL={position_to_close['upl']:.2f} USDT) при загрузке (allow_concurrent=false)"
                        )
                        await self.position_manager.close_position_manually(
                            symbol, reason="opposite_position_on_load"
                        )
                        # Удаляем закрытую позицию из списка для загрузки
                        symbol_positions.remove(
                            next(
                                p
                                for p in symbol_positions
                                if p["position_side"] == side_to_close
                            )
                        )
                    except Exception as e:
                        logger.error(
                            f"❌ Ошибка закрытия противоположной позиции {symbol} {side_to_close.upper()}: {e}"
                        )

            loaded_count = 0
            # Теперь загружаем оставшиеся позиции
            for symbol, symbol_positions in positions_by_symbol.items():
                for p_info in symbol_positions:
                    pos = p_info["pos"]
                    pos_size = float(pos.get("pos", "0"))
                    inst_id = pos.get("instId", "")
                    position_side = p_info["position_side"]
                    pos_size_abs = p_info["pos_size"]

                    # Получаем данные позиции
                    entry_price = float(pos.get("avgPx", "0"))
                    side = "buy" if position_side == "long" else "sell"

                    if entry_price == 0:
                        logger.warning(f"⚠️ Entry price = 0 для {symbol}, пропускаем")
                        continue

                    # Получаем текущую цену
                    # ✅ ИСПРАВЛЕНО: Пробуем получить через API, если не получается - используем entry_price
                    # Это нормально при загрузке позиций, цена будет обновлена при следующем тикере из WebSocket
                    try:
                        ticker = await self.client.get_ticker(symbol)
                        current_price = float(ticker.get("last", entry_price))
                        if current_price == entry_price:
                            # API вернул цену = entry_price, это нормально
                            logger.debug(
                                f"✅ Текущая цена для {symbol} получена через API: ${current_price:.2f} (= entry_price)"
                            )
                        else:
                            logger.debug(
                                f"✅ Текущая цена для {symbol} получена через API: ${current_price:.2f}"
                            )
                    except Exception as e:
                        # ✅ ИСПРАВЛЕНО: Используем entry_price как fallback, логируем как debug (не warning)
                        # Это нормально при загрузке позиций - цена будет обновлена при следующем тикере из WebSocket
                        current_price = entry_price
                        logger.debug(
                            f"⚠️ Не удалось получить текущую цену для {symbol} через API ({type(e).__name__}: {e}), "
                            f"используем entry_price=${entry_price:.2f} (цена будет обновлена при следующем тикере из WebSocket)"
                        )

                    # Добавляем в active_positions

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем реальное время открытия позиции из API
                    # Пробуем получить из cTime (create time) или uTime (update time)
                    entry_time_dt = None
                    c_time = pos.get("cTime")
                    u_time = pos.get("uTime")
                    entry_time_str = c_time or u_time

                    if entry_time_str:
                        try:
                            # OKX возвращает время в миллисекундах
                            entry_timestamp_ms = int(entry_time_str)
                            entry_timestamp_sec = entry_timestamp_ms / 1000.0
                            entry_time_dt = datetime.fromtimestamp(entry_timestamp_sec)
                            logger.debug(
                                f"✅ Реальное время открытия для {symbol} получено из API: {entry_time_dt} "
                                f"(из {'cTime' if c_time else 'uTime'})"
                            )
                        except (ValueError, TypeError) as e:
                            logger.warning(
                                f"⚠️ Не удалось распарсить cTime/uTime для {symbol}: {e}, "
                                f"используем текущее время (fallback)"
                            )
                            from datetime import timezone

                            entry_time_dt = datetime.now(timezone.utc)
                    else:
                        logger.warning(
                            f"⚠️ cTime/uTime не найдены для {symbol} в данных позиции, "
                            f"используем текущее время (fallback)"
                        )
                        entry_time_dt = datetime.now(timezone.utc)

                    self.active_positions[symbol] = {
                        "instId": inst_id,
                        "side": side,  # "buy" или "sell" для внутреннего использования
                        "position_side": position_side,  # "long" или "short" для правильного расчета PnL
                        "size": pos_size_abs,
                        "entry_price": entry_price,
                        "margin": float(pos.get("margin", "0")),
                        "entry_time": entry_time_dt,  # ✅ КРИТИЧЕСКОЕ: Реальное время открытия из API
                        "timestamp": datetime.now(timezone.utc),
                        "time_extended": False,
                    }

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #4: Получаем режим рынка для адаптации TSL параметров
                    regime = None
                    if (
                        hasattr(self.signal_generator, "regime_manager")
                        and self.signal_generator.regime_manager
                    ):
                        try:
                            regime = (
                                self.signal_generator.regime_manager.get_current_regime()
                            )
                            logger.debug(f"✅ Режим рынка для {symbol}: {regime}")
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Не удалось получить режим рынка для {symbol}: {e}"
                            )
                    elif hasattr(
                        self.signal_generator, "regime_managers"
                    ) and symbol in getattr(
                        self.signal_generator, "regime_managers", {}
                    ):
                        manager = self.signal_generator.regime_managers.get(symbol)
                        if manager:
                            try:
                                regime = manager.get_current_regime()
                                logger.debug(
                                    f"✅ Режим рынка для {symbol} из regime_managers: {regime}"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"⚠️ Не удалось получить режим рынка для {symbol} из regime_managers: {e}"
                                )

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #4: Передаем position_side ("long"/"short") в TrailingSLCoordinator
                    signal_with_regime = {"regime": regime} if regime else None
                    # ✅ КРИТИЧЕСКОЕ: Передаем entry_time для правильной инициализации entry_timestamp в TSL
                    signal_with_regime = signal_with_regime or {}
                    signal_with_regime["entry_time"] = entry_time_dt

                    tsl = self.trailing_sl_coordinator.initialize_trailing_stop(
                        symbol=symbol,
                        entry_price=entry_price,
                        side=position_side,  # "long" или "short", а не "buy"/"sell"
                        current_price=current_price,
                        signal=signal_with_regime,  # ✅ Передаем regime и entry_time для адаптации параметров
                    )
                    if tsl:
                        logger.info(
                            f"✅ Загружена позиция {symbol} {side.upper()}: "
                            f"size={pos_size_abs}, entry={entry_price:.2f}, "
                            f"entry_time={entry_time_dt}, TrailingStopLoss инициализирован"
                        )
                    else:
                        logger.warning(
                            f"⚠️ Не удалось инициализировать TrailingStopLoss для {symbol}: "
                            f"entry_price={entry_price}, current_price={current_price}, entry_time={entry_time_dt}"
                        )
                    # ✅ КРИТИЧЕСКОЕ: Регистрируем позицию в PositionRegistry с правильными метаданными
                    from .core.position_registry import PositionMetadata

                    metadata = PositionMetadata(
                        entry_time=entry_time_dt,
                        regime=regime,
                        entry_price=entry_price,
                        position_side=position_side,
                        size_in_coins=pos_size_abs,
                        margin_used=float(pos.get("margin", "0")),
                    )
                    await self.position_registry.register_position(
                        symbol=symbol,
                        position=self.active_positions[symbol],
                        metadata=metadata,
                    )

                    loaded_count += 1

            if loaded_count > 0:
                logger.info(
                    f"📊 Загружено {loaded_count} существующих позиций с TrailingStopLoss"
                )
            else:
                logger.info("📊 Открытых позиций не найдено")

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки существующих позиций: {e}", exc_info=True)

    @staticmethod
    def _get_config_value(source: Any, key: str, default: Any = None) -> Any:
        """Безопасно извлекает значение из объекта конфигурации или dict."""
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default) if hasattr(source, key) else default

    async def _sync_positions_with_exchange(self, force: bool = False) -> None:
        """
        ✅ МОДЕРНИЗАЦИЯ: Синхронизирует локальные позиции и лимиты с фактическими данными биржи.

        Обновляет:
        - active_positions
        - total_margin_used (используя _get_used_margin())
        - max_size_limiter.position_sizes
        - trailing_sl_by_symbol
        """
        now = time.time()
        # ✅ МОДЕРНИЗАЦИЯ: Адаптивный интервал синхронизации из конфига
        # Получаем параметры синхронизации из конфига (адаптивные)
        positions_sync_config = getattr(self.scalping_config, "positions_sync", None)
        if positions_sync_config:
            base_interval_min = (
                getattr(positions_sync_config, "base_interval_min", 5.0) or 5.0
            )
            base_interval_multiplier = (
                getattr(positions_sync_config, "base_interval_multiplier", 1.0) or 1.0
            )

            # Определяем режим и баланс для адаптивного интервала
            regime = None
            if (
                hasattr(self.signal_generator, "regime_manager")
                and self.signal_generator.regime_manager
            ):
                regime = self.signal_generator.regime_manager.get_current_regime()

            # ✅ НОВОЕ: Читаем баланс из DataRegistry
            balance = None
            if self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    if balance_data:
                        balance = balance_data.get("balance")
                        profile_name = balance_data.get("profile")
                        logger.debug(
                            f"📊 Баланс получен из DataRegistry: ${balance:.2f} (profile={profile_name})"
                        )
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка получения баланса из DataRegistry: {e}")

            # Fallback на прямой запрос к API
            if balance is None:
                balance = await self.client.get_balance()
                balance_profile = self.config_manager.get_balance_profile(balance)
                profile_name = balance_profile.get("name", "small")

            # ✅ НОВОЕ: Обновляем баланс в DataRegistry (если получили из API)
            if self.data_registry:
                try:
                    await self.data_registry.update_balance(balance, profile_name)
                    logger.debug(
                        f"✅ DataRegistry: Обновлен баланс: ${balance:.2f} USDT (profile={profile_name})"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка обновления баланса в DataRegistry: {e}")

            # Получаем множитель интервала по режиму (ПРИОРИТЕТ 1)
            by_regime = self.config_manager.to_dict(
                getattr(positions_sync_config, "by_regime", {})
            )
            regime_multiplier = 1.0
            if regime:
                regime_config = self.config_manager.to_dict(
                    by_regime.get(regime.lower(), {})
                )
                regime_multiplier = regime_config.get("interval_multiplier", 1.0) or 1.0

            # Получаем множитель интервала по балансу (ПРИОРИТЕТ 2, если режим не переопределил)
            by_balance = self.config_manager.to_dict(
                getattr(positions_sync_config, "by_balance", {})
            )
            balance_multiplier = 1.0
            if profile_name:
                balance_config = self.config_manager.to_dict(
                    by_balance.get(profile_name, {})
                )
                balance_multiplier = (
                    balance_config.get("interval_multiplier", 1.0) or 1.0
                )

            # Применяем множитель (приоритет: режим > баланс)
            interval_multiplier = (
                regime_multiplier if regime_multiplier != 1.0 else balance_multiplier
            )
            sync_interval = base_interval_min * interval_multiplier
        else:
            # Fallback: используем старое поведение
            check_interval = getattr(self.scalping_config, "check_interval", 5.0) or 5.0
            sync_interval = max(
                5.0, check_interval * 1.0
            )  # ✅ МОДЕРНИЗАЦИЯ: 5 секунд вместо 15

        if not force and (now - self._last_positions_sync) < sync_interval:
            return

        try:
            exchange_positions = await self.client.get_positions()
        except Exception as e:
            logger.debug(f"⚠️ Не удалось синхронизировать позиции с биржей: {e}")
            return

        self._last_positions_sync = time.time()
        seen_symbols: set[str] = set()
        total_margin = 0.0

        for pos in exchange_positions or []:
            try:
                pos_size = float(pos.get("pos", "0") or 0)
            except (TypeError, ValueError):
                pos_size = 0.0

            if abs(pos_size) < 1e-8:
                continue

            inst_id = pos.get("instId", "")
            if not inst_id:
                continue

            symbol = inst_id.replace("-SWAP", "")
            seen_symbols.add(symbol)

            # ✅ FIX: DRIFT_ADD log — позиция на бирже, но нет в реестре
            is_drift_add = symbol not in self.active_positions
            if is_drift_add:
                logger.critical(
                    f"DRIFT_ADD {symbol} found on exchange but not in registry"
                )

            try:
                entry_price = float(pos.get("avgPx", 0) or 0)
            except (TypeError, ValueError):
                entry_price = 0.0

            try:
                mark_price = float(pos.get("markPx", entry_price) or entry_price)
            except (TypeError, ValueError):
                mark_price = entry_price

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильное определение направления позиции
            # Используем posSide из API, если доступен, иначе определяем по знаку pos
            pos_side_raw = pos.get("posSide", "").lower()
            if pos_side_raw in ["long", "short"]:
                position_side = pos_side_raw  # "long" или "short"
                side = (
                    "buy" if position_side == "long" else "sell"
                )  # Для внутреннего использования
            else:
                # Fallback: определяем по знаку pos
                if pos_size > 0:
                    position_side = "long"
                    side = "buy"  # LONG
                else:
                    position_side = "short"
                    side = "sell"  # SHORT

            abs_size = abs(pos_size)

            # ✅ Получаем ctVal для корректного перевода контрактов в монеты
            ct_val = 0.01
            try:
                details = await self.client.get_instrument_details(symbol)
                if details:
                    ct_val = float(details.get("ctVal", ct_val)) or ct_val
            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось получить ctVal для {symbol} при синхронизации позиций: {e}"
                )

            size_in_coins = abs_size * ct_val

            margin_raw = pos.get("margin")
            try:
                margin = float(margin_raw) if margin_raw is not None else 0.0
            except (TypeError, ValueError):
                margin = 0.0

            if margin <= 0 and entry_price > 0:
                leverage = getattr(self.scalping_config, "leverage", 3) or 3
                margin = (size_in_coins * entry_price) / max(leverage, 1e-6)

            total_margin += max(margin, 0.0)

            effective_price = entry_price or mark_price
            # ✅ FIX #3: Используем UTC для корректного расчета времени в позиции
            timestamp = datetime.now(timezone.utc)
            active_position = self.active_positions.setdefault(symbol, {})
            if "entry_time" not in active_position:
                active_position["entry_time"] = timestamp

            # ✅ НОВОЕ: Сохраняем ADL данные (если доступны из API)
            adl_rank = pos.get("adlRank") or pos.get("adl")
            if adl_rank is not None:
                try:
                    active_position["adl_rank"] = int(adl_rank)
                except (ValueError, TypeError):
                    pass
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сохраняем режим в позицию для адаптивных TP
            regime = None
            if hasattr(self.signal_generator, "regime_managers") and symbol in getattr(
                self.signal_generator, "regime_managers", {}
            ):
                manager = self.signal_generator.regime_managers.get(symbol)
                if manager:
                    regime = manager.get_current_regime()
            # Fallback на глобальный режим если per-symbol режим не найден
            if not regime:
                if (
                    hasattr(self.signal_generator, "regime_manager")
                    and self.signal_generator.regime_manager
                ):
                    try:
                        regime = (
                            self.signal_generator.regime_manager.get_current_regime()
                        )
                    except Exception:
                        pass

            active_position.update(
                {
                    "instId": inst_id,
                    "side": side,  # "buy" или "sell" для внутреннего использования
                    "position_side": position_side,  # "long" или "short" для правильного расчета PnL
                    "size": size_in_coins,
                    "contracts": abs_size,
                    "entry_price": effective_price,
                    "margin": margin,
                    "timestamp": timestamp,
                    "regime": regime,  # ✅ КРИТИЧЕСКОЕ: Сохраняем режим для адаптивных TP
                }
            )

            # ✅ FIX #1: DRIFT_ADD — принудительная регистрация в PositionRegistry
            if is_drift_add:
                try:
                    # Проверяем что позиции нет в registry
                    has_in_registry = await self.position_registry.has_position(symbol)
                    if not has_in_registry:
                        # Создаём данные позиции для registry
                        position_data = {
                            "symbol": symbol,
                            "instId": inst_id,
                            "pos": str(pos_size),
                            "posSide": position_side,
                            "avgPx": str(effective_price),
                            "markPx": str(mark_price),
                            "size": size_in_coins,
                            "entry_price": effective_price,
                            "position_side": position_side,
                            "margin_used": margin,
                        }
                        # Создаём metadata
                        from .positions.entry_manager import PositionMetadata

                        metadata = PositionMetadata(
                            entry_time=timestamp,
                            regime=regime,
                            balance_profile="small",  # Fallback
                            entry_price=effective_price,
                            position_side=position_side,
                            size_in_coins=size_in_coins,
                            margin_used=margin,
                        )
                        # Регистрируем
                        await self.position_registry.register_position(
                            symbol=symbol,
                            position=position_data,
                            metadata=metadata,
                        )
                        logger.warning(
                            f"DRIFT_ADD_SYNCED {symbol} force-registered in PositionRegistry"
                        )
                except Exception as e:
                    logger.error(f"DRIFT_ADD_SYNC_FAILED {symbol}: {e}")

            # ✅ НОВОЕ: Логируем ADL для всех позиций (если доступно)
            if "adl_rank" in active_position:
                adl_rank = active_position["adl_rank"]
                adl_status = (
                    "🔴 ВЫСОКИЙ"
                    if adl_rank >= 4
                    else "🟡 СРЕДНИЙ"
                    if adl_rank >= 2
                    else "🟢 НИЗКИЙ"
                )
                logger.info(
                    f"📊 ADL для {symbol}: rank={adl_rank} ({adl_status}) "
                    f"(PnL={pos.get('upl', '0')} USDT, margin={margin:.2f} USDT)"
                )

                # Предупреждение при высоком ADL
                if adl_rank >= 4:
                    logger.warning(
                        f"⚠️ ВЫСОКИЙ ADL для {symbol}: rank={adl_rank} "
                        f"(риск автоматического сокращения позиции биржей)"
                    )

            if not self.trailing_sl_coordinator.get_tsl(symbol):
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Передаем position_side ("long"/"short") в initialize_trailing_stop
                # Используем position_side из active_positions, если доступен, иначе конвертируем side
                trailing_side = (
                    position_side
                    if position_side
                    else ("long" if side == "buy" else "short")
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем режим для правильных параметров TSL
                regime = None
                if hasattr(
                    self.signal_generator, "regime_managers"
                ) and symbol in getattr(self.signal_generator, "regime_managers", {}):
                    manager = self.signal_generator.regime_managers.get(symbol)
                    if manager:
                        regime = manager.get_current_regime()

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Создаем signal с режимом для передачи в initialize_trailing_stop
                signal_with_regime = {"regime": regime} if regime else {}

                # ✅ КРИТИЧЕСКОЕ: Получаем entry_time из активной позиции или метаданных для передачи в TSL
                entry_time_for_tsl = None
                if symbol in self.active_positions:
                    entry_time_for_tsl = self.active_positions[symbol].get("entry_time")
                if not entry_time_for_tsl:
                    # Пробуем получить из PositionRegistry
                    try:
                        metadata = await self.position_registry.get_metadata(symbol)
                        if metadata and metadata.entry_time:
                            entry_time_for_tsl = metadata.entry_time
                    except Exception:
                        pass
                if entry_time_for_tsl:
                    signal_with_regime["entry_time"] = entry_time_for_tsl

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем результат инициализации TSL
                tsl = self.trailing_sl_coordinator.initialize_trailing_stop(
                    symbol=symbol,
                    entry_price=effective_price,
                    side=trailing_side,  # "long" или "short", а не "buy"/"sell"
                    current_price=mark_price,
                    signal=signal_with_regime
                    if signal_with_regime
                    else None,  # ✅ КРИТИЧЕСКОЕ: Передаем режим и entry_time через signal
                )
                if not tsl:
                    logger.warning(
                        f"⚠️ Не удалось инициализировать TrailingStopLoss для {symbol} "
                        f"при синхронизации: entry_price={effective_price}, side={trailing_side}"
                    )
                # ✅ FIX #2: Логируем создание TSL для DRIFT_ADD позиций
                elif is_drift_add:
                    logger.warning(
                        f"DRIFT_ADD_TSL_CREATED {symbol} TSL initialized "
                        f"(entry={effective_price:.4f}, side={trailing_side}, regime={regime})"
                    )

            if effective_price > 0:
                self.max_size_limiter.position_sizes[symbol] = (
                    size_in_coins * effective_price
                )

        stale_symbols = set(self.active_positions.keys()) - seen_symbols
        for symbol in list(stale_symbols):
            # ✅ FIX: DRIFT_REMOVE log — позиция в реестре, но нет на бирже
            logger.warning(f"DRIFT_REMOVE {symbol} not on exchange")
            logger.info(
                f"♻️ Позиция {symbol} отсутствует на бирже, очищаем локальное состояние"
            )
            self.active_positions.pop(symbol, None)
            # ✅ РЕФАКТОРИНГ: Используем trailing_sl_coordinator для удаления TSL
            tsl = self.trailing_sl_coordinator.remove_tsl(symbol)
            if tsl:
                tsl.reset()
            if symbol in self.max_size_limiter.position_sizes:
                self.max_size_limiter.remove_position(symbol)
            normalized_symbol = self.config_manager.normalize_symbol(symbol)
            if normalized_symbol in self.last_orders_cache:
                self.last_orders_cache[normalized_symbol]["status"] = "closed"

        # ✅ ЭТАП 6.3: Обновляем total_margin_used с актуальными данными с биржи
        # Используем _get_used_margin() для получения точной маржи с биржи
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: total_margin инициализируется до try блока
        # (уже инициализирована на строке 1323, но убеждаемся что она доступна в except)
        try:
            used_margin = await self._get_used_margin()
            self.total_margin_used = used_margin
            if hasattr(self, "_total_margin_used_ref") and self._total_margin_used_ref:
                self._total_margin_used_ref[0] = used_margin

            # ✅ НОВОЕ: Обновляем маржу в DataRegistry
            if self.data_registry:
                try:
                    # Получаем баланс для расчета доступной маржи
                    balance_data = await self.data_registry.get_balance()
                    balance = balance_data.get("balance", 0) if balance_data else 0
                    available_margin = (
                        balance - used_margin if balance > used_margin else 0
                    )
                    total_margin_value = balance  # Общая маржа = баланс

                    await self.data_registry.update_margin(
                        used=used_margin,
                        available=available_margin,
                        total=total_margin_value,
                    )
                    logger.debug(
                        f"✅ DataRegistry: Обновлена маржа: used=${used_margin:.2f}, available=${available_margin:.2f}"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка обновления маржи в DataRegistry: {e}")
        except Exception as e:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем расчетную total_margin (которая уже вычислена выше)
            # total_margin уже инициализирована на строке 1323 и обновляется в цикле позиций (строка 1393)
            calculated_margin = total_margin  # Используем расчетную маржу из позиций
            logger.warning(
                f"⚠️ Не удалось получить использованную маржу с биржи: {e}, используем расчетную: {calculated_margin:.2f}"
            )
            # ✅ НОВОЕ: Маржа обновляется в DataRegistry, локальная переменная для обратной совместимости
            self.total_margin_used = calculated_margin  # DEPRECATED: Используйте data_registry.get_margin_used()
            if hasattr(self, "_total_margin_used_ref") and self._total_margin_used_ref:
                self._total_margin_used_ref[0] = calculated_margin

            # ✅ НОВОЕ: Обновляем маржу в DataRegistry даже при ошибке (используем расчетную)
            if self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    balance = balance_data.get("balance", 0) if balance_data else 0
                    available_margin = (
                        balance - calculated_margin
                        if balance > calculated_margin
                        else 0
                    )
                    total_margin_value = balance

                    await self.data_registry.update_margin(
                        used=calculated_margin,
                        available=available_margin,
                        total=total_margin_value,
                    )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка обновления расчетной маржи в DataRegistry: {e}"
                    )

        # ✅ ЭТАП 5.3: MaxSizeLimiter уже обновлен выше (строки 1004-1006, 1018)
        # Позиции добавляются/удаляются из MaxSizeLimiter сразу после синхронизации
        logger.debug(
            f"🔁 Синхронизация позиций завершена: активных={len(seen_symbols)}, "
            f"маржа={self.total_margin_used:.2f}"
        )

    async def _main_trading_loop(self):
        """Основной торговый цикл"""
        logger.info("🔄 Запуск основного торгового цикла")

        while self.is_running:
            try:
                # Проверяем is_running перед каждым шагом
                if not self.is_running:
                    break

                # Обновление состояния
                await self._update_state()

                if not self.is_running:
                    break

                # Генерация сигналов
                # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование каждого цикла
                # logger.debug("🔄 Основной цикл: генерация сигналов...")
                signals = await self.signal_generator.generate_signals()
                if len(signals) > 0:
                    logger.info(
                        f"📊 Основной цикл: сгенерировано {len(signals)} сигналов"
                    )
                else:
                    logger.debug("📊 Основной цикл: сигналов не сгенерировано")

                if not self.is_running:
                    break

                # Обработка сигналов
                await self.signal_coordinator.process_signals(signals)

                if not self.is_running:
                    break

                # Управление позициями
                await self._manage_positions()

                if not self.is_running:
                    break

                # ✅ НОВОЕ: Мониторинг лимитных ордеров (таймаут и замена на рыночные)
                await self.order_coordinator.monitor_limit_orders()

                if not self.is_running:
                    break

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Периодически обновляем статус ордеров в кэше
                await self.order_coordinator.update_orders_cache_status(
                    self._normalize_symbol
                )

                if not self.is_running:
                    break

                # ✅ Новое: синхронизация локальных позиций с биржей
                await self._sync_positions_with_exchange()

                if not self.is_running:
                    break

                # Обновление статистики
                await self._update_performance()

                if not self.is_running:
                    break

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #1: Периодическая проверка TSL независимо от тикеров
                # Проверяем TSL каждые 1-2 секунды для всех открытых позиций
                await self._periodic_tsl_check()

                if not self.is_running:
                    break

                # Пауза между итерациями
                await asyncio.sleep(self.scalping_config.check_interval)

            except asyncio.CancelledError:
                logger.info("🛑 Торговый цикл отменен")
                break
            except Exception as e:
                logger.error(f"Ошибка в торговом цикле: {e}")
                if self.is_running:
                    await asyncio.sleep(5)  # Пауза при ошибке
                else:
                    break

    async def _update_state(self):
        """Обновление состояния системы"""
        try:
            # ✅ Проверяем is_running перед выполнением операций
            if not self.is_running:
                return

            # Получение текущих позиций
            positions = await self.client.get_positions()

            if not self.is_running:
                return

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновление позиций через PositionRegistry с сохранением метаданных
            # Сохраняем существующие метаданные перед обновлением позиций
            all_registered = await self.position_registry.get_all_positions()
            all_metadata = await self.position_registry.get_all_metadata()

            # Удаляем позиции, которых больше нет на бирже
            exchange_symbols = set()
            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if abs(size) >= 1e-8:
                    exchange_symbols.add(symbol)

            # Удаляем позиции, которых нет на бирже
            for symbol in list(all_registered.keys()):
                if symbol not in exchange_symbols:
                    await self.position_registry.unregister_position(symbol)

            # Обновляем/регистрируем позиции с сохранением метаданных
            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if abs(size) >= 1e-8:
                    # ✅ КРИТИЧЕСКОЕ: Сохраняем существующие метаданные
                    existing_metadata = all_metadata.get(symbol)

                    # Получаем entry_price из position данных
                    try:
                        entry_price_from_api = float(position.get("avgPx", 0) or 0)
                    except (TypeError, ValueError):
                        entry_price_from_api = 0.0

                    # ✅ КРИТИЧЕСКОЕ: Получаем entry_time из API (cTime/uTime), если метаданных нет
                    entry_time_from_api = None
                    c_time = position.get("cTime")
                    u_time = position.get("uTime")
                    entry_time_str = c_time or u_time
                    if entry_time_str:
                        try:
                            entry_timestamp_ms = int(entry_time_str)
                            entry_timestamp_sec = entry_timestamp_ms / 1000.0
                            entry_time_from_api = datetime.fromtimestamp(
                                entry_timestamp_sec
                            )
                        except (ValueError, TypeError):
                            pass

                    # Если метаданные уже есть, обновляем только entry_price если нужно
                    if existing_metadata:
                        # ✅ КРИТИЧЕСКОЕ: Сохраняем entry_time, если он еще не установлен, но есть в API
                        if (
                            not existing_metadata.entry_time
                            or existing_metadata.entry_time == datetime.now()
                        ):
                            if entry_time_from_api:
                                existing_metadata.entry_time = entry_time_from_api

                        # Обновляем entry_price в метаданных если он изменился или отсутствует
                        if (
                            not existing_metadata.entry_price
                            or existing_metadata.entry_price == 0
                        ):
                            if entry_price_from_api > 0:
                                existing_metadata.entry_price = entry_price_from_api

                        # Получаем текущий режим из signal_generator если regime отсутствует
                        if not existing_metadata.regime:
                            regime = None
                            if hasattr(
                                self.signal_generator, "regime_managers"
                            ) and symbol in getattr(
                                self.signal_generator, "regime_managers", {}
                            ):
                                manager = self.signal_generator.regime_managers.get(
                                    symbol
                                )
                                if manager:
                                    regime = manager.get_current_regime()
                            if not regime:
                                if (
                                    hasattr(self.signal_generator, "regime_manager")
                                    and self.signal_generator.regime_manager
                                ):
                                    regime = (
                                        self.signal_generator.regime_manager.get_current_regime()
                                    )
                            if regime:
                                existing_metadata.regime = regime

                        # Обновляем position_side если отсутствует
                        pos_side_raw = position.get("posSide", "").lower()
                        if (
                            pos_side_raw in ["long", "short"]
                            and not existing_metadata.position_side
                        ):
                            existing_metadata.position_side = pos_side_raw

                        # Используем существующие метаданные с обновлениями
                        await self.position_registry.register_position(
                            symbol=symbol,
                            position=position,
                            metadata=existing_metadata,
                        )
                    else:
                        # Новая позиция - создаем метаданные
                        from .core.position_registry import PositionMetadata

                        # ✅ КРИТИЧЕСКОЕ: Используем entry_time из API, если доступно, иначе текущее время
                        entry_time_for_metadata = (
                            entry_time_from_api
                            if entry_time_from_api
                            else datetime.now()
                        )

                        # Получаем режим для новой позиции
                        regime = None
                        if hasattr(
                            self.signal_generator, "regime_managers"
                        ) and symbol in getattr(
                            self.signal_generator, "regime_managers", {}
                        ):
                            manager = self.signal_generator.regime_managers.get(symbol)
                            if manager:
                                regime = manager.get_current_regime()
                        if not regime:
                            if (
                                hasattr(self.signal_generator, "regime_manager")
                                and self.signal_generator.regime_manager
                            ):
                                regime = (
                                    self.signal_generator.regime_manager.get_current_regime()
                                )

                        # Определяем position_side
                        pos_side_raw = position.get("posSide", "").lower()
                        position_side = None
                        if pos_side_raw in ["long", "short"]:
                            position_side = pos_side_raw
                        else:
                            position_side = "long" if size > 0 else "short"

                        # Создаем метаданные для новой позиции
                        new_metadata = PositionMetadata(
                            entry_time=entry_time_for_metadata,  # ✅ КРИТИЧЕСКОЕ: Используем entry_time из API (cTime/uTime)
                            regime=regime,
                            entry_price=entry_price_from_api
                            if entry_price_from_api > 0
                            else None,
                            position_side=position_side,
                        )

                        await self.position_registry.register_position(
                            symbol=symbol,
                            position=position,
                            metadata=new_metadata,
                        )

            # ✅ Проверяем is_running перед API запросом
            if not self.is_running:
                return

            # Проверка здоровья маржи
            margin_status = await self.liquidation_guard.get_margin_status(self.client)

            if not self.is_running:
                return

            if margin_status.get("health_status", {}).get("status") == "critical":
                logger.critical("🚨 КРИТИЧЕСКОЕ СОСТОЯНИЕ МАРЖИ!")
                await self._emergency_close_all_positions()

        except asyncio.CancelledError:
            logger.debug("Обновление состояния отменено при остановке")
            raise  # Пробрасываем дальше
        except Exception as e:
            # Не логируем ошибки при остановке
            if self.is_running:
                logger.error(f"Ошибка обновления состояния: {e}")
            else:
                logger.debug(f"Обновление состояния прервано при остановке: {e}")

    # ✅ РЕФАКТОРИНГ: Методы _process_signals, _validate_signal, _execute_signal, _check_for_signals, _execute_signal_from_price удалены - перенесены в SignalCoordinator

    # ✅ РЕФАКТОРИНГ: Метод _execute_signal удален - перенесен в SignalCoordinator

    async def _manage_positions(self):
        """Управление открытыми позициями"""
        try:
            # ✅ ИСПРАВЛЕНИЕ: Создаем копию словаря, чтобы избежать "dictionary changed size during iteration"
            positions_copy = dict(self.active_positions)
            for symbol, position in positions_copy.items():
                await self.position_manager.manage_position(position)

            # ✅ НОВОЕ: Периодический мониторинг ADL для всех позиций
            # Логируем ADL для всех открытых позиций раз в минуту
            if hasattr(self, "_last_adl_log_time"):
                if time.time() - self._last_adl_log_time < 60:  # Раз в минуту
                    return
            else:
                self._last_adl_log_time = 0

            # Получаем актуальные данные позиций с биржи для ADL
            try:
                exchange_positions = await self.client.get_positions()
                adl_summary = []
                for pos in exchange_positions or []:
                    pos_size = float(pos.get("pos", "0") or 0)
                    if abs(pos_size) < 1e-8:
                        continue
                    inst_id = pos.get("instId", "")
                    if not inst_id:
                        continue
                    symbol = inst_id.replace("-SWAP", "")
                    adl_rank = pos.get("adlRank") or pos.get("adl")
                    if adl_rank is not None:
                        try:
                            adl_rank = int(adl_rank)
                            upl = float(pos.get("upl", "0") or 0)
                            margin = float(pos.get("margin", "0") or 0)
                            adl_status = (
                                "🔴 ВЫСОКИЙ"
                                if adl_rank >= 4
                                else "🟡 СРЕДНИЙ"
                                if adl_rank >= 2
                                else "🟢 НИЗКИЙ"
                            )
                            adl_summary.append(
                                {
                                    "symbol": symbol,
                                    "adl_rank": adl_rank,
                                    "status": adl_status,
                                    "upl": upl,
                                    "margin": margin,
                                }
                            )
                            # Обновляем ADL в active_positions
                            if symbol in self.active_positions:
                                self.active_positions[symbol]["adl_rank"] = adl_rank
                        except (ValueError, TypeError):
                            pass

                # Логируем сводку ADL для всех позиций
                if adl_summary:
                    adl_info = ", ".join(
                        [
                            f"{item['symbol']}: {item['status']} (rank={item['adl_rank']}, PnL={item['upl']:.2f} USDT)"
                            for item in adl_summary
                        ]
                    )
                    logger.info(f"📊 ADL мониторинг всех позиций: {adl_info}")

                    # Предупреждение при высоком ADL на любой позиции
                    high_adl_positions = [
                        item for item in adl_summary if item["adl_rank"] >= 4
                    ]
                    if high_adl_positions:
                        high_adl_info = ", ".join(
                            [
                                f"{item['symbol']} (rank={item['adl_rank']})"
                                for item in high_adl_positions
                            ]
                        )
                        logger.warning(
                            f"⚠️ ВЫСОКИЙ ADL обнаружен для позиций: {high_adl_info} "
                            f"(риск автоматического сокращения биржей)"
                        )

                self._last_adl_log_time = time.time()
            except Exception as e:
                logger.debug(f"⚠️ Не удалось получить ADL данные: {e}")

            # ✅ НОВОЕ: Периодический мониторинг статистики разворотов (раз в 5 минут)
            if hasattr(self, "_last_reversal_stats_log_time"):
                if (
                    time.time() - self._last_reversal_stats_log_time < 300
                ):  # Раз в 5 минут
                    pass
                else:
                    try:
                        if self.trading_statistics:
                            # Получаем статистику разворотов для всех символов и режимов
                            all_symbols = list(set(self.active_positions.keys()))
                            if all_symbols:
                                reversal_summary = []
                                for symbol in all_symbols:
                                    stats = self.trading_statistics.get_reversal_stats(
                                        symbol=symbol
                                    )
                                    if stats["total_reversals"] > 0:
                                        reversal_summary.append(
                                            f"{symbol}: {stats['total_reversals']} разворотов "
                                            f"(↓{stats['v_down_count']}, ↑{stats['v_up_count']}, "
                                            f"avg={stats['avg_price_change']:.2%})"
                                        )

                                if reversal_summary:
                                    reversal_info = ", ".join(reversal_summary)
                                    logger.info(
                                        f"📊 Статистика разворотов: {reversal_info}"
                                    )

                            # Общая статистика по режимам
                            for regime in ["trending", "ranging", "choppy"]:
                                stats = self.trading_statistics.get_reversal_stats(
                                    regime=regime
                                )
                                if stats["total_reversals"] > 0:
                                    logger.info(
                                        f"📊 Развороты в режиме {regime}: "
                                        f"{stats['total_reversals']} разворотов "
                                        f"(↓{stats['v_down_count']}, ↑{stats['v_up_count']})"
                                    )

                        self._last_reversal_stats_log_time = time.time()
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить статистику разворотов: {e}"
                        )
            else:
                self._last_reversal_stats_log_time = 0

        except Exception as e:
            logger.error(f"Ошибка управления позициями: {e}")

    async def _monitor_limit_orders(self):
        """Совместимость: делегирует мониторинг лимитных ордеров координатору."""
        await self.order_coordinator.monitor_limit_orders()

    async def _update_performance(self):
        """Обновление статистики производительности"""
        try:
            # Обновление статистики (update_stats не async, убираем await)
            self.performance_tracker.update_stats(self.active_positions)

        except Exception as e:
            logger.error(f"Ошибка обновления статистики: {e}")

    async def _on_liquidation_warning(
        self,
        level: str,
        symbol: str,
        side: str,
        margin_ratio: float,
        details: Dict[str, Any],
    ):
        """Обработка предупреждений о ликвидации"""
        try:
            if level == "critical":
                logger.critical(
                    f"🚨 КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: {symbol} {side} - маржа: {margin_ratio:.1f}%"
                )

                # Дополнительные действия при критическом уровне
                await self._emergency_actions(symbol, side)

        except Exception as e:
            logger.error(f"Ошибка обработки предупреждения о ликвидации: {e}")

    async def _emergency_close_all_positions(self):
        """Экстренное закрытие всех позиций"""
        try:
            logger.critical("🚨 ЭКСТРЕННОЕ ЗАКРЫТИЕ ВСЕХ ПОЗИЦИЙ!")

            for symbol in list(self.active_positions.keys()):
                await self.position_manager.close_position_manually(symbol)
                logger.info(f"✅ Позиция {symbol} закрыта экстренно")

        except Exception as e:
            logger.error(f"Ошибка экстренного закрытия позиций: {e}")

    async def _emergency_actions(self, symbol: str, side: str):
        """Экстренные действия при критическом уровне"""
        try:
            # Дополнительные проверки и действия
            logger.critical(f"🚨 Экстренные действия для {symbol} {side}")

        except Exception as e:
            logger.error(f"Ошибка экстренных действий: {e}")

    def _normalize_symbol(self, symbol: str) -> str:
        """Нормализует символ для единообразного использования в кэшах и блокировках"""
        # Убираем все разделители и приводим к верхнему регистру
        # "BTC-USDT" → "BTCUSDT", "BTCUSDT" → "BTCUSDT", "BTC-USDT-SWAP" → "BTCUSDT"
        normalized = symbol.replace("-", "").replace("_", "").upper()
        # Если есть SWAP, убираем
        normalized = normalized.replace("SWAP", "")
        return normalized

    # ✅ РЕФАКТОРИНГ: Методы _check_for_signals, _create_market_data_from_price, _execute_signal_from_price удалены - перенесены в SignalCoordinator

    # ✅ РЕФАКТОРИНГ: Метод _calculate_position_size удален - вся логика перенесена в RiskManager.calculate_position_size

    def _get_balance_profile(self, balance: float) -> dict:
        """Определяет профиль баланса - ВСЕ параметры из конфига!"""
        balance_profiles = getattr(self.scalping_config, "balance_profiles", {})

        if not balance_profiles:
            logger.error(
                "❌ balance_profiles не найден в конфиге! Проверьте config_futures.yaml"
            )
            raise ValueError("balance_profiles должен быть указан в конфиге")

        # ✅ АДАПТИВНАЯ СИСТЕМА: Профили берутся из конфига, сортируем по threshold
        profile_list = []
        for profile_name, profile_config in balance_profiles.items():
            threshold = getattr(profile_config, "threshold", None)
            if threshold is None:
                logger.warning(
                    f"⚠️ Профиль {profile_name} не имеет threshold, пропускаем"
                )
                continue
            profile_list.append(
                {"name": profile_name, "threshold": threshold, "config": profile_config}
            )

        # Сортируем по threshold (от меньшего к большему)
        profile_list.sort(key=lambda x: x["threshold"])

        if not profile_list:
            logger.error("❌ Не найдено ни одного валидного профиля в конфиге!")
            raise ValueError("Должен быть хотя бы один профиль в balance_profiles")

        # Определяем профиль по балансу
        for profile in profile_list:
            if balance <= profile["threshold"]:
                profile_config = profile["config"]
                profile_name = profile["name"]

                # ✅ ВАРИАНТ B: Прогрессивная адаптация
                progressive = getattr(profile_config, "progressive", False)
                if progressive:
                    min_balance = getattr(profile_config, "min_balance", None)
                    size_at_min = getattr(profile_config, "size_at_min", None)
                    size_at_max = getattr(profile_config, "size_at_max", None)

                    if (
                        min_balance is not None
                        and size_at_min is not None
                        and size_at_max is not None
                    ):
                        threshold = profile_config.threshold

                        # Для профиля 'large' используется max_balance вместо threshold
                        if profile_name == "large":
                            max_balance = getattr(
                                profile_config, "max_balance", threshold
                            )
                            if balance <= min_balance:
                                base_pos_usd = size_at_min
                            elif balance >= max_balance:
                                base_pos_usd = size_at_max
                            else:
                                progress = (balance - min_balance) / (
                                    max_balance - min_balance
                                )
                                base_pos_usd = (
                                    size_at_min + (size_at_max - size_at_min) * progress
                                )
                        else:
                            # Для других профилей
                            if balance <= min_balance:
                                base_pos_usd = size_at_min
                            elif balance >= threshold:
                                base_pos_usd = size_at_max
                            else:
                                progress = (balance - min_balance) / (
                                    threshold - min_balance
                                )
                                base_pos_usd = (
                                    size_at_min + (size_at_max - size_at_min) * progress
                                )

                        logger.debug(
                            f"📊 Прогрессивная адаптация для {profile_name}: "
                            f"баланс ${balance:.2f} → размер ${base_pos_usd:.2f} "
                            f"(min_balance=${min_balance:.2f}, threshold=${threshold:.2f}, "
                            f"size_at_min=${size_at_min:.2f}, size_at_max=${size_at_max:.2f})"
                        )
                    else:
                        # Если параметры прогрессивной адаптации не указаны, используем base_position_usd
                        base_pos_usd = getattr(
                            profile_config, "base_position_usd", None
                        )
                        if base_pos_usd is None or base_pos_usd <= 0:
                            logger.error(
                                f"❌ Профиль {profile_name}: base_position_usd не указан или <= 0 в конфиге!"
                            )
                            raise ValueError(
                                f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                            )
                else:
                    # Используем фиксированный base_position_usd
                    base_pos_usd = getattr(profile_config, "base_position_usd", None)
                    if base_pos_usd is None or base_pos_usd <= 0:
                        logger.error(
                            f"❌ Профиль {profile_name}: base_position_usd не указан или <= 0 в конфиге!"
                        )
                        raise ValueError(
                            f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                        )

                # ✅ МОДЕРНИЗАЦИЯ: Убираем fallback значения, требуем из конфига
                min_pos_usd = getattr(profile_config, "min_position_usd", None)
                max_pos_usd = getattr(profile_config, "max_position_usd", None)

                if min_pos_usd is None or min_pos_usd <= 0:
                    logger.error(
                        f"❌ min_position_usd не указан в конфиге для профиля {profile_name}! "
                        f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> min_position_usd"
                    )
                    raise ValueError(
                        f"min_position_usd должен быть указан в конфиге для профиля {profile_name}"
                    )
                if max_pos_usd is None or max_pos_usd <= 0:
                    logger.error(
                        f"❌ max_position_usd не указан в конфиге для профиля {profile_name}! "
                        f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_position_usd"
                    )
                    raise ValueError(
                        f"max_position_usd должен быть указан в конфиге для профиля {profile_name}"
                    )

                max_open_positions = getattr(profile_config, "max_open_positions", None)
                if max_open_positions is None or max_open_positions <= 0:
                    logger.error(
                        f"❌ max_open_positions не указан в конфиге для профиля {profile_name}! "
                        f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_open_positions"
                    )
                    raise ValueError(
                        f"max_open_positions должен быть указан в конфиге для профиля {profile_name}"
                    )

                # ✅ МОДЕРНИЗАЦИЯ: Убираем fallback значения, требуем из конфига
                max_position_percent = getattr(
                    profile_config, "max_position_percent", None
                )
                if max_position_percent is None or max_position_percent <= 0:
                    logger.error(
                        f"❌ max_position_percent не указан в конфиге для профиля {profile_name}! "
                        f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_position_percent"
                    )
                    raise ValueError(
                        f"max_position_percent должен быть указан в конфиге для профиля {profile_name}"
                    )

                return {
                    "name": profile_name,
                    "base_position_usd": base_pos_usd,
                    "min_position_usd": min_pos_usd,
                    "max_position_usd": max_pos_usd,
                    "max_open_positions": max_open_positions,
                    "max_position_percent": max_position_percent,
                }

        # Если баланс больше всех порогов - используем последний (самый большой) профиль
        last_profile = profile_list[-1]
        profile_config = last_profile["config"]
        profile_name = last_profile["name"]
        logger.debug(
            f"📊 Баланс {balance:.2f} больше всех порогов, используем профиль {profile_name}"
        )

        # ✅ ВАРИАНТ B: Прогрессивная адаптация для последнего профиля
        progressive = getattr(profile_config, "progressive", False)
        if progressive:
            min_balance = getattr(profile_config, "min_balance", None)
            size_at_min = getattr(profile_config, "size_at_min", None)
            size_at_max = getattr(profile_config, "size_at_max", None)

            if (
                min_balance is not None
                and size_at_min is not None
                and size_at_max is not None
            ):
                # Для профиля 'large' используется max_balance
                if profile_name == "large":
                    max_balance = getattr(profile_config, "max_balance", 999999.0)
                    if balance <= min_balance:
                        base_pos_usd = size_at_min
                    elif balance >= max_balance:
                        base_pos_usd = size_at_max
                    else:
                        progress = (balance - min_balance) / (max_balance - min_balance)
                        base_pos_usd = (
                            size_at_min + (size_at_max - size_at_min) * progress
                        )
                else:
                    threshold = profile_config.threshold
                    if balance <= min_balance:
                        base_pos_usd = size_at_min
                    elif balance >= threshold:
                        base_pos_usd = size_at_max
                    else:
                        progress = (balance - min_balance) / (threshold - min_balance)
                        base_pos_usd = (
                            size_at_min + (size_at_max - size_at_min) * progress
                        )

                logger.debug(
                    f"📊 Прогрессивная адаптация для {profile_name}: "
                    f"баланс ${balance:.2f} → размер ${base_pos_usd:.2f}"
                )
            else:
                base_pos_usd = getattr(profile_config, "base_position_usd", None)
                if base_pos_usd is None or base_pos_usd <= 0:
                    logger.error(
                        f"❌ Профиль {profile_name}: base_position_usd не указан в конфиге!"
                    )
                    raise ValueError(
                        f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                    )
        else:
            base_pos_usd = getattr(profile_config, "base_position_usd", None)
            if base_pos_usd is None or base_pos_usd <= 0:
                logger.error(
                    f"❌ Профиль {profile_name}: base_position_usd не указан в конфиге!"
                )
                raise ValueError(
                    f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                )

        # ✅ МОДЕРНИЗАЦИЯ: Убираем fallback значения, требуем из конфига
        min_pos_usd = getattr(profile_config, "min_position_usd", None)
        max_pos_usd = getattr(profile_config, "max_position_usd", None)
        if min_pos_usd is None or min_pos_usd <= 0:
            logger.error(
                f"❌ min_position_usd не указан в конфиге для профиля {profile_name}! "
                f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> min_position_usd"
            )
            raise ValueError(
                f"min_position_usd должен быть указан в конфиге для профиля {profile_name}"
            )
        if max_pos_usd is None or max_pos_usd <= 0:
            logger.error(
                f"❌ max_position_usd не указан в конфиге для профиля {profile_name}! "
                f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_position_usd"
            )
            raise ValueError(
                f"max_position_usd должен быть указан в конфиге для профиля {profile_name}"
            )

        max_open_positions = getattr(profile_config, "max_open_positions", None)
        if max_open_positions is None or max_open_positions <= 0:
            logger.error(
                f"❌ max_open_positions не указан в конфиге для профиля {profile_name}! "
                f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_open_positions"
            )
            raise ValueError(
                f"max_open_positions должен быть указан в конфиге для профиля {profile_name}"
            )

        max_position_percent = getattr(profile_config, "max_position_percent", None)
        if max_position_percent is None or max_position_percent <= 0:
            logger.error(
                f"❌ max_position_percent не указан в конфиге для профиля {profile_name}! "
                f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_position_percent"
            )
            raise ValueError(
                f"max_position_percent должен быть указан в конфиге для профиля {profile_name}"
            )

        return {
            "name": profile_name,
            "base_position_usd": base_pos_usd,
            "min_position_usd": min_pos_usd,
            "max_position_usd": max_pos_usd,
            "max_open_positions": max_open_positions,
            "max_position_percent": max_position_percent,
        }

    def _get_regime_params(
        self, regime_name: str, symbol: Optional[str] = None
    ) -> dict:
        """Получает параметры текущего режима из ARM"""
        try:
            scalping_config = getattr(self.config, "scalping", None)
            if not scalping_config:
                logger.warning("scalping_config не найден")
                return {}

            adaptive_regime = None
            if hasattr(scalping_config, "adaptive_regime"):
                adaptive_regime = getattr(scalping_config, "adaptive_regime", None)
            elif isinstance(scalping_config, dict):
                adaptive_regime = scalping_config.get("adaptive_regime", {})

            if not adaptive_regime:
                logger.debug("adaptive_regime не найден в scalping_config")
                return {}

            adaptive_dict = self.config_manager.to_dict(adaptive_regime)
            regime_params = self.config_manager.to_dict(
                adaptive_dict.get(regime_name, {})
            )

            if symbol:
                symbol_profile = self.symbol_profiles.get(symbol, {})
                regime_profile = symbol_profile.get(regime_name.lower(), {})
                arm_override = self.config_manager.to_dict(
                    regime_profile.get("arm", {})
                )
                if arm_override:
                    regime_params = self.config_manager.deep_merge_dict(
                        regime_params, arm_override
                    )

            return regime_params

        except Exception as e:
            logger.warning(f"Ошибка получения параметров режима {regime_name}: {e}")
            return {}

    def _get_adaptive_risk_params(
        self, balance: float, regime: Optional[str] = None, symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        ✅ НОВОЕ: Получает адаптивные параметры риска с учетом режима рынка и баланса.

        Приоритет параметров:
        1. Режим рынка (ARM) - ПРИОРИТЕТ 1
        2. Баланс профиль (Balance Profiles) - ПРИОРИТЕТ 2
        3. Базовые параметры (fallback) - ПРИОРИТЕТ 3

        Args:
            balance: Текущий баланс
            regime: Режим рынка (trending, ranging, choppy). Если None, определяется автоматически.
            symbol: Символ для торговли (опционально)

        Returns:
            Словарь с адаптивными параметрами риска:
            - max_loss_per_trade_percent: Максимальная потеря на сделку (%)
            - max_margin_percent: Максимальная маржа (%)
            - max_drawdown_percent: Максимальная просадка (%)
            - max_margin_safety_percent: Максимальная маржа безопасности (%)
            - min_balance_usd: Минимальный баланс (USD)
            - min_time_between_orders_seconds: Минимальное время между ордерами (сек)
            - position_override_tolerance_percent: Толерантность для override (%)
            - strength_multipliers: Множители силы сигнала (dict)
            - strength_thresholds: Пороги силы сигнала (dict)
        """
        try:
            # 1. Получаем базовые параметры из конфига
            risk_config = getattr(self.config, "risk", None)
            if not risk_config:
                logger.warning(
                    "⚠️ risk конфигурация не найдена, используем fallback значения"
                )
                return self._get_fallback_risk_params()

            # ✅ ЭТАП 1: Используем ConfigManager для получения адаптивных параметров риска
            # Этот метод уже вынесен в ConfigManager, просто вызываем его
            return self.config_manager.get_adaptive_risk_params(
                balance, regime, symbol, signal_generator=self.signal_generator
            )

        except Exception as e:
            logger.error(
                f"❌ Ошибка получения адаптивных параметров риска: {e}", exc_info=True
            )
            return self.config_manager.get_fallback_risk_params()

    def _get_adaptive_delay(self, delay_key: str, default_ms: float) -> float:
        """✅ ЭТАП 1: Получает адаптивную задержку через ConfigManager"""
        return self.config_manager.get_adaptive_delay(
            delay_key, default_ms, self._delays_config, self.signal_generator
        )

    def _get_fallback_risk_params(self) -> Dict[str, Any]:
        """✅ ЭТАП 1: Возвращает fallback параметры риска через ConfigManager"""
        return self.config_manager.get_fallback_risk_params()

    def _validate_risk_params(
        self, params: Dict[str, Any], regime: str, profile_name: str
    ) -> Dict[str, Any]:
        """✅ ЭТАП 1: Валидация параметров риска через ConfigManager"""
        return self.config_manager.validate_risk_params(params, regime, profile_name)

    async def _get_used_margin(self) -> float:
        """
        ✅ НОВОЕ: Получает использованную маржу из всех открытых позиций на бирже.

        Returns:
            Использованная маржа в USD (сумма маржи всех открытых позиций)
        """
        try:
            # Получаем все позиции с биржи
            exchange_positions = await self.client.get_positions()
            if not exchange_positions:
                return 0.0

            total_margin = 0.0

            for pos in exchange_positions:
                try:
                    pos_size = float(pos.get("pos", "0") or 0)
                except (TypeError, ValueError):
                    pos_size = 0.0

                # Пропускаем закрытые позиции
                if abs(pos_size) < 1e-8:
                    continue

                inst_id = pos.get("instId", "")
                if not inst_id:
                    continue

                symbol = inst_id.replace("-SWAP", "")

                # Получаем маржу из позиции
                margin_raw = pos.get("margin")
                try:
                    margin = float(margin_raw) if margin_raw is not None else 0.0
                except (TypeError, ValueError):
                    margin = 0.0

                # Если маржа не указана в позиции, рассчитываем её
                if margin <= 0:
                    try:
                        entry_price = float(pos.get("avgPx", 0) or 0)
                    except (TypeError, ValueError):
                        entry_price = 0.0

                    if entry_price > 0:
                        # Получаем ctVal для корректного перевода контрактов в монеты
                        ct_val = 0.01
                        try:
                            details = await self.client.get_instrument_details(symbol)
                            if details:
                                ct_val = float(details.get("ctVal", ct_val)) or ct_val
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Не удалось получить ctVal для {symbol} при расчете маржи: {e}"
                            )

                        abs_size = abs(pos_size)
                        size_in_coins = abs_size * ct_val

                        # Рассчитываем маржу: (size_in_coins * entry_price) / leverage
                        leverage = getattr(self.scalping_config, "leverage", 3) or 3
                        margin = (size_in_coins * entry_price) / max(leverage, 1e-6)

                total_margin += max(margin, 0.0)

            logger.debug(f"📊 Использованная маржа с биржи: ${total_margin:.2f}")
            return total_margin

        except Exception as e:
            logger.error(f"❌ Ошибка получения использованной маржи: {e}", exc_info=True)
            # ✅ НОВОЕ: Fallback - пытаемся прочитать из DataRegistry
            if self.data_registry:
                try:
                    margin_data = await self.data_registry.get_margin()
                    if margin_data and margin_data.get("used") is not None:
                        return margin_data["used"]
                except Exception:
                    pass
            # Последний fallback - возвращаем 0.0
            return 0.0

    async def _check_drawdown_protection(self) -> bool:
        """
        🛡️ Защита от drawdown

        Проверяет просадку баланса и блокирует новые сделки при превышении лимита

        Returns:
            True - можно торговать
            False - drawdown активирован, стоп торговле
        """
        try:
            if self.initial_balance is None:
                return True

            # ✅ НОВОЕ: Читаем баланс из DataRegistry
            current_balance = None
            if self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    if balance_data:
                        current_balance = balance_data.get("balance")
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка получения баланса из DataRegistry для drawdown: {e}"
                    )

            # Fallback на прямой запрос к API
            if current_balance is None:
                current_balance = await self.client.get_balance()

            drawdown = (self.initial_balance - current_balance) / self.initial_balance

            # ✅ МОДЕРНИЗАЦИЯ: Получаем адаптивный max_drawdown_percent из конфига
            # Определяем режим и баланс профиль для получения адаптивных параметров
            regime = None
            if (
                hasattr(self.signal_generator, "regime_manager")
                and self.signal_generator.regime_manager
            ):
                regime = self.signal_generator.regime_manager.get_current_regime()

            adaptive_risk_params = self.config_manager.get_adaptive_risk_params(
                current_balance, regime, signal_generator=self.signal_generator
            )
            max_drawdown_percent = (
                adaptive_risk_params.get("max_drawdown_percent", 5.0) / 100.0
            )  # Конвертируем в доли

            if drawdown > max_drawdown_percent:
                logger.critical(
                    f"🚨 DRAWDOWN ЗАЩИТА! "
                    f"Просадка: {drawdown*100:.2f}% > {max_drawdown_percent*100:.1f}% "
                    f"(режим={regime or 'unknown'})"
                )

                # 🛑 Emergency Stop
                await self._emergency_stop()

                return False

            elif drawdown > max_drawdown_percent * 0.7:  # 70% от лимита
                logger.warning(
                    f"⚠️ Близко к drawdown: {drawdown*100:.2f}% "
                    f"(лимит: {max_drawdown_percent*100:.1f}%, режим={regime or 'unknown'})"
                )

            return True

        except Exception as e:
            logger.error(f"Ошибка проверки drawdown: {e}")
            return True  # На всякий случай разрешаем

    async def _emergency_stop(self):
        """
        🛑 Emergency Stop - Аварийная остановка

        Используется при критических ситуациях:
        - Drawdown > max_drawdown_percent
        - Margin close to call
        - Multiple losses in a row

        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Теперь блокирует торговлю временно,
        но автоматически разблокирует при восстановлении баланса.
        """
        try:
            logger.critical("🚨 EMERGENCY STOP АКТИВИРОВАН!")

            # 1. Немедленно закрываем ВСЕ позиции
            logger.critical("🛑 Закрытие всех позиций...")
            for symbol, position in list(self.active_positions.items()):
                try:
                    await self.position_manager.close_position_manually(symbol)
                    logger.info(f"✅ Позиция {symbol} закрыта")
                except Exception as e:
                    logger.error(f"❌ Ошибка закрытия {symbol}: {e}")

            # 2. ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Блокируем новые сделки ВРЕМЕННО
            # Сохраняем флаг emergency_stop для автоматической разблокировки
            self._emergency_stop_active = True
            self._emergency_stop_time = time.time()
            self._emergency_stop_balance = await self.client.get_balance()

            # ✅ ИСПРАВЛЕНО: НЕ останавливаем весь бот (self.is_running остается True)
            # Блокируем только открытие новых позиций через флаг _emergency_stop_active
            # Это позволяет автоматически разблокировать при восстановлении баланса
            logger.critical("🛑 Торговля временно заблокирована (emergency stop)")
            logger.critical(
                f"📊 Баланс при emergency stop: ${self._emergency_stop_balance:.2f}, "
                f"будет автоматически разблокировано при восстановлении"
            )

            # 3. Отправляем alert (здесь можно добавить телеграм/email)
            current_balance = await self.client.get_balance()
            drawdown = (
                (self.initial_balance - current_balance) / self.initial_balance * 100
            )
            logger.critical(
                f"📧 ALERT: Emergency Stop activated! "
                f"Balance: ${current_balance:.2f}, "
                f"Drawdown: {drawdown:.2f}%"
            )

            # 4. Сохраняем логи
            logger.critical("💾 Логи сохранены")

            # 5. ✅ ИСПРАВЛЕНО: Не ждем ручного разрешения - будет автоматическая разблокировка
            logger.critical(
                "⏸️ Торговля заблокирована. Будет автоматически разблокирована при восстановлении баланса."
            )

        except Exception as e:
            logger.error(f"Ошибка в Emergency Stop: {e}")

    async def _update_trailing_stop_loss(self, symbol: str, current_price: float):
        """Совместимость: делегирует обновление TrailingStopLoss координатору."""
        await self.trailing_sl_coordinator.update_trailing_stop_loss(
            symbol, current_price
        )

    async def _periodic_tsl_check(self):
        """Совместимость: делегирует периодическую проверку TSL координатору."""
        await self.trailing_sl_coordinator.periodic_check()

    async def _handle_private_ws_positions(self, positions_data: list):
        """Совместимость: делегирует обработку обновлений позиций координатору."""
        await self.websocket_coordinator.handle_private_ws_positions(positions_data)

    async def _handle_private_ws_orders(self, orders_data: list):
        """Совместимость: делегирует обработку обновлений ордеров координатору."""
        await self.websocket_coordinator.handle_private_ws_orders(orders_data)

    async def _handle_position_closed_via_ws(self, symbol: str):
        """Совместимость: делегирует обработку закрытия позиции координатору."""
        await self.websocket_coordinator.handle_position_closed_via_ws(symbol)

    async def _get_current_price_fallback(self, symbol: str) -> Optional[float]:
        """
        Получение текущей цены через REST API (fallback если WebSocket не отвечает).

        Делегирует вызов WebSocketCoordinator.

        Args:
            symbol: Символ (например, BTC-USDT)

        Returns:
            Текущая цена или None если не удалось получить
        """
        if hasattr(self, "websocket_coordinator") and self.websocket_coordinator:
            return await self.websocket_coordinator.get_current_price_fallback(symbol)
        # Fallback для случая, когда координатор еще не инициализирован
        return None

    async def _check_emergency_stop_unlock(self):
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Проверка возможности разблокировки после emergency stop

        Автоматически разблокирует торговлю если:
        - Прошло достаточно времени (минимум 5 минут)
        - Drawdown восстановился до <70% от лимита
        - Баланс восстановился или стабилизировался
        """
        try:
            if (
                not hasattr(self, "_emergency_stop_active")
                or not self._emergency_stop_active
            ):
                return

            import time

            current_time = time.time()
            time_since_emergency = current_time - self._emergency_stop_time

            # ✅ АДАПТИВНО: Получаем параметры emergency_stop из конфига по режиму
            emergency_config = getattr(self.scalping_config, "emergency_stop", {})
            if not emergency_config or not getattr(emergency_config, "enabled", True):
                return  # Emergency stop отключен

            # Определяем текущий режим рынка
            regime = None
            if (
                hasattr(self.signal_generator, "regime_manager")
                and self.signal_generator.regime_manager
            ):
                regime_obj = self.signal_generator.regime_manager.get_current_regime()
                if hasattr(regime_obj, "value"):
                    regime = regime_obj.value.lower()
                elif isinstance(regime_obj, str):
                    regime = regime_obj.lower()

            # Получаем параметры для текущего режима
            by_regime = getattr(emergency_config, "by_regime", {})
            regime_config = getattr(by_regime, regime, None) if regime else None

            if regime_config:
                min_lock_minutes = getattr(regime_config, "min_lock_minutes", 5)
                unlock_threshold_percent = getattr(
                    regime_config, "unlock_threshold_percent", 70
                )
            else:
                # Fallback значения
                min_lock_minutes = 5
                unlock_threshold_percent = 70

            min_lock_time = min_lock_minutes * 60  # Конвертируем в секунды

            if time_since_emergency < min_lock_time:
                return  # Слишком рано для разблокировки

            # Получаем текущий баланс
            current_balance = await self.client.get_balance()

            # Проверяем drawdown
            current_drawdown = (
                self.initial_balance - current_balance
            ) / self.initial_balance

            # Получаем адаптивный max_drawdown_percent
            adaptive_risk_params = self.config_manager.get_adaptive_risk_params(
                current_balance, regime, signal_generator=self.signal_generator
            )
            max_drawdown_percent = (
                adaptive_risk_params.get("max_drawdown_percent", 5.0) / 100.0
            )

            # ✅ АДАПТИВНО: Разблокируем если drawdown < unlock_threshold_percent% от лимита
            unlock_threshold = max_drawdown_percent * (unlock_threshold_percent / 100.0)

            if current_drawdown < unlock_threshold:
                logger.info(
                    f"✅ Emergency Stop разблокирован автоматически: "
                    f"drawdown={current_drawdown*100:.2f}% < {unlock_threshold*100:.2f}% "
                    f"(лимит: {max_drawdown_percent*100:.1f}%), "
                    f"время блокировки: {time_since_emergency/60:.1f} мин"
                )
                self._emergency_stop_active = False
                self._emergency_stop_time = 0.0
                self._emergency_stop_balance = 0.0
            else:
                logger.debug(
                    f"⏸️ Emergency Stop все еще активен: "
                    f"drawdown={current_drawdown*100:.2f}% >= {unlock_threshold*100:.2f}%, "
                    f"время блокировки: {time_since_emergency/60:.1f} мин"
                )

        except Exception as e:
            logger.error(f"Ошибка проверки разблокировки emergency stop: {e}")

    async def _periodic_tsl_check(self):
        """Совместимость: делегирует периодическую проверку TSL координатору."""
        await self.trailing_sl_coordinator.periodic_check()

    async def _handle_private_ws_positions(self, positions_data: list):
        """Совместимость: делегирует обработку обновлений позиций координатору."""
        await self.websocket_coordinator.handle_private_ws_positions(positions_data)

    async def _handle_private_ws_orders(self, orders_data: list):
        """Совместимость: делегирует обработку обновлений ордеров координатору."""
        await self.websocket_coordinator.handle_private_ws_orders(orders_data)

    async def _handle_position_closed_via_ws(self, symbol: str):
        """Совместимость: делегирует обработку закрытия позиции координатору."""
        await self.websocket_coordinator.handle_position_closed_via_ws(symbol)

    async def _get_current_price_fallback(self, symbol: str) -> Optional[float]:
        """
        Получение текущей цены через REST API (fallback если WebSocket не отвечает).

        Делегирует вызов WebSocketCoordinator.

        Args:
            symbol: Символ (например, BTC-USDT)

        Returns:
            Текущая цена или None если не удалось получить
        """
        if hasattr(self, "websocket_coordinator") and self.websocket_coordinator:
            return await self.websocket_coordinator.get_current_price_fallback(symbol)
        # Fallback для случая, когда координатор еще не инициализирован
        return None

    async def _check_emergency_stop_unlock(self):
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Проверка возможности разблокировки после emergency stop

        Автоматически разблокирует торговлю если:
        - Прошло достаточно времени (минимум 5 минут)
        - Drawdown восстановился до <70% от лимита
        - Баланс восстановился или стабилизировался
        """
        try:
            if (
                not hasattr(self, "_emergency_stop_active")
                or not self._emergency_stop_active
            ):
                return

            import time

            current_time = time.time()
            time_since_emergency = current_time - self._emergency_stop_time

            # ✅ АДАПТИВНО: Получаем параметры emergency_stop из конфига по режиму
            emergency_config = getattr(self.scalping_config, "emergency_stop", {})
            if not emergency_config or not getattr(emergency_config, "enabled", True):
                return  # Emergency stop отключен

            # Определяем текущий режим рынка
            regime = None
            if (
                hasattr(self.signal_generator, "regime_manager")
                and self.signal_generator.regime_manager
            ):
                regime_obj = self.signal_generator.regime_manager.get_current_regime()
                if hasattr(regime_obj, "value"):
                    regime = regime_obj.value.lower()
                elif isinstance(regime_obj, str):
                    regime = regime_obj.lower()

            # Получаем параметры для текущего режима
            by_regime = getattr(emergency_config, "by_regime", {})
            regime_config = getattr(by_regime, regime, None) if regime else None

            if regime_config:
                min_lock_minutes = getattr(regime_config, "min_lock_minutes", 5)
                unlock_threshold_percent = getattr(
                    regime_config, "unlock_threshold_percent", 70
                )
            else:
                # Fallback значения
                min_lock_minutes = 5
                unlock_threshold_percent = 70

            min_lock_time = min_lock_minutes * 60  # Конвертируем в секунды

            if time_since_emergency < min_lock_time:
                return  # Слишком рано для разблокировки

            # Получаем текущий баланс
            current_balance = await self.client.get_balance()

            # Проверяем drawdown
            current_drawdown = (
                self.initial_balance - current_balance
            ) / self.initial_balance

            # Получаем адаптивный max_drawdown_percent
            adaptive_risk_params = self.config_manager.get_adaptive_risk_params(
                current_balance, regime, signal_generator=self.signal_generator
            )
            max_drawdown_percent = (
                adaptive_risk_params.get("max_drawdown_percent", 5.0) / 100.0
            )

            # ✅ АДАПТИВНО: Разблокируем если drawdown < unlock_threshold_percent% от лимита
            unlock_threshold = max_drawdown_percent * (unlock_threshold_percent / 100.0)

            if current_drawdown < unlock_threshold:
                logger.info(
                    f"✅ Emergency Stop разблокирован автоматически: "
                    f"drawdown={current_drawdown*100:.2f}% < {unlock_threshold*100:.2f}% "
                    f"(лимит: {max_drawdown_percent*100:.1f}%), "
                    f"время блокировки: {time_since_emergency/60:.1f} мин"
                )
                self._emergency_stop_active = False
                self._emergency_stop_time = 0.0
                self._emergency_stop_balance = 0.0
            else:
                logger.debug(
                    f"⏸️ Emergency Stop все еще активен: "
                    f"drawdown={current_drawdown*100:.2f}% >= {unlock_threshold*100:.2f}%, "
                    f"время блокировки: {time_since_emergency/60:.1f} мин"
                )

        except Exception as e:
            logger.error(f"❌ Ошибка проверки разблокировки emergency stop: {e}")

    async def _check_position_holding_time(
        self,
        symbol: str,
        current_price: float,
        profit_pct: float,
        market_regime: str = None,
    ):
        """
        ✅ НОВОЕ: Проверка времени жизни позиции с продлением для прибыльных

        Args:
            symbol: Символ позиции
            current_price: Текущая цена
            profit_pct: Прибыль в процентах (с учетом комиссии)
            market_regime: Режим рынка (trending/ranging/choppy)
        """
        try:
            position = self.active_positions.get(symbol, {})
            if not position:
                return

            entry_time = position.get("entry_time")
            if not entry_time:
                # Если нет entry_time - пытаемся использовать timestamp
                entry_time = position.get("timestamp")
                if not entry_time:
                    # ✅ ИСПРАВЛЕНО: Используем DEBUG вместо WARNING, так как это временное состояние при открытии позиции
                    logger.debug(
                        f"⚠️ Нет времени открытия для позиции {symbol} (позиция только что открыта, entry_time будет установлен при инициализации TSL)"
                    )
                    return

            # Вычисляем время удержания
            if isinstance(entry_time, datetime):
                # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                elif entry_time.tzinfo != timezone.utc:
                    entry_time = entry_time.astimezone(timezone.utc)
                time_held = (
                    datetime.now(timezone.utc) - entry_time
                ).total_seconds() / 60  # в минутах
            else:
                # Если это строка или другой формат - пропускаем
                logger.debug(
                    f"⚠️ Неверный формат entry_time для {symbol}: {entry_time}"
                )
                return

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: TIMEOUT - абсолютный лимит времени
            # Получаем timeout_minutes из TSL (жесткий лимит времени) ПЕРЕД остальными проверками
            timeout_minutes = None
            tsl = self.trailing_sl_coordinator.get_tsl(symbol)
            if tsl and hasattr(tsl, "timeout_minutes"):
                timeout_minutes = tsl.timeout_minutes

            # ✅ ПЕРВАЯ ПРОВЕРКА: TIMEOUT - принудительное закрытие после максимального времени
            if timeout_minutes is not None and time_held >= timeout_minutes:
                logger.info(
                    f"⏰ TIMEOUT для {symbol}: {time_held:.1f} минут >= {timeout_minutes:.1f} минут, "
                    f"принудительно закрываем (прибыль: {profit_pct:.2%})"
                )
                await self._close_position(symbol, "timeout")
                return

            # Получаем параметры режима
            try:
                if (
                    hasattr(self.signal_generator, "regime_manager")
                    and self.signal_generator.regime_manager
                ):
                    regime_obj = (
                        self.signal_generator.regime_manager.get_current_regime()
                        if not market_regime
                        else market_regime
                    )
                    if isinstance(regime_obj, str):
                        regime_obj = regime_obj.lower()

                    # ✅ ИСПРАВЛЕНО: Получаем параметры режима через get_current_parameters()
                    # и из scalping_config для параметров продления времени
                    regime_params = (
                        self.signal_generator.regime_manager.get_current_parameters()
                    )

                    if regime_params:
                        max_holding_minutes = getattr(
                            regime_params, "max_holding_minutes", 30
                        )

                        # Получаем параметры продления времени из scalping_config
                        regime_name = (
                            regime_obj
                            if isinstance(regime_obj, str)
                            else regime_obj.value.lower()
                        )
                        regime_config = getattr(
                            self.scalping_config.adaptive_regime, regime_name, None
                        )

                        if regime_config:
                            extend_time_if_profitable = getattr(
                                regime_config, "extend_time_if_profitable", True
                            )
                            min_profit_for_extension = getattr(
                                regime_config, "min_profit_for_extension", 0.1
                            )
                            extension_percent = getattr(
                                regime_config, "extension_percent", 50
                            )
                        else:
                            # Fallback если режим не найден в конфиге
                            extend_time_if_profitable = True
                            min_profit_for_extension = 0.1
                            extension_percent = 50
                    else:
                        # Fallback значения
                        max_holding_minutes = 30
                        extend_time_if_profitable = True
                        min_profit_for_extension = 0.1
                        extension_percent = 50
                else:
                    # Fallback значения
                    max_holding_minutes = 30
                    extend_time_if_profitable = True
                    min_profit_for_extension = 0.1
                    extension_percent = 50
            except Exception as e:
                logger.debug(
                    f"Не удалось получить параметры режима: {e}, используем fallback"
                )
                max_holding_minutes = 30
                extend_time_if_profitable = True
                min_profit_for_extension = 0.1
                extension_percent = 50

            # Используем сохраненное значение max_holding_minutes, если было продление
            actual_max_holding = position.get(
                "max_holding_minutes", max_holding_minutes
            )

            # Проверяем, истекло ли время (max_holding, но не TIMEOUT)
            if time_held >= actual_max_holding:
                time_extended = position.get("time_extended", False)

                # Если время можно продлить и позиция в прибыли
                if (
                    extend_time_if_profitable
                    and not time_extended
                    and profit_pct > min_profit_for_extension
                ):
                    # Продлеваем время от исходного значения
                    original_max_holding = max_holding_minutes
                    extension_minutes = original_max_holding * (
                        extension_percent / 100.0
                    )
                    new_max_holding = original_max_holding + extension_minutes
                    position["time_extended"] = True
                    position[
                        "max_holding_minutes"
                    ] = new_max_holding  # Сохраняем новое значение

                    logger.info(
                        f"⏰ Позиция {symbol} в прибыли {profit_pct:.2%} (>{min_profit_for_extension:.2%}), "
                        f"продлеваем время на {extension_minutes:.1f} минут "
                        f"(до {new_max_holding:.1f} минут, было {original_max_holding:.1f})"
                    )
                    return  # Продлили, не закрываем
                else:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #6: Проверяем min_profit_to_close перед закрытием по времени
                    # НЕ закрываем по max_holding если позиция в прибыли > min_profit_to_close
                    min_profit_to_close = None
                    tsl = self.trailing_sl_coordinator.get_tsl(symbol)
                    if tsl:
                        min_profit_to_close = getattr(tsl, "min_profit_to_close", None)

                    if (
                        min_profit_to_close is not None
                        and profit_pct > min_profit_to_close
                    ):
                        # Позиция в прибыли превышает min_profit_to_close - НЕ закрываем по max_holding
                        # Бот продолжает искать оптимальный момент закрытия через TP/SL
                        logger.info(
                            f"⏰ Позиция {symbol} удерживается {time_held:.1f} минут "
                            f"(лимит: {actual_max_holding:.1f} минут), "
                            f"прибыль {profit_pct:.2%} > min_profit_to_close {min_profit_to_close:.2%}, "
                            f"не закрываем по max_holding (бот продолжает искать оптимальный момент через TP/SL)"
                        )
                        return  # Не закрываем по max_holding, даем боту время найти оптимальный момент

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: НЕ закрываем убыточные позиции по времени
                    # Убыточные позиции должны закрываться только по trailing stop или loss cut
                    if profit_pct <= 0:
                        logger.info(
                            f"⏰ Позиция {symbol} удерживается {time_held:.1f} минут "
                            f"(лимит: {actual_max_holding:.1f} минут), "
                            f"но прибыль {profit_pct:.2%} <= 0%, "
                            f"НЕ закрываем по времени (используем только trailing stop и loss cut)"
                        )
                        return  # Не закрываем убыточные позиции по времени

                    # Время истекло и позиция не в прибыли > min_profit_to_close - закрываем
                    logger.info(
                        f"⏰ Позиция {symbol} удерживается {time_held:.1f} минут "
                        f"(лимит: {actual_max_holding:.1f} минут), "
                        f"прибыль: {profit_pct:.2%}, закрываем по времени"
                    )
                    await self._close_position(symbol, "max_holding_time")
                    return

        except Exception as e:
            logger.error(f"Ошибка проверки времени жизни позиции {symbol}: {e}")

    async def _update_orders_cache_status(self):
        """Совместимость: делегирует обновление статуса ордеров координатору."""
        await self.order_coordinator.update_orders_cache_status(self._normalize_symbol)

    async def _close_position(self, symbol: str, reason: str):
        """Закрытие позиции через position_manager"""
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем, что позиция еще не закрывается
            # Это предотвращает множественные попытки закрытия одной и той же позиции
            if not hasattr(self, "_closing_positions"):
                self._closing_positions = set()

            if symbol in self._closing_positions:
                logger.debug(
                    f"⚠️ Позиция {symbol} уже закрывается (reason={reason}), пропускаем"
                )
                return

            position = self.active_positions.get(symbol, {})

            if not position:
                logger.debug(
                    f"⚠️ Позиция {symbol} уже закрыта или не найдена (reason={reason})"
                )
                return

            # ✅ Помечаем позицию как закрывающуюся
            self._closing_positions.add(symbol)

            try:
                # ✅ ЛОГИРОВАНИЕ: Логируем причину закрытия и детали позиции
                # ✅ FIX: Приводим к float чтобы избежать TypeError при сравнении str vs int
                entry_price = float(position.get("entry_price", 0) or 0)
                size = float(position.get("size", 0) or 0)
                side = position.get("position_side", "unknown")
                entry_time = position.get("entry_time")

                # Вычисляем время в позиции
                import time
                from datetime import datetime

                if isinstance(entry_time, datetime):
                    # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                    elif entry_time.tzinfo != timezone.utc:
                        entry_time = entry_time.astimezone(timezone.utc)
                    minutes_in_position = (
                        datetime.now(timezone.utc) - entry_time
                    ).total_seconds() / 60.0
                else:
                    minutes_in_position = 0.0

                logger.info(
                    f"🛑 Закрытие позиции {symbol}: {reason} "
                    f"(side={side}, size={size}, entry={entry_price}, time={minutes_in_position:.2f} мин)"
                )

                # ✅ Закрываем через position_manager (API)
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем TradeResult для записи в CSV
                # ✅ ИСПРАВЛЕНО: Передаем reason в close_position_manually
                trade_result = await self.position_manager.close_position_manually(
                    symbol, reason=reason
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Записываем сделку в CSV через performance_tracker
                if trade_result and hasattr(self, "performance_tracker"):
                    try:
                        self.performance_tracker.record_trade(trade_result)
                        logger.debug(f"✅ Сделка {symbol} записана в CSV")
                    except Exception as e:
                        logger.error(f"❌ Ошибка записи сделки в CSV: {e}")

                # ✅ НОВОЕ: Записываем статистику для динамической адаптации
                if trade_result and hasattr(self, "trading_statistics"):
                    try:
                        # ✅ ИСПРАВЛЕНО: Получаем режим рынка из per-symbol ARM (если есть)
                        regime = "ranging"  # Fallback
                        if hasattr(self, "signal_generator") and self.signal_generator:
                            # Сначала пробуем per-symbol ARM
                            if (
                                hasattr(self.signal_generator, "regime_managers")
                                and symbol in self.signal_generator.regime_managers
                            ):
                                regime_manager = self.signal_generator.regime_managers[
                                    symbol
                                ]
                                regime_obj = regime_manager.get_current_regime()
                                if regime_obj:
                                    regime = (
                                        regime_obj.value.lower()
                                        if hasattr(regime_obj, "value")
                                        else str(regime_obj).lower()
                                    )
                            # Если нет per-symbol ARM - используем общий
                            elif (
                                hasattr(self.signal_generator, "regime_manager")
                                and self.signal_generator.regime_manager
                            ):
                                regime_obj = (
                                    self.signal_generator.regime_manager.get_current_regime()
                                )
                                if regime_obj:
                                    regime = (
                                        regime_obj.value.lower()
                                        if hasattr(regime_obj, "value")
                                        else str(regime_obj).lower()
                                    )

                        # Получаем данные из trade_result
                        side = (
                            trade_result.side
                            if hasattr(trade_result, "side")
                            else position.get("side", "buy")
                        )
                        pnl = trade_result.pnl if hasattr(trade_result, "pnl") else 0.0
                        entry_price = (
                            trade_result.entry_price
                            if hasattr(trade_result, "entry_price")
                            else position.get("entry_price", 0)
                        )
                        exit_price = (
                            trade_result.exit_price
                            if hasattr(trade_result, "exit_price")
                            else position.get("current_price", 0)
                        )
                        entry_time = (
                            trade_result.entry_time
                            if hasattr(trade_result, "entry_time")
                            else position.get("entry_time", datetime.now())
                        )
                        exit_time = (
                            trade_result.exit_time
                            if hasattr(trade_result, "exit_time")
                            else datetime.now()
                        )
                        signal_strength = position.get("signal_strength", 0.0)
                        signal_type = position.get("signal_type", "unknown")

                        # Записываем статистику
                        self.trading_statistics.record_trade(
                            symbol=symbol,
                            side=side,
                            regime=regime,
                            pnl=pnl,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            entry_time=entry_time,
                            exit_time=exit_time,
                            signal_strength=signal_strength,
                            signal_type=signal_type,
                        )
                        logger.debug(
                            f"📊 Статистика записана для {symbol}: regime={regime}, pnl={pnl:.2f}, "
                            f"win_rate={self.trading_statistics.get_win_rate(regime, symbol):.2%} "
                            f"(по паре), общий win_rate={self.trading_statistics.get_win_rate(regime):.2%} (по режиму)"
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка записи статистики: {e}")

                # ✅ Обновляем кэш ордеров
                normalized_symbol = self.config_manager.normalize_symbol(symbol)
                if normalized_symbol in self.last_orders_cache:
                    self.last_orders_cache[normalized_symbol]["status"] = "closed"
                    logger.debug(f"📦 Обновлен статус ордера для {symbol} на 'closed'")

                # 🛡️ Обновляем маржу и лимит позиций
                position_margin = position.get("margin", 0)
                if position_margin > 0:
                    # ✅ МОДЕРНИЗАЦИЯ: Обновляем total_margin_used (будет пересчитано при следующей синхронизации)
                    # Временно обновляем локально для быстрого доступа
                    self.total_margin_used -= position_margin
                    logger.debug(
                        f"💼 Общая маржа после закрытия: ${self.total_margin_used:.2f}"
                    )
                    # ✅ МОДЕРНИЗАЦИЯ: После закрытия позиции синхронизируем маржу с биржей
                    # Это гарантирует, что total_margin_used всегда актуален
                    try:
                        # Быстрая синхронизация маржи (без полной синхронизации позиций)
                        updated_margin = await self._get_used_margin()
                        self.total_margin_used = updated_margin
                        if (
                            hasattr(self, "_total_margin_used_ref")
                            and self._total_margin_used_ref
                        ):
                            self._total_margin_used_ref[0] = updated_margin
                            logger.debug(
                                f"💼 Обновлена маржа с биржи: ${self.total_margin_used:.2f} (после закрытия позиции)"
                            )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Не удалось обновить маржу с биржи после закрытия позиции: {e}"
                        )

                # ✅ FIX: Приводим к float чтобы избежать TypeError
                position_size = float(position.get("size", 0) or 0)
                entry_price = float(position.get("entry_price", 0) or 0)
                if position_size > 0 and entry_price > 0:
                    size_usd = position_size * entry_price
                    if symbol in self.max_size_limiter.position_sizes:
                        self.max_size_limiter.remove_position(symbol)
                        logger.debug(
                            f"✅ Позиция {symbol} удалена из MaxSizeLimiter: ${size_usd:.2f} (осталось: ${self.max_size_limiter.get_total_size():.2f})"
                        )

                # Удаляем локальное состояние вне зависимости от маржи
                if symbol in self.active_positions:
                    del self.active_positions[symbol]

                # ✅ РЕФАКТОРИНГ: Используем trailing_sl_coordinator для удаления TSL
                tsl = self.trailing_sl_coordinator.remove_tsl(symbol)
                if tsl:
                    tsl.reset()

                logger.debug(
                    f"🔄 Позиция {symbol} закрыта, система готова к новым сигналам"
                )

                await self._sync_positions_with_exchange(force=True)
            except Exception as e:
                logger.error(f"Ошибка закрытия позиции {symbol}: {e}")
            finally:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Убираем позицию из списка закрывающихся
                # Это позволяет закрыть позицию снова, если она откроется заново
                if hasattr(self, "_closing_positions"):
                    self._closing_positions.discard(symbol)

        except Exception as e:
            logger.error(f"Критическая ошибка закрытия позиции {symbol}: {e}")
            # ✅ Убираем позицию из списка закрывающихся при критической ошибке
            if hasattr(self, "_closing_positions"):
                self._closing_positions.discard(symbol)

    @property
    def active_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        ✅ ПРОКСИ к PositionRegistry для обратной совместимости.

        Возвращает все позиции из единого источника истины (PositionRegistry).
        Это свойство обеспечивает обратную совместимость с существующим кодом,
        который использует orchestrator.active_positions напрямую.

        ⚠️ ВНИМАНИЕ: Для записи используйте position_registry.register_position()
        Прямое присваивание в active_positions не синхронизирует данные!

        Returns:
            Копия словаря всех позиций из PositionRegistry
        """
        try:
            return self.position_registry.get_all_positions_sync()
        except Exception as e:
            logger.error(
                f"❌ Ошибка получения active_positions из PositionRegistry: {e}"
            )
            return {}  # Fallback: пустой словарь

    async def get_status(self) -> Dict[str, Any]:
        """Получение статуса системы"""
        try:
            # ✅ НОВОЕ: Читаем баланс из DataRegistry
            balance = None
            if self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    if balance_data:
                        balance = balance_data.get("balance")
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка получения баланса из DataRegistry для статуса: {e}"
                    )

            # Fallback на прямой запрос к API
            if balance is None:
                balance = await self.client.get_balance()
            margin_status = await self.liquidation_guard.get_margin_status(self.client)
            slippage_stats = self.slippage_guard.get_slippage_statistics()

            return {
                "is_running": self.is_running,
                "balance": balance,
                "active_positions_count": len(self.active_positions),
                "margin_status": margin_status,
                "slippage_statistics": slippage_stats,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Ошибка получения статуса: {e}")
            return {"error": str(e), "timestamp": datetime.now().isoformat()}

    def _to_dict(self, raw: Any) -> Dict[str, Any]:
        """Преобразует объект в словарь, поддерживая Pydantic модели и обычные объекты"""
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        # ✅ Поддержка Pydantic v2 (model_dump)
        if hasattr(raw, "model_dump"):
            try:
                return raw.model_dump()  # type: ignore[attr-defined]
            except Exception:
                pass
        # ✅ Поддержка Pydantic v1 (dict)
        if hasattr(raw, "dict"):
            try:
                return dict(raw.dict(by_alias=True))  # type: ignore[attr-defined]
            except TypeError:
                try:
                    return dict(raw.dict())  # type: ignore[attr-defined]
                except Exception:
                    pass
        # ✅ Поддержка обычных объектов (__dict__)
        if hasattr(raw, "__dict__"):
            return dict(raw.__dict__)
        return {}

    def _deep_merge_dict(
        self, base: Dict[str, Any], override: Dict[str, Any]
    ) -> Dict[str, Any]:
        merged = dict(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _normalize_symbol_profiles(
        self, raw_profiles: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        profiles: Dict[str, Dict[str, Any]] = {}
        for symbol, profile in (raw_profiles or {}).items():
            normalized: Dict[str, Any] = {}
            profile_dict = self._to_dict(profile)

            # ✅ ВАРИАНТ B: Сохраняем position_multiplier на верхнем уровне символа
            if "position_multiplier" in profile_dict:
                normalized["position_multiplier"] = profile_dict["position_multiplier"]

            # ✅ НОВОЕ: Сохраняем tp_percent на верхнем уровне символа (если есть)
            if "tp_percent" in profile_dict:
                tp_value = profile_dict["tp_percent"]
                # Проверяем, что это число, а не dict
                if isinstance(tp_value, (int, float)):
                    normalized["tp_percent"] = float(tp_value)
                elif isinstance(tp_value, str):
                    try:
                        normalized["tp_percent"] = float(tp_value)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"⚠️ Не удалось конвертировать tp_percent в float для {symbol}: {tp_value}"
                        )

            for regime_name, regime_data in profile_dict.items():
                regime_key = str(regime_name).lower()
                # Пропускаем position_multiplier и tp_percent, так как они уже сохранены выше
                if regime_key in {"position_multiplier", "tp_percent"}:
                    continue
                if regime_key in {"__detection__", "detection"}:
                    normalized["__detection__"] = self._to_dict(regime_data)
                    continue
                regime_dict = self._to_dict(regime_data)
                # ✅ НОВОЕ: Сохраняем tp_percent на уровне режима (если есть)
                if "tp_percent" in regime_dict:
                    tp_value = regime_dict["tp_percent"]
                    # Проверяем, что это число, а не dict
                    if isinstance(tp_value, (int, float)):
                        if regime_key not in normalized:
                            normalized[regime_key] = {}
                        normalized[regime_key]["tp_percent"] = float(tp_value)
                    elif isinstance(tp_value, str):
                        try:
                            if regime_key not in normalized:
                                normalized[regime_key] = {}
                            normalized[regime_key]["tp_percent"] = float(tp_value)
                        except (ValueError, TypeError):
                            logger.warning(
                                f"⚠️ Не удалось конвертировать tp_percent в float для {symbol} ({regime_key}): {tp_value}"
                            )

                for section, section_value in list(regime_dict.items()):
                    # Пропускаем tp_percent, так как он уже обработан выше
                    if section == "tp_percent":
                        continue
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

    def _load_symbol_profiles(self) -> Dict[str, Dict[str, Any]]:
        scalping_config = getattr(self.config, "scalping", None)
        if not scalping_config:
            return {}
        adaptive_regime = None
        if hasattr(scalping_config, "adaptive_regime"):
            adaptive_regime = getattr(scalping_config, "adaptive_regime", None)
        elif isinstance(scalping_config, dict):
            adaptive_regime = scalping_config.get("adaptive_regime")
        adaptive_dict = self._to_dict(adaptive_regime)
        raw_profiles = adaptive_dict.get("symbol_profiles", {})
        return self._normalize_symbol_profiles(raw_profiles)

    def _get_symbol_regime_profile(
        self, symbol: Optional[str], regime: Optional[str]
    ) -> Dict[str, Any]:
        if not symbol:
            return {}
        profile = self.symbol_profiles.get(symbol, {})
        if not profile:
            return {}
        if regime:
            return self._to_dict(profile.get(regime.lower(), {}))
        return {}
