"""
Конфигурация для Order Executor
"""

from pydantic import BaseModel, Field


class OrderExecutorConfig(BaseModel):
    """Конфигурация исполнителя ордеров"""

    # Параметры исполнения
    use_post_only_entry: bool = Field(default=True)
    max_wait_for_fill_sec: int = Field(default=30, ge=5, le=120)
    stp_mode: str = Field(
        default="CancelMaker", description="Self-Trade Prevention mode"
    )
    use_ioc_fallback: bool = Field(default=True)
    use_oso_oco: bool = Field(default=True)
    oso_primary_type: str = Field(
        default="limit", description="Primary order type for OSO-OCO"
    )
    oso_wait_for_trigger: bool = Field(default=True)

    # Параметры размера позиций
    base_position_size: float = Field(default=100.0, ge=1.0, le=10000.0)
    min_position_size: float = Field(default=10.0, ge=1.0, le=1000.0)
    max_position_size: float = Field(default=1000.0, ge=10.0, le=50000.0)

    # Параметры риска
    max_position_percent: float = Field(default=5.0, ge=0.1, le=100.0)
    max_open_positions: int = Field(default=3, ge=1, le=10)
