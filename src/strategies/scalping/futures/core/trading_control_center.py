"""
TradingControlCenter - Единый центр управления всеми процессами торговли.

Координирует:
- SignalPipeline (генерация сигналов)
- EntryManager (открытие позиций)
- ExitAnalyzer (закрытие позиций)
- PositionMonitor (мониторинг позиций)
"""

from typing import Any, Dict, Optional

from loguru import logger

from .data_registry import DataRegistry
from .position_registry import PositionRegistry, PositionMetadata


class TradingControlCenter:
    """
    Единый центр управления всеми процессами торговли.

    Это главный координатор, который управляет:
    - Генерацией и валидацией сигналов
    - Открытием позиций
    - Мониторингом и закрытием позиций
    - Синхронизацией данных

    Все операции проходят через этот центр для единообразия.
    """

    def __init__(
        self,
        position_registry: PositionRegistry,
        data_registry: DataRegistry,
    ):
        """
        Инициализация центра управления.

        Args:
            position_registry: Реестр позиций
            data_registry: Реестр данных
        """
        self.position_registry = position_registry
        self.data_registry = data_registry

        # Эти модули будут инициализированы позже (после их создания)
        self.signal_pipeline = None  # SignalPipeline
        self.entry_manager = None  # EntryManager
        self.exit_analyzer = None  # ExitAnalyzer
        self.position_monitor = None  # PositionMonitor

        logger.info("✅ TradingControlCenter инициализирован")

    def set_signal_pipeline(self, signal_pipeline):
        """Установить SignalPipeline"""
        self.signal_pipeline = signal_pipeline
        logger.debug("✅ TradingControlCenter: SignalPipeline установлен")

    def set_entry_manager(self, entry_manager):
        """Установить EntryManager"""
        self.entry_manager = entry_manager
        logger.debug("✅ TradingControlCenter: EntryManager установлен")

    def set_exit_analyzer(self, exit_analyzer):
        """Установить ExitAnalyzer"""
        self.exit_analyzer = exit_analyzer
        logger.debug("✅ TradingControlCenter: ExitAnalyzer установлен")

    def set_position_monitor(self, position_monitor):
        """Установить PositionMonitor"""
        self.position_monitor = position_monitor
        logger.debug("✅ TradingControlCenter: PositionMonitor установлен")

    async def start(self) -> None:
        """
        Запуск центра управления.

        Инициализирует все модули и начинает главный цикл.
        """
        logger.info("🚀 TradingControlCenter: Запуск...")

        # Проверяем, что все модули установлены
        if not self.signal_pipeline:
            logger.warning("⚠️ TradingControlCenter: SignalPipeline не установлен")
        if not self.entry_manager:
            logger.warning("⚠️ TradingControlCenter: EntryManager не установлен")
        if not self.exit_analyzer:
            logger.warning("⚠️ TradingControlCenter: ExitAnalyzer не установлен")
        if not self.position_monitor:
            logger.warning("⚠️ TradingControlCenter: PositionMonitor не установлен")

        logger.info("✅ TradingControlCenter: Запущен")

    async def stop(self) -> None:
        """
        Остановка центра управления.

        Корректно останавливает все модули.
        """
        logger.info("🛑 TradingControlCenter: Остановка...")
        logger.info("✅ TradingControlCenter: Остановлен")

    async def generate_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Генерация сигнала для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Сгенерированный сигнал или None
        """
        if not self.signal_pipeline:
            logger.warning(
                f"⚠️ TradingControlCenter: Невозможно сгенерировать сигнал для {symbol} - SignalPipeline не установлен"
            )
            return None

        # Получаем market data из DataRegistry
        market_data = await self.data_registry.get_market_data(symbol)
        if not market_data:
            logger.debug(f"⚠️ TradingControlCenter: Нет market data для {symbol}")
            return None

        # Генерируем сигнал через SignalPipeline
        signal = await self.signal_pipeline.generate_signal(symbol, market_data)

        if signal:
            logger.debug(f"✅ TradingControlCenter: Сгенерирован сигнал для {symbol}")
        else:
            logger.debug(f"ℹ️ TradingControlCenter: Сигнал для {symbol} не сгенерирован")

        return signal

    async def open_position(self, signal: Dict[str, Any]) -> bool:
        """
        Открытие позиции на основе сигнала.

        Args:
            signal: Торговый сигнал

        Returns:
            True если позиция успешно открыта
        """
        if not self.entry_manager:
            logger.warning(
                f"⚠️ TradingControlCenter: Невозможно открыть позицию - EntryManager не установлен"
            )
            return False

        symbol = signal.get("symbol")
        if not symbol:
            logger.error("❌ TradingControlCenter: Сигнал не содержит symbol")
            return False

        # Открываем позицию через EntryManager
        success = await self.entry_manager.open_position(signal)

        if success:
            logger.info(f"✅ TradingControlCenter: Позиция {symbol} открыта")
        else:
            logger.warning(f"⚠️ TradingControlCenter: Не удалось открыть позицию {symbol}")

        return success

    async def analyze_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Анализ позиции для принятия решения о закрытии.

        Args:
            symbol: Торговый символ

        Returns:
            Решение ExitAnalyzer или None
        """
        if not self.exit_analyzer:
            logger.warning(
                f"⚠️ TradingControlCenter: Невозможно проанализировать позицию {symbol} - ExitAnalyzer не установлен"
            )
            return None

        # Проверяем, что позиция существует
        has_position = await self.position_registry.has_position(symbol)
        if not has_position:
            logger.debug(f"ℹ️ TradingControlCenter: Позиция {symbol} не найдена")
            return None

        # Анализируем позицию через ExitAnalyzer
        decision = await self.exit_analyzer.analyze_position(symbol)

        return decision

    async def close_position(
        self, symbol: str, reason: str, decision: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Закрытие позиции.

        Args:
            symbol: Торговый символ
            reason: Причина закрытия
            decision: Решение ExitAnalyzer (опционально)

        Returns:
            True если позиция успешно закрыта
        """
        if not self.exit_analyzer:
            logger.warning(
                f"⚠️ TradingControlCenter: Невозможно закрыть позицию {symbol} - ExitAnalyzer не установлен"
            )
            return False

        # Закрываем позицию через ExitAnalyzer
        success = await self.exit_analyzer.close_position(symbol, reason, decision)

        if success:
            logger.info(f"✅ TradingControlCenter: Позиция {symbol} закрыта (reason={reason})")
        else:
            logger.warning(f"⚠️ TradingControlCenter: Не удалось закрыть позицию {symbol}")

        return success

    async def update_market_data(self, symbol: str, data: Dict[str, Any]) -> None:
        """
        Обновить рыночные данные для символа.

        Args:
            symbol: Торговый символ
            data: Рыночные данные
        """
        await self.data_registry.update_market_data(symbol, data)

    async def update_regime(
        self, symbol: str, regime: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Обновить режим рынка для символа.

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            params: Параметры режима
        """
        await self.data_registry.update_regime(symbol, regime, params)

    async def update_balance(self, balance: float, profile: Optional[str] = None) -> None:
        """
        Обновить баланс и профиль баланса.

        Args:
            balance: Текущий баланс
            profile: Профиль баланса (small, medium, large)
        """
        await self.data_registry.update_balance(balance, profile)

