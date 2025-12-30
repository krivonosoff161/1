"""
Holding Time Metrics - Отслеживание времени удержания позиций.

Отслеживает:
- Среднее время удержания позиций
- Время удержания по режимам
- Время удержания по типам выхода (TP, SL, Emergency, etc.)
- Распределение времени удержания
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger


class HoldingTimeMetrics:
    """
    Метрики времени удержания позиций.

    Отслеживает время от открытия до закрытия позиций.
    """

    def __init__(self):
        """Инициализация Holding Time Metrics."""
        # История позиций
        self._positions_history: List[Dict[str, Any]] = []
        self._max_history_size = 10000

        # Статистика по режимам
        self.holding_times_by_regime: Dict[str, List[float]] = defaultdict(
            list
        )  # {regime: [seconds, ...]}

        # Статистика по типам выхода
        self.holding_times_by_exit: Dict[str, List[float]] = defaultdict(
            list
        )  # {exit_reason: [seconds, ...]}

        # Статистика по символам
        self.holding_times_by_symbol: Dict[str, List[float]] = defaultdict(
            list
        )  # {symbol: [seconds, ...]}

        logger.info("✅ HoldingTimeMetrics инициализирован")

    def record_position_opened(
        self,
        symbol: str,
        regime: Optional[str] = None,
        position_id: Optional[str] = None,
    ) -> None:
        """
        Записать открытие позиции.

        Args:
            symbol: Торговый символ
            regime: Режим рынка
            position_id: ID позиции (для связи с закрытием)
        """
        self._positions_history.append(
            {
                "position_id": position_id or f"{symbol}_{datetime.now().timestamp()}",
                "symbol": symbol,
                "regime": regime,
                "opened_at": datetime.now(),
                "closed_at": None,
                "exit_reason": None,
                "holding_seconds": None,
            }
        )

        # Ограничиваем размер истории
        if len(self._positions_history) > self._max_history_size:
            self._positions_history = self._positions_history[-self._max_history_size :]

    def record_position_closed(
        self,
        symbol: str,
        exit_reason: str,
        position_id: Optional[str] = None,
        opened_at: Optional[datetime] = None,
    ) -> None:
        """
        Записать закрытие позиции.

        Args:
            symbol: Торговый символ
            exit_reason: Причина закрытия (tp_reached, sl_reached, emergency_loss, etc.)
            position_id: ID позиции (для связи с открытием)
            opened_at: Время открытия (если не указано, ищется в истории)
        """
        closed_at = datetime.now()

        # Ищем позицию в истории
        position = None
        if position_id:
            for pos in reversed(self._positions_history):
                if (
                    pos.get("position_id") == position_id
                    and pos.get("closed_at") is None
                ):
                    position = pos
                    break

        # Если не нашли по ID, ищем по символу и времени открытия
        if not position and opened_at:
            for pos in reversed(self._positions_history):
                if (
                    pos.get("symbol") == symbol
                    and pos.get("opened_at") == opened_at
                    and pos.get("closed_at") is None
                ):
                    position = pos
                    break

        # Если не нашли, создаем новую запись
        if not position:
            position = {
                "position_id": position_id or f"{symbol}_{closed_at.timestamp()}",
                "symbol": symbol,
                "regime": None,
                "opened_at": opened_at or closed_at,
                "closed_at": None,
                "exit_reason": None,
                "holding_seconds": None,
            }
            self._positions_history.append(position)

        # Обновляем позицию
        position["closed_at"] = closed_at
        position["exit_reason"] = exit_reason

        # Рассчитываем время удержания
        if position["opened_at"]:
            holding_seconds = (closed_at - position["opened_at"]).total_seconds()
            position["holding_seconds"] = holding_seconds

            # Добавляем в статистику
            if position.get("regime"):
                self.holding_times_by_regime[position["regime"]].append(holding_seconds)

            self.holding_times_by_exit[exit_reason].append(holding_seconds)
            self.holding_times_by_symbol[symbol].append(holding_seconds)

    def get_average_holding_time(
        self,
        symbol: Optional[str] = None,
        regime: Optional[str] = None,
        exit_reason: Optional[str] = None,
        period_hours: int = 24,
    ) -> float:
        """
        Получить среднее время удержания.

        Args:
            symbol: Торговый символ (если None - все символы)
            regime: Режим рынка (если None - все режимы)
            exit_reason: Причина закрытия (если None - все причины)
            period_hours: Период для расчета (часы)

        Returns:
            Среднее время удержания в секундах
        """
        cutoff_time = datetime.now() - timedelta(hours=period_hours)

        # Фильтруем закрытые позиции за период
        closed_positions = [
            p
            for p in self._positions_history
            if p.get("closed_at")
            and p.get("closed_at") >= cutoff_time
            and p.get("holding_seconds") is not None
        ]

        if symbol:
            closed_positions = [
                p for p in closed_positions if p.get("symbol") == symbol
            ]

        if regime:
            closed_positions = [
                p for p in closed_positions if p.get("regime") == regime
            ]

        if exit_reason:
            closed_positions = [
                p for p in closed_positions if p.get("exit_reason") == exit_reason
            ]

        if not closed_positions:
            return 0.0

        total_seconds = sum(p.get("holding_seconds", 0) for p in closed_positions)
        return total_seconds / len(closed_positions)

    def get_holding_time_stats(
        self,
        symbol: Optional[str] = None,
        regime: Optional[str] = None,
        period_hours: int = 24,
    ) -> Dict[str, Any]:
        """
        Получить статистику времени удержания.

        Args:
            symbol: Торговый символ (если None - все символы)
            regime: Режим рынка (если None - все режимы)
            period_hours: Период для расчета (часы)

        Returns:
            Словарь со статистикой:
            {
                "average": float,
                "median": float,
                "min": float,
                "max": float,
                "count": int,
                "by_exit_reason": {exit_reason: average_seconds},
            }
        """
        cutoff_time = datetime.now() - timedelta(hours=period_hours)

        # Фильтруем закрытые позиции за период
        closed_positions = [
            p
            for p in self._positions_history
            if p.get("closed_at")
            and p.get("closed_at") >= cutoff_time
            and p.get("holding_seconds") is not None
        ]

        if symbol:
            closed_positions = [
                p for p in closed_positions if p.get("symbol") == symbol
            ]

        if regime:
            closed_positions = [
                p for p in closed_positions if p.get("regime") == regime
            ]

        if not closed_positions:
            return {
                "average": 0.0,
                "median": 0.0,
                "min": 0.0,
                "max": 0.0,
                "count": 0,
                "by_exit_reason": {},
            }

        holding_times = [p.get("holding_seconds", 0) for p in closed_positions]
        holding_times.sort()

        # Статистика по причинам выхода
        by_exit_reason = defaultdict(list)
        for p in closed_positions:
            exit_reason = p.get("exit_reason", "unknown")
            by_exit_reason[exit_reason].append(p.get("holding_seconds", 0))

        exit_stats = {
            reason: sum(times) / len(times) if times else 0.0
            for reason, times in by_exit_reason.items()
        }

        return {
            "average": sum(holding_times) / len(holding_times),
            "median": holding_times[len(holding_times) // 2] if holding_times else 0.0,
            "min": min(holding_times) if holding_times else 0.0,
            "max": max(holding_times) if holding_times else 0.0,
            "count": len(holding_times),
            "by_exit_reason": exit_stats,
        }

    def get_regime_stats(self, period_hours: int = 24) -> Dict[str, Dict[str, Any]]:
        """
        Получить статистику по режимам.

        Args:
            period_hours: Период для расчета (часы)

        Returns:
            Словарь {regime: {average, median, min, max, count}}
        """
        stats = {}
        for regime in self.holding_times_by_regime.keys():
            regime_stats = self.get_holding_time_stats(
                regime=regime, period_hours=period_hours
            )
            stats[regime] = regime_stats

        return stats

    def get_exit_reason_stats(
        self, period_hours: int = 24
    ) -> Dict[str, Dict[str, Any]]:
        """
        Получить статистику по причинам выхода.

        Args:
            period_hours: Период для расчета (часы)

        Returns:
            Словарь {exit_reason: {average, median, min, max, count}}
        """
        stats = {}
        for exit_reason in self.holding_times_by_exit.keys():
            exit_stats = self.get_holding_time_stats(
                exit_reason=exit_reason, period_hours=period_hours
            )
            stats[exit_reason] = exit_stats

        return stats

    def get_summary(self, period_hours: int = 24) -> Dict[str, Any]:
        """
        Получить сводку метрик за период.

        Args:
            period_hours: Период для расчета (часы)

        Returns:
            Словарь с полной сводкой метрик
        """
        overall_stats = self.get_holding_time_stats(period_hours=period_hours)
        regime_stats = self.get_regime_stats(period_hours=period_hours)
        exit_reason_stats = self.get_exit_reason_stats(period_hours=period_hours)

        return {
            "period_hours": period_hours,
            "overall": overall_stats,
            "by_regime": regime_stats,
            "by_exit_reason": exit_reason_stats,
        }

    def log_summary(self, period_hours: int = 24) -> None:
        """
        Логировать сводку метрик.

        Args:
            period_hours: Период для расчета (часы)
        """
        summary = self.get_summary(period_hours=period_hours)

        overall = summary["overall"]
        avg_seconds = overall["average"]
        avg_minutes = avg_seconds / 60

        logger.info(
            f"⏱️ HoldingTimeMetrics (за {period_hours}ч): "
            f"Среднее время удержания={avg_minutes:.1f}мин ({avg_seconds:.0f}с), "
            f"Медиана={overall['median']/60:.1f}мин, "
            f"Позиций={overall['count']}"
        )

        if summary["by_exit_reason"]:
            logger.info(
                f"📊 По причинам выхода: "
                + ", ".join(
                    [
                        f"{reason}={stats['average']/60:.1f}мин"
                        for reason, stats in summary["by_exit_reason"].items()
                    ]
                )
            )

    def reset(self) -> None:
        """Сбросить все метрики."""
        self._positions_history.clear()
        self.holding_times_by_regime.clear()
        self.holding_times_by_exit.clear()
        self.holding_times_by_symbol.clear()
        logger.info("✅ HoldingTimeMetrics: Все метрики сброшены")

