"""
Core модули - ядро системы управления торговлей.

Модули:
- candle_buffer: Циклический буфер для хранения свечей
- data_registry: Единый реестр всех данных (market data, indicators, regimes, balance)
- position_registry: Единый реестр всех позиций (position + metadata)
- position_sync: Синхронизация позиций с биржей
"""

from .candle_buffer import CandleBuffer
from .data_registry import DataRegistry
from .position_registry import PositionMetadata, PositionRegistry
from .position_sync import PositionSync

__all__ = [
    "CandleBuffer",
    "DataRegistry",
    "PositionRegistry",
    "PositionMetadata",
    "PositionSync",
]
