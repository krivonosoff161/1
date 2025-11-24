"""
Модули расчетов.

Модули:
- regime_calculator: Расчет TP/SL для режимов
- balance_calculator: Расчеты по балансу
- margin_calculator: Расчеты маржи (ПЕРЕМЕЩЕН из modules/)
- position_sizer: Расчет размера позиций
- pnl_calculator: Расчет PnL, комиссий, duration
"""

from .balance_calculator import BalanceCalculator
from .margin_calculator import MarginCalculator
from .pnl_calculator import PnLCalculator
from .position_sizer import PositionSizer
from .regime_calculator import RegimeCalculator

__all__ = [
    "RegimeCalculator",
    "BalanceCalculator",
    "MarginCalculator",
    "PositionSizer",
    "PnLCalculator",
]

