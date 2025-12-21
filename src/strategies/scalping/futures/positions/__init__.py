"""
Модули управления позициями.

Модули:
- entry_manager: Открытие позиций
- exit_analyzer: Централизованное управление закрытием позиций
- position_monitor: Периодический мониторинг позиций
- exit_decision_logger: Логирование решений ExitAnalyzer
- peak_profit_tracker: Отслеживание максимальной прибыли
- take_profit_manager: Управление Take Profit
- stop_loss_manager: Управление Stop Loss
"""

from .entry_manager import EntryManager
from .exit_analyzer import ExitAnalyzer
from .exit_decision_logger import ExitDecisionLogger
from .peak_profit_tracker import PeakProfitTracker
from .position_monitor import PositionMonitor
from .stop_loss_manager import StopLossManager
from .take_profit_manager import TakeProfitManager

__all__ = [
    "EntryManager",
    "ExitAnalyzer",
    "PositionMonitor",
    "ExitDecisionLogger",
    "PeakProfitTracker",
    "TakeProfitManager",
    "StopLossManager",
]
