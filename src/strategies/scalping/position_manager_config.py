"""
Конфигурация для Position Manager
"""

from pydantic import BaseModel, Field

class PositionManagerConfig(BaseModel):
    """Конфигурация менеджера позиций"""
    
    # Параметры управления позициями
    max_open_positions: int = Field(default=3, ge=1, le=10)
    max_position_percent: float = Field(default=5.0, ge=0.1, le=100.0)
    
    # Параметры Take Profit и Stop Loss
    take_profit_atr_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    stop_loss_atr_multiplier: float = Field(default=1.5, ge=0.5, le=3.0)
    max_holding_minutes: int = Field(default=15, ge=1, le=60)
    
    # Параметры Profit Harvesting
    ph_enabled: bool = Field(default=True)
    ph_threshold: float = Field(default=0.5, ge=0.1, le=2.0)
    ph_time_limit_minutes: int = Field(default=5, ge=1, le=30)
    
    # Параметры мониторинга
    check_interval_seconds: int = Field(default=10, ge=1, le=60)
    force_close_threshold_minutes: int = Field(default=30, ge=5, le=120)

