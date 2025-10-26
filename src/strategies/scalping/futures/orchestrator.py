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
from .order_executor import FuturesOrderExecutor
from .position_manager import FuturesPositionManager
from .signal_generator import FuturesSignalGenerator


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

        # Модули безопасности
        self.margin_calculator = MarginCalculator(
            default_leverage=config.futures.get("leverage", 3),
            maintenance_margin_ratio=config.futures.get(
                "maintenance_margin_ratio", 0.01
            ),
            initial_margin_ratio=config.futures.get("initial_margin_ratio", 0.1),
        )

        self.liquidation_guard = LiquidationGuard(
            margin_calculator=self.margin_calculator,
            warning_threshold=config.futures.get("warning_threshold", 1.8),
            danger_threshold=config.futures.get("danger_threshold", 1.3),
            critical_threshold=config.futures.get("critical_threshold", 1.1),
            auto_close_threshold=config.futures.get("auto_close_threshold", 1.05),
        )

        self.slippage_guard = SlippageGuard(
            max_slippage_percent=config.futures.get("max_slippage_percent", 0.1),
            max_spread_percent=config.futures.get("max_spread_percent", 0.05),
            order_timeout=config.futures.get("order_timeout", 30.0),
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

        # Закрытие клиента
        await self.client.close()

        logger.info("✅ Futures торговый бот остановлен")

    async def _initialize_client(self):
        """Инициализация клиента"""
        try:
            # Проверка баланса
            balance = await self.client.get_balance()
            logger.info(f"💰 Доступный баланс: {balance:.2f} USDT")

            if balance < 100:  # Минимальный баланс
                raise ValueError(f"Недостаточный баланс: {balance:.2f} USDT")

            # Установка плеча для торговых пар
            for symbol in self.scalping_config.symbols:
                try:
                    await self.client.set_leverage(
                        symbol, self.config.futures.get("leverage", 3)
                    )
                    logger.info(
                        f"✅ Плечо {self.config.futures.get('leverage', 3)}x установлено для {symbol}"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось установить плечо для {symbol}: {e}")

        except Exception as e:
            logger.error(f"Ошибка инициализации клиента: {e}")
            raise

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
            # Обновление статистики
            await self.performance_tracker.update_stats(self.active_positions)

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

    async def get_status(self) -> Dict[str, Any]:
        """Получение статуса системы"""
        try:
            balance = await self.client.get_balance()
            margin_status = await self.liquidation_guard.get_margin_status(
                self.client
            )
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
