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
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig
# Futures-специфичные модули безопасности
from src.strategies.modules.liquidation_guard import LiquidationGuard
from src.strategies.modules.margin_calculator import MarginCalculator
from src.strategies.modules.slippage_guard import SlippageGuard

from ..spot.performance_tracker import PerformanceTracker
from .indicators.fast_adx import FastADX
from .indicators.funding_rate_monitor import FundingRateMonitor
from .indicators.order_flow_indicator import OrderFlowIndicator
from .indicators.trailing_stop_loss import TrailingStopLoss
from .order_executor import FuturesOrderExecutor
from .position_manager import FuturesPositionManager
from .risk.max_size_limiter import MaxSizeLimiter
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

        # 🛡️ Защиты риска
        self.initial_balance = None  # Для drawdown расчета
        self.total_margin_used = 0.0  # Для max margin проверки
        self.max_loss_per_trade = 0.02  # 2% макс потеря на сделку
        self.max_margin_percent = 0.80  # 80% макс маржа
        self.max_drawdown_percent = 0.05  # 5% макс просадка

        # Получение API конфигурации
        okx_config = config.get_okx_config()

        # Клиент
        # ✅ АДАПТИВНО: leverage из конфига (используем self.scalping_config, который уже определен выше)
        leverage = getattr(self.scalping_config, "leverage", 3)
        if leverage is None or leverage <= 0:
            logger.warning("⚠️ leverage не указан в конфиге, используем 3 (fallback)")
            leverage = 3

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

        self.margin_calculator = MarginCalculator(
            default_leverage=leverage,  # ✅ АДАПТИВНО: Из конфига (уже получен выше)
            maintenance_margin_ratio=0.01,
            initial_margin_ratio=0.1,
        )

        self.liquidation_guard = LiquidationGuard(
            margin_calculator=self.margin_calculator,
            warning_threshold=1.8,
            danger_threshold=1.3,
            critical_threshold=1.1,
            auto_close_threshold=1.05,
        )

        self.slippage_guard = SlippageGuard(
            max_slippage_percent=slippage_config.get("max_slippage_percent", 0.1),
            max_spread_percent=slippage_config.get("max_spread_percent", 0.05),
            order_timeout=slippage_config.get("order_timeout", 30.0),
        )

        # Торговые модули
        # ✅ Передаем клиент в signal_generator для инициализации фильтров
        self.signal_generator = FuturesSignalGenerator(config, client=self.client)
        self.order_executor = FuturesOrderExecutor(
            config, self.client, self.slippage_guard
        )
        self.position_manager = FuturesPositionManager(
            config, self.client, self.margin_calculator
        )
        self.performance_tracker = PerformanceTracker()

        self.symbol_profiles: Dict[str, Dict[str, Any]] = self._load_symbol_profiles()

        # TrailingStopLoss для каждой позиции (словарь по символам)
        self.trailing_sl_by_symbol = {}

        # FastADX для быстрого определения тренда
        self.fast_adx = FastADX(period=9, threshold=20.0)

        # OrderFlowIndicator для анализа потока ордеров
        order_flow_params = None
        if getattr(config, "futures_modules", None):
            order_flow_params = getattr(config.futures_modules, "order_flow", None)
        if isinstance(order_flow_params, dict):
            of_window = order_flow_params.get("window", 100)
            of_long = order_flow_params.get("long_threshold", 0.1)
            of_short = order_flow_params.get("short_threshold", -0.1)
        else:
            of_window = getattr(order_flow_params, "window", 100)
            of_long = getattr(order_flow_params, "long_threshold", 0.1)
            of_short = getattr(order_flow_params, "short_threshold", -0.1)
        self.order_flow = OrderFlowIndicator(
            window=of_window,
            long_threshold=of_long,
            short_threshold=of_short,
        )

        # FundingRateMonitor для мониторинга фандинга
        self.funding_monitor = FundingRateMonitor(max_funding_rate=0.05)  # 0.05%

        # MaxSizeLimiter для защиты от больших позиций
        self.max_size_limiter = MaxSizeLimiter(
            max_single_size_usd=1000.0,  # $1000 за позицию
            max_total_size_usd=5000.0,  # $5000 всего
            max_positions=5,  # Максимум 5 позиций
        )

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

        # Состояние
        self.is_running = False
        self.active_positions = {}
        self.trading_session = None

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Кэш последних ордеров и задержки между сигналами
        # Кэш последних ордеров: {symbol: {order_id, timestamp, status}}
        self.last_orders_cache = {}
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
        self.signal_locks = {}  # Будет создаваться по требованию

        # ✅ Параметры синхронизации состояния с биржей
        check_interval = getattr(self.scalping_config, "check_interval", 5.0) or 5.0
        self.positions_sync_interval = max(15.0, check_interval * 3)
        self._last_positions_sync = 0.0

        logger.info("FuturesScalpingOrchestrator инициализирован")

    async def start(self):
        """Запуск Futures торгового бота"""
        try:
            logger.info("🚀 Запуск Futures торгового бота...")

            # Инициализация клиента
            await self._initialize_client()

            # Подключение WebSocket
            await self._initialize_websocket()

            # Запуск модулей безопасности
            await self._start_safety_modules()

            # Запуск торговых модулей
            await self._start_trading_modules()

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Загружаем существующие позиции и инициализируем TrailingStopLoss
            await self._load_existing_positions()

            # Основной торговый цикл
            self.is_running = True
            await self._main_trading_loop()

        except Exception as e:
            logger.error(f"❌ Критическая ошибка в Futures Orchestrator: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Остановка Futures торгового бота"""
        logger.info("🛑 Остановка Futures торгового бота...")

        self.is_running = False

        # Остановка модулей безопасности
        await self.liquidation_guard.stop_monitoring()
        await self.slippage_guard.stop_monitoring()

        # Отключение WebSocket
        await self.ws_manager.disconnect()

        # Закрытие клиента
        await self.client.close()

        logger.info("✅ Futures торговый бот остановлен")

    async def _initialize_client(self):
        """Инициализация клиента"""
        try:
            # Проверка баланса
            balance = await self.client.get_balance()
            logger.info(f"💰 Доступный баланс: {balance:.2f} USDT")

            # 🛡️ Инициализация начального баланса для drawdown
            if self.initial_balance is None:
                self.initial_balance = balance
                logger.info(f"📊 Начальный баланс: ${self.initial_balance:.2f}")

            if balance < 100:  # Минимальный баланс
                raise ValueError(f"Недостаточный баланс: {balance:.2f} USDT")

            # Установка плеча для торговых пар (только для production)
            if not self.client.sandbox:
                for symbol in self.scalping_config.symbols:
                    try:
                        # ✅ АДАПТИВНО: leverage из конфига
                        leverage = getattr(self.scalping_config, "leverage", None)
                        if leverage is None or leverage <= 0:
                            logger.warning(
                                f"⚠️ leverage не указан в конфиге для {symbol}, используем 3 (fallback)"
                            )
                            leverage = 3
                        await self.client.set_leverage(symbol, leverage)
                        logger.info(f"✅ Плечо {leverage}x установлено для {symbol}")
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Не удалось установить плечо для {symbol}: {e}"
                        )
            else:
                logger.info("Sandbox mode: пропускаем установку leverage")

        except Exception as e:
            logger.error(f"Ошибка инициализации клиента: {e}")
            raise

    async def _initialize_websocket(self):
        """Инициализация WebSocket для получения рыночных данных"""
        try:
            logger.info("📡 Подключение к WebSocket...")

            # Подключение
            if await self.ws_manager.connect():
                logger.info("✅ WebSocket подключен")

                # Callback для обработки тикеров (один на все инструменты)
                async def ticker_callback(data):
                    # Извлекаем instId из данных
                    if "data" in data and len(data["data"]) > 0:
                        inst_id = data["data"][0].get("instId", "")
                        # Убираем -SWAP суффикс для получения символа
                        symbol = inst_id.replace("-SWAP", "")
                        if symbol:
                            # ✅ Логируем получение данных из WebSocket (DEBUG, но будет видно в логах)
                            # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование каждого WebSocket сообщения
                            # logger.debug(f"📡 WebSocket: получены данные для {symbol}")
                            await self._handle_ticker_data(symbol, data)

                # Подписка на тикеры для всех символов
                for symbol in self.scalping_config.symbols:
                    inst_id = f"{symbol}-SWAP"
                    await self.ws_manager.subscribe(
                        channel="tickers",
                        inst_id=inst_id,
                        callback=ticker_callback,  # Один callback для всех
                    )

                logger.info(
                    f"📊 Подписка на тикеры для {len(self.scalping_config.symbols)} пар"
                )
            else:
                logger.warning("⚠️ Не удалось подключиться к WebSocket")

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации WebSocket: {e}")

    async def _handle_ticker_data(self, symbol: str, data: dict):
        """Обработка данных тикера"""
        try:
            # Извлекаем данные из ответа WebSocket
            if "data" in data and len(data["data"]) > 0:
                ticker = data["data"][0]

                # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование каждого тикера
                # Логируем только через INFO уровень (цена) для экономии места
                # logger.debug(f"🔍 Диагностика {symbol}: ...")

                if "last" in ticker:
                    price = float(ticker["last"])

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем FastADX для расчета тренда
                    # FastADX нужен для TrailingSL, чтобы адаптивно закрывать позиции
                    # ⚠️ ВАЖНО: Тикер не содержит high/low текущей свечи, поэтому используем
                    # текущую цену как приближение (high=low=close=price)
                    # Для точного расчета нужны свечные данные (1m), но тикер обновляется чаще
                    try:
                        if hasattr(self, "fast_adx") and self.fast_adx:
                            # Для тикера используем текущую цену как high/low/close
                            # Это даст базовое значение тренда (хотя и не идеально точное)
                            # В будущем можно добавить подписку на свечи 1m для более точного расчета
                            high = price
                            low = price
                            close = price

                            # Обновляем FastADX для расчета тренда
                            self.fast_adx.update(high=high, low=low, close=close)
                            # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование каждого FastADX update
                            # logger.debug(f"📊 FastADX обновлен для {symbol}")
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось обновить FastADX для {symbol}: {e}"
                        )

                    # ✅ Логируем получение данных тикера (INFO для видимости)
                    logger.info(f"💰 {symbol}: ${price:.2f}")

                    # Проверка TrailingStopLoss для открытых позиций
                    if (
                        symbol in self.active_positions
                        and "entry_price" in self.active_positions.get(symbol, {})
                    ):
                        await self._update_trailing_stop_loss(symbol, price)
                    else:
                        # Генерируем сигналы только если позиции нет
                        logger.debug(f"🔍 Проверка сигналов для {symbol}...")
                        await self._check_for_signals(symbol, price)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки данных тикера: {e}")

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

    async def _load_existing_positions(self):
        """✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Загружаем существующие позиции и инициализируем TrailingStopLoss"""
        try:
            logger.info("📊 Загрузка существующих позиций с биржи...")

            # Получаем все позиции с биржи
            all_positions = await self.client.get_positions()

            loaded_count = 0
            for pos in all_positions:
                pos_size = float(pos.get("pos", "0"))
                if abs(pos_size) < 0.000001:
                    continue  # Пропускаем нулевые позиции

                inst_id = pos.get("instId", "")
                symbol = inst_id.replace("-SWAP", "")

                # Получаем данные позиции
                entry_price = float(pos.get("avgPx", "0"))
                pos_side_raw = pos.get("posSide", "").lower()
                pos_size_abs = abs(pos_size)

                # Определяем сторону (buy/sell)
                if pos_size > 0:
                    side = "buy"  # LONG
                else:
                    side = "sell"  # SHORT

                if entry_price == 0:
                    logger.warning(f"⚠️ Entry price = 0 для {symbol}, пропускаем")
                    continue

                # Получаем текущую цену
                try:
                    ticker = await self.client.get_ticker(symbol)
                    current_price = float(ticker.get("last", entry_price))
                except:
                    current_price = entry_price
                    logger.warning(
                        f"⚠️ Не удалось получить текущую цену для {symbol}, используем entry_price"
                    )

                # Добавляем в active_positions
                from datetime import datetime

                self.active_positions[symbol] = {
                    "instId": inst_id,
                    "side": side,
                    "size": pos_size_abs,
                    "entry_price": entry_price,
                    "margin": float(pos.get("margin", "0")),
                    "entry_time": datetime.now(),  # Время загрузки (не точное время открытия)
                    "timestamp": datetime.now(),
                    "time_extended": False,
                }

                tsl = self._initialize_trailing_stop(
                    symbol=symbol,
                    entry_price=entry_price,
                    side=side,
                    current_price=current_price,
                )
                if tsl:
                    logger.info(
                        f"✅ Загружена позиция {symbol} {side.upper()}: "
                        f"size={pos_size_abs}, entry={entry_price:.2f}, "
                        f"TrailingStopLoss инициализирован"
                    )
                else:
                    logger.warning(
                        f"⚠️ Не удалось инициализировать TrailingStopLoss для {symbol}: "
                        f"entry_price={entry_price}, current_price={current_price}"
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

    def _get_trailing_sl_params(self) -> Dict[str, Optional[float]]:
        """Возвращает параметры Trailing SL с учетом конфига и fallback значений."""
        params: Dict[str, Optional[float]] = {
            "trading_fee_rate": 0.0009,
            "initial_trail": 0.05,
            "max_trail": 0.2,
            "min_trail": 0.02,
            "loss_cut_percent": None,
            "timeout_loss_percent": None,
            "timeout_minutes": None,
        }

        trailing_sl_config = None
        if hasattr(self.config, "futures_modules") and self.config.futures_modules:
            trailing_sl_config = self._get_config_value(
                self.config.futures_modules, "trailing_sl", None
            )

        if trailing_sl_config:
            params["trading_fee_rate"] = self._get_config_value(
                trailing_sl_config, "trading_fee_rate", params["trading_fee_rate"]
            )
            params["initial_trail"] = self._get_config_value(
                trailing_sl_config, "initial_trail", params["initial_trail"]
            )
            params["max_trail"] = self._get_config_value(
                trailing_sl_config, "max_trail", params["max_trail"]
            )
            params["min_trail"] = self._get_config_value(
                trailing_sl_config, "min_trail", params["min_trail"]
            )
            params["loss_cut_percent"] = self._get_config_value(
                trailing_sl_config, "loss_cut_percent", params["loss_cut_percent"]
            )
            params["timeout_loss_percent"] = self._get_config_value(
                trailing_sl_config,
                "timeout_loss_percent",
                params["timeout_loss_percent"],
            )
            params["timeout_minutes"] = self._get_config_value(
                trailing_sl_config, "timeout_minutes", params["timeout_minutes"]
            )

        # Нормализуем числовые значения
        if params["trading_fee_rate"] is not None:
            params["trading_fee_rate"] = max(0.0, float(params["trading_fee_rate"]))
        for key in ("initial_trail", "max_trail", "min_trail"):
            if params[key] is not None:
                params[key] = max(0.0, float(params[key]))

        return params

    def _initialize_trailing_stop(
        self,
        symbol: str,
        entry_price: float,
        side: str,
        current_price: Optional[float] = None,
        signal: Optional[Dict[str, Any]] = None,
    ) -> Optional[TrailingStopLoss]:
        """
        Создает или переинициализирует TrailingStopLoss для указанного символа.
        """
        if entry_price <= 0:
            return None

        params = self._get_trailing_sl_params()
        regime = signal.get("regime") if signal else None
        if (
            not regime
            and hasattr(self.signal_generator, "regime_managers")
            and symbol in getattr(self.signal_generator, "regime_managers", {})
        ):
            manager = self.signal_generator.regime_managers.get(symbol)
            if manager:
                regime = manager.get_current_regime()
        regime_profile = self._get_symbol_regime_profile(symbol, regime)
        trailing_overrides = self._to_dict(regime_profile.get("trailing_sl", {}))
        if trailing_overrides:
            for key, value in trailing_overrides.items():
                if key in params and value is not None:
                    params[key] = float(value)
        impulse_trailing = None
        if signal and signal.get("is_impulse"):
            impulse_trailing = signal.get("impulse_trailing") or {}
            if impulse_trailing:
                params["initial_trail"] = impulse_trailing.get(
                    "initial_trail", params["initial_trail"]
                )

        # Сбрасываем предыдущий экземпляр, если он был
        existing_tsl = self.trailing_sl_by_symbol.get(symbol)
        if existing_tsl:
            existing_tsl.reset()

        initial_trail = params["initial_trail"] or 0.0
        max_trail = params["max_trail"] or initial_trail
        min_trail = params["min_trail"] or 0.0
        trading_fee_rate = params["trading_fee_rate"] or 0.0

        tsl = TrailingStopLoss(
            initial_trail=initial_trail,
            max_trail=max_trail,
            min_trail=min_trail,
            trading_fee_rate=trading_fee_rate,
            loss_cut_percent=params["loss_cut_percent"],
            timeout_loss_percent=params["timeout_loss_percent"],
            timeout_minutes=params["timeout_minutes"],
        )
        tsl.initialize(entry_price=entry_price, side=side)
        if impulse_trailing:
            step_profit = float(impulse_trailing.get("step_profit", 0) or 0)
            step_trail = float(impulse_trailing.get("step_trail", 0) or 0)
            aggressive_cap = impulse_trailing.get("aggressive_max_trail")
            if step_profit > 0 and step_trail > 0:
                tsl.enable_aggressive_mode(
                    step_profit=step_profit,
                    step_trail=step_trail,
                    aggressive_max_trail=aggressive_cap,
                )
                logger.info(
                    f"🚀 TrailingSL импульсный режим для {symbol}: step_profit={step_profit:.3%}, "
                    f"step_trail={step_trail:.3%}, cap={aggressive_cap if aggressive_cap else 'auto'}"
                )
        if current_price and current_price > 0:
            tsl.update(current_price)
        self.trailing_sl_by_symbol[symbol] = tsl
        fee_display = trading_fee_rate if trading_fee_rate else 0.0
        logger.debug(
            f"TrailingStopLoss для {symbol}: trail={tsl.current_trail:.3%}, "
            f"fee={fee_display:.3%}"
        )
        return tsl

    async def _sync_positions_with_exchange(self, force: bool = False) -> None:
        """Синхронизирует локальные позиции и лимиты с фактическими данными биржи."""
        now = time.time()
        if (
            not force
            and (now - self._last_positions_sync) < self.positions_sync_interval
        ):
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

            try:
                entry_price = float(pos.get("avgPx", 0) or 0)
            except (TypeError, ValueError):
                entry_price = 0.0

            try:
                mark_price = float(pos.get("markPx", entry_price) or entry_price)
            except (TypeError, ValueError):
                mark_price = entry_price

            side = "buy" if pos_size > 0 else "sell"
            abs_size = abs(pos_size)

            margin_raw = pos.get("margin")
            try:
                margin = float(margin_raw) if margin_raw is not None else 0.0
            except (TypeError, ValueError):
                margin = 0.0

            if margin <= 0 and entry_price > 0:
                leverage = getattr(self.scalping_config, "leverage", 3) or 3
                margin = (abs_size * entry_price) / max(leverage, 1e-6)

            total_margin += max(margin, 0.0)

            effective_price = entry_price or mark_price
            timestamp = datetime.now()
            active_position = self.active_positions.setdefault(symbol, {})
            if "entry_time" not in active_position:
                active_position["entry_time"] = timestamp
            active_position.update(
                {
                    "instId": inst_id,
                    "side": side,
                    "size": abs_size,
                    "entry_price": effective_price,
                    "margin": margin,
                    "timestamp": timestamp,
                }
            )

            if symbol not in self.trailing_sl_by_symbol:
                self._initialize_trailing_stop(
                    symbol=symbol,
                    entry_price=effective_price,
                    side=side,
                    current_price=mark_price,
                )

            if effective_price > 0:
                self.max_size_limiter.position_sizes[symbol] = (
                    abs_size * effective_price
                )

        stale_symbols = set(self.active_positions.keys()) - seen_symbols
        for symbol in list(stale_symbols):
            logger.info(
                f"♻️ Позиция {symbol} отсутствует на бирже, очищаем локальное состояние"
            )
            self.active_positions.pop(symbol, None)
            if symbol in self.trailing_sl_by_symbol:
                self.trailing_sl_by_symbol[symbol].reset()
                self.trailing_sl_by_symbol.pop(symbol, None)
            if symbol in self.max_size_limiter.position_sizes:
                self.max_size_limiter.remove_position(symbol)
            normalized_symbol = self._normalize_symbol(symbol)
            if normalized_symbol in self.last_orders_cache:
                self.last_orders_cache[normalized_symbol]["status"] = "closed"

        self.total_margin_used = total_margin
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
                await self._process_signals(signals)

                if not self.is_running:
                    break

                # Управление позициями
                await self._manage_positions()

                if not self.is_running:
                    break

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Периодически обновляем статус ордеров в кэше
                await self._update_orders_cache_status()

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

            # Обновление активных позиций
            self.active_positions = {}
            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if size != 0:
                    self.active_positions[symbol] = position

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

    async def _process_signals(self, signals: List[Dict[str, Any]]):
        """Обработка торговых сигналов"""
        try:
            # 🔄 НОВОЕ: отключаем legacy-обработку, чтобы не дублировать реальные сигналы,
            # которые приходят из WebSocket (_check_for_signals)
            if not getattr(self.scalping_config, "use_legacy_signal_processing", False):
                logger.debug(
                    "⏭️ Legacy _process_signals пропущен (используется realtime обработка сигналов через WebSocket)."
                )
                return

            for signal in signals:
                symbol = signal.get("symbol")
                side = signal.get("side")
                strength = signal.get("strength", 0)

                # Проверка минимальной силы сигнала
                if strength < self.scalping_config.min_signal_strength:
                    continue

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем направление позиции!
                # На OKX Futures несколько ордеров в ОДНОМ направлении объединяются в ОДНУ позицию
                # Поэтому нужно блокировать новые ордера, если уже есть позиция в этом направлении
                max_positions_per_symbol = getattr(
                    self.scalping_config, "max_positions_per_symbol", 4
                )
                allow_concurrent = getattr(
                    self.scalping_config, "allow_concurrent_positions", False
                )

                try:
                    # Получаем реальные позиции с биржи
                    all_positions = await self.client.get_positions()
                    signal_side = signal.get("side", "").lower()  # "buy" или "sell"

                    # Определяем направление позиции для сигнала
                    signal_position_side = "long" if signal_side == "buy" else "short"

                    symbol_positions = [
                        p
                        for p in all_positions
                        if (
                            p.get("instId", "").replace("-SWAP", "") == symbol
                            or p.get("instId", "") == symbol
                        )
                        and abs(float(p.get("pos", "0"))) > 0.000001
                    ]

                    # Проверяем, есть ли уже позиция в направлении сигнала
                    position_in_signal_direction = None
                    for pos in symbol_positions:
                        pos_side = pos.get("posSide", "").lower()
                        pos_size = float(pos.get("pos", "0"))

                        # Определяем направление позиции
                        if pos_size > 0:
                            actual_side = "long"
                        else:
                            actual_side = "short"

                        # Если позиция в том же направлении, что и сигнал
                        if actual_side == signal_position_side:
                            position_in_signal_direction = pos
                            break

                    if position_in_signal_direction:
                        # ✅ КРИТИЧЕСКОЕ: Позиция уже есть в направлении сигнала
                        # На OKX Futures новый ордер в том же направлении просто увеличит размер позиции
                        # Это означает, что мы НЕ создаем новую позицию, а увеличиваем существующую
                        # Поэтому блокируем, чтобы не накапливать комиссию на одной позиции
                        pos_size = abs(
                            float(position_in_signal_direction.get("pos", "0"))
                        )
                        logger.warning(
                            f"⚠️ Позиция {symbol} {signal_position_side.upper()} УЖЕ ОТКРЫТА (size={pos_size}), "
                            f"БЛОКИРУЕМ новый {signal_side.upper()} ордер "
                            f"(на OKX Futures ордера в одном направлении объединяются в одну позицию, комиссия накапливается!)"
                        )
                        continue
                    elif len(symbol_positions) > 0:
                        # Есть позиции в ДРУГОМ направлении
                        if not allow_concurrent:
                            # РЕЖИМ 1: Не разрешаем несколько позиций
                            logger.debug(
                                f"⚠️ Позиция {symbol} в другом направлении уже открыта ({len(symbol_positions)} позиций), "
                                f"БЛОКИРУЕМ новые сигналы (allow_concurrent=false)"
                            )
                            continue
                        else:
                            # РЕЖИМ 2: Разрешаем позиции в разных направлениях, но проверяем лимит
                            if len(symbol_positions) >= max_positions_per_symbol:
                                logger.debug(
                                    f"⚠️ Достигнут лимит позиций по {symbol}: {len(symbol_positions)}/{max_positions_per_symbol}, "
                                    f"БЛОКИРУЕМ новые сигналы"
                                )
                                continue
                            else:
                                # Разрешаем - позиция в другом направлении (LONG + SHORT одновременно)
                                logger.debug(
                                    f"📊 Есть {len(symbol_positions)} позиция(й) по {symbol} в другом направлении, "
                                    f"разрешаем открытие {signal_position_side.upper()} позиции (allow_concurrent=true)"
                                )
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка проверки позиций для {symbol}: {e}")
                    # При ошибке - лучше пропустить, чем создать дубликат
                    continue

                # Валидация сигнала
                if await self._validate_signal(signal):
                    await self._execute_signal(signal)

        except Exception as e:
            logger.error(f"Ошибка обработки сигналов: {e}")

    async def _validate_signal(self, signal: Dict[str, Any]) -> bool:
        """Валидация торгового сигнала"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")

            # Получение баланса
            balance = await self.client.get_balance()

            # Расчет максимального размера позиции
            current_price = signal.get("price", 0)
            max_size = self.margin_calculator.calculate_max_position_size(
                balance, current_price
            )

            # Проверка минимального размера
            min_size = self.scalping_config.min_position_size
            if max_size < min_size:
                logger.warning(
                    f"Максимальный размер позиции {max_size:.6f} меньше минимального {min_size:.6f}"
                )
                return False

            # Валидация через Slippage Guard
            (
                is_valid,
                reason,
            ) = await self.slippage_guard.validate_order_before_placement(
                symbol=symbol,
                side=side,
                order_type="market",
                price=None,
                size=max_size,
                client=self.client,
            )

            if not is_valid:
                logger.warning(f"Сигнал не прошел валидацию: {reason}")
                return False

            return True

        except Exception as e:
            logger.error(f"Ошибка валидации сигнала: {e}")
            return False

    async def _execute_signal(self, signal: Dict[str, Any]):
        """Исполнение торгового сигнала"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            strength = signal.get("strength", 0)

            logger.info(f"🎯 Исполнение сигнала: {symbol} {side} (сила: {strength:.2f})")

            # 🔥 КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем активные ордера перед размещением
            try:
                inst_id = f"{symbol}-SWAP"
                active_orders = await self.client.get_active_orders(symbol)
                open_position_orders = [
                    o
                    for o in active_orders
                    if o.get("instId") == inst_id
                    and o.get("side", "").lower() in ["buy", "sell"]
                    and o.get("reduceOnly", "false").lower() != "true"
                ]
                if len(open_position_orders) > 0:
                    logger.warning(
                        f"⚠️ Уже есть {len(open_position_orders)} активных ордеров для {symbol}, пропускаем"
                    )
                    return
            except Exception as e:
                logger.warning(f"⚠️ Ошибка проверки активных ордеров: {e}")
                return

            # Расчет размера позиции
            balance = await self.client.get_balance()
            current_price = signal.get("price", 0)

            # Адаптивный размер позиции на основе силы сигнала
            risk_percentage = self.scalping_config.base_risk_percentage * strength
            position_size = self.margin_calculator.calculate_optimal_position_size(
                balance, current_price, risk_percentage
            )

            # Исполнение ордера
            result = await self.order_executor.execute_signal(signal, position_size)

            if result.get("success"):
                logger.info(f"✅ Сигнал {symbol} {side} успешно исполнен")
            else:
                logger.error(
                    f"❌ Ошибка исполнения сигнала {symbol}: {result.get('error')}"
                )

        except Exception as e:
            logger.error(f"Ошибка исполнения сигнала: {e}")

    async def _manage_positions(self):
        """Управление открытыми позициями"""
        try:
            for symbol, position in self.active_positions.items():
                await self.position_manager.manage_position(position)

        except Exception as e:
            logger.error(f"Ошибка управления позициями: {e}")

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

    async def _check_for_signals(self, symbol: str, price: float):
        """✅ РЕАЛЬНАЯ генерация сигналов на основе индикаторов"""
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Нормализуем символ для блокировки
            # Это предотвращает race condition при разных форматах ("BTC-USDT" vs "BTCUSDT")
            normalized_symbol = self._normalize_symbol(symbol)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: БЛОКИРОВКА для предотвращения race condition
            # Создаем блокировку для нормализованного символа, если её нет
            if normalized_symbol not in self.signal_locks:
                self.signal_locks[normalized_symbol] = asyncio.Lock()

            # Используем блокировку - только один поток может обрабатывать сигнал для символа одновременно
            async with self.signal_locks[normalized_symbol]:
                # ✅ ИСПРАВЛЕНИЕ: Убираем проверку "если позиция уже есть по символу"
                # Теперь разрешаем несколько позиций по одному символу (например, 3 на BTC и 3 на ETH)
                # Проверяем только общий лимит позиций

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1: Проверка задержки между сигналами (используем нормализованный символ)
                import time

                current_time = time.time()
                if normalized_symbol in self.last_signal_time:
                    time_since_last = (
                        current_time - self.last_signal_time[normalized_symbol]
                    )
                    if time_since_last < self.signal_cooldown_seconds:
                        logger.debug(
                            f"⏱️ Задержка между сигналами для {symbol}: {time_since_last:.1f}s < {self.signal_cooldown_seconds}s, пропускаем"
                        )
                        return

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2: Проверка последнего ордера через кэш (используем нормализованный символ)
                if normalized_symbol in self.last_orders_cache:
                    last_order = self.last_orders_cache[normalized_symbol]
                    order_time = last_order.get("timestamp", 0)
                    order_status = last_order.get("status", "unknown")
                    # ✅ УСИЛЕНО: Если ордер был размещен менее 15 секунд назад и pending - строго блокируем
                    # Это предотвращает двойные ордера из-за задержки API
                    time_since_order = current_time - order_time
                    if time_since_order < 15 and order_status == "pending":
                        logger.warning(
                            f"⚠️ Ордер для {symbol} был размещен {time_since_order:.1f}s назад (status=pending), "
                            f"строго блокируем новый ордер (предотвращение двойных ордеров)"
                        )
                        return
                    # Если последний ордер был недавно (менее 30 секунд) и не был отменен/исполнен - пропускаем
                    if time_since_order < 30 and order_status not in [
                        "filled",
                        "cancelled",
                        "rejected",
                    ]:
                        logger.debug(
                            f"⏱️ Последний ордер для {symbol} был недавно ({current_time - order_time:.1f}s назад), "
                            f"статус: {order_status}, пропускаем новый сигнал"
                        )
                        return

                # 🔥 КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем активные ордера ПЕРЕД генерацией сигнала
                # Используем кэш для оптимизации (проверяем не чаще раза в 5 секунд)
                inst_id = f"{symbol}-SWAP"
                should_check_orders = True
                if normalized_symbol in self.last_orders_check_time:
                    time_since_check = (
                        current_time - self.last_orders_check_time[normalized_symbol]
                    )
                    if time_since_check < 5:  # Проверяем не чаще раза в 5 секунд
                        # Используем кэш (с нормализованным символом)
                        if normalized_symbol in self.active_orders_cache:
                            cached_orders = self.active_orders_cache[normalized_symbol]
                            if cached_orders.get("order_ids"):
                                logger.debug(
                                    f"📦 Используем кэш активных ордеров для {symbol}: {len(cached_orders['order_ids'])} ордеров"
                                )
                                if len(cached_orders["order_ids"]) > 0:
                                    logger.warning(
                                        f"⚠️ В кэше есть {len(cached_orders['order_ids'])} активных ордеров для {symbol}, "
                                        f"пропускаем генерацию нового сигнала"
                                    )
                                    return
                                should_check_orders = False

                if should_check_orders:
                    try:
                        active_orders = await self.client.get_active_orders(symbol)
                        # Считаем только ордера на открытие позиции (не reduceOnly)
                        open_position_orders = [
                            o
                            for o in active_orders
                            if o.get("instId") == inst_id
                            and o.get("side", "").lower() in ["buy", "sell"]
                            and o.get("reduceOnly", "false").lower() != "true"
                        ]

                        # Обновляем кэш (с нормализованным символом)
                        self.active_orders_cache[normalized_symbol] = {
                            "order_ids": [o.get("ordId") for o in open_position_orders],
                            "timestamp": current_time,
                        }
                        self.last_orders_check_time[normalized_symbol] = current_time

                        if len(open_position_orders) > 0:
                            logger.warning(
                                f"⚠️ Уже есть {len(open_position_orders)} активных ордеров на открытие позиции {symbol}, "
                                f"пропускаем генерацию нового сигнала"
                            )
                            return
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка проверки активных ордеров для {symbol}: {e}"
                        )
                        # Если не можем проверить - лучше пропустить, чем создать дубликат
                        return

                # 🔥 СКАЛЬПИНГ: Проверяем реальные позиции на бирже перед открытием новых
                try:
                    all_positions = await self.client.get_positions()
                    active_positions_count = len(
                        [p for p in all_positions if float(p.get("pos", "0")) != 0]
                    )

                    # ✅ ИСПРАВЛЕНИЕ: Проверяем позиции по нескольким вариантам instId
                    # instId может быть в форматах: "ETH-USDT-SWAP", "ETH-USDT", "ETHUSDT-SWAP"
                    symbol_positions = []
                    for p in all_positions:
                        pos_inst_id = p.get("instId", "")
                        pos_size = abs(float(p.get("pos", "0")))

                        # Проверяем все возможные форматы
                        if pos_size > 0.000001:
                            # Формат "-SWAP" (стандартный)
                            if pos_inst_id == inst_id:
                                symbol_positions.append(p)
                            # Формат без "-SWAP" (если API вернул без суффикса)
                            elif pos_inst_id == symbol:
                                symbol_positions.append(p)
                            # Формат с другим разделителем
                            elif pos_inst_id.replace("-", "") == inst_id.replace(
                                "-", ""
                            ):
                                symbol_positions.append(p)

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем направление позиции!
                    # На OKX Futures несколько ордеров в ОДНОМ направлении объединяются в ОДНУ позицию
                    # Поэтому нужно блокировать новые ордера, если уже есть позиция в этом направлении
                    max_positions_per_symbol = getattr(
                        self.scalping_config, "max_positions_per_symbol", 4
                    )
                    allow_concurrent = getattr(
                        self.scalping_config, "allow_concurrent_positions", False
                    )

                    # Получаем направление сигнала из генератора сигналов
                    # Нужно определить направление сигнала здесь - но в _check_for_signals мы еще не знаем направление
                    # Поэтому проверяем все позиции и блокируем, если есть позиция в любом направлении
                    # (проверка направления будет в _process_signals)

                    if len(symbol_positions) > 0:
                        # ✅ КРИТИЧЕСКОЕ: На OKX Futures ордера в одном направлении объединяются
                        # Поэтому блокируем новые ордера, если уже есть позиция (независимо от направления)
                        # Это предотвращает накопление комиссии на одной позиции
                        positions_info = [
                            f"{p.get('instId')}: {p.get('pos')}"
                            for p in symbol_positions
                        ]
                        pos_size = abs(float(symbol_positions[0].get("pos", "0")))
                        pos_side = (
                            "long"
                            if float(symbol_positions[0].get("pos", "0")) > 0
                            else "short"
                        )
                        logger.warning(
                            f"⚠️ Позиция {symbol} {pos_side.upper()} УЖЕ ОТКРЫТА (size={pos_size}), "
                            f"БЛОКИРУЕМ новые ордера (на OKX Futures ордера в одном направлении объединяются в одну позицию, комиссия накапливается!). "
                            f"Позиции: {positions_info}"
                        )
                        return

                    balance = await self.client.get_balance()
                    balance_profile = self._get_balance_profile(balance)
                    max_open = balance_profile.get(
                        "max_open_positions", 6
                    )  # ✅ Увеличено до 6 (3 на BTC + 3 на ETH)

                    if active_positions_count >= max_open:
                        logger.debug(
                            f"⚠️ Достигнут лимит открытых позиций на бирже: {active_positions_count}/{max_open}. "
                            f"Пропускаем открытие {symbol}"
                        )
                        return

                    # 🔥 СКАЛЬПИНГ: Проверяем реальный баланс на бирже
                    # get_balance() возвращает equity (общий баланс с учетом PnL)
                    if balance < 20.0:  # Минимум $20 баланса для открытия позиции
                        logger.debug(
                            f"⚠️ Недостаточно баланса на бирже: ${balance:.2f} < $20.00. "
                            f"Пропускаем открытие {symbol}"
                        )
                        return

                except Exception as e:
                    logger.warning(f"⚠️ Ошибка проверки лимита позиций: {e}")

                # ✅ РЕАЛЬНАЯ ГЕНЕРАЦИЯ СИГНАЛОВ через signal_generator
                # Используем реальные индикаторы, а не тестовую логику!
                try:
                    # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование (есть INFO логи)
                    # logger.debug(f"🔍 Генерация сигналов для {symbol}...")

                    # ✅ Получаем текущие позиции для CorrelationFilter
                    try:
                        all_positions = await self.client.get_positions()
                        # Конвертируем в формат для CorrelationFilter
                        current_positions_dict = {}
                        for pos in all_positions:
                            pos_size = float(pos.get("pos", "0"))
                            if pos_size != 0:
                                inst_id_pos = pos.get("instId", "")
                                # ✅ ИСПРАВЛЕНИЕ: Убираем только -SWAP, оставляем -USDT (формат "BTC-USDT")
                                symbol_key = inst_id_pos.replace("-SWAP", "")
                                current_positions_dict[symbol_key] = pos
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить позиции для CorrelationFilter: {e}"
                        )
                        current_positions_dict = {}

                    # Генерируем сигналы для всех символов (система сама отфильтрует по symbol)
                    # Передаем позиции в signal_generator для CorrelationFilter
                    signals = await self.signal_generator.generate_signals(
                        current_positions=current_positions_dict
                    )

                    # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование
                    # logger.debug(f"📊 Сгенерировано сигналов: {len(signals)}")

                    # Ищем сигнал для текущего символа
                    symbol_signal = None
                    for signal in signals:
                        if signal.get("symbol") == symbol:
                            symbol_signal = signal
                            break

                    # Если нашли реальный сигнал - выполняем его
                    if symbol_signal:
                        side = symbol_signal.get("side")
                        strength = symbol_signal.get("strength", 0)
                        side_str = "LONG" if side == "buy" else "SHORT"

                        logger.info(
                            f"🎯 РЕАЛЬНЫЙ СИГНАЛ {symbol} {side_str} @ ${price:.2f} "
                            f"(сила={strength:.2f})"
                        )

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем время последнего сигнала СРАЗУ (с нормализованным символом)
                        # Это предотвращает повторную обработку сигнала
                        self.last_signal_time[normalized_symbol] = current_time

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Дополнительная проверка перед выполнением
                        # Проверяем, не был ли уже размещен ордер за последние 2 секунды (с нормализованным символом)
                        if normalized_symbol in self.last_orders_cache:
                            last_order = self.last_orders_cache[normalized_symbol]
                            order_time = last_order.get("timestamp", 0)
                            if (current_time - order_time) < 2:
                                logger.warning(
                                    f"⚠️ Ордер для {symbol} был размещен {current_time - order_time:.1f}s назад, "
                                    f"пропускаем выполнение сигнала (блокировка внутри lock)"
                                )
                                return

                        # Выполняем реальный сигнал
                        success = await self._execute_signal_from_price(
                            symbol, price, symbol_signal
                        )
                        if success:
                            logger.info(
                                f"✅ Позиция {symbol} {side_str} открыта по реальному сигналу"
                            )
                        else:
                            logger.warning(
                                f"⚠️ Не удалось открыть позицию {symbol} {side_str} (недостаточно маржи или другие ограничения)"
                            )
                    else:
                        # ✅ Изменено на INFO для видимости - важно знать что сигналов нет
                        logger.info(
                            f"📊 {symbol}: сигналов нет (индикаторы не дают сигнала). "
                            f"Всего сгенерировано: {len(signals)} сигналов."
                        )

                except Exception as e:
                    logger.error(
                        f"❌ Ошибка генерации реальных сигналов для {symbol}: {e}",
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(f"❌ Ошибка проверки сигналов: {e}")

    def _create_market_data_from_price(self, symbol: str, price: float):
        """Создает MarketData из текущей цены (временная заглушка)"""
        from datetime import datetime

        from src.models import OHLCV, MarketData

        # Создаем одну свечу с текущей ценой
        ohlcv = OHLCV(
            timestamp=int(datetime.now().timestamp()),
            symbol=symbol,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1.0,
        )

        return MarketData(symbol=symbol, timeframe="1m", ohlcv_data=[ohlcv])

    async def _execute_signal_from_price(
        self, symbol: str, price: float, signal=None
    ) -> bool:
        """Выполняет торговый сигнал на основе цены. Возвращает True если позиция успешно открыта."""
        try:
            # 🔥 КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем РЕАЛЬНЫЕ позиции на бирже ПЕРЕД открытием новой
            # Это предотвращает дубликаты даже при race condition или перезапуске бота
            try:
                inst_id = f"{symbol}-SWAP"
                # Проверяем все позиции (не только по символу, чтобы увидеть все)
                all_positions = await self.client.get_positions()
                for pos in all_positions:
                    pos_size = float(pos.get("pos", "0"))
                    pos_inst_id = pos.get("instId", "")

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем все возможные форматы instId
                    # instId может быть: "BTC-USDT-SWAP", "BTCUSDT-SWAP", "BTC-USDT" и т.д.
                    if (
                        abs(pos_size) > 0.000001
                    ):  # Учитываем даже очень маленькие позиции
                        # Нормализуем оба instId (убираем разделители и приводим к одному формату)
                        normalized_pos_id = pos_inst_id.replace("-", "").upper()
                        normalized_inst_id = inst_id.replace("-", "").upper()

                        # Проверяем совпадение
                        if (
                            normalized_pos_id == normalized_inst_id
                            or pos_inst_id == inst_id
                        ):
                            logger.warning(
                                f"⚠️ Позиция {symbol} уже открыта на бирже (size={pos_size}, instId={pos_inst_id}), "
                                f"пропускаем открытие дубликата"
                            )
                            return False

                # 🔥 ДОПОЛНИТЕЛЬНО: Проверяем активные ордера на открытие позиции
                # Если есть pending ордер - тоже не открываем дубликат
                active_orders = await self.client.get_active_orders(symbol)
                for order in active_orders:
                    order_inst_id = order.get("instId", "")
                    order_side = order.get("side", "").lower()

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем все возможные форматы instId
                    normalized_order_id = order_inst_id.replace("-", "").upper()
                    normalized_inst_id = inst_id.replace("-", "").upper()

                    # Если есть активный ордер на открытие позиции (не закрытие) - пропускаем
                    if (
                        normalized_order_id == normalized_inst_id
                        or order_inst_id == inst_id
                    ) and order_side in ["buy", "sell"]:
                        # Проверяем, что это не ордер на закрытие (reduceOnly)
                        is_reduce_only = (
                            order.get("reduceOnly", "false").lower() == "true"
                        )
                        if not is_reduce_only:
                            logger.warning(
                                f"⚠️ Уже есть активный ордер на открытие позиции {symbol} (ordId={order.get('ordId', 'N/A')}, instId={order_inst_id}), "
                                f"пропускаем открытие дубликата"
                            )
                            return False
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка проверки позиций/ордеров на бирже для {symbol}: {e}"
                )
                # Если не удалось проверить - лучше пропустить, чем открыть дубликат
                # СТРОГАЯ ПРОВЕРКА: если не можем проверить - не открываем
                return False

            # Дополнительная проверка внутреннего счетчика (быстрая, но может быть неактуальной)
            if (
                symbol in self.active_positions
                and "order_id" in self.active_positions[symbol]
            ):
                logger.debug(f"Позиция {symbol} уже в активных, пропускаем")
                return False

            # Используем переданный сигнал или создаем тестовый
            if signal is None:
                # Определяем режим (если ARM активен)
                regime = "ranging"  # По умолчанию
                if (
                    hasattr(self.signal_generator, "regime_manager")
                    and self.signal_generator.regime_manager
                ):
                    try:
                        regime = (
                            self.signal_generator.regime_manager.get_current_regime()
                        )
                    except Exception as e:
                        logger.debug(f"Не удалось получить режим: {e}")
                        regime = None

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем РЫНОЧНЫЕ ордера (Market) для мгновенного исполнения
                # Лимитные ордера могут оставаться в pending и не открывать позиции
                # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: Используем limit ордера для экономии комиссий
                # Limit ордера дешевле в 2.5 раза (0.02% vs 0.05%), экономия $126/месяц при 180-200 сделках/день
                # Если limit ордер не исполнится - следующий сигнал, это нормально для скальпинга
                order_type = (
                    "limit"  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий
                )

                # Проверяем конфиг, можно ли переопределить
                try:
                    if hasattr(self.config, "scalping") and self.config.scalping:
                        scalping_config = self.config.scalping
                        if hasattr(scalping_config, "order_type"):
                            order_type = getattr(
                                scalping_config, "order_type", "limit"
                            )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" по умолчанию
                        elif hasattr(scalping_config, "prefer_market_orders"):
                            if getattr(scalping_config, "prefer_market_orders", False):
                                order_type = "market"
                except Exception as e:
                    logger.debug(
                        f"Не удалось получить тип ордера из конфига: {e}, используем limit (экономия комиссий)"
                    )

                signal = {
                    "symbol": symbol,
                    "side": "buy",
                    "price": price,
                    "strength": 0.8,
                    "regime": regime,  # ✅ Добавляем режим для адаптивных TP/SL
                    "type": order_type,  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: Limit ордера для экономии комиссий
                }

            # Рассчитываем размер позиции
            balance = await self.client.get_balance()
            position_size = await self._calculate_position_size(balance, price, signal)

            if position_size <= 0:
                logger.warning(f"Размер позиции слишком мал: {position_size}")
                return False

            # Проверка через MaxSizeLimiter
            # ⚠️ ИСПРАВЛЕНИЕ: size_usd = notional (номинальная стоимость), а не маржа!
            leverage = getattr(self.scalping_config, "leverage", 3)
            size_usd = position_size * price  # Это notional (номинальная стоимость)
            can_open, reason = self.max_size_limiter.can_open_position(symbol, size_usd)

            if not can_open:
                logger.warning(f"Нельзя открыть позицию: {reason}")
                return False

            # Проверка через FundingRateMonitor
            if not self.funding_monitor.is_funding_favorable(signal["side"]):
                logger.warning(f"Funding неблагоприятен для {signal['side']}")
                return False

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Последняя проверка перед размещением ордера (с нормализованным символом)
            # Проверяем, не был ли только что размещен ордер (даже если его еще нет в активных)
            import time

            current_time = time.time()
            normalized_symbol = self._normalize_symbol(symbol)
            if normalized_symbol in self.last_orders_cache:
                last_order = self.last_orders_cache[normalized_symbol]
                order_time = last_order.get("timestamp", 0)
                order_status = last_order.get("status", "unknown")
                time_since_order = current_time - order_time
                # ✅ УСИЛЕНО: Если ордер был размещен менее 15 секунд назад и pending - строго блокируем
                if time_since_order < 15 and order_status == "pending":
                    logger.warning(
                        f"⚠️ Ордер для {symbol} был размещен {time_since_order:.1f}s назад (status=pending), "
                        f"СТРОГО блокируем размещение дубликата (предотвращение двойных ордеров)"
                    )
                    return False
                # Если ордер был размещен менее 30 секунд назад и еще не исполнен/отменен - блокируем
                if time_since_order < 30 and order_status not in [
                    "filled",
                    "cancelled",
                    "rejected",
                ]:
                    logger.warning(
                        f"⚠️ Ордер для {symbol} был размещен {time_since_order:.1f}s назад, "
                        f"пропускаем размещение дубликата"
                    )
                    return False

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Финальная проверка активных ордеров ПЕРЕД размещением
            # Это предотвращает race condition, когда два сигнала проходят проверку одновременно
            try:
                active_orders = await self.client.get_active_orders(symbol)
                inst_id = f"{symbol}-SWAP"
                open_position_orders = [
                    o
                    for o in active_orders
                    if o.get("instId") == inst_id
                    and o.get("side", "").lower() in ["buy", "sell"]
                    and o.get("reduceOnly", "false").lower() != "true"
                ]

                if len(open_position_orders) > 0:
                    order_ids = [o.get("ordId") for o in open_position_orders]
                    logger.warning(
                        f"⚠️ Обнаружены {len(open_position_orders)} активных ордеров для {symbol} ПЕРЕД размещением: {order_ids}, "
                        f"БЛОКИРУЕМ размещение дубликата (race condition защита)"
                    )
                    return False
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка финальной проверки активных ордеров для {symbol}: {e}"
                )
                # При ошибке - лучше пропустить, чем создать дубликат
                return False

            # Выполняем ордер с TP/SL
            result = await self.order_executor.execute_signal(signal, position_size)

            if result.get("success"):
                order_id = result.get("order_id")
                order_type = result.get(
                    "order_type",
                    "limit",  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий
                )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем кэш СРАЗУ после размещения ордера
                # Это предотвращает race condition, когда второй сигнал проходит проверку
                # до того, как первый ордер появится в API
                import time

                current_time = time.time()
                normalized_symbol = self._normalize_symbol(symbol)
                self.last_orders_cache[normalized_symbol] = {
                    "order_id": order_id,
                    "timestamp": current_time,
                    "status": "pending",  # Временно pending, будет обновлен после проверки
                    "order_type": order_type,
                    "side": signal.get("side", "unknown"),
                }
                logger.debug(
                    f"📦 Кэш обновлен СРАЗУ после размещения ордера {order_id} для {symbol} (race condition защита)"
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем, действительно ли позиция открылась
                # Для рыночных ордеров - сразу открыта (исполняются мгновенно)
                # Для лимитных ордеров - проверяем, что ордер исполнен
                position_opened = False
                if order_type == "market":
                    # Рыночный ордер - позиция открыта сразу
                    position_opened = True
                    logger.info(
                        f"✅ Рыночный ордер исполнен, позиция открыта: {symbol} {position_size:.6f}"
                    )
                else:
                    # Лимитный ордер - проверяем статус
                    try:
                        # Ждем немного для исполнения лимитного ордера (1-2 секунды)
                        await asyncio.sleep(2)
                        # Проверяем статус ордера
                        active_orders = await self.client.get_active_orders(symbol)
                        inst_id = f"{symbol}-SWAP"
                        order_filled = True
                        for order in active_orders:
                            if (
                                str(order.get("ordId", "")) == str(order_id)
                                and order.get("instId") == inst_id
                            ):
                                # Ордер еще активен - не исполнен
                                order_filled = False
                                order_state = order.get("state", "").lower()
                                if order_state in ["filled", "partially_filled"]:
                                    order_filled = True
                                break

                        if order_filled:
                            # Проверяем, что позиция действительно открылась
                            positions = await self.client.get_positions()
                            for pos in positions:
                                pos_inst_id = pos.get("instId", "")
                                pos_size = abs(float(pos.get("pos", "0")))
                                if (
                                    pos_inst_id == inst_id or pos_inst_id == symbol
                                ) and pos_size > 0.000001:
                                    position_opened = True
                                    logger.info(
                                        f"✅ Лимитный ордер исполнен, позиция открыта: {symbol} {position_size:.6f}"
                                    )
                                    break

                        if not position_opened:
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем, не был ли ордер отменен
                            # Если ордер был отменен (например, Slippage Guard), но позиция не открылась,
                            # проверяем еще раз через 1 секунду на случай, если ордер был частично исполнен
                            try:
                                await asyncio.sleep(1)
                                # Проверяем статус ордера
                                active_orders = await self.client.get_active_orders(
                                    symbol
                                )
                                order_cancelled = True
                                for order in active_orders:
                                    if str(order.get("ordId", "")) == str(order_id):
                                        order_state = order.get("state", "").lower()
                                        if order_state in [
                                            "filled",
                                            "partially_filled",
                                        ]:
                                            # Ордер исполнен! Проверяем позицию еще раз
                                            positions = (
                                                await self.client.get_positions()
                                            )
                                            for pos in positions:
                                                pos_inst_id = pos.get("instId", "")
                                                pos_size = abs(
                                                    float(pos.get("pos", "0"))
                                                )
                                                if (
                                                    pos_inst_id == inst_id
                                                    or pos_inst_id == symbol
                                                ) and pos_size > 0.000001:
                                                    position_opened = True
                                                    logger.info(
                                                        f"✅ Лимитный ордер {order_id} исполнен после проверки, позиция открыта: {symbol}"
                                                    )
                                                    break
                                        order_cancelled = False
                                        break

                                if order_cancelled:
                                    logger.warning(
                                        f"⚠️ Лимитный ордер {order_id} для {symbol} был отменен (возможно Slippage Guard), "
                                        f"позиция НЕ открылась"
                                    )
                                    # Обновляем кэш со статусом "cancelled"
                                    self.last_orders_cache[normalized_symbol] = {
                                        "order_id": order_id,
                                        "timestamp": current_time,
                                        "status": "cancelled",
                                        "order_type": order_type,
                                        "side": signal.get("side", "unknown"),
                                    }
                                    return False
                            except Exception as e:
                                logger.debug(
                                    f"Ошибка повторной проверки ордера {order_id}: {e}"
                                )

                            if not position_opened:
                                logger.warning(
                                    f"⚠️ Лимитный ордер {order_id} размещен для {symbol}, но позиция НЕ открылась "
                                    f"(ордер еще pending или не исполнен). НЕ считаем позицию открытой!"
                                )
                                # Обновляем кэш, но НЕ считаем позицию открытой
                                self.last_orders_cache[normalized_symbol] = {
                                    "order_id": order_id,
                                    "timestamp": current_time,
                                    "status": "pending",
                                    "order_type": order_type,
                                    "side": signal.get("side", "unknown"),
                                }
                                return False  # Позиция не открыта - выходим
                    except Exception as e:
                        logger.error(f"Ошибка проверки статуса ордера {order_id}: {e}")
                        # При ошибке - лучше не считать позицию открытой
                        return False

                # ✅ ТОЛЬКО если позиция действительно открылась - продолжаем
                if not position_opened:
                    logger.warning(
                        f"⚠️ Позиция {symbol} НЕ открылась после размещения ордера {order_id}"
                    )
                    return False

                logger.info(f"✅ Позиция открыта: {symbol} {position_size:.6f}")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем кэш последних ордеров СРАЗУ после размещения (с нормализованным символом)
                if order_id:
                    self.last_orders_cache[normalized_symbol] = {
                        "order_id": order_id,
                        "timestamp": current_time,
                        "status": "filled",  # ✅ Исправлено: статус filled, так как позиция открылась
                        "order_type": order_type,
                        "side": signal.get("side", "unknown"),
                    }
                    logger.debug(
                        f"📦 Обновлен кэш последнего ордера для {symbol}: {order_id} (status=filled)"
                    )

                # 🛡️ Обновляем total_margin_used
                # ⚠️ ИСПРАВЛЕНИЕ: Правильный расчет margin из position_size (монеты)
                # position_size в МОНЕТАХ, price в USD, leverage из конфига
                # margin = (size_in_coins × price) / leverage = notional / leverage
                # ✅ АДАПТИВНО: leverage из конфига
                leverage = getattr(self.scalping_config, "leverage", None)
                if leverage is None or leverage <= 0:
                    logger.error(
                        "❌ leverage не указан в конфиге! Проверьте config_futures.yaml"
                    )
                    leverage = 3  # Fallback только для расчета, но логируем ошибку
                    logger.warning(
                        f"⚠️ Используем fallback leverage={leverage}, но это не должно происходить!"
                    )
                notional = position_size * price  # Номинальная стоимость позиции
                margin_used = notional / leverage  # Маржа = notional / leverage
                self.total_margin_used += margin_used
                logger.debug(
                    f"💼 Общая маржа: ${self.total_margin_used:.2f} "
                    f"(notional=${notional:.2f}, margin=${margin_used:.2f}, leverage={leverage}x)"
                )

                # 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавляем позицию в MaxSizeLimiter!
                # Без этого лимитер не отслеживает открытые позиции и разрешает открывать больше!
                self.max_size_limiter.add_position(symbol, size_usd)
                logger.debug(
                    f"✅ Позиция {symbol} добавлена в MaxSizeLimiter: ${size_usd:.2f} (всего: ${self.max_size_limiter.get_total_size():.2f})"
                )

                # Сохраняем в active_positions
                if symbol not in self.active_positions:
                    self.active_positions[symbol] = {}
                entry_time = datetime.now()
                self.active_positions[symbol].update(
                    {
                        "order_id": result.get("order_id"),
                        "side": signal["side"],
                        "size": position_size,
                        "entry_price": price,
                        "margin": margin_used,  # margin для этой позиции
                        "entry_time": entry_time,  # ✅ НОВОЕ: Время открытия позиции
                        "timestamp": entry_time,  # Для совместимости
                        "time_extended": False,  # ✅ НОВОЕ: Флаг продления времени
                        # ✅ БЕЗ tp_order_id и sl_order_id - используем TrailingSL!
                    }
                )

                tsl = self._initialize_trailing_stop(
                    symbol=symbol,
                    entry_price=price,
                    side=signal["side"],
                    current_price=price,
                    signal=signal,
                )
                if tsl:
                    self.trailing_sl_by_symbol[symbol] = tsl
                    logger.info(f"🎯 Позиция {symbol} открыта с TrailingSL")
                else:
                    logger.warning(
                        f"⚠️ TrailingStopLoss не был инициализирован для {symbol} (entry={price})"
                    )
                return True
            else:
                error_msg = result.get("error", "Неизвестная ошибка")
                logger.error(f"❌ Не удалось разместить ордер для {symbol}: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"Ошибка выполнения сигнала: {e}", exc_info=True)
            return False

    async def _calculate_position_size(
        self, balance: float, price: float, signal: dict
    ) -> float:
        """Рассчитывает размер позиции с учетом Balance Profiles и режима рынка"""
        try:
            symbol = signal.get("symbol")
            symbol_regime = signal.get("regime")
            if (
                symbol
                and not symbol_regime
                and hasattr(self.signal_generator, "regime_managers")
            ):
                manager = self.signal_generator.regime_managers.get(symbol)
                if manager:
                    symbol_regime = manager.get_current_regime()
            if (
                not symbol_regime
                and hasattr(self.signal_generator, "regime_manager")
                and self.signal_generator.regime_manager
            ):
                symbol_regime = (
                    self.signal_generator.regime_manager.get_current_regime()
                )

            balance_profile = self._get_balance_profile(balance)

            base_usd_size = balance_profile["base_position_usd"]
            min_usd_size = balance_profile["min_position_usd"]
            max_usd_size = balance_profile["max_position_usd"]

            position_overrides: Dict[str, Any] = {}
            if symbol:
                regime_profile = self._get_symbol_regime_profile(symbol, symbol_regime)
                position_overrides = self._to_dict(regime_profile.get("position", {}))

            if position_overrides.get("base_position_usd") is not None:
                base_usd_size = float(position_overrides["base_position_usd"])
            if position_overrides.get("min_position_usd") is not None:
                min_usd_size = float(position_overrides["min_position_usd"])
            if position_overrides.get("max_position_usd") is not None:
                max_usd_size = float(position_overrides["max_position_usd"])

            if position_overrides.get("max_position_percent") is not None:
                balance_profile["max_position_percent"] = float(
                    position_overrides["max_position_percent"]
                )

            if min_usd_size is None or min_usd_size <= 0:
                min_usd_size = base_usd_size * 0.5
            if max_usd_size is None or max_usd_size <= 0:
                max_usd_size = base_usd_size * 2.0

            profile_max_positions = balance_profile.get("max_open_positions")
            if position_overrides.get("max_open_positions") is not None:
                profile_max_positions = int(position_overrides["max_open_positions"])
            global_max_positions = getattr(
                self.risk_config, "max_open_positions", profile_max_positions
            )
            if profile_max_positions:
                allowed_positions = max(
                    1, min(profile_max_positions, global_max_positions)
                )
                if self.max_size_limiter.max_positions != allowed_positions:
                    logger.debug(
                        f"🔧 MaxSizeLimiter: обновляем max_positions {self.max_size_limiter.max_positions} → {allowed_positions}"
                    )
                    self.max_size_limiter.max_positions = allowed_positions
                max_total_size = max_usd_size * allowed_positions
                if self.max_size_limiter.max_total_size_usd != max_total_size:
                    logger.debug(
                        f"🔧 MaxSizeLimiter: обновляем max_total_size_usd {self.max_size_limiter.max_total_size_usd:.2f} → {max_total_size:.2f}"
                    )
                    self.max_size_limiter.max_total_size_usd = max_total_size

            if (
                hasattr(self.signal_generator, "regime_manager")
                and self.signal_generator.regime_manager
            ):
                try:
                    regime_key = (
                        symbol_regime
                        or self.signal_generator.regime_manager.get_current_regime()
                    )
                    if regime_key:
                        regime_params = self._get_regime_params(regime_key, symbol)
                        multiplier = regime_params.get("position_size_multiplier")
                        if multiplier is not None:
                            base_usd_size *= multiplier
                            logger.debug(f"Режим {regime_key}: multiplier={multiplier}")
                except Exception as e:
                    logger.warning(f"Ошибка адаптации под режим: {e}")

            has_conflict = signal.get("has_conflict", False)
            signal_strength = signal.get("strength", 0.5)

            if has_conflict:
                # При конфликте: уменьшенный размер (50% от стандартного) для снижения риска
                strength_multiplier = 0.5
                logger.debug(
                    f"⚡ Конфликт RSI/EMA: уменьшенный размер для быстрого скальпа "
                    f"(strength={signal_strength:.2f}, multiplier=0.5)"
                )
            elif signal_strength > 0.8:
                # Очень сильный сигнал → увеличиваем размер
                strength_multiplier = 1.5  # +50% для очень сильного
                logger.debug(
                    f"Сильный сигнал (strength={signal_strength:.2f}): multiplier=1.5"
                )
            elif signal_strength > 0.6:
                # Хороший сигнал → стандартный размер
                strength_multiplier = 1.2  # +20% для хорошего
                logger.debug(
                    f"Хороший сигнал (strength={signal_strength:.2f}): multiplier=1.2"
                )
            elif signal_strength > 0.4:
                # Средний сигнал → стандартный размер
                strength_multiplier = 1.0  # Стандарт
                logger.debug(
                    f"Средний сигнал (strength={signal_strength:.2f}): multiplier=1.0"
                )
            else:
                # Слабый сигнал → минимум
                strength_multiplier = 0.8  # -20% для слабого
                logger.debug(
                    f"Слабый сигнал (strength={signal_strength:.2f}): multiplier=0.8"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Применяем multiplier, но ограничиваем max_usd_size!
            base_usd_size *= strength_multiplier
            # Гарантируем, что base_usd_size не превышает max_usd_size
            base_usd_size = min(base_usd_size, max_usd_size)
            logger.debug(
                f"💰 После multiplier: base_usd_size=${base_usd_size:.2f} (max=${max_usd_size:.2f})"
            )

            # 4. ПРИМЕНЯЕМ ЛЕВЕРИДЖ (Futures) - из конфига!
            leverage = getattr(self.scalping_config, "leverage", None)
            if leverage is None or leverage <= 0:
                logger.error(
                    "❌ leverage не указан в конфиге или <= 0! Проверьте config_futures.yaml"
                )
                raise ValueError(
                    "leverage должен быть указан в конфиге (например, leverage: 3)"
                )
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: base_usd_size это НОМИНАЛЬНАЯ стоимость (notional)
            # Маржа = номинальная стоимость / леверидж
            # Например: notional=$25, leverage=3x → margin=$8.33
            margin_required = base_usd_size / leverage  # Требуемая маржа (в USD)

            # ✅ Пересчитываем min/max из номинальной стоимости в маржу для проверок
            min_margin_usd = min_usd_size / leverage  # min в марже
            max_margin_usd = max_usd_size / leverage  # max в марже

            # 5. 🛡️ ЗАЩИТА: Max Margin Used (80%)
            max_margin_allowed = balance * self.max_margin_percent  # 80%
            if self.total_margin_used + margin_required > max_margin_allowed:
                logger.warning(
                    f"⚠️ Достигнут лимит маржи: {self.total_margin_used + margin_required:.2f} > {max_margin_allowed:.2f}"
                )
                margin_required = max(0, max_margin_allowed - self.total_margin_used)
                if margin_required < min_margin_usd:
                    logger.error(
                        f"❌ Недостаточно свободной маржи для открытия позиции (требуется минимум ${min_margin_usd:.2f} маржи)"
                    )
                    return 0.0

            # 6. 🛡️ ЗАЩИТА: Max Loss per Trade (2%)
            max_loss_usd = balance * self.max_loss_per_trade  # 2% макс потеря
            sl_percent = getattr(self.scalping_config, "sl_percent", 0.2)

            # ⚠️ sl_percent в конфиге может быть как в долях (0.2 = 20%) или в процентах (20)
            # Конвертируем в доли для единообразия
            if sl_percent > 1:
                sl_percent_decimal = sl_percent / 100  # Если в процентах (20 → 0.2)
            else:
                sl_percent_decimal = sl_percent  # Уже в долях (0.2)

            # Рассчитываем максимально безопасный размер маржи
            # Формула: max_safe_margin = max_loss / sl_percent
            # Пример: max_loss=$8, sl_percent=20% (0.2) → max_safe_margin = $8 / 0.2 = $40
            max_safe_margin = (
                max_loss_usd / sl_percent_decimal
                if sl_percent_decimal > 0
                else float("inf")
            )

            if margin_required > max_safe_margin:
                logger.warning(
                    f"⚠️ Позиция слишком большая для max loss: {margin_required:.2f} > {max_safe_margin:.2f}"
                )
                margin_required = max_safe_margin

            # 7. Проверка маржи (90% безопасности - финальная проверка)
            if margin_required > balance * 0.9:
                logger.warning(
                    f"⚠️ Недостаточно маржи: {margin_required:.2f} > {balance * 0.9:.2f}"
                )
                margin_required = balance * 0.9

            # 8. ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Применяем ограничения к МАРЖЕ (не к notional!)
            # margin_usd = маржа (то что блокируется), используем min/max_margin_usd
            margin_usd = max(min_margin_usd, min(margin_required, max_margin_usd))

            # 9. ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Переводим МАРЖУ в количество монет
            # position_size = (margin_usd * leverage) / price
            # Это даст НОМИНАЛЬНУЮ стоимость = margin_usd * leverage
            # Например: margin=$180, leverage=3x → notional=$540, position_size = $540 / $110k = 0.0049 BTC
            position_size = (margin_usd * leverage) / price

            # 10. 🛡️ ЗАЩИТА: Проверяем drawdown перед открытием
            if not await self._check_drawdown_protection():
                logger.warning(
                    "⚠️ Drawdown protection активирован - пропускаем позицию"
                )
                return 0.0

            # Вычисляем номинальную стоимость для логов
            notional_usd = margin_usd * leverage

            logger.info(
                f"💰 Расчет: balance=${balance:.2f}, "
                f"profile={balance_profile['name']}, "
                f"margin=${margin_usd:.2f} (лимит: ${min_margin_usd:.2f}-${max_margin_usd:.2f} маржи), "
                f"notional=${notional_usd:.2f} (leverage={leverage}x), "
                f"position_size={position_size:.6f}"
            )

            return position_size

        except Exception as e:
            logger.error(f"Ошибка расчета размера позиции: {e}")
            return 0.0

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

                # ✅ ВСЕ параметры из конфига, без fallback!
                base_pos_usd = getattr(profile_config, "base_position_usd", None)
                if base_pos_usd is None or base_pos_usd <= 0:
                    logger.error(
                        f"❌ Профиль {profile_name}: base_position_usd не указан или <= 0 в конфиге!"
                    )
                    raise ValueError(
                        f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                    )

                min_pos_usd = getattr(profile_config, "min_position_usd", None)
                max_pos_usd = getattr(profile_config, "max_position_usd", None)

                # ✅ Если min/max не заданы - рассчитываем из base (50% и 200% номинальной стоимости)
                if min_pos_usd is None or min_pos_usd <= 0:
                    min_pos_usd = base_pos_usd * 0.5  # 50% от base
                    logger.debug(
                        f"📊 Профиль {profile_name}: min_position_usd рассчитан из base ({min_pos_usd:.2f})"
                    )
                if max_pos_usd is None or max_pos_usd <= 0:
                    max_pos_usd = base_pos_usd * 2.0  # 200% от base
                    logger.debug(
                        f"📊 Профиль {profile_name}: max_position_usd рассчитан из base ({max_pos_usd:.2f})"
                    )

                max_open_positions = getattr(profile_config, "max_open_positions", None)
                if max_open_positions is None:
                    logger.warning(
                        f"⚠️ Профиль {profile_name}: max_open_positions не указан, используем 2"
                    )
                    max_open_positions = 2

                max_position_percent = getattr(
                    profile_config, "max_position_percent", None
                )
                if max_position_percent is None:
                    logger.warning(
                        f"⚠️ Профиль {profile_name}: max_position_percent не указан, используем 8.0"
                    )
                    max_position_percent = 8.0

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

        base_pos_usd = getattr(profile_config, "base_position_usd", None)
        if base_pos_usd is None or base_pos_usd <= 0:
            logger.error(
                f"❌ Профиль {profile_name}: base_position_usd не указан в конфиге!"
            )
            raise ValueError(
                f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
            )

        min_pos_usd = getattr(profile_config, "min_position_usd", None)
        max_pos_usd = getattr(profile_config, "max_position_usd", None)
        if min_pos_usd is None or min_pos_usd <= 0:
            min_pos_usd = base_pos_usd * 0.5
        if max_pos_usd is None or max_pos_usd <= 0:
            max_pos_usd = base_pos_usd * 2.0

        max_open_positions = getattr(profile_config, "max_open_positions", 2)
        max_position_percent = getattr(profile_config, "max_position_percent", 8.0)

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

            adaptive_dict = self._to_dict(adaptive_regime)
            regime_params = self._to_dict(adaptive_dict.get(regime_name, {}))

            if symbol:
                symbol_profile = self.symbol_profiles.get(symbol, {})
                regime_profile = symbol_profile.get(regime_name.lower(), {})
                arm_override = self._to_dict(regime_profile.get("arm", {}))
                if arm_override:
                    regime_params = self._deep_merge_dict(regime_params, arm_override)

            return regime_params

        except Exception as e:
            logger.warning(f"Ошибка получения параметров режима {regime_name}: {e}")
            return {}

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

            current_balance = await self.client.get_balance()
            drawdown = (self.initial_balance - current_balance) / self.initial_balance

            if drawdown > self.max_drawdown_percent:
                logger.critical(
                    f"🚨 DRAWDOWN ЗАЩИТА! "
                    f"Просадка: {drawdown*100:.2f}% > {self.max_drawdown_percent*100:.0f}%"
                )

                # 🛑 Emergency Stop
                await self._emergency_stop()

                return False

            elif drawdown > self.max_drawdown_percent * 0.7:  # 70% от лимита
                logger.warning(f"⚠️ Близко к drawdown: {drawdown*100:.2f}%")

            return True

        except Exception as e:
            logger.error(f"Ошибка проверки drawdown: {e}")
            return True  # На всякий случай разрешаем

    async def _emergency_stop(self):
        """
        🛑 Emergency Stop - Аварийная остановка

        Используется при критических ситуациях:
        - Drawdown > 5%
        - Margin close to call
        - Multiple losses in a row
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

            # 2. Блокируем новые сделки
            self.is_running = False
            logger.critical("🛑 Торговля заблокирована")

            # 3. Отправляем alert (здесь можно добавить телеграм/email)
            logger.critical(
                f"📧 ALERT: Emergency Stop activated! "
                f"Balance: ${await self.client.get_balance():.2f}, "
                f"Drawdown: {(self.initial_balance - await self.client.get_balance()) / self.initial_balance * 100:.2f}%"
            )

            # 4. Сохраняем логи
            logger.critical("💾 Логи сохранены")

            # 5. Wait for manual intervention
            logger.critical("⏸️ Ждем ручного разрешения для продолжения")

        except Exception as e:
            logger.error(f"Ошибка в Emergency Stop: {e}")

    async def _update_trailing_stop_loss(self, symbol: str, current_price: float):
        """Обновление TrailingStopLoss для открытой позиции"""
        try:
            position = self.active_positions.get(symbol, {})

            if not position:
                return

            # Получаем entry_price из позиции
            entry_price = position.get("entry_price", 0)
            if entry_price == 0:
                logger.warning(f"⚠️ Entry price = 0 для {symbol}")
                return

            # Получаем TrailingStopLoss для этой позиции
            if symbol not in self.trailing_sl_by_symbol:
                # ✅ УЛУЧШЕНО: Логируем, если TrailingStopLoss не инициализирован
                logger.warning(
                    f"⚠️ TrailingStopLoss не инициализирован для {symbol} "
                    f"(позиция найдена в active_positions, но нет в trailing_sl_by_symbol). "
                    f"Это может быть позиция, открытая до перезапуска бота."
                )
                return

            tsl = self.trailing_sl_by_symbol[symbol]

            # Обновляем трейлинг стоп с новой ценой
            tsl.update(current_price)

            stop_loss = tsl.get_stop_loss()
            # ⚠️ ИСПРАВЛЕНИЕ: Используем прибыль С УЧЕТОМ КОМИССИИ!
            profit_pct = tsl.get_profit_pct(current_price, include_fees=True)
            profit_pct_gross = tsl.get_profit_pct(
                current_price, include_fees=False
            )  # Для логов
            highest = tsl.highest_price

            # 🎯 Получаем информацию о тренде и режиме рынка для адаптивной логики
            trend_strength = None
            market_regime = None

            # Получаем trend_strength из FastADX (если есть данные)
            try:
                if hasattr(self, "fast_adx") and self.fast_adx:
                    # Используем метод get_current_adx() для получения значения ADX
                    adx_value = self.fast_adx.get_current_adx()
                    if adx_value and adx_value > 0:
                        # Нормализуем ADX к 0-1 (ADX обычно 0-100)
                        trend_strength = min(adx_value / 100.0, 1.0)
            except Exception as e:
                logger.debug(f"Не удалось получить trend_strength: {e}")

            # Получаем market_regime из AdaptiveRegimeManager
            try:
                if (
                    hasattr(self.signal_generator, "regime_manager")
                    and self.signal_generator.regime_manager
                ):
                    regime_obj = (
                        self.signal_generator.regime_manager.get_current_regime()
                    )
                    if regime_obj:
                        market_regime = (
                            regime_obj.lower() if isinstance(regime_obj, str) else None
                        )
            except Exception as e:
                logger.debug(f"Не удалось получить market_regime: {e}")

            # DEBUG: Логируем состояние (каждые 5 секунд) с учетом комиссии
            if not hasattr(self, "_tsl_log_count"):
                self._tsl_log_count = {}
            if symbol not in self._tsl_log_count:
                self._tsl_log_count[symbol] = 0
            self._tsl_log_count[symbol] += 1

            if self._tsl_log_count[symbol] % 5 == 0:  # Каждые 5-й раз
                trend_str = (
                    f"{trend_strength:.2f}" if trend_strength is not None else "N/A"
                )
                regime_str = market_regime or "N/A"
                # Показываем и gross (без комиссии) и net (с комиссией) прибыль
                logger.info(
                    f"📊 TrailingSL {symbol}: price={current_price:.2f}, entry={entry_price:.2f}, "
                    f"highest={highest:.2f}, stop={stop_loss:.2f}, "
                    f"profit={profit_pct:.2%} (net), gross={profit_pct_gross:.2%}, "
                    f"trend={trend_str}, regime={regime_str}"
                )

            # 🎯 Проверяем, нужно ли закрывать позицию по трейлинг стопу
            # Теперь передаем информацию о тренде и режиме для адаптивной логики
            if tsl.should_close_position(
                current_price,
                trend_strength=trend_strength,
                market_regime=market_regime,
            ):
                logger.info(
                    f"🛑 Позиция {symbol} достигла трейлинг стоп-лосса (price={current_price:.2f} <= stop={stop_loss:.2f}, "
                    f"profit={profit_pct:.2%}, trend={trend_strength:.2f if trend_strength else 'N/A'})"
                )
                await self._close_position(symbol, "trailing_stop")
                return

            # ✅ НОВОЕ: Проверка времени жизни позиции с продлением
            await self._check_position_holding_time(
                symbol, current_price, profit_pct, market_regime
            )

        except Exception as e:
            logger.error(f"Ошибка обновления трейлинг стоп-лосса: {e}")

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
                    logger.warning(f"⚠️ Нет времени открытия для позиции {symbol}")
                    return

            # Вычисляем время удержания
            if isinstance(entry_time, datetime):
                time_held = (
                    datetime.now() - entry_time
                ).total_seconds() / 60  # в минутах
            else:
                # Если это строка или другой формат - пропускаем
                logger.debug(
                    f"⚠️ Неверный формат entry_time для {symbol}: {entry_time}"
                )
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

                    # Получаем параметры режима из конфига
                    regime_params = None
                    if regime_obj == "trending":
                        regime_params = (
                            self.signal_generator.regime_manager.config.trending
                        )
                    elif regime_obj == "ranging":
                        regime_params = (
                            self.signal_generator.regime_manager.config.ranging
                        )
                    elif regime_obj == "choppy":
                        regime_params = (
                            self.signal_generator.regime_manager.config.choppy
                        )

                    if regime_params:
                        max_holding_minutes = getattr(
                            regime_params, "max_holding_minutes", 30
                        )
                        extend_time_if_profitable = getattr(
                            regime_params, "extend_time_if_profitable", True
                        )
                        min_profit_for_extension = getattr(
                            regime_params, "min_profit_for_extension", 0.1
                        )
                        extension_percent = getattr(
                            regime_params, "extension_percent", 50
                        )
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

            # Проверяем, истекло ли время
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
                    # Время истекло - закрываем
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
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляет статус ордеров в кэше
        Проверяет статус последних ордеров и обновляет кэш
        """
        try:
            import time

            current_time = time.time()

            # Проверяем только ордера, которые были размещены недавно (менее 5 минут назад)
            symbols_to_check = []
            for normalized_symbol_key, order_info in self.last_orders_cache.items():
                order_time = order_info.get("timestamp", 0)
                order_status = order_info.get("status", "unknown")
                # Проверяем только pending ордера, которые старше 10 секунд
                if order_status == "pending" and (current_time - order_time) > 10:
                    # Находим оригинальный символ для API запросов
                    symbol = None
                    for config_symbol in self.scalping_config.symbols:
                        if (
                            self._normalize_symbol(config_symbol)
                            == normalized_symbol_key
                        ):
                            symbol = config_symbol
                            break
                    if symbol:
                        symbols_to_check.append((symbol, normalized_symbol_key))

            # Проверяем статус ордеров (не чаще раза в 30 секунд на символ)
            for symbol, normalized_symbol_key in symbols_to_check:
                try:
                    # Проверяем активные ордера
                    active_orders = await self.client.get_active_orders(symbol)
                    inst_id = f"{symbol}-SWAP"

                    order_info = self.last_orders_cache.get(normalized_symbol_key, {})
                    order_id = order_info.get("order_id")

                    if order_id:
                        # Ищем наш ордер среди активных
                        found = False
                        for order in active_orders:
                            if (
                                order.get("ordId") == str(order_id)
                                and order.get("instId") == inst_id
                            ):
                                # Ордер все еще активен
                                order_state = order.get("state", "").lower()
                                if order_state in ["filled", "partially_filled"]:
                                    self.last_orders_cache[normalized_symbol_key][
                                        "status"
                                    ] = "filled"
                                    logger.debug(
                                        f"✅ Ордер {order_id} для {symbol} исполнен"
                                    )
                                elif order_state in ["cancelled", "canceled"]:
                                    self.last_orders_cache[normalized_symbol_key][
                                        "status"
                                    ] = "cancelled"
                                    logger.debug(
                                        f"⚠️ Ордер {order_id} для {symbol} отменен"
                                    )
                                found = True
                                break

                        # Если ордера нет среди активных - возможно исполнен
                        if not found:
                            # Проверяем позиции - возможно ордер исполнился
                            all_positions = await self.client.get_positions()
                            for pos in all_positions:
                                if (
                                    pos.get("instId") == inst_id
                                    and abs(float(pos.get("pos", "0"))) > 0.000001
                                ):
                                    # Есть позиция - возможно ордер исполнился
                                    self.last_orders_cache[normalized_symbol_key][
                                        "status"
                                    ] = "filled"
                                    logger.debug(
                                        f"✅ Ордер {order_id} для {symbol} вероятно исполнен (есть позиция)"
                                    )
                                    break
                            else:
                                # Нет активного ордера и нет позиции - возможно отменен
                                self.last_orders_cache[normalized_symbol_key][
                                    "status"
                                ] = "cancelled"
                                logger.debug(
                                    f"⚠️ Ордер {order_id} для {symbol} вероятно отменен (нет в активных)"
                                )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка обновления статуса ордера для {symbol}: {e}"
                    )
        except Exception as e:
            logger.debug(f"⚠️ Ошибка обновления кэша ордеров: {e}")

    async def _close_position(self, symbol: str, reason: str):
        """Закрытие позиции через position_manager"""
        try:
            position = self.active_positions.get(symbol, {})

            if position:
                logger.info(f"🛑 Закрытие позиции {symbol}: {reason}")

                # ✅ Закрываем через position_manager (API)
                await self.position_manager.close_position_manually(symbol)

                # ✅ Обновляем кэш ордеров
                normalized_symbol = self._normalize_symbol(symbol)
                if normalized_symbol in self.last_orders_cache:
                    self.last_orders_cache[normalized_symbol]["status"] = "closed"
                    logger.debug(f"📦 Обновлен статус ордера для {symbol} на 'closed'")

                # 🛡️ Обновляем маржу и лимит позиций
                position_margin = position.get("margin", 0)
                if position_margin > 0:
                    self.total_margin_used -= position_margin
                    logger.debug(
                        f"💼 Общая маржа после закрытия: ${self.total_margin_used:.2f}"
                    )

                position_size = position.get("size", 0)
                entry_price = position.get("entry_price", 0)
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

                if symbol in self.trailing_sl_by_symbol:
                    self.trailing_sl_by_symbol[symbol].reset()
                    del self.trailing_sl_by_symbol[symbol]

                logger.debug(
                    f"🔄 Позиция {symbol} закрыта, система готова к новым сигналам"
                )

                await self._sync_positions_with_exchange(force=True)

        except Exception as e:
            logger.error(f"Ошибка закрытия позиции: {e}")

    async def get_status(self) -> Dict[str, Any]:
        """Получение статуса системы"""
        try:
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
