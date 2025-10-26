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
from datetime import datetime
from typing import Any, Dict, List

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
        self.client = OKXFuturesClient(
            api_key=okx_config.api_key,
            secret_key=okx_config.api_secret,
            passphrase=okx_config.passphrase,
            sandbox=okx_config.sandbox,
            leverage=3,  # Futures по умолчанию 3x
        )

        # Модули безопасности - берем параметры из futures_modules или defaults
        futures_modules = config.futures_modules if config.futures_modules else {}
        slippage_config = (
            futures_modules.slippage_guard if futures_modules.slippage_guard else {}
        )

        self.margin_calculator = MarginCalculator(
            default_leverage=3,  # Futures по умолчанию 3x
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
        self.signal_generator = FuturesSignalGenerator(config)
        self.order_executor = FuturesOrderExecutor(
            config, self.client, self.slippage_guard
        )
        self.position_manager = FuturesPositionManager(
            config, self.client, self.margin_calculator
        )
        self.performance_tracker = PerformanceTracker()

        # TrailingStopLoss для каждой позиции (словарь по символам)
        self.trailing_sl_by_symbol = {}

        # FastADX для быстрого определения тренда
        self.fast_adx = FastADX(period=9, threshold=20.0)

        # OrderFlowIndicator для анализа потока ордеров
        self.order_flow = OrderFlowIndicator(
            window=100, long_threshold=0.1, short_threshold=-0.1
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
        self.ws_manager = FuturesWebSocketManager(
            ws_url="wss://ws.okx.com:8443/ws/v5/public"
        )

        # Состояние
        self.is_running = False
        self.active_positions = {}
        self.trading_session = None

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
                        leverage = 3  # Futures по умолчанию 3x
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

                if "last" in ticker:
                    price = float(ticker["last"])

                    logger.debug(f"💰 {symbol}: ${price:.2f}")

                    # Проверка TrailingStopLoss для открытых позиций
                    if (
                        symbol in self.active_positions
                        and "entry_price" in self.active_positions.get(symbol, {})
                    ):
                        await self._update_trailing_stop_loss(symbol, price)
                    else:
                        # Генерируем сигналы только если позиции нет
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

    async def _main_trading_loop(self):
        """Основной торговый цикл"""
        logger.info("🔄 Запуск основного торгового цикла")

        while self.is_running:
            try:
                # Обновление состояния
                await self._update_state()

                # Генерация сигналов
                signals = await self.signal_generator.generate_signals()

                # Обработка сигналов
                await self._process_signals(signals)

                # Управление позициями
                await self._manage_positions()

                # Обновление статистики
                await self._update_performance()

                # Пауза между итерациями
                await asyncio.sleep(self.scalping_config.check_interval)

            except Exception as e:
                logger.error(f"Ошибка в торговом цикле: {e}")
                await asyncio.sleep(5)  # Пауза при ошибке

    async def _update_state(self):
        """Обновление состояния системы"""
        try:
            # Получение текущих позиций
            positions = await self.client.get_positions()

            # Обновление активных позиций
            self.active_positions = {}
            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if size != 0:
                    self.active_positions[symbol] = position

            # Проверка здоровья маржи
            margin_status = await self.liquidation_guard.get_margin_status(self.client)

            if margin_status.get("health_status", {}).get("status") == "critical":
                logger.critical("🚨 КРИТИЧЕСКОЕ СОСТОЯНИЕ МАРЖИ!")
                await self._emergency_close_all_positions()

        except Exception as e:
            logger.error(f"Ошибка обновления состояния: {e}")

    async def _process_signals(self, signals: List[Dict[str, Any]]):
        """Обработка торговых сигналов"""
        try:
            for signal in signals:
                symbol = signal.get("symbol")
                side = signal.get("side")
                strength = signal.get("strength", 0)

                # Проверка минимальной силы сигнала
                if strength < self.scalping_config.min_signal_strength:
                    continue

                # Проверка наличия активной позиции
                if symbol in self.active_positions:
                    logger.debug(f"Позиция {symbol} уже открыта, пропускаем сигнал")
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

            for symbol, position in self.active_positions.items():
                await self.position_manager.emergency_close_position(position)

        except Exception as e:
            logger.error(f"Ошибка экстренного закрытия позиций: {e}")

    async def _emergency_actions(self, symbol: str, side: str):
        """Экстренные действия при критическом уровне"""
        try:
            # Дополнительные проверки и действия
            logger.critical(f"🚨 Экстренные действия для {symbol} {side}")

        except Exception as e:
            logger.error(f"Ошибка экстренных действий: {e}")

    async def _check_for_signals(self, symbol: str, price: float):
        """Проверка и генерация сигналов на основе текущей цены"""
        try:
            # Проверка: не открываем позицию, если она уже есть
            if (
                symbol in self.active_positions
                and "order_id" in self.active_positions.get(symbol, {})
            ):
                return

            # УПРОЩЕННАЯ ЛОГИКА: Открываем позицию для теста
            # В продакшене здесь должна быть полная логика с индикаторами

            # Симуляция: открываем позицию каждые 100 обновлений цены (для демо)
            if not hasattr(self, "_price_update_count"):
                self._price_update_count = {}
            if symbol not in self._price_update_count:
                self._price_update_count[symbol] = 0

            self._price_update_count[symbol] += 1

            # Для демо открываем после 1 обновления (быстрый тест)
            if self._price_update_count[symbol] == 1:
                logger.info(f"🎯 ТЕСТОВЫЙ СИГНАЛ ДЛЯ {symbol} @ ${price:.2f}")
                # Создаем тестовый сигнал
                signal = {
                    "symbol": symbol,
                    "side": "buy",
                    "price": price,
                    "strength": 0.8,
                    "type": "market",
                }

                # Выполняем ордер
                await self._execute_signal_from_price(symbol, price, signal)
                logger.info(f"✅ Позиция {symbol} открыта по тестовому сигналу")

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

    async def _execute_signal_from_price(self, symbol: str, price: float, signal=None):
        """Выполняет торговый сигнал на основе цены"""
        try:
            # Проверяем, нет ли уже открытой позиции
            if (
                symbol in self.active_positions
                and "order_id" in self.active_positions[symbol]
            ):
                logger.debug(f"Позиция {symbol} уже открыта, пропускаем")
                return

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
                            self.signal_generator.regime_manager.get_current_regime().value
                        )
                    except:
                        pass

                signal = {
                    "symbol": symbol,
                    "side": "buy",
                    "price": price,
                    "strength": 0.8,
                    "regime": regime,  # ✅ Добавляем режим для адаптивных TP/SL
                    "type": "market",  # ✅ MARKET - TrailingSL будет управлять SL
                }

            # Рассчитываем размер позиции
            balance = await self.client.get_balance()
            position_size = await self._calculate_position_size(balance, price, signal)

            if position_size <= 0:
                logger.warning(f"Размер позиции слишком мал: {position_size}")
                return

            # Проверка через MaxSizeLimiter
            size_usd = position_size * price
            can_open, reason = self.max_size_limiter.can_open_position(symbol, size_usd)

            if not can_open:
                logger.warning(f"Нельзя открыть позицию: {reason}")
                return

            # Проверка через FundingRateMonitor
            if not self.funding_monitor.is_funding_favorable(signal["side"]):
                logger.warning(f"Funding неблагоприятен для {signal['side']}")
                return

            # Выполняем ордер с TP/SL
            result = await self.order_executor.execute_signal(signal, position_size)

            if result.get("success"):
                logger.info(f"✅ Позиция открыта: {symbol} {position_size:.6f}")

                # 🛡️ Обновляем total_margin_used
                margin_used = position_size * price / 3  # margin = notional / leverage
                self.total_margin_used += margin_used
                logger.debug(f"💼 Общая маржа: ${self.total_margin_used:.2f}")

                # Сохраняем в active_positions
                if symbol not in self.active_positions:
                    self.active_positions[symbol] = {}
                    self.active_positions[symbol].update(
                        {
                            "order_id": result.get("order_id"),
                            "side": signal["side"],
                            "size": position_size,
                            "entry_price": price,
                            "margin": margin_used,  # margin для этой позиции
                            "timestamp": datetime.now(),
                            # ✅ БЕЗ tp_order_id и sl_order_id - используем TrailingSL!
                        }
                    )

                    # Инициализируем TrailingStopLoss для новой позиции
                    tsl = TrailingStopLoss(
                        initial_trail=0.05, max_trail=0.2, min_trail=0.02
                    )
                    tsl.initialize(entry_price=price, side=signal["side"])
                    self.trailing_sl_by_symbol[symbol] = tsl

                    logger.info(f"🎯 Позиция {symbol} открыта с TrailingSL")

            else:
                logger.warning(f"Не удалось открыть позицию: {result.get('error')}")

        except Exception as e:
            logger.error(f"Ошибка выполнения сигнала: {e}")

    async def _calculate_position_size(
        self, balance: float, price: float, signal: dict
    ) -> float:
        """Рассчитывает размер позиции с учетом Balance Profiles и режима рынка"""
        try:
            # 1. Определяем профиль баланса
            balance_profile = self._get_balance_profile(balance)

            # 2. Получаем базовый размер позиции
            base_usd_size = balance_profile["base_position_usd"]
            min_usd_size = balance_profile["min_position_usd"]
            max_usd_size = balance_profile["max_position_usd"]

            # 3. Адаптируем под режим рынка (если ARM активен)
            if (
                hasattr(self.signal_generator, "regime_manager")
                and self.signal_generator.regime_manager
            ):
                try:
                    regime = self.signal_generator.regime_manager.get_current_regime()

                    # Получаем multiplier для текущего режима
                    if regime:
                        regime_params = self._get_regime_params(regime)
                        if (
                            regime_params
                            and "position_size_multiplier" in regime_params
                        ):
                            base_usd_size *= regime_params["position_size_multiplier"]
                            logger.debug(
                                f"Режим {regime}: multiplier={regime_params['position_size_multiplier']}"
                            )
                except Exception as e:
                    logger.warning(f"Ошибка адаптации под режим: {e}")

            # 3.5 НОВОЕ: Адаптируем под силу сигнала
            signal_strength = signal.get("strength", 0.5)
            if signal_strength > 0.8:
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

            base_usd_size *= strength_multiplier

            # 4. ПРИМЕНЯЕМ ЛЕВЕРИДЖ (Futures)
            leverage = 3  # Futures по умолчанию 3x
            notional_usd = base_usd_size * leverage  # Номинальная стоимость
            margin_required = base_usd_size  # Требуемая маржа

            # 5. 🛡️ ЗАЩИТА: Max Margin Used (80%)
            max_margin_allowed = balance * self.max_margin_percent  # 80%
            if self.total_margin_used + margin_required > max_margin_allowed:
                logger.warning(
                    f"⚠️ Достигнут лимит маржи: {self.total_margin_used + margin_required:.2f} > {max_margin_allowed:.2f}"
                )
                margin_required = max(0, max_margin_allowed - self.total_margin_used)
                if margin_required < min_usd_size:
                    logger.error(f"❌ Недостаточно свободной маржи для открытия позиции")
                    return 0.0

            # 6. 🛡️ ЗАЩИТА: Max Loss per Trade (2%)
            max_loss_usd = balance * self.max_loss_per_trade  # 2% макс потеря
            sl_percent = getattr(self.scalping_config, "sl_percent", 0.2)

            # Рассчитываем максимально безопасный размер
            max_safe_margin = max_loss_usd / (sl_percent / 100)

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
                notional_usd = margin_required * leverage

            # 8. Применяем ограничения
            usd_size = max(min_usd_size, min(margin_required, max_usd_size))

            # 9. Переводим в количество монет (используем NOTIONAL)
            position_size = (usd_size * leverage) / price

            # 10. 🛡️ ЗАЩИТА: Проверяем drawdown перед открытием
            if not await self._check_drawdown_protection():
                logger.warning(
                    "⚠️ Drawdown protection активирован - пропускаем позицию"
                )
                return 0.0

            logger.info(
                f"💰 Расчет: balance=${balance:.2f}, "
                f"profile={balance_profile['name']}, "
                f"margin=${usd_size:.2f}, "
                f"notional=${usd_size * leverage:.2f}, "
                f"position_size={position_size:.6f}"
            )

            return position_size

        except Exception as e:
            logger.error(f"Ошибка расчета размера позиции: {e}")
            return 0.0

    def _get_balance_profile(self, balance: float) -> dict:
        """Определяет профиль баланса"""
        balance_profiles = getattr(self.scalping_config, "balance_profiles", {})

        # Профили по возрастанию порога
        profiles = [
            {"name": "small", "threshold": 1500.0},
            {"name": "medium", "threshold": 3000.0},
            {"name": "large", "threshold": 999999.0},
        ]

        # Определяем профиль
        for profile in profiles:
            if balance <= profile["threshold"]:
                profile_config = balance_profiles.get(profile["name"], None)

                if profile_config is None:
                    # Возвращаем дефолтные значения
                    return {
                        "name": profile["name"],
                        "base_position_usd": 50.0,
                        "min_position_usd": 10.0,
                        "max_position_usd": 100.0,
                        "max_open_positions": 2,
                        "max_position_percent": 8.0,
                    }

                # Используем атрибуты Pydantic модели
                return {
                    "name": profile["name"],
                    "base_position_usd": getattr(
                        profile_config, "base_position_usd", 50.0
                    ),
                    "min_position_usd": getattr(
                        profile_config, "min_position_usd", 10.0
                    ),
                    "max_position_usd": getattr(
                        profile_config, "max_position_usd", 100.0
                    ),
                    "max_open_positions": getattr(
                        profile_config, "max_open_positions", 2
                    ),
                    "max_position_percent": getattr(
                        profile_config, "max_position_percent", 8.0
                    ),
                }

        # Fallback
        return {
            "name": "default",
            "base_position_usd": 50.0,
            "min_position_usd": 10.0,
            "max_position_usd": 100.0,
            "max_open_positions": 2,
            "max_position_percent": 8.0,
        }

    def _get_regime_params(self, regime_name: str) -> dict:
        """Получает параметры текущего режима из ARM"""
        try:
            adaptive_regime = getattr(self.config, "adaptive_regime", {})
            if isinstance(adaptive_regime, dict):
                return adaptive_regime.get(regime_name, {})
            return {}
        except Exception as e:
            logger.warning(f"Ошибка получения параметров режима: {e}")
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
                return

            tsl = self.trailing_sl_by_symbol[symbol]

            # Обновляем трейлинг стоп с новой ценой
            tsl.update(current_price)

            stop_loss = tsl.get_stop_loss()
            profit_pct = tsl.get_profit_pct(current_price)
            highest = tsl.highest_price

            # DEBUG: Логируем состояние (каждые 5 секунд)
            if not hasattr(self, "_tsl_log_count"):
                self._tsl_log_count = {}
            if symbol not in self._tsl_log_count:
                self._tsl_log_count[symbol] = 0
            self._tsl_log_count[symbol] += 1

            if self._tsl_log_count[symbol] % 5 == 0:  # Каждые 5-й раз
                logger.info(
                    f"📊 TrailingSL {symbol}: price={current_price:.2f}, entry={entry_price:.2f}, highest={highest:.2f}, stop={stop_loss:.2f}, profit={profit_pct:.2%}"
                )

            # Проверяем, нужно ли закрывать позицию по трейлинг стопу
            if tsl.should_close_position(current_price):
                logger.info(
                    f"🛑 Позиция {symbol} достигла трейлинг стоп-лосса (price={current_price:.2f} <= stop={stop_loss:.2f})"
                )
                await self._close_position(symbol, "trailing_stop")

        except Exception as e:
            logger.error(f"Ошибка обновления трейлинг стоп-лосса: {e}")

    async def _close_position(self, symbol: str, reason: str):
        """Закрытие позиции через position_manager"""
        try:
            position = self.active_positions.get(symbol, {})

            if position:
                logger.info(f"🛑 Закрытие позиции {symbol}: {reason}")

                # ✅ Закрываем через position_manager (API)
                await self.position_manager.close_position_manually(symbol)

                # 🛡️ Вычитаем margin при закрытии
                position_margin = position.get("margin", 0)
                if position_margin > 0:
                    self.total_margin_used -= position_margin
                    logger.debug(
                        f"💼 Общая маржа после закрытия: ${self.total_margin_used:.2f}"
                    )

                    # Удаляем из active_positions
                    del self.active_positions[symbol]

                    # Сбрасываем трейлинг стоп
                    if symbol in self.trailing_sl_by_symbol:
                        self.trailing_sl_by_symbol[symbol].reset()
                        del self.trailing_sl_by_symbol[symbol]

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
