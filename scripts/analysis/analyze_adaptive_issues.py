#!/usr/bin/env python3
"""
Анализ проблем с учетом адаптивной системы бота
Проверяет расчеты с учетом режимов рынка, баланс-профилей и символ-специфичных параметров
"""
import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Добавляем путь к проекту
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.strategies.scalping.futures.config.config_manager import ConfigManager


class AdaptiveIssueAnalyzer:
    def __init__(self):
        self.config = None
        self.config_manager = None
        self.trades = []
        self.issues = []

    def load_config(self):
        """Загрузка конфигурации"""
        try:
            self.config = load_config()
            self.config_manager = ConfigManager(self.config)
            print("✅ Конфигурация загружена")
            return True
        except Exception as e:
            print(f"❌ Ошибка загрузки конфигурации: {e}")
            return False

    def load_trades(self, csv_path: Path):
        """Загрузка сделок из CSV"""
        print(f"\n📊 Загрузка сделок из {csv_path.name}...")
        try:
            df = pd.read_csv(csv_path)
            self.trades = df.to_dict("records")
            print(f"✅ Загружено {len(self.trades)} сделок")
            return True
        except Exception as e:
            print(f"❌ Ошибка загрузки CSV: {e}")
            return False

    def analyze_duration_issues(self):
        """Анализ проблем с duration_sec с учетом адаптивности"""
        print("\n" + "=" * 80)
        print("🔍 АНАЛИЗ ПРОБЛЕМ DURATION_SEC (С УЧЕТОМ АДАПТИВНОСТИ)")
        print("=" * 80)

        issues = []

        for trade in self.trades:
            symbol = trade.get("symbol", "")
            duration_sec = trade.get("duration_sec", 0)
            reason = trade.get("reason", "")
            timestamp = trade.get("timestamp", "")

            # Проблемы с duration
            if duration_sec < 0:
                issues.append(
                    {
                        "type": "negative_duration",
                        "symbol": symbol,
                        "duration_sec": duration_sec,
                        "reason": reason,
                        "timestamp": timestamp,
                        "issue": f"Отрицательный duration: {duration_sec:.2f}s",
                    }
                )
            elif duration_sec == 0:
                issues.append(
                    {
                        "type": "zero_duration",
                        "symbol": symbol,
                        "duration_sec": duration_sec,
                        "reason": reason,
                        "timestamp": timestamp,
                        "issue": f"Нулевой duration: {duration_sec}s",
                    }
                )

        # Группируем по типам
        negative_count = len([i for i in issues if i["type"] == "negative_duration"])
        zero_count = len([i for i in issues if i["type"] == "zero_duration"])

        print(f"\n📊 СТАТИСТИКА:")
        print(
            f"   Отрицательных duration: {negative_count} ({negative_count/len(self.trades)*100:.1f}%)"
        )
        print(
            f"   Нулевых duration: {zero_count} ({zero_count/len(self.trades)*100:.1f}%)"
        )

        # Анализ по символам
        print(f"\n📊 ПО СИМВОЛАМ:")
        symbols = set(i["symbol"] for i in issues)
        for symbol in symbols:
            symbol_issues = [i for i in issues if i["symbol"] == symbol]
            negative = len(
                [i for i in symbol_issues if i["type"] == "negative_duration"]
            )
            zero = len([i for i in symbol_issues if i["type"] == "zero_duration"])
            print(f"   {symbol}: отрицательных={negative}, нулевых={zero}")

        # Анализ по причинам закрытия
        print(f"\n📊 ПО ПРИЧИНАМ ЗАКРЫТИЯ:")
        reasons = set(i["reason"] for i in issues)
        for reason in reasons:
            reason_issues = [i for i in issues if i["reason"] == reason]
            negative = len(
                [i for i in reason_issues if i["type"] == "negative_duration"]
            )
            zero = len([i for i in reason_issues if i["type"] == "zero_duration"])
            print(f"   {reason}: отрицательных={negative}, нулевых={zero}")

        self.issues.extend(issues)
        return issues

    def analyze_max_holding_issues(self):
        """Анализ проблем с max_holding_exceeded с учетом адаптивности"""
        print("\n" + "=" * 80)
        print("🔍 АНАЛИЗ ПРОБЛЕМ MAX_HOLDING_EXCEEDED (С УЧЕТОМ АДАПТИВНОСТИ)")
        print("=" * 80)

        max_holding_trades = [
            t for t in self.trades if t.get("reason") == "max_holding_exceeded"
        ]

        if not max_holding_trades:
            print("✅ Нет сделок с max_holding_exceeded")
            return []

        print(f"\n📊 СТАТИСТИКА:")
        print(f"   Всего сделок max_holding_exceeded: {len(max_holding_trades)}")

        # Анализ по символам
        print(f"\n📊 ПО СИМВОЛАМ:")
        symbols = set(t.get("symbol") for t in max_holding_trades)
        for symbol in symbols:
            symbol_trades = [t for t in max_holding_trades if t.get("symbol") == symbol]
            total_pnl = sum(float(t.get("net_pnl", 0)) for t in symbol_trades)
            avg_pnl = total_pnl / len(symbol_trades) if symbol_trades else 0
            print(
                f"   {symbol}: {len(symbol_trades)} сделок, PnL=${total_pnl:+.2f}, средний=${avg_pnl:+.2f}"
            )

        # Анализ duration для max_holding
        print(f"\n📊 АНАЛИЗ DURATION:")
        durations = [float(t.get("duration_sec", 0)) for t in max_holding_trades]
        if durations:
            avg_duration = sum(durations) / len(durations)
            min_duration = min(durations)
            max_duration = max(durations)
            print(
                f"   Средний duration: {avg_duration:.0f}s ({avg_duration/60:.1f} мин)"
            )
            print(f"   Минимальный: {min_duration:.0f}s ({min_duration/60:.1f} мин)")
            print(f"   Максимальный: {max_duration:.0f}s ({max_duration/60:.1f} мин)")

        # Проверка адаптивных параметров
        print(f"\n📊 ПРОВЕРКА АДАПТИВНЫХ ПАРАМЕТРОВ:")
        try:
            # Получаем параметры для разных режимов
            for regime in ["trending", "ranging", "choppy"]:
                regime_config = getattr(
                    self.config.scalping.adaptive_regime, regime, None
                )
                if regime_config:
                    max_holding = getattr(regime_config, "max_holding_minutes", None)
                    if max_holding:
                        print(f"   {regime}: max_holding_minutes={max_holding}")
        except Exception as e:
            print(f"   ⚠️ Ошибка получения параметров: {e}")

        issues = []
        for trade in max_holding_trades:
            if float(trade.get("net_pnl", 0)) < 0:
                issues.append(
                    {
                        "type": "max_holding_loss",
                        "symbol": trade.get("symbol"),
                        "net_pnl": trade.get("net_pnl"),
                        "duration_sec": trade.get("duration_sec"),
                        "timestamp": trade.get("timestamp"),
                        "issue": f"max_holding_exceeded закрыл убыточную позицию: PnL=${trade.get('net_pnl')}",
                    }
                )

        self.issues.extend(issues)
        return issues

    def analyze_pnl_calculation_issues(self):
        """Анализ проблем расчета PnL с учетом адаптивности"""
        print("\n" + "=" * 80)
        print("🔍 АНАЛИЗ ПРОБЛЕМ РАСЧЕТА PnL (С УЧЕТОМ АДАПТИВНОСТИ)")
        print("=" * 80)

        issues = []

        # Проверяем комиссии
        print(f"\n📊 АНАЛИЗ КОМИССИЙ:")
        total_commission = sum(float(t.get("commission", 0)) for t in self.trades)
        avg_commission = total_commission / len(self.trades) if self.trades else 0
        print(f"   Общие комиссии: ${total_commission:.4f} USDT")
        print(f"   Средняя комиссия: ${avg_commission:.4f} USDT")

        # Проверяем расчет комиссий
        commission_config = getattr(self.config.scalping, "commission", None)
        if commission_config:
            maker_fee = getattr(commission_config, "maker_fee_rate", 0.0002)
            taker_fee = getattr(commission_config, "taker_fee_rate", 0.0005)
            print(f"   Maker fee: {maker_fee*100:.3f}%")
            print(f"   Taker fee: {taker_fee*100:.3f}%")

        # Проверяем PnL
        print(f"\n📊 АНАЛИЗ PnL:")
        total_pnl = sum(float(t.get("net_pnl", 0)) for t in self.trades)
        total_gross_pnl = sum(float(t.get("gross_pnl", 0)) for t in self.trades)
        print(f"   Общий Gross PnL: ${total_gross_pnl:+.4f} USDT")
        print(f"   Общий Net PnL: ${total_pnl:+.4f} USDT")
        print(f"   Разница (комиссии): ${total_gross_pnl - total_pnl:.4f} USDT")

        # Проверяем расчеты для каждой сделки
        for trade in self.trades[:10]:  # Первые 10 для примера
            symbol = trade.get("symbol", "")
            entry_price = float(trade.get("entry_price", 0))
            exit_price = float(trade.get("exit_price", 0))
            size = float(trade.get("size", 0))
            side = trade.get("side", "")
            gross_pnl = float(trade.get("gross_pnl", 0))
            commission = float(trade.get("commission", 0))
            net_pnl = float(trade.get("net_pnl", 0))

            # Пересчитываем gross_pnl
            if side.lower() == "long":
                calculated_gross = (exit_price - entry_price) * size
            else:
                calculated_gross = (entry_price - exit_price) * size

            # Проверяем разницу
            diff = abs(calculated_gross - gross_pnl)
            if diff > 0.01:  # Разница больше 1 цента
                issues.append(
                    {
                        "type": "pnl_calculation_error",
                        "symbol": symbol,
                        "calculated_gross": calculated_gross,
                        "recorded_gross": gross_pnl,
                        "difference": diff,
                        "issue": f"Расхождение в gross_pnl: рассчитано=${calculated_gross:.4f}, записано=${gross_pnl:.4f}",
                    }
                )

        if issues:
            print(f"\n⚠️ Найдено {len(issues)} проблем с расчетом PnL")
        else:
            print(f"\n✅ Проблем с расчетом PnL не найдено")

        self.issues.extend(issues)
        return issues

    def analyze_entry_time_issues(self):
        """Анализ проблем с entry_time"""
        print("\n" + "=" * 80)
        print("🔍 АНАЛИЗ ПРОБЛЕМ ENTRY_TIME")
        print("=" * 80)

        issues = []

        # Анализируем сделки с отрицательным duration
        negative_duration_trades = [
            t for t in self.trades if float(t.get("duration_sec", 0)) < 0
        ]

        print(f"\n📊 СТАТИСТИКА:")
        print(f"   Сделок с отрицательным duration: {len(negative_duration_trades)}")

        # Анализ временных меток
        print(f"\n📊 АНАЛИЗ TIMESTAMP:")
        for trade in negative_duration_trades[:5]:
            timestamp = trade.get("timestamp", "")
            duration = trade.get("duration_sec", 0)
            symbol = trade.get("symbol", "")
            print(f"   {symbol}: timestamp={timestamp}, duration={duration:.0f}s")

            issues.append(
                {
                    "type": "entry_time_issue",
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "duration_sec": duration,
                    "issue": f"Отрицательный duration указывает на проблему с entry_time",
                }
            )

        self.issues.extend(issues)
        return issues

    def generate_report(self):
        """Генерация отчета"""
        print("\n" + "=" * 80)
        print("📋 ИТОГОВЫЙ ОТЧЕТ")
        print("=" * 80)

        print(f"\n📊 ВСЕГО НАЙДЕНО ПРОБЛЕМ: {len(self.issues)}")

        # Группируем по типам
        issue_types = {}
        for issue in self.issues:
            issue_type = issue["type"]
            if issue_type not in issue_types:
                issue_types[issue_type] = []
            issue_types[issue_type].append(issue)

        print(f"\n📊 ПО ТИПАМ:")
        for issue_type, issues_list in issue_types.items():
            print(f"   {issue_type}: {len(issues_list)} проблем")

        # Сохраняем отчет
        report_path = Path("adaptive_issues_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "analysis_date": datetime.now(timezone.utc).isoformat(),
                    "total_trades": len(self.trades),
                    "total_issues": len(self.issues),
                    "issues_by_type": issue_types,
                    "all_issues": self.issues,
                },
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

        print(f"\n✅ Отчет сохранен в {report_path}")

        return report_path


def main():
    csv_path = Path(
        "logs/futures/archived/logs_2025-12-06_15-58-40/trades_2025-12-04.csv"
    )

    if not csv_path.exists():
        print(f"❌ CSV файл не найден: {csv_path}")
        return

    analyzer = AdaptiveIssueAnalyzer()

    # Загрузка конфигурации
    if not analyzer.load_config():
        return

    # Загрузка сделок
    if not analyzer.load_trades(csv_path):
        return

    # Анализ проблем
    analyzer.analyze_duration_issues()
    analyzer.analyze_max_holding_issues()
    analyzer.analyze_pnl_calculation_issues()
    analyzer.analyze_entry_time_issues()

    # Генерация отчета
    analyzer.generate_report()

    print("\n" + "=" * 80)
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print("=" * 80)


if __name__ == "__main__":
    main()
