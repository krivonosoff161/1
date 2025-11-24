"""
Адаптивные системы.

Модули:
- regime_manager: Определение режима рынка (trending/ranging/choppy) (ПЕРЕМЕЩЕН из modules/)
- balance_manager: Определение профиля баланса (small/medium/large) (ПЕРЕМЕЩЕН из balance/)
- parameter_adapter: Объединение и приоритизация параметров
"""

from .balance_manager import AdaptiveBalanceManager
from .parameter_adapter import ParameterAdapter
from .regime_manager import AdaptiveRegimeManager

__all__ = [
    "AdaptiveRegimeManager",
    "AdaptiveBalanceManager",
    "ParameterAdapter",
]

