"""
Priority Resolver - Резолвер приоритетов для торговых решений.

Обеспечивает единую систему приоритетов для всех торговых операций:
- Закрытие позиций
- Открытие позиций
- Модификация ордеров
- Управление рисками

Предотвращает конфликты приоритетов между различными системами.
"""

from typing import Any, Dict, List, Optional

from loguru import logger


class PriorityResolver:
    """
    Резолвер приоритетов для торговых решений.

    Обеспечивает единую систему приоритетов и разрешает конфликты.
    """

    # Матрица приоритетов для закрытия позиций
    EXIT_PRIORITIES = {
        "emergency_loss_protection": 1,  # Критический убыток
        "sl_reached": 2,  # Stop Loss
        "tp_reached": 3,  # Take Profit
        "trailing_stop": 4,  # Trailing Stop Loss
        "max_holding_time": 5,  # Максимальное время удержания
        "smart_exit_reversal": 6,  # Умное закрытие по развороту
        "smart_exit_pattern": 7,  # Умное закрытие по паттерну
        "partial_tp": 8,  # Частичное закрытие
        "extend_tp": 9,  # Продление TP
    }

    # Матрица приоритетов для открытия позиций
    ENTRY_PRIORITIES = {
        "high_confidence_signal": 1,  # Высокая уверенность
        "medium_confidence_signal": 2,  # Средняя уверенность
        "low_confidence_signal": 3,  # Низкая уверенность
        "scaling_in": 4,  # Добавление к позиции
    }

    # Матрица приоритетов для управления рисками
    RISK_PRIORITIES = {
        "liquidation_risk": 1,  # Риск ликвидации
        "margin_call": 2,  # Margin call
        "max_drawdown": 3,  # Максимальная просадка
        "correlation_limit": 4,  # Лимит корреляции
        "position_limit": 5,  # Лимит позиций
    }

    def __init__(self):
        """Инициализация Priority Resolver."""
        logger.info("✅ PriorityResolver инициализирован")

    def resolve_exit_priority(
        self, decisions: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Разрешает конфликт приоритетов для решений о закрытии.

        Args:
            decisions: Список решений о закрытии от разных систем

        Returns:
            Решение с наивысшим приоритетом или None
        """
        if not decisions:
            return None

        # Сортируем по приоритету
        sorted_decisions = sorted(
            decisions,
            key=lambda d: self._get_exit_priority(d.get("reason", "unknown")),
        )

        best_decision = sorted_decisions[0]
        priority = self._get_exit_priority(best_decision.get("reason", "unknown"))

        # Логируем если было несколько решений
        if len(decisions) > 1:
            logger.debug(
                f"🔍 PriorityResolver: Разрешено {len(decisions)} решений, "
                f"выбрано: {best_decision.get('reason')} (приоритет={priority})"
            )

        return best_decision

    def resolve_entry_priority(
        self, signals: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Разрешает конфликт приоритетов для сигналов на открытие.

        Args:
            signals: Список сигналов от разных систем

        Returns:
            Сигнал с наивысшим приоритетом или None
        """
        if not signals:
            return None

        # Сортируем по приоритету
        sorted_signals = sorted(
            signals,
            key=lambda s: self._get_entry_priority(
                s.get("confidence", "low_confidence_signal")
            ),
        )

        return sorted_signals[0]

    def resolve_risk_priority(
        self, risk_actions: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Разрешает конфликт приоритетов для действий управления рисками.

        Args:
            risk_actions: Список действий управления рисками

        Returns:
            Действие с наивысшим приоритетом или None
        """
        if not risk_actions:
            return None

        # Сортируем по приоритету
        sorted_actions = sorted(
            risk_actions,
            key=lambda a: self._get_risk_priority(a.get("risk_type", "unknown")),
        )

        return sorted_actions[0]

    def _get_exit_priority(self, reason: str) -> int:
        """
        Получить приоритет для причины закрытия.

        Args:
            reason: Причина закрытия

        Returns:
            Приоритет (меньшее число = выше приоритет)
        """
        return self.EXIT_PRIORITIES.get(reason, 99)

    def _get_entry_priority(self, confidence: str) -> int:
        """
        Получить приоритет для сигнала на открытие.

        Args:
            confidence: Уровень уверенности

        Returns:
            Приоритет (меньшее число = выше приоритет)
        """
        return self.ENTRY_PRIORITIES.get(confidence, 99)

    def _get_risk_priority(self, risk_type: str) -> int:
        """
        Получить приоритет для действия управления рисками.

        Args:
            risk_type: Тип риска

        Returns:
            Приоритет (меньшее число = выше приоритет)
        """
        return self.RISK_PRIORITIES.get(risk_type, 99)

    def get_priority_matrix(self, matrix_type: str = "exit") -> Dict[str, int]:
        """
        Получить матрицу приоритетов для отладки.

        Args:
            matrix_type: Тип матрицы ("exit", "entry", "risk")

        Returns:
            Словарь {причина: приоритет}
        """
        if matrix_type == "exit":
            return self.EXIT_PRIORITIES.copy()
        elif matrix_type == "entry":
            return self.ENTRY_PRIORITIES.copy()
        elif matrix_type == "risk":
            return self.RISK_PRIORITIES.copy()
        else:
            logger.warning(f"⚠️ Неизвестный тип матрицы: {matrix_type}")
            return {}

    def compare_priorities(
        self, reason1: str, reason2: str, matrix_type: str = "exit"
    ) -> int:
        """
        Сравнить приоритеты двух причин.

        Args:
            reason1: Первая причина
            reason2: Вторая причина
            matrix_type: Тип матрицы ("exit", "entry", "risk")

        Returns:
            -1 если reason1 имеет более высокий приоритет
            0 если приоритеты равны
            1 если reason2 имеет более высокий приоритет
        """
        if matrix_type == "exit":
            priority1 = self._get_exit_priority(reason1)
            priority2 = self._get_exit_priority(reason2)
        elif matrix_type == "entry":
            priority1 = self._get_entry_priority(reason1)
            priority2 = self._get_entry_priority(reason2)
        elif matrix_type == "risk":
            priority1 = self._get_risk_priority(reason1)
            priority2 = self._get_risk_priority(reason2)
        else:
            return 0

        if priority1 < priority2:
            return -1
        elif priority1 > priority2:
            return 1
        else:
            return 0
