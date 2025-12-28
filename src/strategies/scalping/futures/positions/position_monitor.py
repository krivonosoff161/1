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
        exit_decision_coordinator=None,  # ✅ НОВОЕ (26.12.2025): ExitDecisionCoordinator
        check_interval: float = 5.0,  # Интервал проверки в секундах
        close_position_callback=None,  # ✅ НОВОЕ: Callback для закрытия позиций
        position_manager=None,  # ✅ НОВОЕ: PositionManager для частичного закрытия
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
        self.exit_decision_coordinator = exit_decision_coordinator  # ✅ НОВОЕ (26.12.2025)
        self.check_interval = check_interval
        self.close_position_callback = close_position_callback  # ✅ НОВОЕ
        self.position_manager = position_manager  # ✅ НОВОЕ

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
            # Проверяем, что позиция существует
            has_position = await self.position_registry.has_position(symbol)
            if not has_position:
                logger.debug(f"ℹ️ PositionMonitor: Позиция {symbol} не найдена")
                return None

            # ✅ НОВОЕ (26.12.2025): Используем ExitDecisionCoordinator если доступен
            if self.exit_decision_coordinator:
                # Получаем позицию и метаданные для координатора
                position = await self.position_registry.get_position(symbol)
                metadata = await self.position_registry.get_metadata(symbol)
                market_data = await self.data_registry.get_market_data(symbol)
                current_price = 0.0
                regime = "ranging"
                
                if market_data:
                    current_price = market_data.current_price if hasattr(market_data, 'current_price') else 0.0
                if hasattr(self.data_registry, 'get_regime_name_sync'):
                    regime = self.data_registry.get_regime_name_sync(symbol) or "ranging"
                
                # ✅ ИСПРАВЛЕНО (27.12.2025): Конвертируем market_data в dict правильно
                market_data_dict = None
                if market_data:
                    if isinstance(market_data, dict):
                        market_data_dict = market_data
                    elif hasattr(market_data, '__dict__'):
                        market_data_dict = market_data.__dict__
                    else:
                        # Fallback: пробуем получить через vars() или создать dict из атрибутов
                        try:
                            market_data_dict = vars(market_data)
                        except (TypeError, AttributeError):
                            # Если не получается, передаем None
                            market_data_dict = None
                
                decision = await self.exit_decision_coordinator.analyze_position(
                    symbol=symbol,
                    position=position,
                    metadata=metadata,
                    market_data=market_data_dict,
                    current_price=current_price,
                    regime=regime
                )
            elif self.exit_analyzer:
                # Fallback: используем ExitAnalyzer напрямую
                decision = await self.exit_analyzer.analyze_position(symbol)
            else:
                logger.warning(f"⚠️ PositionMonitor: Нет ни ExitDecisionCoordinator, ни ExitAnalyzer для {symbol}")
                return None

            if decision:
                action = decision.get("action")
                reason = decision.get("reason", "exit_analyzer")
                pnl_pct = decision.get("pnl_pct", 0.0)

                logger.info(
                    f"🎯 PositionMonitor: Решение для {symbol}: action={action}, "
                    f"reason={reason}, pnl={pnl_pct:.2f}%"
                )

                # ✅ ОБРАБОТКА РЕШЕНИЙ ExitAnalyzer
                if action == "close":
                    if self.close_position_callback:
                        logger.info(
                            f"✅ PositionMonitor: Закрываем {symbol} (reason={reason})"
                        )
                        await self.close_position_callback(symbol, reason)
                    else:
                        logger.warning(
                            f"⚠️ PositionMonitor: Решение закрыть {symbol}, но close_position_callback не установлен"
                        )
                elif action == "partial_close":
                    fraction = decision.get("fraction", 0.5)
                    if self.position_manager and hasattr(
                        self.position_manager, "close_partial_position"
                    ):
                        try:
                            partial_result = (
                                await self.position_manager.close_partial_position(
                                    symbol=symbol,
                                    fraction=fraction,
                                    reason=reason,
                                )
                            )
                            if partial_result and partial_result.get("success"):
                                logger.info(
                                    f"✅ PositionMonitor: Частичное закрытие {symbol} выполнено: "
                                    f"закрыто {fraction*100:.0f}%"
                                )
                        except Exception as e:
                            logger.error(
                                f"❌ PositionMonitor: Ошибка частичного закрытия {symbol}: {e}",
                                exc_info=True,
                            )
                    else:
                        logger.warning(
                            f"⚠️ PositionMonitor: Решение частично закрыть {symbol}, но position_manager не доступен"
                        )
                elif action == "extend_tp":
                    logger.debug(
                        f"📈 PositionMonitor: TP продлен для {symbol} (reason={reason})"
                    )
                    # Продление TP обрабатывается в trailing_sl_coordinator
                elif action == "hold":
                    logger.debug(
                        f"⏸️ PositionMonitor: Держим позицию {symbol} (reason={reason})"
                    )
                else:
                    logger.warning(
                        f"⚠️ PositionMonitor: Неизвестный action={action} для {symbol}"
                    )

            return decision

        except Exception as e:
            logger.error(
                f"❌ PositionMonitor: Ошибка проверки позиции {symbol}: {e}",
                exc_info=True,
            )
            return None
