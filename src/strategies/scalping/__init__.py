"""
Модульная скальпинг стратегия.

Архитектура:
- orchestrator.py - главный координатор
- signal_generator.py - генерация сигналов + scoring
- order_executor.py - исполнение ордеров
- position_manager.py - управление позициями
- performance_tracker.py - статистика и экспорт

Внешние зависимости:
- src.risk.risk_controller - риск-менеджмент (в общей папке risk/)
"""

from src.risk.risk_controller import RiskController

from .orchestrator import ScalpingOrchestrator
from .order_executor import OrderExecutor
from .performance_tracker import PerformanceTracker
from .position_manager import PositionManager, TradeResult
from .signal_generator import SignalGenerator

__all__ = [
    "ScalpingOrchestrator",
    "SignalGenerator",
    "OrderExecutor",
    "PositionManager",
    "TradeResult",
    "RiskController",
    "PerformanceTracker",
]
