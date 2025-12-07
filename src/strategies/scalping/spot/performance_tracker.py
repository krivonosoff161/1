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
from typing import Dict

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
        self.positions_open_csv_path = None
        self.orders_csv_path = None
        self.signals_csv_path = None
        self._init_csv()

        logger.info("✅ PerformanceTracker initialized")

    def _init_csv(self):
        """Инициализация CSV файлов для сделок, позиций, ордеров и сигналов"""
        today = datetime.utcnow().strftime("%Y-%m-%d")

        # CSV для закрытых сделок
        self.csv_path = f"logs/trades_{today}.csv"
        self._init_csv_file(
            self.csv_path,
            [
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
            "trades",
        )

        # CSV для открытия позиций
        self.positions_open_csv_path = f"logs/positions_open_{today}.csv"
        self._init_csv_file(
            self.positions_open_csv_path,
            [
                "timestamp",
                "symbol",
                "side",
                "entry_price",
                "size",
                "regime",
                "order_id",
                "order_type",
            ],
            "positions_open",
        )

        # CSV для ордеров
        self.orders_csv_path = f"logs/orders_{today}.csv"
        self._init_csv_file(
            self.orders_csv_path,
            [
                "timestamp",
                "symbol",
                "side",
                "order_type",
                "order_id",
                "size",
                "price",
                "status",
                "fill_price",
                "fill_size",
                "execution_time_ms",
                "slippage",
            ],
            "orders",
        )

        # CSV для сигналов
        self.signals_csv_path = f"logs/signals_{today}.csv"
        self._init_csv_file(
            self.signals_csv_path,
            [
                "timestamp",
                "symbol",
                "side",
                "price",
                "strength",
                "regime",
                "filters_passed",
                "executed",
                "order_id",
            ],
            "signals",
        )

    def _init_csv_file(self, filepath: str, fieldnames: list, file_type: str):
        """Инициализация CSV файла с заголовками"""
        try:
            with open(filepath, "x", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                logger.info(f"📊 Created new {file_type} CSV: {filepath}")
        except FileExistsError:
            logger.debug(f"📊 Using existing {file_type} CSV: {filepath}")

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
            # 🔥 ИСПРАВЛЕНО: PnL теперь считается правильно!
            # Формула: (exit_price - entry_price) * size - commission
            # LONG: (exit - entry) * size
            # SHORT: (entry - exit) * size

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
                        "net_pnl": f"{trade.net_pnl:.4f}",  # ✅ Уже правильный из position_manager!
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

    def update_stats(self, stats: Dict):
        """
        Обновление статистики (заглушка для совместимости).

        Args:
            stats: Словарь со статистикой
        """
        # Статистика уже обновляется в record_trade()
        # Этот метод добавлен для совместимости с futures-версией
        pass

    def record_position_open(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        regime: str,
        order_id: str = None,
        order_type: str = None,
    ) -> None:
        """
        Записать открытие позиции в CSV.

        Args:
            symbol: Торговый символ
            side: Направление (long/short)
            entry_price: Цена входа
            size: Размер позиции
            regime: Режим рынка
            order_id: ID ордера
            order_type: Тип ордера (limit/market)
        """
        try:
            with open(
                self.positions_open_csv_path, "a", newline="", encoding="utf-8"
            ) as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "symbol",
                        "side",
                        "entry_price",
                        "size",
                        "regime",
                        "order_id",
                        "order_type",
                    ],
                )
                writer.writerow(
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "symbol": symbol,
                        "side": side,
                        "entry_price": f"{entry_price:.8f}",
                        "size": f"{size:.8f}",
                        "regime": regime,
                        "order_id": order_id or "",
                        "order_type": order_type or "",
                    }
                )
        except Exception as e:
            logger.error(f"❌ Failed to export position open to CSV: {e}")

    def record_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        order_id: str,
        size: float,
        price: float = None,
        status: str = "placed",
        fill_price: float = None,
        fill_size: float = None,
        execution_time_ms: float = None,
        slippage: float = None,
    ) -> None:
        """
        Записать ордер в CSV.

        Args:
            symbol: Торговый символ
            side: Направление (buy/sell)
            order_type: Тип ордера (limit/market)
            order_id: ID ордера
            size: Размер ордера
            price: Цена ордера (для limit)
            status: Статус (placed/filled/cancelled)
            fill_price: Цена исполнения
            fill_size: Размер исполнения
            execution_time_ms: Время исполнения в мс
            slippage: Проскальзывание в процентах
        """
        try:
            with open(self.orders_csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "symbol",
                        "side",
                        "order_type",
                        "order_id",
                        "size",
                        "price",
                        "status",
                        "fill_price",
                        "fill_size",
                        "execution_time_ms",
                        "slippage",
                    ],
                )
                writer.writerow(
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "symbol": symbol,
                        "side": side,
                        "order_type": order_type,
                        "order_id": order_id or "",
                        "size": f"{size:.8f}",
                        "price": f"{price:.8f}" if price else "",
                        "status": status,
                        "fill_price": f"{fill_price:.8f}" if fill_price else "",
                        "fill_size": f"{fill_size:.8f}" if fill_size else "",
                        "execution_time_ms": f"{execution_time_ms:.2f}"
                        if execution_time_ms
                        else "",
                        "slippage": f"{slippage:.4f}" if slippage else "",
                    }
                )
        except Exception as e:
            logger.error(f"❌ Failed to export order to CSV: {e}")

    def record_signal(
        self,
        symbol: str,
        side: str,
        price: float,
        strength: float,
        regime: str = None,
        filters_passed: list = None,
        executed: bool = False,
        order_id: str = None,
    ) -> None:
        """
        Записать сигнал в CSV.

        Args:
            symbol: Торговый символ
            side: Направление (buy/sell)
            price: Цена сигнала
            strength: Сила сигнала
            regime: Режим рынка
            filters_passed: Список пройденных фильтров
            executed: Был ли сигнал исполнен
            order_id: ID ордера (если исполнен)
        """
        try:
            with open(self.signals_csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "symbol",
                        "side",
                        "price",
                        "strength",
                        "regime",
                        "filters_passed",
                        "executed",
                        "order_id",
                    ],
                )
                writer.writerow(
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "symbol": symbol,
                        "side": side,
                        "price": f"{price:.8f}",
                        "strength": f"{strength:.4f}",
                        "regime": regime or "",
                        "filters_passed": ",".join(filters_passed)
                        if filters_passed
                        else "",
                        "executed": "1" if executed else "0",
                        "order_id": order_id or "",
                    }
                )
        except Exception as e:
            logger.error(f"❌ Failed to export signal to CSV: {e}")
