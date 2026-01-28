from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParameterStatus:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class SignalParams:
    regime: str
    min_signal_strength: float
    min_signal_strength_ranging: float
    min_adx: float
    min_score_threshold: float
    max_trades_per_hour: int
    position_size_multiplier: float
    indicators: Dict[str, Any] = field(default_factory=dict)
    sources: Dict[str, str] = field(default_factory=dict)


@dataclass
class ExitParams:
    regime: str
    tp_percent: float
    sl_percent: float
    tp_atr_multiplier: float
    sl_atr_multiplier: float
    tp_min_percent: float
    tp_max_percent: Optional[float]
    sl_min_percent: float
    sl_max_percent: Optional[float]
    max_holding_minutes: float
    min_holding_minutes: float
    min_profit_for_extension: float
    extension_percent: float
    ph_threshold_type: Optional[str] = None
    ph_threshold_percent: Optional[float] = None
    ph_min_absolute_usd: Optional[float] = None
    sources: Dict[str, str] = field(default_factory=dict)


@dataclass
class OrderParams:
    regime: str
    limit_offset_percent: float
    max_wait_seconds: float
    auto_cancel_enabled: bool
    auto_replace_enabled: bool
    replace_with_market: bool
    post_only: bool
    adaptive_spread_offset: bool
    sources: Dict[str, str] = field(default_factory=dict)


@dataclass
class RiskParams:
    regime: str
    leverage: float
    position_size_usd: float
    min_position_usd: float
    max_position_usd: float
    max_open_positions: int
    max_position_percent: float
    sources: Dict[str, str] = field(default_factory=dict)


@dataclass
class PatternParams:
    regime: str
    enabled: bool
    timeframe: str
    thresholds: Dict[str, Any] = field(default_factory=dict)
    sources: Dict[str, str] = field(default_factory=dict)


@dataclass
class ParameterBundle:
    status: ParameterStatus
    signal: Optional[SignalParams] = None
    exit: Optional[ExitParams] = None
    order: Optional[OrderParams] = None
    risk: Optional[RiskParams] = None
    patterns: Optional[PatternParams] = None
