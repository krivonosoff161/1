"""
Модульная скальпинг стратегия.

Архитектура:
- spot/ - Spot торговля
- futures/ - Futures торговля
- modules/ - общие модули безопасности

Внешние зависимости:
- src.risk.risk_controller - риск-менеджмент (в общей папке risk/)
"""

from src.risk.risk_controller import RiskController

# Futures модули
from .futures.orchestrator import FuturesScalpingOrchestrator
# Spot модули
from .spot.orchestrator import ScalpingOrchestrator
from .spot.order_executor import OrderExecutor
from .spot.performance_tracker import PerformanceTracker
from .spot.position_manager import PositionManager, TradeResult
from .spot.signal_generator import SignalGenerator

__all__ = [
    # Spot
    "ScalpingOrchestrator",
    "SignalGenerator",
    "OrderExecutor",
    "PositionManager",
    "TradeResult",
    "PerformanceTracker",
    # Futures
    "FuturesScalpingOrchestrator",
    # Общие
    "RiskController",
]
