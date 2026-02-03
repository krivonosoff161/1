"""
PositionMonitor - Периодический мониторинг позиций.

Отвечает за:
- Периодический вызов ExitAnalyzer для всех открытых позиций
- Обновление данных позиций в DataRegistry
- Обнаружение новых позиций и добавление их в мониторинг
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

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
        client=None,  # ✅ Клиент для REST (опционально)
        exit_analyzer=None,  # ExitAnalyzer (будет создан позже)
        exit_decision_coordinator=None,  # ✅ НОВОЕ (26.12.2025): ExitDecisionCoordinator
        check_interval: float = 5.0,  # Интервал проверки в секундах
        close_position_callback=None,  # ✅ НОВОЕ: Callback для закрытия позиций
        position_manager=None,  # ✅ НОВОЕ: PositionManager для частичного закрытия
        allow_rest_fallback: bool = True,  # ✅ Разрешить REST fallback для цены
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
        self.client = client
        self.exit_analyzer = exit_analyzer
        self.exit_decision_coordinator = (
            exit_decision_coordinator  # ✅ НОВОЕ (26.12.2025)
        )
        self.check_interval = check_interval
        self.close_position_callback = close_position_callback  # ✅ НОВОЕ
        self.position_manager = position_manager  # ✅ НОВОЕ
        self.allow_rest_fallback = allow_rest_fallback

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

            position = None
            metadata = None
            regime = None
            current_price = None
            price_source = None
            price_age = None

            # ✅ НОВОЕ (26.12.2025): Используем ExitDecisionCoordinator если доступен
            if self.exit_decision_coordinator:
                # Получаем позицию и метаданные для координатора
                position = await self.position_registry.get_position(symbol)
                metadata = await self.position_registry.get_metadata(symbol)
                market_data = await self.data_registry.get_market_data(symbol)
                if market_data is None:
                    if not self.allow_rest_fallback:
                        logger.warning(
                            f"⚠️ PositionMonitor: Нет свежих рыночных данных для {symbol} (market_data is None), "
                            f"fallback запрещен — пропускаем анализ позиции"
                        )
                        return None
                    logger.warning(
                        f"⚠️ PositionMonitor: Нет свежих рыночных данных для {symbol} (market_data is None), "
                        f"продолжаем с fallback ценой"
                    )
                    market_data = {}
                # 🔴 BUG #10 FIX: 4-уровневый fallback для current_price
                (
                    current_price,
                    price_source,
                    price_age,
                ) = await self._get_current_price_with_fallback(
                    symbol=symbol, market_data=market_data, position=position
                )
                if not isinstance(current_price, (int, float)) or current_price <= 0:
                    logger.error(
                        f"❌ PositionMonitor: Некорректная цена для {symbol} (current_price={current_price}), "
                        f"пропускаем анализ позиции"
                    )
                    return None
                regime = "ranging"
                if hasattr(self.data_registry, "get_regime_name_sync"):
                    regime = (
                        self.data_registry.get_regime_name_sync(symbol) or "ranging"
                    )
                # ✅ ИСПРАВЛЕНО (27.12.2025): Конвертируем market_data в dict правильно
                market_data_dict = None
                if market_data:
                    if isinstance(market_data, dict):
                        market_data_dict = market_data
                    elif hasattr(market_data, "__dict__"):
                        market_data_dict = market_data.__dict__
                    else:
                        try:
                            market_data_dict = vars(market_data)
                        except (TypeError, AttributeError):
                            market_data_dict = None
                decision = await self.exit_decision_coordinator.analyze_position(
                    symbol=symbol,
                    position=position,
                    metadata=metadata,
                    market_data=market_data_dict,
                    current_price=current_price,
                    regime=regime,
                )
            elif self.exit_analyzer:
                # Fallback: используем ExitAnalyzer напрямую
                decision = await self.exit_analyzer.analyze_position(symbol)
            else:
                logger.warning(
                    f"⚠️ PositionMonitor: Нет ни ExitDecisionCoordinator, ни ExitAnalyzer для {symbol}"
                )
                return None

            if decision:
                decision_payload = None
                if position is None:
                    position = await self.position_registry.get_position(symbol)
                if metadata is None:
                    metadata = await self.position_registry.get_metadata(symbol)
                time_in_pos_sec = None
                entry_time = None
                if metadata and getattr(metadata, "entry_time", None):
                    entry_time = metadata.entry_time
                elif isinstance(position, dict):
                    entry_time = position.get("entry_time")
                if isinstance(entry_time, str):
                    try:
                        entry_time = datetime.fromisoformat(
                            entry_time.replace("Z", "+00:00")
                        )
                    except Exception:
                        entry_time = None
                if isinstance(entry_time, datetime):
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                    time_in_pos_sec = (
                        datetime.now(timezone.utc) - entry_time
                    ).total_seconds()
                elif entry_time is not None:
                    try:
                        entry_ts = float(entry_time)
                        time_in_pos_sec = time.time() - entry_ts
                    except Exception:
                        time_in_pos_sec = None

                position_payload = None
                if position is not None:
                    if isinstance(position, dict):
                        position_payload = position
                    elif hasattr(position, "to_dict"):
                        position_payload = position.to_dict()
                    elif hasattr(position, "__dict__"):
                        position_payload = dict(position.__dict__)

                decision_payload = {
                    "price": current_price,
                    "price_source": price_source,
                    "price_age": price_age,
                    "pnl_pct": decision.get("pnl_pct"),
                    "net_pnl_pct": decision.get("net_pnl_pct"),
                    "time_in_pos": time_in_pos_sec,
                    "position_data": position_payload,
                    "regime": decision.get("regime") or regime,
                    "decision": decision,
                }

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
                        await self.close_position_callback(
                            symbol, reason, decision_payload
                        )
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

    async def _get_current_price_with_fallback(
        self, symbol: str, market_data, position
    ) -> Tuple[float, str, Optional[float]]:
        """Four-level fallback for current_price.

        Levels:
        1. DataRegistry (WS)
        2. REST mark_price
        3. REST last_price
        4. Last known price in memory (TTL)

        Returns:
            (price, source, age_seconds)
        """

        def _calc_age(updated_at: Optional[datetime]) -> Optional[float]:
            if not updated_at or not isinstance(updated_at, datetime):
                return None
            if updated_at.tzinfo is None:
                now = datetime.now()
            else:
                now = datetime.now(updated_at.tzinfo)
            return (now - updated_at).total_seconds()

        # Level 1: DataRegistry (WS)
        if market_data:
            if isinstance(market_data, dict):
                updated_at = market_data.get("updated_at")
                source = market_data.get("source") or "WEBSOCKET"
                price = market_data.get("price") or market_data.get("last_price")
                if price:
                    return float(price), source, _calc_age(updated_at)

                tick = market_data.get("current_tick")
                if tick is not None and hasattr(tick, "price"):
                    return float(tick.price), source, _calc_age(updated_at)
            elif hasattr(market_data, "price"):
                updated_at = getattr(market_data, "updated_at", None)
                source = getattr(market_data, "source", None) or "WEBSOCKET"
                return float(market_data.price), source, _calc_age(updated_at)

        if not self.allow_rest_fallback:
            return 0.0, "NONE", None

        # Level 2 & 3: REST API (mark_price, last_price)
        if self.client:
            try:
                ticker = await self.client.get_ticker(symbol)
                if ticker:
                    mark_price = ticker.get("markPx")
                    if mark_price:
                        return float(mark_price), "REST", 0.0
                    last_price = ticker.get("last")
                    if last_price:
                        return float(last_price), "REST", 0.0
            except Exception as e:
                logger.debug(f"REST price fallback error for {symbol}: {e}")

        # Level 4: last_known_price (TTL 15s)
        if hasattr(self, "_last_known_prices"):
            last_price, timestamp = self._last_known_prices.get(symbol, (None, 0))
            if last_price:
                age = time.time() - float(timestamp)
                if age < 15:
                    return float(last_price), "MEMORY", age

        # Ultimate fallback: entry_price if available
        if position and hasattr(position, "entry_price"):
            if position.entry_price:
                logger.warning(
                    f"PositionMonitor {symbol}: using entry_price={position.entry_price} "
                    "(all fallbacks exhausted)"
                )
                return float(position.entry_price), "ENTRY", None

        logger.warning(
            f"PositionMonitor {symbol}: current_price=0.0 (no data from any fallback)"
        )
        return 0.0, "NONE", None
