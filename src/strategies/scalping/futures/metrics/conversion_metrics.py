"""
Conversion Metrics - Отслеживание конверсии сигналов в позиции.

Отслеживает:
- Количество сгенерированных сигналов
- Количество сигналов, прошедших фильтры
- Количество сигналов, исполненных (открыты позиции)
- Конверсию на каждом этапе
- Причины блокировки сигналов
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger


class ConversionMetrics:
    """
    Метрики конверсии сигналов в позиции.

    Отслеживает весь путь сигнала от генерации до открытия позиции.
    """

    def __init__(self):
        """Инициализация Conversion Metrics."""
        # Счетчики сигналов
        self.signals_generated: Dict[str, int] = defaultdict(int)  # {symbol: count}
        self.signals_filtered: Dict[str, int] = defaultdict(int)  # {symbol: count}
        self.signals_executed: Dict[str, int] = defaultdict(int)  # {symbol: count}

        # Причины блокировки сигналов
        self.filter_reasons: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )  # {symbol: {reason: count}}

        # Временные метки для расчета конверсии за период
        self._signals_history: List[Dict[str, Any]] = []  # История сигналов
        self._max_history_size = 10000  # Максимальный размер истории

        # Статистика по режимам
        self.signals_by_regime: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )  # {regime: {status: count}}

        # Статистика по типам сигналов
        self.signals_by_type: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )  # {signal_type: {status: count}}

        logger.info("✅ ConversionMetrics инициализирован")

    def record_signal_generated(
        self,
        symbol: str,
        signal_type: Optional[str] = None,
        regime: Optional[str] = None,
        strength: Optional[float] = None,
    ) -> None:
        """
        Записать сгенерированный сигнал.

        Args:
            symbol: Торговый символ
            signal_type: Тип сигнала (rsi_oversold, macd_bullish, etc.)
            regime: Режим рынка (trending, ranging, choppy)
            strength: Сила сигнала (0.0-1.0)
        """
        self.signals_generated[symbol] += 1

        if regime:
            self.signals_by_regime[regime]["generated"] += 1

        if signal_type:
            self.signals_by_type[signal_type]["generated"] += 1

        # Сохраняем в историю
        self._signals_history.append(
            {
                "timestamp": datetime.now(),
                "symbol": symbol,
                "signal_type": signal_type,
                "regime": regime,
                "strength": strength,
                "status": "generated",
            }
        )

        # Ограничиваем размер истории
        if len(self._signals_history) > self._max_history_size:
            self._signals_history = self._signals_history[-self._max_history_size :]

    def record_signal_filtered(
        self,
        symbol: str,
        reason: str,
        signal_type: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> None:
        """
        Записать отфильтрованный сигнал.

        Args:
            symbol: Торговый символ
            reason: Причина фильтрации
            signal_type: Тип сигнала
            regime: Режим рынка
        """
        self.signals_filtered[symbol] += 1
        self.filter_reasons[symbol][reason] += 1

        if regime:
            self.signals_by_regime[regime]["filtered"] += 1

        if signal_type:
            self.signals_by_type[signal_type]["filtered"] += 1

        # Обновляем историю
        for signal in reversed(self._signals_history):
            if (
                signal.get("symbol") == symbol
                and signal.get("status") == "generated"
                and signal.get("signal_type") == signal_type
            ):
                signal["status"] = "filtered"
                signal["filter_reason"] = reason
                break

    def record_signal_executed(
        self,
        symbol: str,
        signal_type: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> None:
        """
        Записать исполненный сигнал (открыта позиция).

        Args:
            symbol: Торговый символ
            signal_type: Тип сигнала
            regime: Режим рынка
        """
        self.signals_executed[symbol] += 1

        if regime:
            self.signals_by_regime[regime]["executed"] += 1

        if signal_type:
            self.signals_by_type[signal_type]["executed"] += 1

        # Обновляем историю
        for signal in reversed(self._signals_history):
            if (
                signal.get("symbol") == symbol
                and signal.get("status") in ["generated", "filtered"]
                and signal.get("signal_type") == signal_type
            ):
                signal["status"] = "executed"
                break

    def record_position_closed(
        self,
        symbol: str,
        reason: str,
        pnl: Optional[float] = None,
        signal_type: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> None:
        """
        Записать закрытие позиции.

        ✅ ИСПРАВЛЕНО (05.01.2026): Добавлен метод для записи закрытия позиций.

        Args:
            symbol: Торговый символ
            reason: Причина закрытия (tp, sl, tsl, emergency_loss, etc.)
            pnl: PnL в процентах
            signal_type: Тип сигнала (опционально, для связи с историей)
            regime: Режим рынка (опционально, для статистики)
        """
        # Обновляем статистику по режимам
        if regime:
            if regime not in self.signals_by_regime:
                self.signals_by_regime[regime] = defaultdict(int)
            self.signals_by_regime[regime]["closed"] = (
                self.signals_by_regime[regime].get("closed", 0) + 1
            )

        # Обновляем статистику по типам сигналов
        if signal_type:
            if signal_type not in self.signals_by_type:
                self.signals_by_type[signal_type] = defaultdict(int)
            self.signals_by_type[signal_type]["closed"] = (
                self.signals_by_type[signal_type].get("closed", 0) + 1
            )

        # Обновляем историю - ищем последний executed сигнал для этого символа
        for signal in reversed(self._signals_history):
            if (
                signal.get("symbol") == symbol
                and signal.get("status") == "executed"
                and (not signal_type or signal.get("signal_type") == signal_type)
            ):
                signal["status"] = "closed"
                signal["exit_reason"] = reason
                if pnl is not None:
                    signal["pnl"] = pnl
                break

    def get_conversion_rate(
        self, symbol: Optional[str] = None, period_hours: int = 24
    ) -> Dict[str, float]:
        """
        Получить конверсию сигналов.

        Args:
            symbol: Торговый символ (если None - общая статистика)
            period_hours: Период для расчета (часы)

        Returns:
            Словарь с метриками конверсии:
            {
                "generated": int,
                "filtered": int,
                "executed": int,
                "filter_to_generated": float,  # Конверсия фильтрации
                "executed_to_generated": float,  # Конверсия исполнения
                "executed_to_filtered": float,  # Конверсия после фильтрации
            }
        """
        cutoff_time = datetime.now() - timedelta(hours=period_hours)

        # Фильтруем историю по периоду
        recent_signals = [
            s for s in self._signals_history if s["timestamp"] >= cutoff_time
        ]

        if symbol:
            recent_signals = [s for s in recent_signals if s.get("symbol") == symbol]

        generated = len([s for s in recent_signals if s.get("status") == "generated"])
        filtered = len([s for s in recent_signals if s.get("status") == "filtered"])
        executed = len([s for s in recent_signals if s.get("status") == "executed"])

        filter_to_generated = (filtered / generated * 100) if generated > 0 else 0.0
        executed_to_generated = (executed / generated * 100) if generated > 0 else 0.0
        executed_to_filtered = (
            (executed / (generated - filtered) * 100)
            if (generated - filtered) > 0
            else 0.0
        )

        return {
            "generated": generated,
            "filtered": filtered,
            "executed": executed,
            "filter_to_generated": filter_to_generated,
            "executed_to_generated": executed_to_generated,
            "executed_to_filtered": executed_to_filtered,
        }

    def get_filter_reasons(
        self, symbol: Optional[str] = None, top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Получить топ причин блокировки сигналов.

        Args:
            symbol: Торговый символ (если None - общая статистика)
            top_n: Количество топ причин

        Returns:
            Список словарей с причинами:
            [{"reason": str, "count": int, "percentage": float}, ...]
        """
        if symbol:
            reasons = self.filter_reasons.get(symbol, {})
        else:
            # Объединяем все символы
            reasons = defaultdict(int)
            for symbol_reasons in self.filter_reasons.values():
                for reason, count in symbol_reasons.items():
                    reasons[reason] += count

        total = sum(reasons.values())
        if total == 0:
            return []

        # Сортируем по количеству
        sorted_reasons = sorted(reasons.items(), key=lambda x: x[1], reverse=True)[
            :top_n
        ]

        return [
            {
                "reason": reason,
                "count": count,
                "percentage": (count / total * 100) if total > 0 else 0.0,
            }
            for reason, count in sorted_reasons
        ]

    def get_regime_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить статистику по режимам.

        Returns:
            Словарь {regime: {generated, filtered, executed, conversion_rate}}
        """
        stats = {}
        for regime, counts in self.signals_by_regime.items():
            generated = counts.get("generated", 0)
            filtered = counts.get("filtered", 0)
            executed = counts.get("executed", 0)

            conversion_rate = (executed / generated * 100) if generated > 0 else 0.0

            stats[regime] = {
                "generated": generated,
                "filtered": filtered,
                "executed": executed,
                "conversion_rate": conversion_rate,
            }

        return stats

    def get_signal_type_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить статистику по типам сигналов.

        Returns:
            Словарь {signal_type: {generated, filtered, executed, conversion_rate}}
        """
        stats = {}
        for signal_type, counts in self.signals_by_type.items():
            generated = counts.get("generated", 0)
            filtered = counts.get("filtered", 0)
            executed = counts.get("executed", 0)

            conversion_rate = (executed / generated * 100) if generated > 0 else 0.0

            stats[signal_type] = {
                "generated": generated,
                "filtered": filtered,
                "executed": executed,
                "conversion_rate": conversion_rate,
            }

        return stats

    def get_summary(self, period_hours: int = 24) -> Dict[str, Any]:
        """
        Получить сводку метрик за период.

        Args:
            period_hours: Период для расчета (часы)

        Returns:
            Словарь с полной сводкой метрик
        """
        conversion = self.get_conversion_rate(period_hours=period_hours)
        filter_reasons = self.get_filter_reasons(top_n=5)
        regime_stats = self.get_regime_stats()
        signal_type_stats = self.get_signal_type_stats()

        return {
            "period_hours": period_hours,
            "conversion": conversion,
            "top_filter_reasons": filter_reasons,
            "regime_stats": regime_stats,
            "signal_type_stats": signal_type_stats,
        }

    def log_summary(self, period_hours: int = 24) -> None:
        """
        Логировать сводку метрик.

        Args:
            period_hours: Период для расчета (часы)
        """
        summary = self.get_summary(period_hours=period_hours)

        logger.info(
            f"📊 ConversionMetrics (за {period_hours}ч): "
            f"Сгенерировано={summary['conversion']['generated']}, "
            f"Отфильтровано={summary['conversion']['filtered']}, "
            f"Исполнено={summary['conversion']['executed']}, "
            f"Конверсия={summary['conversion']['executed_to_generated']:.1f}%"
        )

        if summary["top_filter_reasons"]:
            logger.info(
                f"🔍 Топ причины блокировки: "
                + ", ".join(
                    [
                        f"{r['reason']}={r['count']}({r['percentage']:.1f}%)"
                        for r in summary["top_filter_reasons"]
                    ]
                )
            )

    def reset(self) -> None:
        """Сбросить все метрики."""
        self.signals_generated.clear()
        self.signals_filtered.clear()
        self.signals_executed.clear()
        self.filter_reasons.clear()
        self._signals_history.clear()
        self.signals_by_regime.clear()
        self.signals_by_type.clear()
        logger.info("✅ ConversionMetrics: Все метрики сброшены")
