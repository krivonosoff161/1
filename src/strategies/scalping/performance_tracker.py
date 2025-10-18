"""
Отслеживание производительности торговли.

Ответственность:
- Запись завершенных сделок
- Расчет win rate, PnL, Sharpe ratio
- Экспорт в trades.csv
- Статистика в логи
- История последних 50 сделок
"""

import csv
from collections import deque
from datetime import datetime
from typing import Dict, List

from loguru import logger

from .position_manager import TradeResult


class PerformanceTracker:
    """
    Отслеживание производительности.

    Ведет историю сделок и рассчитывает метрики.
    """

    def __init__(self):
        """Инициализация трекера"""
        # История сделок
        self.trade_history: deque = deque(maxlen=1000)  # Последние 1000 сделок
        self.recent_trades: deque = deque(maxlen=50)  # Последние 50 для логов

        # Статистика
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
        self.start_balance = 0.0

        # Для CSV экспорта
        self.csv_path = None
        self._init_csv()

        logger.info("✅ PerformanceTracker initialized")

    def _init_csv(self):
        """Инициализация CSV файла для сделок"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        self.csv_path = f"logs/trades_{today}.csv"

        # Создаем файл с заголовками если не существует
        try:
            with open(self.csv_path, "x", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "symbol",
                        "side",
                        "entry_price",
                        "exit_price",
                        "size",
                        "gross_pnl",
                        "commission",
                        "net_pnl",
                        "duration_sec",
                        "reason",
                        "win_rate",
                    ],
                )
                writer.writeheader()
                logger.info(f"📊 Created new trades CSV: {self.csv_path}")
        except FileExistsError:
            logger.info(f"📊 Using existing trades CSV: {self.csv_path}")

    def record_trade(self, trade_result: TradeResult):
        """
        Записать завершенную сделку.

        Args:
            trade_result: Результат закрытия сделки
        """
        # Обновляем статистику
        self.total_trades += 1
        if trade_result.net_pnl > 0:
            self.winning_trades += 1

        self.total_pnl += trade_result.net_pnl
        self.daily_pnl += trade_result.net_pnl

        # Добавляем в историю
        self.trade_history.append(trade_result)
        self.recent_trades.append(trade_result)

        # Экспорт в CSV
        self._export_trade_to_csv(trade_result)

        # Логирование
        win_rate = self.calculate_win_rate()

        logger.info(
            f"📊 TRADE RECORDED | "
            f"Total: {self.total_trades} | "
            f"Win Rate: {win_rate:.1f}% | "
            f"Daily PnL: ${self.daily_pnl:.2f}"
        )

    def _export_trade_to_csv(self, trade: TradeResult):
        """
        Экспорт сделки в CSV.

        Args:
            trade: Результат сделки
        """
        try:
            with open(self.csv_path, "a", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "symbol",
                        "side",
                        "entry_price",
                        "exit_price",
                        "size",
                        "gross_pnl",
                        "commission",
                        "net_pnl",
                        "duration_sec",
                        "reason",
                        "win_rate",
                    ],
                )

                writer.writerow(
                    {
                        "timestamp": trade.timestamp.isoformat(),
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "entry_price": f"{trade.entry_price:.4f}",
                        "exit_price": f"{trade.exit_price:.4f}",
                        "size": f"{trade.size:.8f}",
                        "gross_pnl": f"{trade.gross_pnl:.4f}",
                        "commission": f"{trade.commission:.4f}",
                        "net_pnl": f"{trade.net_pnl:.4f}",
                        "duration_sec": trade.duration_sec,
                        "reason": trade.reason,
                        "win_rate": f"{self.calculate_win_rate():.2f}",
                    }
                )

        except Exception as e:
            logger.error(f"❌ Failed to export trade to CSV: {e}")

    def calculate_win_rate(self) -> float:
        """
        Расчет win rate.

        Returns:
            float: Win rate в процентах (0-100)
        """
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100.0

    def get_stats(self) -> Dict:
        """
        Получить полную статистику.

        Returns:
            Dict со всеми метриками
        """
        win_rate = self.calculate_win_rate()

        # Avg win/loss
        wins = [t.net_pnl for t in self.trade_history if t.net_pnl > 0]
        losses = [t.net_pnl for t in self.trade_history if t.net_pnl < 0]

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        # Best/worst
        best_trade = (
            max([t.net_pnl for t in self.trade_history]) if self.trade_history else 0.0
        )
        worst_trade = (
            min([t.net_pnl for t in self.trade_history]) if self.trade_history else 0.0
        )

        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": win_rate,
            "total_pnl": self.total_pnl,
            "daily_pnl": self.daily_pnl,
            "start_balance": self.start_balance,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
        }

    def log_recent_trades(self, count: int = 10):
        """
        Логирование последних N сделок.

        Args:
            count: Количество сделок для вывода
        """
        if not self.recent_trades:
            return

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"📊 LAST {min(count, len(self.recent_trades))} TRADES:")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        for i, trade in enumerate(list(self.recent_trades)[-count:], 1):
            result_emoji = "✅" if trade.net_pnl > 0 else "❌"
            logger.info(
                f"  {i}. {result_emoji} {trade.symbol} {trade.side.upper()} | "
                f"Entry: ${trade.entry_price:.4f} → Exit: ${trade.exit_price:.4f} | "
                f"NET: ${trade.net_pnl:.2f} | Duration: {trade.duration_sec:.0f}s | "
                f"Reason: {trade.reason}"
            )

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def reset_daily_stats(self):
        """Сброс дневной статистики (вызывается в начале нового дня)"""
        self.daily_pnl = 0.0
        logger.info("🔄 Daily stats reset")

    def set_start_balance(self, balance: float):
        """
        Установить стартовый баланс дня.

        Args:
            balance: Баланс в USDT
        """
        self.start_balance = balance
        logger.info(f"💼 Daily start balance set: ${balance:.2f}")
