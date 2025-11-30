#!/usr/bin/env python3
"""
Автоматический мониторинг работы ExitAnalyzer.

Анализирует логи в реальном времени и выявляет проблемы:
- Правильность расчета PnL%
- Достижение TP/big_profit_exit/partial_tp
- Проблемы с закрытием позиций
"""

import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import loguru


class ExitAnalyzerMonitor:
    """Мониторинг работы ExitAnalyzer"""

    def __init__(self, log_file: str):
        self.log_file = Path(log_file)
        self.last_position = 0
        self.positions_data: Dict[str, Dict] = defaultdict(dict)
        self.issues: List[Dict] = []

    def parse_log_line(self, line: str) -> Optional[Dict]:
        """Парсит строку лога ExitAnalyzer"""
        # Паттерн для детального логирования
        pattern = r"ExitAnalyzer RANGING (\w+-\w+): entry_price=([0-9.]+), current_price=([0-9.]+), side=(\w+), PnL%=([0-9.-]+)%, entry_time=(.+)"
        match = re.search(pattern, line)
        if match:
            (
                symbol,
                entry_price,
                current_price,
                side,
                pnl_pct,
                entry_time,
            ) = match.groups()
            return {
                "symbol": symbol,
                "entry_price": float(entry_price),
                "current_price": float(current_price),
                "side": side,
                "pnl_pct": float(pnl_pct),
                "entry_time": entry_time,
                "timestamp": line.split("|")[0].strip() if "|" in line else None,
            }
        return None

    def parse_tp_check(self, line: str) -> Optional[Dict]:
        """Парсит проверку TP"""
        pattern = r"ExitAnalyzer RANGING (\w+-\w+): TP=([0-9.]+)%, PnL%=([0-9.-]+)%, достигнут=(True|False)"
        match = re.search(pattern, line)
        if match:
            symbol, tp, pnl_pct, reached = match.groups()
            return {
                "symbol": symbol,
                "tp": float(tp),
                "pnl_pct": float(pnl_pct),
                "reached": reached == "True",
            }
        return None

    def parse_partial_tp_check(self, line: str) -> Optional[Dict]:
        """Парсит проверку partial_tp"""
        pattern = r"ExitAnalyzer RANGING (\w+-\w+): partial_tp trigger=([0-9.]+)%, PnL%=([0-9.-]+)%, достигнут=(True|False)"
        match = re.search(pattern, line)
        if match:
            symbol, trigger, pnl_pct, reached = match.groups()
            return {
                "symbol": symbol,
                "trigger": float(trigger),
                "pnl_pct": float(pnl_pct),
                "reached": reached == "True",
            }
        return None

    def calculate_expected_pnl(
        self, entry_price: float, current_price: float, side: str
    ) -> float:
        """Рассчитывает ожидаемый PnL%"""
        if entry_price == 0:
            return 0.0

        if side.lower() == "long":
            gross_pnl = (current_price - entry_price) / entry_price
        else:  # short
            gross_pnl = (entry_price - current_price) / entry_price

        return gross_pnl * 100  # В процентах

    def analyze(self) -> Dict:
        """Анализирует логи и выявляет проблемы"""
        if not self.log_file.exists():
            return {"error": f"Log file not found: {self.log_file}"}

        with open(self.log_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            # Читаем только новые строки
            new_lines = lines[self.last_position :]
            self.last_position = len(lines)

        results = {
            "positions": {},
            "issues": [],
            "statistics": {
                "total_checks": 0,
                "tp_reached": 0,
                "partial_tp_reached": 0,
                "big_profit_reached": 0,
                "closes": 0,
            },
        }

        for line in new_lines:
            # Парсим детальное логирование
            pos_data = self.parse_log_line(line)
            if pos_data:
                symbol = pos_data["symbol"]
                self.positions_data[symbol] = pos_data

                # Проверяем правильность расчета PnL%
                expected_pnl = self.calculate_expected_pnl(
                    pos_data["entry_price"], pos_data["current_price"], pos_data["side"]
                )
                actual_pnl = pos_data["pnl_pct"]

                # Разница > 0.01% считается проблемой
                if abs(expected_pnl - actual_pnl) > 0.01:
                    results["issues"].append(
                        {
                            "type": "pnl_calculation_error",
                            "symbol": symbol,
                            "expected_pnl": expected_pnl,
                            "actual_pnl": actual_pnl,
                            "difference": abs(expected_pnl - actual_pnl),
                            "timestamp": pos_data.get("timestamp"),
                        }
                    )

            # Парсим проверку TP
            tp_data = self.parse_tp_check(line)
            if tp_data:
                results["statistics"]["total_checks"] += 1
                symbol = tp_data["symbol"]

                if tp_data["reached"]:
                    results["statistics"]["tp_reached"] += 1
                    # Проверяем, было ли закрытие
                    if "TP достигнут" not in line and "Закрываем" not in line:
                        results["issues"].append(
                            {
                                "type": "tp_not_closed",
                                "symbol": symbol,
                                "tp": tp_data["tp"],
                                "pnl_pct": tp_data["pnl_pct"],
                                "timestamp": line.split("|")[0].strip()
                                if "|" in line
                                else None,
                            }
                        )

            # Парсим проверку partial_tp
            partial_tp_data = self.parse_partial_tp_check(line)
            if partial_tp_data:
                if partial_tp_data["reached"]:
                    results["statistics"]["partial_tp_reached"] += 1
                    # Проверяем, было ли частичное закрытие
                    if "Частичное закрытие" not in line:
                        results["issues"].append(
                            {
                                "type": "partial_tp_not_closed",
                                "symbol": partial_tp_data["symbol"],
                                "trigger": partial_tp_data["trigger"],
                                "pnl_pct": partial_tp_data["pnl_pct"],
                                "timestamp": line.split("|")[0].strip()
                                if "|" in line
                                else None,
                            }
                        )

            # Ищем закрытия
            if (
                "ExitAnalyzer: Закрываем" in line
                or "ExitAnalyzer решение.*close" in line
            ):
                results["statistics"]["closes"] += 1

        # Формируем сводку по позициям
        for symbol, data in self.positions_data.items():
            results["positions"][symbol] = {
                "entry_price": data["entry_price"],
                "current_price": data["current_price"],
                "pnl_pct": data["pnl_pct"],
                "side": data["side"],
                "entry_time": data.get("entry_time"),
            }

        return results

    def print_report(self, results: Dict):
        """Выводит отчет"""
        print(f"\n{'='*60}")
        print(
            f"📊 ОТЧЕТ ExitAnalyzer Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"{'='*60}\n")

        # Статистика
        stats = results.get("statistics", {})
        print(f"📈 Статистика:")
        print(f"   Всего проверок: {stats.get('total_checks', 0)}")
        print(f"   TP достигнут: {stats.get('tp_reached', 0)}")
        print(f"   Partial TP достигнут: {stats.get('partial_tp_reached', 0)}")
        print(f"   Big Profit достигнут: {stats.get('big_profit_reached', 0)}")
        print(f"   Закрытий: {stats.get('closes', 0)}")
        print()

        # Позиции
        positions = results.get("positions", {})
        if positions:
            print(f"📋 Активные позиции ({len(positions)}):")
            for symbol, data in positions.items():
                print(f"   {symbol}:")
                print(
                    f"      Entry: ${data['entry_price']:.2f}, Current: ${data['current_price']:.2f}"
                )
                print(f"      PnL%: {data['pnl_pct']:.2f}%, Side: {data['side']}")
                print()
        else:
            print("📋 Активных позиций не найдено\n")

        # Проблемы
        issues = results.get("issues", [])
        if issues:
            print(f"⚠️  ПРОБЛЕМЫ ({len(issues)}):")
            for issue in issues:
                print(f"   [{issue['type']}] {issue.get('symbol', 'unknown')}: {issue}")
            print()
        else:
            print("✅ Проблем не обнаружено\n")

        print(f"{'='*60}\n")


def main():
    """Главная функция"""
    import sys

    # Путь к лог-файлу
    log_file = (
        Path(__file__).parent.parent
        / "logs"
        / "futures"
        / "futures_main_2025-11-30.log"
    )

    if len(sys.argv) > 1:
        log_file = Path(sys.argv[1])

    monitor = ExitAnalyzerMonitor(str(log_file))

    print("🔍 ExitAnalyzer Monitor запущен...")
    print(f"📁 Лог-файл: {log_file}")
    print("Нажмите Ctrl+C для остановки\n")

    try:
        while True:
            results = monitor.analyze()
            if "error" not in results:
                monitor.print_report(results)
            time.sleep(10)  # Проверка каждые 10 секунд
    except KeyboardInterrupt:
        print("\n\n👋 Мониторинг остановлен")


if __name__ == "__main__":
    main()
