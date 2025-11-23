"""
Модуль отслеживания статистики торговли для динамической адаптации параметров.

Отслеживает:
- Win rate по режимам
- Средний PnL
- Количество сделок
- Эффективность сигналов
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from loguru import logger


class TradingStatistics:
    """Отслеживание статистики торговли для адаптации параметров"""

    def __init__(self, lookback_hours: int = 24):
        """
        Инициализация модуля статистики

        Args:
            lookback_hours: Количество часов для анализа статистики
        """
        self.lookback_hours = lookback_hours
        self.trades: List[Dict] = []
        self.signals: List[Dict] = []
        # ✅ НОВОЕ: Статистика разворотов
        self.reversals: List[Dict] = []  # Список обнаруженных разворотов

    def record_trade(
        self,
        symbol: str,
        side: str,
        regime: str,
        pnl: float,
        entry_price: float,
        exit_price: float,
        entry_time: datetime,
        exit_time: datetime,
        signal_strength: float = 0.0,
        signal_type: str = "unknown",
    ):
        """
        Запись завершенной сделки

        Args:
            symbol: Торговая пара
            side: Направление (buy/sell)
            regime: Режим рынка (trending/ranging/choppy)
            pnl: Прибыль/убыток
            entry_price: Цена входа
            exit_price: Цена выхода
            entry_time: Время входа
            exit_time: Время выхода
            signal_strength: Сила сигнала (0-1)
            signal_type: Тип сигнала
        """
        trade = {
            "symbol": symbol,
            "side": side,
            "regime": regime.lower(),
            "pnl": pnl,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "signal_strength": signal_strength,
            "signal_type": signal_type,
            "is_win": pnl > 0,
            "duration_minutes": (exit_time - entry_time).total_seconds() / 60.0,
        }
        self.trades.append(trade)

        # Очищаем старые сделки
        cutoff_time = datetime.now() - timedelta(hours=self.lookback_hours)
        self.trades = [t for t in self.trades if t["entry_time"] >= cutoff_time]

    def record_signal(
        self,
        symbol: str,
        side: str,
        regime: str,
        strength: float,
        signal_type: str,
        was_executed: bool = False,
    ):
        """
        Запись сигнала (выполненного или нет)

        Args:
            symbol: Торговая пара
            side: Направление (buy/sell)
            regime: Режим рынка
            strength: Сила сигнала (0-1)
            signal_type: Тип сигнала
            was_executed: Был ли сигнал выполнен
        """
        signal = {
            "symbol": symbol,
            "side": side,
            "regime": regime.lower(),
            "strength": strength,
            "signal_type": signal_type,
            "was_executed": was_executed,
            "timestamp": datetime.now(),
        }
        self.signals.append(signal)

        # Очищаем старые сигналы
        cutoff_time = datetime.now() - timedelta(hours=self.lookback_hours)
        self.signals = [s for s in self.signals if s["timestamp"] >= cutoff_time]

    def record_reversal(
        self,
        symbol: str,
        reversal_type: str,  # "v_down" или "v_up"
        regime: str,
        price_change: float,  # Процент изменения цены
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
    ):
        """
        ✅ НОВОЕ: Запись обнаруженного разворота

        Args:
            symbol: Торговая пара
            reversal_type: Тип разворота ("v_down" или "v_up")
            regime: Режим рынка
            price_change: Процент изменения цены
            max_price: Максимальная цена (для v_down)
            min_price: Минимальная цена (для v_up)
        """
        reversal = {
            "symbol": symbol,
            "reversal_type": reversal_type,
            "regime": regime.lower(),
            "price_change": price_change,
            "max_price": max_price,
            "min_price": min_price,
            "timestamp": datetime.now(),
        }
        self.reversals.append(reversal)

        # Очищаем старые развороты
        cutoff_time = datetime.now() - timedelta(hours=self.lookback_hours)
        self.reversals = [r for r in self.reversals if r["timestamp"] >= cutoff_time]

    def get_reversal_stats(
        self, regime: Optional[str] = None, symbol: Optional[str] = None
    ) -> Dict[str, any]:
        """
        ✅ НОВОЕ: Получить статистику разворотов

        Args:
            regime: Режим рынка (опционально)
            symbol: Торговая пара (опционально)

        Returns:
            Словарь со статистикой разворотов
        """
        if not self.reversals:
            return {
                "total_reversals": 0,
                "v_down_count": 0,
                "v_up_count": 0,
                "avg_price_change": 0.0,
            }

        # Фильтруем по символу и режиму
        filtered_reversals = self.reversals
        if symbol:
            filtered_reversals = [
                r for r in filtered_reversals if r["symbol"] == symbol
            ]
        if regime:
            filtered_reversals = [
                r
                for r in filtered_reversals
                if r["regime"].lower() == regime.lower()
            ]

        if not filtered_reversals:
            return {
                "total_reversals": 0,
                "v_down_count": 0,
                "v_up_count": 0,
                "avg_price_change": 0.0,
            }

        v_down_count = sum(
            1 for r in filtered_reversals if r["reversal_type"] == "v_down"
        )
        v_up_count = sum(
            1 for r in filtered_reversals if r["reversal_type"] == "v_up"
        )
        avg_price_change = (
            sum(r["price_change"] for r in filtered_reversals)
            / len(filtered_reversals)
            if filtered_reversals
            else 0.0
        )

        return {
            "total_reversals": len(filtered_reversals),
            "v_down_count": v_down_count,
            "v_up_count": v_up_count,
            "avg_price_change": avg_price_change,
        }

    def get_win_rate(
        self, regime: Optional[str] = None, symbol: Optional[str] = None
    ) -> float:
        """
        Получить win rate

        Args:
            regime: Режим рынка (опционально). Если None - общий win rate
            symbol: Торговая пара (опционально). Если None - для всех пар

        Returns:
            Win rate (0-1)
        """
        if not self.trades:
            return 0.5  # Fallback: 50% если нет данных

        # Фильтруем по символу и режиму
        filtered_trades = self.trades
        if symbol:
            filtered_trades = [t for t in filtered_trades if t["symbol"] == symbol]
        if regime:
            filtered_trades = [
                t for t in filtered_trades if t["regime"].lower() == regime.lower()
            ]

        if not filtered_trades:
            return 0.5  # Fallback если нет данных

        wins = sum(1 for t in filtered_trades if t["is_win"])
        return wins / len(filtered_trades)

    def get_avg_pnl(
        self, regime: Optional[str] = None, symbol: Optional[str] = None
    ) -> Tuple[float, float]:
        """
        Получить средний PnL (wins и losses отдельно)

        Args:
            regime: Режим рынка (опционально)
            symbol: Торговая пара (опционально)

        Returns:
            Tuple (avg_win, avg_loss)
        """
        if not self.trades:
            return (0.0, 0.0)

        # Фильтруем по символу и режиму
        filtered_trades = self.trades
        if symbol:
            filtered_trades = [t for t in filtered_trades if t["symbol"] == symbol]
        if regime:
            filtered_trades = [
                t for t in filtered_trades if t["regime"].lower() == regime.lower()
            ]
        trades = filtered_trades

        wins = [t["pnl"] for t in trades if t["is_win"]]
        losses = [t["pnl"] for t in trades if not t["is_win"]]

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        return (avg_win, avg_loss)

    def get_trade_count(
        self, regime: Optional[str] = None, symbol: Optional[str] = None
    ) -> int:
        """
        Получить количество сделок

        Args:
            regime: Режим рынка (опционально)
            symbol: Торговая пара (опционально)

        Returns:
            Количество сделок
        """
        filtered_trades = self.trades
        if symbol:
            filtered_trades = [t for t in filtered_trades if t["symbol"] == symbol]
        if regime:
            filtered_trades = [
                t for t in filtered_trades if t["regime"].lower() == regime.lower()
            ]
        return len(filtered_trades)

    def get_signal_execution_rate(self, regime: Optional[str] = None) -> float:
        """
        Получить процент выполнения сигналов

        Args:
            regime: Режим рынка (опционально)

        Returns:
            Процент выполнения (0-1)
        """
        if not self.signals:
            return 0.0

        if regime:
            regime_signals = [
                s for s in self.signals if s["regime"].lower() == regime.lower()
            ]
            if not regime_signals:
                return 0.0
            executed = sum(1 for s in regime_signals if s["was_executed"])
            return executed / len(regime_signals)
        else:
            executed = sum(1 for s in self.signals if s["was_executed"])
            return executed / len(self.signals)

    def get_statistics(
        self, regime: Optional[str] = None, symbol: Optional[str] = None
    ) -> Dict:
        """
        Получить полную статистику

        Args:
            regime: Режим рынка (опционально)
            symbol: Торговая пара (опционально)

        Returns:
            Словарь со статистикой
        """
        win_rate = self.get_win_rate(regime, symbol)
        avg_win, avg_loss = self.get_avg_pnl(regime, symbol)
        trade_count = self.get_trade_count(regime, symbol)
        signal_execution_rate = self.get_signal_execution_rate(regime)

        return {
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "trade_count": trade_count,
            "signal_execution_rate": signal_execution_rate,
            "risk_reward_ratio": (abs(avg_win / avg_loss) if avg_loss != 0 else 0.0),
        }
