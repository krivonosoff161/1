"""
Exit Decision Coordinator - Координатор решений о закрытии позиций.

Объединяет все системы закрытия и принимает финальное решение с учетом приоритетов:
1. Emergency Loss Protection (критический убыток)
2. Stop Loss (SL)
3. Take Profit (TP)
4. Trailing Stop Loss (TSL)
5. Max Holding Time
6. Smart Exit (разворот, паттерны)
7. Partial TP

Предотвращает конфликты между системами и обеспечивает единую логику приоритетов.
"""

from typing import Any, Dict, List, Optional

from loguru import logger


class ExitDecisionCoordinator:
    """
    Координатор решений о закрытии позиций.

    Объединяет решения от всех систем закрытия и выбирает приоритетное действие.
    """

    # Матрица приоритетов для различных причин закрытия
    # Меньшее число = выше приоритет
    EXIT_PRIORITIES = {
        "emergency_loss_protection": 1,  # Критический убыток - самый высокий приоритет
        "sl_reached": 2,  # Stop Loss достигнут
        "tp_reached": 3,  # Take Profit достигнут
        "trailing_stop": 4,  # Trailing Stop Loss сработал
        "max_holding_time": 5,  # Превышено максимальное время удержания
        "smart_exit_reversal": 6,  # Умное закрытие по развороту
        "smart_exit_pattern": 7,  # Умное закрытие по паттерну
        "partial_tp": 8,  # Частичное закрытие по TP
        "extend_tp": 9,  # Продление TP (не закрытие)
    }

    def __init__(
        self,
        exit_analyzer=None,
        trailing_sl_coordinator=None,
        smart_exit_coordinator=None,
        position_manager=None,
        priority_resolver=None,  # ✅ НОВОЕ (26.12.2025): PriorityResolver для разрешения конфликтов
    ):
        """
        Инициализация Exit Decision Coordinator.

        Args:
            exit_analyzer: ExitAnalyzer для анализа позиций
            trailing_sl_coordinator: TrailingSLCoordinator для трейлинг стоп-лоссов
            smart_exit_coordinator: SmartExitCoordinator для умного закрытия
            position_manager: PositionManager для проверки TP/SL
            priority_resolver: PriorityResolver для разрешения конфликтов приоритетов
        """
        self.exit_analyzer = exit_analyzer
        self.trailing_sl_coordinator = trailing_sl_coordinator
        self.smart_exit_coordinator = smart_exit_coordinator
        self.position_manager = position_manager
        self.priority_resolver = priority_resolver  # ✅ НОВОЕ (26.12.2025)

        logger.info("✅ ExitDecisionCoordinator инициализирован")

    async def analyze_position(
        self,
        symbol: str,
        position: Any,
        metadata: Any = None,
        market_data: Optional[Dict[str, Any]] = None,
        current_price: float = 0.0,
        regime: str = "ranging",
    ) -> Optional[Dict[str, Any]]:
        """
        Анализирует позицию и возвращает приоритетное решение о закрытии.

        Собирает решения от всех систем закрытия и выбирает самое приоритетное.

        Args:
            symbol: Торговый символ
            position: Данные позиции
            metadata: Метаданные позиции
            market_data: Рыночные данные
            current_price: Текущая цена
            regime: Режим рынка (trending, ranging, choppy)

        Returns:
            Решение о закрытии с наивысшим приоритетом или None
        """
        try:
            # Собираем решения от всех систем
            all_decisions: List[Dict[str, Any]] = []

            # 1. ExitAnalyzer - основная система анализа
            # ✅ ИСПРАВЛЕНО (27.12.2025): ExitAnalyzer.analyze_position принимает только symbol
            if self.exit_analyzer:
                try:
                    exit_decision = await self.exit_analyzer.analyze_position(
                        symbol=symbol
                    )
                    if exit_decision:
                        exit_decision["source"] = "exit_analyzer"
                        all_decisions.append(exit_decision)
                except Exception as e:
                    logger.debug(
                        f"⚠️ ExitDecisionCoordinator: Ошибка получения решения от ExitAnalyzer для {symbol}: {e}"
                    )

            # 2. Trailing Stop Loss Coordinator
            if self.trailing_sl_coordinator:
                try:
                    tsl_decision = await self._check_trailing_stop(
                        symbol, position, metadata, current_price
                    )
                    if tsl_decision:
                        tsl_decision["source"] = "trailing_sl"
                        all_decisions.append(tsl_decision)
                except Exception as e:
                    logger.debug(
                        f"⚠️ ExitDecisionCoordinator: Ошибка проверки Trailing SL для {symbol}: {e}"
                    )

            # 3. Smart Exit Coordinator
            if self.smart_exit_coordinator:
                try:
                    smart_decision = await self._check_smart_exit(
                        symbol, position, metadata, market_data, current_price, regime
                    )
                    if smart_decision:
                        smart_decision["source"] = "smart_exit"
                        all_decisions.append(smart_decision)
                except Exception as e:
                    logger.debug(
                        f"⚠️ ExitDecisionCoordinator: Ошибка проверки Smart Exit для {symbol}: {e}"
                    )

            # 4. Position Manager (TP/SL проверки)
            if self.position_manager:
                try:
                    pm_decision = await self._check_position_manager(
                        symbol, position, metadata, current_price
                    )
                    if pm_decision:
                        pm_decision["source"] = "position_manager"
                        all_decisions.append(pm_decision)
                except Exception as e:
                    logger.debug(
                        f"⚠️ ExitDecisionCoordinator: Ошибка проверки Position Manager для {symbol}: {e}"
                    )

            # Выбираем решение с наивысшим приоритетом
            if not all_decisions:
                return None

            # ✅ НОВОЕ (26.12.2025): Используем PriorityResolver для разрешения конфликтов
            if self.priority_resolver:
                best_decision = self.priority_resolver.resolve_exit_priority(
                    all_decisions
                )
                if best_decision:
                    priority = self.priority_resolver._get_exit_priority(
                        best_decision.get("reason", "unknown")
                    )
                else:
                    return None
            else:
                # Fallback: используем встроенную логику приоритетов
                all_decisions.sort(
                    key=lambda d: self._get_priority(d.get("reason", "unknown"))
                )
                best_decision = all_decisions[0]
                priority = self._get_priority(best_decision.get("reason", "unknown"))

            # Логируем все решения для диагностики
            if len(all_decisions) > 1:
                logger.debug(
                    f"🔍 ExitDecisionCoordinator {symbol}: Найдено {len(all_decisions)} решений, "
                    f"выбрано: {best_decision.get('reason')} (приоритет={priority})"
                )
                for i, decision in enumerate(all_decisions[:3]):  # Показываем топ-3
                    logger.debug(
                        f"   {i+1}. {decision.get('reason')} от {decision.get('source')} "
                        f"(приоритет={self._get_priority(decision.get('reason', 'unknown'))})"
                    )

            return best_decision

        except Exception as e:
            logger.error(
                f"❌ ExitDecisionCoordinator: Ошибка анализа позиции {symbol}: {e}",
                exc_info=True,
            )
            return None

    def _get_priority(self, reason: str) -> int:
        """
        Получить приоритет для причины закрытия.

        Args:
            reason: Причина закрытия

        Returns:
            Приоритет (меньшее число = выше приоритет)
        """
        normalized = self._normalize_reason(reason)
        return self.EXIT_PRIORITIES.get(normalized, 99)  # По умолчанию низкий приоритет

    def _normalize_reason(self, reason: Optional[str]) -> str:
        """Normalize exit reasons to priority matrix keys."""
        if not reason:
            return "unknown"
        if reason in self.EXIT_PRIORITIES:
            return reason
        if reason.startswith("emergency_loss_protection"):
            return "emergency_loss_protection"
        if reason.startswith("sl_reached") or reason in {
            "sl_grace_period",
            "sl_blocked_by_min_holding",
            "min_holding_not_reached_before_sl",
        }:
            return "sl_reached"
        if reason.startswith("tp_reached") or reason in {
            "big_profit_exit",
            "strong_trend_profit",
            "tp_rejected_negative_real_pnl",
        }:
            return "tp_reached"
        if reason in {"tsl_hit", "profit_too_low_vs_peak"}:
            return "trailing_stop"
        if reason.startswith("max_holding"):
            return "max_holding_time"
        if reason in {"reversal_detected"} or reason.startswith("smart_forced_close"):
            return "smart_exit_reversal"
        if reason in {"partial_tp_min_holding_wait"}:
            return "partial_tp"
        if reason in {"strong_trend_extend_tp"}:
            return "extend_tp"
        return reason

    async def _check_trailing_stop(
        self,
        symbol: str,
        position: Any,
        metadata: Any,
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Проверяет Trailing Stop Loss.

        Args:
            symbol: Торговый символ
            position: Данные позиции
            metadata: Метаданные позиции
            current_price: Текущая цена

        Returns:
            Решение о закрытии или None
        """
        try:
            if not self.trailing_sl_coordinator:
                return None

            # Получаем trailing stop для символа
            # ✅ ИСПРАВЛЕНО (27.12.2025): Правильное имя метода - get_tsl, а не get_trailing_stop
            trailing_stop = self.trailing_sl_coordinator.get_tsl(symbol)
            if not trailing_stop:
                return None

            # Проверяем, сработал ли trailing stop
            # ✅ ИСПРАВЛЕНО (08.01.2026): Метод должен быть should_close_position, а не should_close
            # 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (10.02.2026): Передаем margin_used и unrealized_pnl для правильного расчета PnL
            margin_used = None
            unrealized_pnl = None
            if metadata:
                # Получаем margin_used из metadata
                if hasattr(metadata, "margin_used"):
                    margin_used = (
                        float(metadata.margin_used)
                        if metadata.margin_used and metadata.margin_used > 0
                        else None
                    )
                elif hasattr(metadata, "margin"):
                    margin_used = (
                        float(metadata.margin)
                        if metadata.margin and metadata.margin > 0
                        else None
                    )
                # Получаем unrealized_pnl из metadata
                if hasattr(metadata, "unrealized_pnl"):
                    unrealized_pnl = (
                        float(metadata.unrealized_pnl)
                        if metadata.unrealized_pnl is not None
                        else None
                    )
                elif hasattr(metadata, "pnl"):
                    unrealized_pnl = (
                        float(metadata.pnl) if metadata.pnl is not None else None
                    )

            effective_price = float(current_price or 0.0)
            if effective_price <= 0 and isinstance(position, dict):
                effective_price = float(
                    position.get("markPx")
                    or position.get("mark_price")
                    or position.get("current_price")
                    or position.get("last")
                    or 0.0
                )
            if effective_price <= 0:
                logger.warning(
                    f"⚠️ ExitDecisionCoordinator: пропуск TSL для {symbol} из-за невалидной цены (current_price={current_price})"
                )
                return None

            should_close, reason = trailing_stop.should_close_position(
                effective_price,
                margin_used=margin_used,
                unrealized_pnl=unrealized_pnl,
            )
            if should_close:
                return {
                    "action": "close",
                    "reason": "trailing_stop",
                    "detail_reason": reason,  # ✅ НОВОЕ: Сохраняем детальную причину
                    "current_price": effective_price,
                    "trailing_stop_price": trailing_stop.get_stop_loss(),
                }

            return None
        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки Trailing SL для {symbol}: {e}")
            return None

    async def _check_smart_exit(
        self,
        symbol: str,
        position: Any,
        metadata: Any,
        market_data: Optional[Dict[str, Any]],
        current_price: float,
        regime: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Проверяет Smart Exit (разворот, паттерны).

        Args:
            symbol: Торговый символ
            position: Данные позиции
            metadata: Метаданные позиции
            market_data: Рыночные данные
            current_price: Текущая цена
            regime: Режим рынка

        Returns:
            Решение о закрытии или None
        """
        try:
            if not self.smart_exit_coordinator:
                return None

            # ✅ ИСПРАВЛЕНИЕ #9 (04.01.2026): Используем правильный метод check_position()
            # Получаем решение от Smart Exit Coordinator
            if hasattr(self.smart_exit_coordinator, "check_position"):
                smart_result = await self.smart_exit_coordinator.check_position(
                    symbol, position
                )
                if smart_result and smart_result.get("action") == "close":
                    return {
                        "action": "close",
                        "reason": smart_result.get("reason", "smart_exit"),
                        "current_price": current_price,
                    }

            return None
        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки Smart Exit для {symbol}: {e}")
            return None

    async def _check_position_manager(
        self,
        symbol: str,
        position: Any,
        metadata: Any,
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Проверяет Position Manager (TP/SL).

        Args:
            symbol: Торговый символ
            position: Данные позиции
            metadata: Метаданные позиции
            current_price: Текущая цена

        Returns:
            Решение о закрытии или None
        """
        # Position Manager обычно проверяется через ExitAnalyzer
        # Здесь можно добавить дополнительные проверки если нужно
        return None

    def get_priority_matrix(self) -> Dict[str, int]:
        """
        Возвращает матрицу приоритетов для отладки.

        Returns:
            Словарь {причина: приоритет}
        """
        return self.EXIT_PRIORITIES.copy()
