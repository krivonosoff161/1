"""
Alert Manager - Менеджер алертов на критические события.

Отслеживает и уведомляет о:
- Низкой конверсии сигналов
- Высокой частоте Emergency Close
- Аномальном времени удержания
- Критических ошибках
- Превышении лимитов
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class AlertManager:
    """
    Менеджер алертов на критические события.

    Отслеживает метрики и генерирует алерты при превышении порогов.
    """

    # Пороги для алертов
    ALERT_THRESHOLDS = {
        "low_conversion_rate": 5.0,  # Конверсия < 5%
        "high_emergency_close_rate": 50.0,  # Emergency Close > 50%
        "short_holding_time": 30.0,  # Среднее время удержания < 30 сек
        "zero_signals_per_day": True,  # 0 сигналов за день
        "high_filter_rate": 90.0,  # Фильтрация > 90%
    }

    def __init__(
        self,
        conversion_metrics=None,  # ConversionMetrics (опционально)
        holding_time_metrics=None,  # HoldingTimeMetrics (опционально)
    ):
        """
        Инициализация Alert Manager.

        Args:
            conversion_metrics: ConversionMetrics для отслеживания конверсии
            holding_time_metrics: HoldingTimeMetrics для отслеживания времени удержания
        """
        self.conversion_metrics = conversion_metrics
        self.holding_time_metrics = holding_time_metrics

        # История алертов
        self._alert_history: List[Dict[str, Any]] = []
        self._max_history_size = 1000

        # Счетчики алертов
        self._alert_counts: Dict[str, int] = defaultdict(int)

        # Callbacks для уведомлений
        self._alert_callbacks: List[Callable[[Dict[str, Any]], None]] = []

        logger.info("✅ AlertManager инициализирован")

    def register_alert_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """
        Зарегистрировать callback для уведомлений об алертах.

        Args:
            callback: Функция, которая будет вызвана при алерте
                     Принимает словарь с данными алерта
        """
        self._alert_callbacks.append(callback)
        logger.debug(f"✅ AlertManager: Зарегистрирован callback для алертов")

    def check_alerts(self, period_hours: int = 24) -> List[Dict[str, Any]]:
        """
        Проверить метрики и сгенерировать алерты.

        Args:
            period_hours: Период для проверки (часы)

        Returns:
            Список алертов
        """
        alerts = []

        # Проверка конверсии сигналов
        if self.conversion_metrics:
            conversion = self.conversion_metrics.get_conversion_rate(
                period_hours=period_hours
            )

            # Низкая конверсия
            if (
                conversion["executed_to_generated"]
                < self.ALERT_THRESHOLDS["low_conversion_rate"]
                and conversion["generated"] > 10
            ):
                alert = self._create_alert(
                    "low_conversion_rate",
                    f"Низкая конверсия сигналов: {conversion['executed_to_generated']:.1f}% "
                    f"(сгенерировано={conversion['generated']}, исполнено={conversion['executed']})",
                    {
                        "conversion_rate": conversion["executed_to_generated"],
                        "generated": conversion["generated"],
                        "executed": conversion["executed"],
                    },
                )
                alerts.append(alert)

            # 0 сигналов за день
            if (
                self.ALERT_THRESHOLDS["zero_signals_per_day"]
                and conversion["generated"] == 0
                and period_hours >= 24
            ):
                alert = self._create_alert(
                    "zero_signals_per_day",
                    "⚠️ КРИТИЧНО: 0 сигналов сгенерировано за последние 24 часа!",
                    {"period_hours": period_hours},
                )
                alerts.append(alert)

            # Высокая фильтрация
            if (
                conversion["filter_to_generated"]
                > self.ALERT_THRESHOLDS["high_filter_rate"]
                and conversion["generated"] > 10
            ):
                alert = self._create_alert(
                    "high_filter_rate",
                    f"Высокая фильтрация сигналов: {conversion['filter_to_generated']:.1f}% "
                    f"(сгенерировано={conversion['generated']}, отфильтровано={conversion['filtered']})",
                    {
                        "filter_rate": conversion["filter_to_generated"],
                        "generated": conversion["generated"],
                        "filtered": conversion["filtered"],
                    },
                )
                alerts.append(alert)

        # Проверка времени удержания
        if self.holding_time_metrics:
            holding_stats = self.holding_time_metrics.get_holding_time_stats(
                period_hours=period_hours
            )

            # Слишком короткое время удержания
            if (
                holding_stats["average"] > 0
                and holding_stats["average"]
                < self.ALERT_THRESHOLDS["short_holding_time"]
                and holding_stats["count"] > 5
            ):
                alert = self._create_alert(
                    "short_holding_time",
                    f"Слишком короткое время удержания: {holding_stats['average']:.1f}с "
                    f"(позиций={holding_stats['count']})",
                    {
                        "average_seconds": holding_stats["average"],
                        "count": holding_stats["count"],
                    },
                )
                alerts.append(alert)

        # Обрабатываем алерты
        for alert in alerts:
            self._process_alert(alert)

        return alerts

    def check_emergency_close_rate(
        self, exit_reason_counts: Dict[str, int], period_hours: int = 24
    ) -> Optional[Dict[str, Any]]:
        """
        Проверить частоту Emergency Close.

        Args:
            exit_reason_counts: Словарь {exit_reason: count}
            period_hours: Период для проверки (часы)

        Returns:
            Алерт если частота превышает порог, иначе None
        """
        total_closes = sum(exit_reason_counts.values())
        if total_closes == 0:
            return None

        emergency_closes = exit_reason_counts.get("emergency_loss_protection", 0)
        emergency_rate = (emergency_closes / total_closes) * 100

        if emergency_rate > self.ALERT_THRESHOLDS["high_emergency_close_rate"]:
            return self._create_alert(
                "high_emergency_close_rate",
                f"⚠️ КРИТИЧНО: Высокая частота Emergency Close: {emergency_rate:.1f}% "
                f"(Emergency={emergency_closes}, Всего={total_closes})",
                {
                    "emergency_rate": emergency_rate,
                    "emergency_count": emergency_closes,
                    "total_count": total_closes,
                },
            )

        return None

    def _create_alert(
        self, alert_type: str, message: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Создать алерт.

        Args:
            alert_type: Тип алерта
            message: Сообщение алерта
            data: Дополнительные данные

        Returns:
            Словарь с данными алерта
        """
        alert = {
            "type": alert_type,
            "message": message,
            "timestamp": datetime.now(),
            "data": data,
            "severity": self._get_severity(alert_type),
        }

        return alert

    def _get_severity(self, alert_type: str) -> str:
        """
        Получить уровень серьезности алерта.

        Args:
            alert_type: Тип алерта

        Returns:
            "critical", "warning" или "info"
        """
        critical_alerts = [
            "zero_signals_per_day",
            "high_emergency_close_rate",
        ]

        if alert_type in critical_alerts:
            return "critical"
        elif "high" in alert_type or "low" in alert_type:
            return "warning"
        else:
            return "info"

    def _process_alert(self, alert: Dict[str, Any]) -> None:
        """
        Обработать алерт (логирование и callbacks).

        Args:
            alert: Данные алерта
        """
        # Логируем алерт
        severity = alert.get("severity", "info")
        if severity == "critical":
            logger.error(f"🚨 КРИТИЧЕСКИЙ АЛЕРТ: {alert['message']}")
        elif severity == "warning":
            logger.warning(f"⚠️ АЛЕРТ: {alert['message']}")
        else:
            logger.info(f"ℹ️ АЛЕРТ: {alert['message']}")

        # Сохраняем в историю
        self._alert_history.append(alert)
        self._alert_counts[alert["type"]] += 1

        # Ограничиваем размер истории
        if len(self._alert_history) > self._max_history_size:
            self._alert_history = self._alert_history[-self._max_history_size :]

        # Вызываем callbacks
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(
                    f"❌ AlertManager: Ошибка в callback для алерта {alert['type']}: {e}"
                )

    def get_alert_history(
        self,
        alert_type: Optional[str] = None,
        period_hours: int = 24,
        severity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Получить историю алертов.

        Args:
            alert_type: Тип алерта (если None - все типы)
            period_hours: Период для фильтрации (часы)
            severity: Уровень серьезности (если None - все уровни)

        Returns:
            Список алертов
        """
        cutoff_time = datetime.now() - timedelta(hours=period_hours)

        filtered = [
            a
            for a in self._alert_history
            if a["timestamp"] >= cutoff_time
            and (alert_type is None or a["type"] == alert_type)
            and (severity is None or a.get("severity") == severity)
        ]

        return sorted(filtered, key=lambda x: x["timestamp"], reverse=True)

    def get_alert_summary(self, period_hours: int = 24) -> Dict[str, Any]:
        """
        Получить сводку алертов за период.

        Args:
            period_hours: Период для расчета (часы)

        Returns:
            Словарь со сводкой
        """
        alerts = self.get_alert_history(period_hours=period_hours)

        by_type = defaultdict(int)
        by_severity = defaultdict(int)

        for alert in alerts:
            by_type[alert["type"]] += 1
            by_severity[alert.get("severity", "info")] += 1

        return {
            "period_hours": period_hours,
            "total_alerts": len(alerts),
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
            "recent_alerts": alerts[:10],  # Последние 10 алертов
        }

    def reset(self) -> None:
        """Сбросить все метрики."""
        self._alert_history.clear()
        self._alert_counts.clear()
        logger.info("✅ AlertManager: Все метрики сброшены")
