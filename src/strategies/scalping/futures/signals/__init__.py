"""
Модули управления сигналами.

Модули:
- signal_pipeline: Pipeline генерации и валидации сигналов
- filter_manager: Координатор всех фильтров
- signal_validator: Финальная валидация сигналов
"""

from .filter_manager import FilterManager
from .signal_pipeline import SignalPipeline
from .signal_validator import SignalValidator

__all__ = [
    "SignalPipeline",
    "FilterManager",
    "SignalValidator",
]
