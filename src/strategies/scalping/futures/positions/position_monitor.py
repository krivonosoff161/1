"""
PositionMonitor - Периодический мониторинг позиций.

Отвечает за:
- Периодический вызов ExitAnalyzer для всех открытых позиций
- Обновление данных позиций в DataRegistry
- Обнаружение новых позиций и добавление их в мониторинг
"""

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from ..core.data_registry import DataRegistry
from ..core.position_registry import PositionRegistry


class PositionMonitor:
    """
    Монитор позиций.

    Периодически проверяет все открытые позиции и вызывает ExitAnalyzer для анализа.
    """

    def __init__(
        self,
        position_registry: PositionRegistry,
        data_registry: DataRegistry,
        exit_analyzer=None,  # ExitAnalyzer (будет создан позже)
        check_interval: float = 5.0,  # Интервал проверки в секундах
    ):
        """
        Инициализация PositionMonitor.

        Args:
            position_registry: Реестр позиций
            data_registry: Реестр данных
            exit_analyzer: ExitAnalyzer для анализа позиций (опционально)
            check_interval: Интервал проверки позиций в секундах
        """
        self.position_registry = position_registry
        self.data_registry = data_registry
        self.exit_analyzer = exit_analyzer
        self.check_interval = check_interval

        self.is_running = False
        self.monitor_task = None

        logger.info(
            f"✅ PositionMonitor инициализирован (check_interval={check_interval} сек)"
        )

    def set_exit_analyzer(self, exit_analyzer):
        """Установить ExitAnalyzer"""
        self.exit_analyzer = exit_analyzer
        logger.debug("✅ PositionMonitor: ExitAnalyzer установлен")

    async def start(self) -> None:
        """
        Запуск мониторинга позиций.

        Запускает фоновую задачу для периодической проверки позиций.
        """
        if self.is_running:
            logger.warning("⚠️ PositionMonitor: Уже запущен")
            return

        self.is_running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())

        logger.info("🚀 PositionMonitor: Запущен")

    async def stop(self) -> None:
        """
        Остановка мониторинга позиций.
        """
        if not self.is_running:
            return

        self.is_running = False

        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("🛑 PositionMonitor: Остановлен")

    async def _monitor_loop(self) -> None:
        """
        Главный цикл мониторинга позиций.
        """
        try:
            while self.is_running:
                await self.check_all_positions()
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.debug("🛑 PositionMonitor: Цикл мониторинга отменен")
        except Exception as e:
            logger.error(
                f"❌ PositionMonitor: Ошибка в цикле мониторинга: {e}", exc_info=True
            )

    async def check_all_positions(self) -> None:
        """
        Проверить все открытые позиции.

        Для каждой позиции вызывает ExitAnalyzer для анализа.
        """
        try:
            # Получаем все позиции из PositionRegistry
            all_positions = await self.position_registry.get_all_positions()

            if not all_positions:
                return

            logger.debug(f"🔍 PositionMonitor: Проверка {len(all_positions)} позиций")

            # Проверяем каждую позицию
            for symbol in all_positions.keys():
                if not self.is_running:
                    break

                await self.check_position(symbol)

        except Exception as e:
            logger.error(
                f"❌ PositionMonitor: Ошибка проверки позиций: {e}", exc_info=True
            )

    async def check_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Проверить конкретную позицию.

        Вызывает ExitAnalyzer для анализа позиции.

        Args:
            symbol: Торговый символ

        Returns:
            Решение ExitAnalyzer или None
        """
        try:
            if not self.exit_analyzer:
                logger.debug(
                    f"ℹ️ PositionMonitor: ExitAnalyzer не установлен для {symbol}"
                )
                return None

            # Проверяем, что позиция существует
            has_position = await self.position_registry.has_position(symbol)
            if not has_position:
                logger.debug(f"ℹ️ PositionMonitor: Позиция {symbol} не найдена")
                return None

            # Вызываем ExitAnalyzer для анализа
            decision = await self.exit_analyzer.analyze_position(symbol)

            if decision:
                logger.debug(
                    f"✅ PositionMonitor: Получено решение для {symbol}: {decision.get('action', 'N/A')}"
                )

            return decision

        except Exception as e:
            logger.error(
                f"❌ PositionMonitor: Ошибка проверки позиции {symbol}: {e}",
                exc_info=True,
            )
            return None
