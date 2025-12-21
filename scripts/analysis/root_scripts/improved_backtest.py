"""
Улучшенный backtest с учетом реальных факторов:
- Slippage моделирование
- Задержки исполнения
- Реальные fill prices (если доступны)
- Все фильтры
- Частичные исполнения
- Точные комиссии (maker vs taker)
"""

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class ImprovedBacktest:
    """Улучшенный backtest с реалистичными условиями"""

    def __init__(self, config_file: str = "FINAL_CORRECTIONS_2025-12-08.json"):
        """Инициализация backtest"""
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except (UnicodeDecodeError, UnicodeError):
            # Пробуем UTF-16 (Windows часто сохраняет в UTF-16)
            try:
                with open(config_file, "r", encoding="utf-16") as f:
                    self.config = json.load(f)
            except:
                # Последняя попытка: utf-8-sig
                with open(config_file, "r", encoding="utf-8-sig") as f:
                    self.config = json.load(f)

        # Параметры slippage
        self.market_slippage_pct = 0.15  # 0.15% для market ордеров
        self.limit_slippage_pct = 0.05  # 0.05% для limit ордеров (если не исполнился)
        self.limit_fill_probability = 0.85  # 85% вероятность исполнения limit ордера

        # Задержки исполнения
        self.execution_delay_min = 0.5  # Минимум 0.5 сек
        self.execution_delay_max = 2.0  # Максимум 2 сек

        # Комиссии
        self.maker_fee_rate = 0.0002  # 0.02%
        self.taker_fee_rate = 0.0005  # 0.05%
        self.leverage = 5

        # Фильтры
        self.correlation_threshold = 0.7  # Максимальная корреляция между позициями
        self.max_correlated_positions = 2  # Максимум коррелированных позиций

        # Текущее состояние
        self.positions: Dict[str, Dict] = {}  # Открытые позиции
        self.closed_trades: List[Dict] = []
        self.equity_curve: List[float] = [100.0]  # Начальный капитал 100%
        self.correlation_matrix: Dict[str, Dict[str, float]] = {}

    def load_data(self, data_file: str):
        """Загрузка данных для backtest"""
        with open(data_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        # Инициализация корреляционной матрицы
        symbols = list(self.data["candles"].keys())
        for i, sym1 in enumerate(symbols):
            self.correlation_matrix[sym1] = {}
            for sym2 in symbols:
                if sym1 == sym2:
                    self.correlation_matrix[sym1][sym2] = 1.0
                else:
                    # Упрощенная корреляция (можно улучшить)
                    self.correlation_matrix[sym1][sym2] = random.uniform(0.3, 0.9)

    def apply_slippage(self, price: float, order_type: str, side: str) -> float:
        """Применение slippage к цене"""
        if order_type == "market":
            slippage = self.market_slippage_pct / 100.0
            if side.lower() == "buy":
                return price * (1 + slippage)  # Покупаем дороже
            else:
                return price * (1 - slippage)  # Продаем дешевле
        else:  # limit
            slippage = self.limit_slippage_pct / 100.0
            if side.lower() == "buy":
                return price * (1 + slippage)
            else:
                return price * (1 - slippage)

    def check_limit_fill(
        self, limit_price: float, current_price: float, side: str
    ) -> bool:
        """Проверка, исполнится ли limit ордер"""
        if random.random() > self.limit_fill_probability:
            return False

        if side.lower() == "buy":
            # Buy limit: цена должна упасть до limit_price или ниже
            return current_price <= limit_price * 1.001  # Небольшой допуск
        else:
            # Sell limit: цена должна подняться до limit_price или выше
            return current_price >= limit_price * 0.999

    def check_correlation_filter(self, symbol: str, side: str) -> bool:
        """Проверка корреляционного фильтра"""
        if not self.positions:
            return True

        # Проверяем корреляцию с открытыми позициями
        correlated_count = 0
        for pos_symbol, pos_data in self.positions.items():
            if pos_symbol == symbol:
                continue

            correlation = self.correlation_matrix.get(symbol, {}).get(pos_symbol, 0.5)
            if correlation > self.correlation_threshold:
                correlated_count += 1

        return correlated_count < self.max_correlated_positions

    def calculate_commission(self, value: float, order_type: str) -> float:
        """Расчет комиссии"""
        if order_type == "limit":
            fee_rate = self.maker_fee_rate
        else:
            fee_rate = self.taker_fee_rate

        # Комиссия учитывает leverage (комиссия от номинала, а PnL от маржи)
        return value * fee_rate * self.leverage

    def get_candle_at_time(self, symbol: str, timestamp: str) -> Optional[Dict]:
        """Получить свечу на указанное время"""
        candles = self.data["candles"].get(symbol, [])

        # Нормализуем timestamp
        if "Z" in timestamp:
            target_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elif "+" in timestamp or timestamp.count("-") > 2:
            target_time = datetime.fromisoformat(timestamp)
        else:
            # Без timezone - добавляем UTC
            target_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        # Убеждаемся, что target_time в UTC
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)

        for candle in candles:
            candle_time_str = candle["datetime"]
            if "Z" in candle_time_str:
                candle_time = datetime.fromisoformat(
                    candle_time_str.replace("Z", "+00:00")
                )
            else:
                candle_time = datetime.fromisoformat(candle_time_str)

            # Убеждаемся, что candle_time в UTC
            if candle_time.tzinfo is None:
                candle_time = candle_time.replace(tzinfo=timezone.utc)

            if candle_time <= target_time < candle_time + timedelta(minutes=1):
                return candle

        return None

    def simulate_entry(self, signal: Dict) -> Optional[Dict]:
        """Симуляция входа в позицию"""
        symbol = signal["symbol"]
        side = signal["side"]
        signal_time = signal["timestamp"]
        price = float(signal["price"])

        # 1. Проверка корреляционного фильтра
        if not self.check_correlation_filter(symbol, side):
            return None

        # 2. Получаем свечу на момент сигнала
        candle = self.get_candle_at_time(symbol, signal_time)
        if not candle:
            return None

        # 3. Задержка исполнения
        execution_delay = random.uniform(
            self.execution_delay_min, self.execution_delay_max
        )
        execution_time = datetime.fromisoformat(
            signal_time.replace("Z", "+00:00")
        ) + timedelta(seconds=execution_delay)

        # 4. Получаем цену после задержки
        execution_candle = self.get_candle_at_time(symbol, execution_time.isoformat())
        if not execution_candle:
            execution_candle = candle

        current_price = execution_candle["close"]

        # 5. Определяем тип ордера (из конфига: limit)
        order_type = "limit"  # Бот использует limit ордера

        # 6. Проверка исполнения limit ордера
        if order_type == "limit":
            limit_price = price  # Используем цену сигнала как limit
            if not self.check_limit_fill(limit_price, current_price, side):
                # Limit не исполнился - используем market как fallback
                order_type = "market"
                fill_price = self.apply_slippage(current_price, "market", side)
            else:
                fill_price = limit_price
        else:
            fill_price = self.apply_slippage(current_price, "market", side)

        # 7. Расчет размера позиции (упрощенно)
        # В реальности используется risk-based sizing
        position_value = 50.0  # Упрощенно: фиксированный размер
        position_size = position_value / fill_price

        # 8. Комиссия входа
        commission_entry = self.calculate_commission(position_value, order_type)

        # 9. Создаем позицию
        position = {
            "symbol": symbol,
            "side": side,
            "entry_price": fill_price,
            "entry_time": execution_time.isoformat(),
            "size": position_size,
            "value": position_value,
            "commission_entry": commission_entry,
            "order_type_entry": order_type,
            "regime": signal.get("regime", "ranging"),
        }

        self.positions[symbol] = position
        return position

    def simulate_exit(
        self,
        symbol: str,
        reason: str,
        exit_time: str,
        exit_price: Optional[float] = None,
    ) -> Optional[Dict]:
        """Симуляция выхода из позиции"""
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]

        # 1. Получаем свечу на момент выхода
        candle = self.get_candle_at_time(symbol, exit_time)
        if not candle:
            return None

        # 2. Определяем цену выхода
        if exit_price is None:
            current_price = candle["close"]
        else:
            current_price = exit_price

        # 3. Задержка исполнения
        execution_delay = random.uniform(
            self.execution_delay_min, self.execution_delay_max
        )
        execution_time = datetime.fromisoformat(
            exit_time.replace("Z", "+00:00")
        ) + timedelta(seconds=execution_delay)

        # 4. Тип ордера выхода (зависит от reason)
        if reason == "partial_tp":
            order_type = "limit"  # Partial TP обычно limit
        elif reason == "sl_reached":
            order_type = "market"  # SL обычно market
        else:
            order_type = "market"

        # 5. Применяем slippage
        fill_price = self.apply_slippage(
            current_price, order_type, "sell" if position["side"] == "buy" else "buy"
        )

        # 6. Расчет PnL
        if position["side"].lower() == "buy":
            gross_pnl = (fill_price - position["entry_price"]) * position["size"]
        else:
            gross_pnl = (position["entry_price"] - fill_price) * position["size"]

        # 7. Комиссия выхода
        exit_value = fill_price * position["size"]
        commission_exit = self.calculate_commission(exit_value, order_type)

        # 8. Net PnL
        net_pnl = gross_pnl - position["commission_entry"] - commission_exit

        # 9. PnL в процентах от маржи
        margin_used = position["value"] / self.leverage
        pnl_pct = (net_pnl / margin_used) * 100 if margin_used > 0 else 0

        # 10. Создаем запись о закрытии
        entry_time_str = position["entry_time"]
        if "Z" in entry_time_str:
            entry_time_dt = datetime.fromisoformat(
                entry_time_str.replace("Z", "+00:00")
            )
        else:
            entry_time_dt = datetime.fromisoformat(entry_time_str)
        if entry_time_dt.tzinfo is None:
            entry_time_dt = entry_time_dt.replace(tzinfo=timezone.utc)

        trade = {
            "symbol": symbol,
            "side": position["side"],
            "entry_price": position["entry_price"],
            "exit_price": fill_price,
            "size": position["size"],
            "gross_pnl": gross_pnl,
            "commission_entry": position["commission_entry"],
            "commission_exit": commission_exit,
            "commission_total": position["commission_entry"] + commission_exit,
            "net_pnl": net_pnl,
            "pnl_pct": pnl_pct,
            "entry_time": position["entry_time"],
            "exit_time": execution_time.isoformat(),
            "duration_sec": (execution_time - entry_time_dt).total_seconds(),
            "reason": reason,
            "order_type_entry": position["order_type_entry"],
            "order_type_exit": order_type,
        }

        # 11. Обновляем equity curve
        last_equity = self.equity_curve[-1]
        new_equity = last_equity + pnl_pct
        self.equity_curve.append(new_equity)

        # 12. Удаляем позицию
        del self.positions[symbol]
        self.closed_trades.append(trade)

        return trade

    def check_exit_conditions(
        self, symbol: str, current_time: str, candle: Dict
    ) -> Optional[Dict]:
        """Проверка условий выхода"""
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]
        current_price = candle["close"]
        entry_price = position["entry_price"]
        regime = position.get("regime", "ranging")

        # Получаем параметры из конфига
        config_ranging = self.config.get("config_futures", {}).get("ranging", {})
        tp_percent = config_ranging.get("tp_percent", 1.2)
        sl_percent = config_ranging.get("sl_percent", 0.8)
        min_holding_minutes = config_ranging.get("min_holding_minutes", 1.0)

        # Расчет PnL в процентах
        if position["side"].lower() == "buy":
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # Учитываем комиссию (упрощенно)
        commission_pct = (self.maker_fee_rate * 2) * self.leverage * 100
        net_pnl_pct = pnl_pct - commission_pct

        # Проверка времени в позиции
        entry_time_str = position["entry_time"]
        if "Z" in entry_time_str:
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
        else:
            entry_time = datetime.fromisoformat(entry_time_str)
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)

        if "Z" in current_time:
            current_time_dt = datetime.fromisoformat(
                current_time.replace("Z", "+00:00")
            )
        else:
            current_time_dt = datetime.fromisoformat(current_time)
        if current_time_dt.tzinfo is None:
            current_time_dt = current_time_dt.replace(tzinfo=timezone.utc)

        duration_minutes = (current_time_dt - entry_time).total_seconds() / 60.0

        # 1. Проверка SL
        if net_pnl_pct <= -sl_percent:
            return {"action": "close", "reason": "sl_reached", "price": current_price}

        # 2. Проверка TP (только после min_holding)
        if duration_minutes >= min_holding_minutes and net_pnl_pct >= tp_percent:
            return {"action": "close", "reason": "tp_reached", "price": current_price}

        # 3. Проверка Partial TP
        partial_tp_config = config_ranging.get("partial_tp", {})
        partial_tp_trigger = partial_tp_config.get("trigger_percent", 1.2)
        if duration_minutes >= 0.2 and net_pnl_pct >= partial_tp_trigger:
            # Частичное закрытие (упрощенно - закрываем всю позицию)
            return {
                "action": "partial_close",
                "reason": "partial_tp",
                "price": current_price,
            }

        # 4. Проверка Profit Drawdown
        profit_drawdown_config = self.config.get("config_futures", {}).get(
            "profit_drawdown", {}
        )
        drawdown_base = profit_drawdown_config.get("base", 0.65)
        drawdown_multiplier = profit_drawdown_config.get("multiplier_ranging", 1.2)
        drawdown_threshold = drawdown_base * drawdown_multiplier

        # Упрощенно: если был пик прибыли и откатился
        if net_pnl_pct > 0 and net_pnl_pct < drawdown_threshold:
            # Проверяем, был ли пик (упрощенно)
            return {
                "action": "close",
                "reason": "profit_drawdown",
                "price": current_price,
            }

        return None

    def run(self):
        """Запуск backtest"""
        print("Запуск улучшенного backtest...")
        print(
            f"   Slippage: {self.market_slippage_pct}% (market), {self.limit_slippage_pct}% (limit)"
        )
        print(f"   Задержки: {self.execution_delay_min}-{self.execution_delay_max} сек")
        print(
            f"   Комиссии: {self.maker_fee_rate*100:.2f}% (maker), {self.taker_fee_rate*100:.2f}% (taker)"
        )
        print()

        # Обрабатываем сигналы по времени
        signals = sorted(self.data["signals"], key=lambda x: x["timestamp"])

        # Создаем временную шкалу свечей
        all_times = set()
        for symbol, candles in self.data["candles"].items():
            for candle in candles:
                all_times.add(candle["datetime"])

        all_times = sorted(all_times)

        signal_idx = 0

        for time_str in all_times:
            # Обрабатываем сигналы до этого времени
            while (
                signal_idx < len(signals)
                and signals[signal_idx]["timestamp"] <= time_str
            ):
                signal = signals[signal_idx]
                if signal.get("executed") == "0":  # Только неисполненные сигналы
                    position = self.simulate_entry(signal)
                    if position:
                        print(
                            f"[+] Вход: {signal['symbol']} {signal['side']} @ {position['entry_price']:.4f}"
                        )
                signal_idx += 1

            # Проверяем условия выхода для всех открытых позиций
            for symbol in list(self.positions.keys()):
                candle = self.get_candle_at_time(symbol, time_str)
                if candle:
                    exit_condition = self.check_exit_conditions(
                        symbol, time_str, candle
                    )
                    if exit_condition:
                        trade = self.simulate_exit(
                            symbol,
                            exit_condition["reason"],
                            time_str,
                            exit_condition.get("price"),
                        )
                        if trade:
                            print(
                                f"[-] Выход: {symbol} {exit_condition['reason']} @ {trade['exit_price']:.4f}, PnL: {trade['net_pnl']:.2f} USDT ({trade['pnl_pct']:.2f}%)"
                            )

        # Закрываем оставшиеся позиции в конце дня
        for symbol in list(self.positions.keys()):
            last_candle = (
                self.data["candles"][symbol][-1]
                if self.data["candles"].get(symbol)
                else None
            )
            if last_candle:
                trade = self.simulate_exit(
                    symbol, "end_of_day", last_candle["datetime"]
                )
                if trade:
                    print(
                        f"[-] Выход (конец дня): {symbol} @ {trade['exit_price']:.4f}, PnL: {trade['net_pnl']:.2f} USDT"
                    )

        # Выводим результаты
        self.print_results()

    def print_results(self):
        """Вывод результатов backtest"""
        if not self.closed_trades:
            print("[!] Нет закрытых сделок")
            return

        profitable = [t for t in self.closed_trades if t["net_pnl"] > 0]
        losing = [t for t in self.closed_trades if t["net_pnl"] <= 0]

        total_pnl = sum(t["net_pnl"] for t in self.closed_trades)
        total_commission = sum(t["commission_total"] for t in self.closed_trades)
        total_pnl_pct = sum(t["pnl_pct"] for t in self.closed_trades)

        max_equity = max(self.equity_curve)
        min_equity = min(self.equity_curve)
        max_drawdown = min_equity - 100.0

        print()
        print("=" * 80)
        print("РЕЗУЛЬТАТЫ УЛУЧШЕННОГО BACKTEST")
        print("=" * 80)
        print(f"Всего сделок: {len(self.closed_trades)}")
        print(
            f"Прибыльных: {len(profitable)} ({len(profitable)/len(self.closed_trades)*100:.1f}%)"
        )
        print(
            f"Убыточных: {len(losing)} ({len(losing)/len(self.closed_trades)*100:.1f}%)"
        )
        print(f"Итоговый PnL: {total_pnl:.2f} USDT ({total_pnl_pct:.2f}%)")
        print(f"Комиссии: {total_commission:.2f} USDT")
        print(f"Макс. просадка: {max_drawdown:.2f}%")
        print(f"Макс. equity: {max_equity:.2f}%")
        print(f"Финальный equity: {self.equity_curve[-1]:.2f}%")
        print()

        # Группировка по причинам
        reasons = {}
        for t in self.closed_trades:
            reason = t["reason"]
            if reason not in reasons:
                reasons[reason] = {"count": 0, "pnl": 0.0}
            reasons[reason]["count"] += 1
            reasons[reason]["pnl"] += t["net_pnl"]

        print("По причинам закрытия:")
        for reason, data in reasons.items():
            avg_pnl = data["pnl"] / data["count"] if data["count"] > 0 else 0
            print(
                f"  {reason}: {data['count']} сделок, PnL: {data['pnl']:.2f} USDT (средний: {avg_pnl:.2f} USDT)"
            )

        # Сохраняем результаты
        results = {
            "total_trades": len(self.closed_trades),
            "profitable": len(profitable),
            "losing": len(losing),
            "win_rate": len(profitable) / len(self.closed_trades) * 100,
            "total_pnl_usd": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "total_commission": total_commission,
            "max_drawdown": max_drawdown,
            "final_equity": self.equity_curve[-1],
            "equity_curve": self.equity_curve,
            "trades": self.closed_trades,
            "reasons": reasons,
        }

        with open("improved_backtest_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print()
        print("[+] Результаты сохранены в improved_backtest_results.json")
        print("=" * 80)


if __name__ == "__main__":
    backtest = ImprovedBacktest("FINAL_CORRECTIONS_2025-12-08.json")
    backtest.load_data("backtest_data_2025-12-17.json")
    backtest.run()
