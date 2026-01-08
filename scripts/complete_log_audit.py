#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
КОМПЛЕКСНЫЙ АУДИТ ЛОГОВ ТОРГОВОГО БОТА
Анализирует: параметры, передачу данных, логику, риск, лимит-ордера
Дата: 2026-01-08
"""

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


class LogAuditor:
    """Комплексный аудит логов"""

    def __init__(self):
        self.base_path = Path(
            r"c:\Users\krivo\simple trading bot okx\logs\futures\archived"
        )
        self.csv_path = (
            self.base_path / "staging_2026-01-08_08-33-22/all_data_2026-01-07.csv"
        )
        self.error_path = (
            self.base_path / "staging_2026-01-08_08-33-22/errors_2026-01-07.log"
        )

        self.csv_data = []
        self.error_lines = []
        self.report = {}

    def load_data(self):
        """Загружает данные из CSV и логов ошибок"""
        # CSV
        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.csv_data = list(reader)
            print(f"✓ CSV загружен: {len(self.csv_data)} записей")
        except Exception as e:
            print(f"✗ Ошибка CSV: {e}")

        # Ошибки
        try:
            with open(self.error_path, "r", encoding="utf-8") as f:
                self.error_lines = f.readlines()
            print(f"✓ Лог ошибок загружен: {len(self.error_lines)} строк")
        except Exception as e:
            print(f"✗ Ошибка логов: {e}")

    def analyze_limit_orders(self) -> Dict[str, Any]:
        """1. АНАЛИЗ ЛИМИТНЫХ ОРДЕРОВ - почему они далеко от цены"""
        print("\n" + "=" * 80)
        print("1️⃣  АНАЛИЗ ЛИМИТНЫХ ОРДЕРОВ")
        print("=" * 80)

        orders = [d for d in self.csv_data if d.get("record_type") == "orders"]
        positions = [
            d for d in self.csv_data if d.get("record_type") == "positions_open"
        ]
        signals = [d for d in self.csv_data if d.get("record_type") == "signals"]

        analysis = {
            "total_limit_orders": len(orders),
            "details": [],
            "symbols": defaultdict(list),
            "spread_analysis": {},
            "errors": [],
        }

        # Ошибки лимитных ордеров из логов
        limit_errors = [
            e
            for e in self.error_lines
            if "Order price is not within the price limit" in e
        ]
        analysis["limit_order_errors"] = len(limit_errors)

        print(f"Всего лимитных ордеров: {analysis['total_limit_orders']}")
        print(f"Ошибок ограничения цены: {analysis['limit_order_errors']}")

        # Анализ каждого ордера
        for order in orders:
            symbol = order.get("symbol")
            order_id = order.get("order_id")
            price = float(order.get("price", 0))
            side = order.get("side")
            timestamp = order.get("timestamp")

            # Найти сигнал перед ордером
            relevant_signals = [
                s
                for s in signals
                if s.get("symbol") == symbol
                and s.get("timestamp") < timestamp
                and s.get("side") == side
            ]

            signal_price = (
                float(relevant_signals[-1].get("price", 0)) if relevant_signals else 0
            )

            # Найти открытую позицию
            matching_pos = next(
                (
                    p
                    for p in positions
                    if p.get("symbol") == symbol and p.get("order_id") == order_id
                ),
                None,
            )

            if matching_pos:
                entry_price = float(matching_pos.get("entry_price", 0))
                size = float(matching_pos.get("size", 0))

                if signal_price > 0:
                    distance_pct = abs(price - signal_price) / signal_price * 100

                    detail = {
                        "symbol": symbol,
                        "side": side,
                        "signal_price": signal_price,
                        "order_price": price,
                        "entry_price": entry_price,
                        "size": size,
                        "distance_from_signal_pct": distance_pct,
                        "timestamp": timestamp,
                    }
                    analysis["details"].append(detail)
                    analysis["symbols"][symbol].append(detail)

                    # Проблема: расстояние > 1%
                    if distance_pct > 1.0:
                        print(
                            f"⚠️ {symbol} {side}: сигнал {signal_price:.2f} → ордер {price:.2f} ({distance_pct:.3f}%)"
                        )

        self.report["limit_orders"] = analysis
        return analysis

    def analyze_parameter_transmission(self) -> Dict[str, Any]:
        """2. АНАЛИЗ ПЕРЕДАЧИ ПАРАМЕТРОВ между модулями"""
        print("\n" + "=" * 80)
        print("2️⃣  АНАЛИЗ ПЕРЕДАЧИ ПАРАМЕТРОВ МЕЖДУ МОДУЛЯМИ")
        print("=" * 80)

        analysis = {
            "config_errors": [],
            "regime_inconsistencies": [],
            "filter_effectiveness": {},
        }

        # Ошибки конфигурации
        config_errors = [
            e for e in self.error_lines if "КОНФИГУРАЦИИ" in e or "max_position" in e
        ]
        for error in config_errors:
            analysis["config_errors"].append(error.strip()[:150])

        print(f"Ошибок конфигурации: {len(config_errors)}")
        for err in analysis["config_errors"][:3]:
            print(f"  • {err}")

        # Анализ фильтров
        signals = [d for d in self.csv_data if d.get("record_type") == "signals"]

        filter_names = set()
        for sig in signals:
            filters = sig.get("filters_passed", "")
            if filters:
                filter_list = [f.strip() for f in filters.split(",")]
                filter_names.update(filter_list)

        for filter_name in sorted(filter_names):
            passed = sum(
                1 for s in signals if filter_name in s.get("filters_passed", "")
            )
            total = len(signals)
            pct = passed / total * 100 if total > 0 else 0
            analysis["filter_effectiveness"][filter_name] = {
                "passed": passed,
                "total": total,
                "effectiveness_pct": pct,
            }
            print(f"  {filter_name}: {passed}/{total} ({pct:.1f}%)")

        self.report["parameter_transmission"] = analysis
        return analysis

    def analyze_trading_logic(self) -> Dict[str, Any]:
        """3. АНАЛИЗ ТОРГОВОЙ ЛОГИКИ И ПРИНЯТИЯ РЕШЕНИЙ"""
        print("\n" + "=" * 80)
        print("3️⃣  АНАЛИЗ ТОРГОВОЙ ЛОГИКИ И ПРИНЯТИЯ РЕШЕНИЙ")
        print("=" * 80)

        signals = [d for d in self.csv_data if d.get("record_type") == "signals"]
        orders = [d for d in self.csv_data if d.get("record_type") == "orders"]

        analysis = {
            "total_signals": len(signals),
            "signals_executed": len(orders),
            "execution_ratio": 0,
            "by_regime": defaultdict(dict),
            "by_symbol": defaultdict(dict),
            "confidence_analysis": {},
        }

        if len(signals) > 0:
            analysis["execution_ratio"] = len(orders) / len(signals) * 100

        print(f"Всего сигналов: {len(signals)}")
        print(f"Ордеров размещено: {len(orders)}")
        print(f"Ratio исполнения: {analysis['execution_ratio']:.2f}%")

        # По режимам
        regimes = defaultdict(lambda: {"signals": 0, "orders": 0})
        for sig in signals:
            regime = sig.get("regime", "unknown")
            regimes[regime]["signals"] += 1

        for order in orders:
            # Найти соответствующий сигнал
            symbol = order.get("symbol")
            timestamp = order.get("timestamp")
            matching_signal = next(
                (
                    s
                    for s in signals
                    if s.get("symbol") == symbol and s.get("timestamp") <= timestamp
                ),
                None,
            )
            if matching_signal:
                regime = matching_signal.get("regime", "unknown")
                regimes[regime]["orders"] += 1

        print("\nПо режимам:")
        for regime in sorted(regimes.keys()):
            stats = regimes[regime]
            ratio = (
                stats["orders"] / stats["signals"] * 100 if stats["signals"] > 0 else 0
            )
            print(
                f"  {regime}: {stats['signals']} сигналов → {stats['orders']} ордеров ({ratio:.1f}%)"
            )
            analysis["by_regime"][regime] = stats

        # Анализ confidence
        confidences = [
            float(s.get("strength", 0)) for s in signals if s.get("strength")
        ]
        if confidences:
            print(f"\nСредняя confidence: {sum(confidences)/len(confidences):.4f}")
            print(f"Min/Max: {min(confidences):.4f} / {max(confidences):.4f}")
            analysis["confidence_analysis"] = {
                "avg": sum(confidences) / len(confidences),
                "min": min(confidences),
                "max": max(confidences),
            }

        self.report["trading_logic"] = analysis
        return analysis

    def analyze_entry_exit(self) -> Dict[str, Any]:
        """4. АНАЛИЗ ВХОЖДЕНИЯ И ВЫХОДА ИЗ СДЕЛОК"""
        print("\n" + "=" * 80)
        print("4️⃣  АНАЛИЗ ВХОЖДЕНИЯ И ВЫХОДА ИЗ СДЕЛОК")
        print("=" * 80)

        orders = [d for d in self.csv_data if d.get("record_type") == "orders"]
        positions = [
            d for d in self.csv_data if d.get("record_type") == "positions_open"
        ]
        trades = [d for d in self.csv_data if d.get("record_type") == "trades"]

        analysis = {
            "entry_analysis": {
                "total_entries": len(positions),
                "by_symbol": defaultdict(int),
                "entry_price_gaps": [],
            },
            "exit_analysis": {
                "total_exits": len(trades),
                "exit_reasons": Counter(),
                "exit_details": [],
            },
            "pnl_analysis": {
                "profitable": 0,
                "losing": 0,
                "breakeven": 0,
            },
        }

        # Входы
        print(f"Всего входов: {len(positions)}")
        for pos in positions:
            symbol = pos.get("symbol")
            analysis["entry_analysis"]["by_symbol"][symbol] += 1

        for symbol, count in sorted(analysis["entry_analysis"]["by_symbol"].items()):
            print(f"  {symbol}: {count} входов")

        # Выходы
        print(f"\nВсего выходов: {len(trades)}")
        for trade in trades:
            reason = trade.get("reason", "unknown")
            analysis["exit_analysis"]["exit_reasons"][reason] += 1

            pnl = float(trade.get("net_pnl", 0))
            if pnl > 0:
                analysis["pnl_analysis"]["profitable"] += 1
            elif pnl < 0:
                analysis["pnl_analysis"]["losing"] += 1
            else:
                analysis["pnl_analysis"]["breakeven"] += 1

            analysis["exit_analysis"]["exit_details"].append(
                {
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "entry": float(trade.get("entry_price", 0)),
                    "exit": float(trade.get("exit_price", 0)),
                    "pnl": pnl,
                    "reason": reason,
                    "duration": float(trade.get("duration_sec", 0)),
                }
            )

        print(f"Причины выхода:")
        for reason, count in sorted(analysis["exit_analysis"]["exit_reasons"].items()):
            pct = count / len(trades) * 100 if len(trades) > 0 else 0
            print(f"  {reason}: {count} ({pct:.1f}%)")

        print(f"\nРезультаты:")
        print(f"  Прибыльные: {analysis['pnl_analysis']['profitable']}")
        print(f"  Убыточные: {analysis['pnl_analysis']['losing']}")
        print(f"  Breakeven: {analysis['pnl_analysis']['breakeven']}")

        self.report["entry_exit"] = analysis
        return analysis

    def analyze_errors_and_anomalies(self) -> Dict[str, Any]:
        """5. ПОИСК ОШИБОК И АНОМАЛИЙ"""
        print("\n" + "=" * 80)
        print("5️⃣  АНАЛИЗ ОШИБОК И АНОМАЛИЙ")
        print("=" * 80)

        analysis = {
            "total_errors": len(self.error_lines),
            "error_types": Counter(),
            "critical_issues": [],
            "connection_problems": 0,
            "position_close_errors": 0,
            "api_errors": 0,
        }

        for line in self.error_lines:
            if "Cannot connect" in line or "SSL" in line or "timeout" in line.lower():
                analysis["connection_problems"] += 1
                analysis["error_types"]["connection"] += 1

            if "close_position" in line or "NoneType" in line:
                analysis["position_close_errors"] += 1
                analysis["error_types"]["position_close"] += 1
                analysis["critical_issues"].append(line.strip()[:100])

            if "OKX API error" in line or "POST" in line:
                analysis["api_errors"] += 1
                analysis["error_types"]["api"] += 1

        print(f"Всего ошибок: {len(self.error_lines)}")
        print(f"Ошибок подключения: {analysis['connection_problems']}")
        print(f"Ошибок закрытия позиций: {analysis['position_close_errors']}")
        print(f"API ошибок: {analysis['api_errors']}")

        if analysis["critical_issues"]:
            print(f"\n🔴 КРИТИЧЕСКИЕ ПРОБЛЕМЫ:")
            for issue in analysis["critical_issues"][:5]:
                print(f"  • {issue}")

        self.report["errors_anomalies"] = analysis
        return analysis

    def analyze_risk_calculations(self) -> Dict[str, Any]:
        """6. АНАЛИЗ РАСЧЕТОВ РИСКА, ПОЗИЦИЙ, ЛЕВЕРИДЖА"""
        print("\n" + "=" * 80)
        print("6️⃣  АНАЛИЗ РАСЧЕТОВ РИСКА И ПОЗИЦИЙ")
        print("=" * 80)

        positions = [
            d for d in self.csv_data if d.get("record_type") == "positions_open"
        ]
        trades = [d for d in self.csv_data if d.get("record_type") == "trades"]

        analysis = {
            "position_sizing": defaultdict(list),
            "risk_metrics": {},
            "leverage_analysis": defaultdict(dict),
        }

        # Размер позиций
        print(f"Открыто позиций: {len(positions)}")
        for pos in positions:
            symbol = pos.get("symbol")
            size = float(pos.get("size", 0))
            entry_price = float(pos.get("entry_price", 0))

            if size > 0 and entry_price > 0:
                usd_value = size * entry_price
                analysis["position_sizing"][symbol].append(
                    {
                        "size": size,
                        "entry_price": entry_price,
                        "usd_value": usd_value,
                    }
                )

        for symbol in sorted(analysis["position_sizing"].keys()):
            positions_list = analysis["position_sizing"][symbol]
            avg_size = sum(p["size"] for p in positions_list) / len(positions_list)
            avg_usd = sum(p["usd_value"] for p in positions_list) / len(positions_list)
            print(f"  {symbol}: avg size={avg_size:.4f}, avg USD=${avg_usd:.2f}")

        # Риск на сделку
        total_pnl = sum(float(t.get("net_pnl", 0)) for t in trades)
        avg_loss_trade = sum(
            float(t.get("net_pnl", 0)) for t in trades if float(t.get("net_pnl", 0)) < 0
        ) / max(1, len([t for t in trades if float(t.get("net_pnl", 0)) < 0]))

        analysis["risk_metrics"] = {
            "total_pnl": total_pnl,
            "avg_loss_per_losing_trade": avg_loss_trade,
            "trades_analyzed": len(trades),
        }

        print(f"\nРисковые метрики:")
        print(f"  Total PnL: ${total_pnl:.2f}")
        print(f"  Avg loss/losing trade: ${avg_loss_trade:.2f}")

        self.report["risk_calculations"] = analysis
        return analysis

    def generate_final_report(self):
        """Генерирует финальный отчет"""
        print("\n" + "=" * 80)
        print("📝 СОХРАНЕНИЕ ОТЧЕТА")
        print("=" * 80)

        # Сохраняем JSON
        report_path = (
            Path("docs/analysis")
            / f"complete_log_audit_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)

        # Преобразуем Counter в dict
        def convert_to_serializable(obj):
            if isinstance(obj, Counter):
                return dict(obj)
            elif isinstance(obj, defaultdict):
                return dict(obj)
            elif isinstance(obj, set):
                return list(obj)
            return obj

        report_data = {}
        for key, value in self.report.items():
            if isinstance(value, dict):
                report_data[key] = {
                    k: convert_to_serializable(v) for k, v in value.items()
                }
            else:
                report_data[key] = convert_to_serializable(value)

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)

        print(f"✓ Отчет сохранен: {report_path}")
        return report_path

    def run(self):
        """Запуск полного аудита"""
        print("🤖 ЗАПУСК КОМПЛЕКСНОГО АУДИТА ЛОГОВ ТОРГОВОГО БОТА")
        print(f"Дата: {datetime.now().isoformat()}")

        self.load_data()

        if not self.csv_data or not self.error_lines:
            print("❌ Не загружены данные!")
            return

        # Выполнение анализов
        self.analyze_limit_orders()
        self.analyze_parameter_transmission()
        self.analyze_trading_logic()
        self.analyze_entry_exit()
        self.analyze_errors_and_anomalies()
        self.analyze_risk_calculations()

        # Сохранение
        report_path = self.generate_final_report()

        print("\n" + "=" * 80)
        print("✅ АУДИТ ЗАВЕРШЕН")
        print("=" * 80)


if __name__ == "__main__":
    auditor = LogAuditor()
    auditor.run()
