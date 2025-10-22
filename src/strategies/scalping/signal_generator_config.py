"""
Конфигурация для Signal Generator
"""

from pydantic import BaseModel, Field


class SignalGeneratorConfig(BaseModel):
    """Конфигурация генератора сигналов"""

    # Основные параметры
    min_score_threshold: float = Field(default=4.0, ge=1.0, le=10.0)
    max_trades_per_hour: int = Field(default=10, ge=1, le=50)
    cooldown_after_trade_seconds: int = Field(default=300, ge=60, le=3600)

    # Параметры сигналов
    min_volatility_atr: float = Field(default=0.0005, ge=0.0001, le=0.01)
    rsi_overbought: int = Field(default=70, ge=60, le=90)
    rsi_oversold: int = Field(default=30, ge=10, le=40)
    volume_threshold: float = Field(default=1.2, ge=1.0, le=3.0)

    # Параметры выхода
    take_profit_atr_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    stop_loss_atr_multiplier: float = Field(default=1.5, ge=0.5, le=3.0)
    max_holding_minutes: int = Field(default=15, ge=1, le=60)
