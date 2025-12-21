"""
Futures-специфичное управление рисками.

Модули:
- adaptive_leverage: Адаптивный леверидж на основе качества сигнала
- liquidation_protector: Защита от ликвидации
- margin_monitor: Мониторинг маржи
- max_size_limiter: Ограничение размера позиций
- position_sizer: Расчет размера позиций
"""

from .adaptive_leverage import AdaptiveLeverage
from .max_size_limiter import MaxSizeLimiter

__all__ = [
    "AdaptiveLeverage",
    "MaxSizeLimiter",
]
