"""
Конфигурация для Risk Controller
"""

from pydantic import BaseModel, Field


class RiskControllerConfig(BaseModel):
    """Конфигурация контроллера рисков"""

    # Основные параметры риска
    max_position_size_percent: float = Field(default=5.0, ge=0.1, le=100.0)
    max_daily_loss_percent: float = Field(default=10.0, ge=1.0, le=50.0)
    risk_per_trade_percent: float = Field(default=1.0, ge=0.1, le=10.0)
    max_open_positions: int = Field(default=3, ge=1, le=10)

    # Параметры мониторинга
    check_interval_seconds: int = Field(default=60, ge=10, le=300)
    emergency_stop_threshold: float = Field(default=0.15, ge=0.05, le=0.5)

    # Параметры уведомлений
    enable_notifications: bool = Field(default=True)
    notification_threshold_percent: float = Field(default=0.05, ge=0.01, le=0.2)
