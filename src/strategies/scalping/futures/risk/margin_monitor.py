"""
MarginMonitor - мониторинг маржи для Futures торговли.

TODO: Реализовать полную функциональность мониторинга маржи.
"""

from typing import Optional


class MarginMonitor:
    """
    Мониторинг маржи для Futures торговли.
    
    TODO: Реализовать проверку маржи на основе:
    - Текущего баланса
    - Использованной маржи
    - Доступной маржи
    - Уровня маржи (margin ratio)
    """

    def __init__(self, config: Optional[dict] = None):
        """
        Инициализация MarginMonitor.
        
        Args:
            config: Конфигурация мониторинга маржи (опционально)
        """
        self.config = config or {}

    def check_margin_available(
        self, 
        required_margin: float,
        current_balance: float,
        used_margin: float
    ) -> tuple[bool, str]:
        """
        Проверяет доступность маржи для новой позиции.
        
        Args:
            required_margin: Требуемая маржа для новой позиции
            current_balance: Текущий баланс
            used_margin: Уже использованная маржа
            
        Returns:
            (allowed, reason) - можно ли открыть позицию и почему
        """
        available_margin = current_balance - used_margin
        
        if required_margin > available_margin:
            reason = (
                f"Недостаточно маржи: требуется {required_margin:.2f}, "
                f"доступно {available_margin:.2f}"
            )
            return False, reason
        
        reason = (
            f"✅ Маржа доступна: требуется {required_margin:.2f}, "
            f"доступно {available_margin:.2f}"
        )
        return True, reason

    def get_margin_ratio(
        self,
        current_balance: float,
        used_margin: float
    ) -> float:
        """
        Вычисляет коэффициент использования маржи.
        
        Args:
            current_balance: Текущий баланс
            used_margin: Использованная маржа
            
        Returns:
            Коэффициент использования маржи (0.0 - 1.0)
        """
        if current_balance <= 0:
            return 1.0
        
        return min(1.0, used_margin / current_balance)
