"""
Data models for trading operations
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Tick:
    """Market data tick"""

    timestamp: datetime
    symbol: str
    price: float
    volume: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None


@dataclass
class OHLCV:
    """OHLCV candlestick data"""

    timestamp: int
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str = "1m"


@dataclass
class Order:
    """Trading order"""

    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    amount: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_amount: float = 0.0
    average_fill_price: float = 0.0
    commission: float = 0.0
    timestamp: datetime = None
    strategy_id: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.id is None:
            self.id = str(uuid.uuid4())


@dataclass
class Position:
    """Trading position"""

    id: str
    symbol: str
    side: PositionSide
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    timestamp: datetime = None
    strategy_id: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    algo_order_id: Optional[str] = None  # ID OCO ордера для отслеживания

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.id is None:
            self.id = str(uuid.uuid4())

    @property
    def market_value(self) -> float:
        """Current market value of position"""
        return self.size * self.current_price

    def update_price(self, new_price: float):
        """Update current price and calculate PnL"""
        self.current_price = new_price
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (new_price - self.entry_price) * self.size
        else:
            self.unrealized_pnl = (self.entry_price - new_price) * self.size


@dataclass
class Trade:
    """Completed trade"""

    id: str
    symbol: str
    side: OrderSide
    amount: float
    price: float
    commission: float
    timestamp: datetime
    order_id: str
    strategy_id: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.id is None:
            self.id = str(uuid.uuid4())


@dataclass
class Balance:
    """Account balance"""

    currency: str
    free: float
    used: float
    total: float
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class Signal:
    """Trading signal from strategy"""

    symbol: str
    side: OrderSide
    strength: float  # Signal strength (0.0 to 1.0)
    price: float
    timestamp: datetime
    strategy_id: str
    indicators: Dict[str, Any] = None
    confidence: float = 0.0

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.indicators is None:
            self.indicators = {}


@dataclass
class MarketData:
    """Market data container"""

    symbol: str
    timeframe: str
    ohlcv_data: List[OHLCV]
    current_tick: Optional[Tick] = None

    def get_closes(self) -> List[float]:
        """Get closing prices"""
        return [candle.close for candle in self.ohlcv_data]

    def get_highs(self) -> List[float]:
        """Get high prices"""
        return [candle.high for candle in self.ohlcv_data]

    def get_lows(self) -> List[float]:
        """Get low prices"""
        return [candle.low for candle in self.ohlcv_data]

    def get_volumes(self) -> List[float]:
        """Get volumes"""
        return [candle.volume for candle in self.ohlcv_data]


@dataclass
class StrategyState:
    """Current state of trading strategy"""

    strategy_id: str
    symbol: str
    active: bool = True
    last_signal_time: Optional[datetime] = None
    open_positions: int = 0
    daily_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    current_drawdown: float = 0.0
    max_drawdown: float = 0.0

    @property
    def win_rate(self) -> float:
        """Calculate win rate percentage"""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100.0


@dataclass
class RiskMetrics:
    """Risk management metrics"""

    account_balance: float
    total_exposure: float
    daily_pnl: float
    max_daily_loss: float
    position_count: int
    max_positions: int
    risk_per_trade: float

    @property
    def exposure_ratio(self) -> float:
        """Total exposure as percentage of balance"""
        if self.account_balance == 0:
            return 0.0
        return (self.total_exposure / self.account_balance) * 100.0

    @property
    def daily_loss_ratio(self) -> float:
        """Daily loss as percentage of balance"""
        if self.account_balance == 0:
            return 0.0
        return abs(min(0, self.daily_pnl) / self.account_balance) * 100.0

    def can_open_position(self, position_size: float) -> bool:
        """Check if new position can be opened"""
        if self.position_count >= self.max_positions:
            return False
        if self.daily_loss_ratio >= (self.max_daily_loss / self.account_balance * 100):
            return False
        new_exposure = self.total_exposure + position_size
        if new_exposure > self.account_balance * 0.5:  # Max 50% exposure
            return False
        return True
