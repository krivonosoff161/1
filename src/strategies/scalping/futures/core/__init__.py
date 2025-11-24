"""
Core модули - ядро системы управления торговлей.

Модули:
- trading_control_center: Единый центр управления всеми процессами
- data_registry: Единый реестр всех данных (market data, indicators, regimes, balance)
- position_registry: Единый реестр всех позиций (position + metadata)
"""

from .data_registry import DataRegistry
from .position_registry import PositionMetadata, PositionRegistry
from .trading_control_center import TradingControlCenter

__all__ = [
    "DataRegistry",
    "PositionRegistry",
    "PositionMetadata",
    "TradingControlCenter",
]
