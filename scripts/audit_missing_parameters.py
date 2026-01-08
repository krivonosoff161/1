#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ недостающих и пустых параметров в логах
Поиск None, N/A, пропущенных параметров MTF и др.
"""

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


class ParameterAuditor:
    """Аудит параметров в логах"""

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
        self.issues = []

    def load_data(self):
        """Загружает данные"""
        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.csv_data = list(reader)
            print(f"✓ CSV загружен: {len(self.csv_data)} записей")
        except Exception as e:
            print(f"✗ Ошибка CSV: {e}")

        try:
            with open(self.error_path, "r", encoding="utf-8") as f:
                self.error_lines = f.readlines()
            print(f"✓ Лог ошибок загружен: {len(self.error_lines)} строк")
        except Exception as e:
            print(f"✗ Ошибка логов: {e}")

    def analyze_positions_with_missing_params(self):
        """Анализирует позиции с недостающими параметрами"""
        print("\n" + "=" * 80)
        print("🔍 ПОИСК ПОЗИЦИЙ С НЕДОСТАЮЩИМИ ПАРАМЕТРАМИ")
        print("=" * 80)

        positions = [
            d for d in self.csv_data if d.get("record_type") == "positions_open"
        ]

        # Ключевые параметры, которые должны быть в позиции
        required_params = [
            "symbol",
            "side",
            "entry_price",
            "size",
            "regime",
            "order_id",
            "timestamp",
        ]

        missing_count = 0
        empty_params = defaultdict(int)

        print(f"\nВсего открытых позиций: {len(positions)}")
        print(f"Требуемые параметры: {required_params}\n")

        for i, pos in enumerate(positions):
            issues_in_pos = []

            for param in required_params:
                value = pos.get(param)

                # Проверка на None/N/A/пусто
                if value is None or value == "" or value == "N/A" or value == "None":
                    issues_in_pos.append(param)
                    empty_params[param] += 1

            if issues_in_pos:
                missing_count += 1
                timestamp = pos.get("timestamp")
                symbol = pos.get("symbol")

                issue = {
                    "position_index": i,
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "missing_params": issues_in_pos,
                    "full_record": pos,
                }
                self.issues.append(issue)

                print(f"⚠️  Позиция #{i} ({symbol}) {timestamp}:")
                print(f"    Недостающие: {', '.join(issues_in_pos)}")
                for param in issues_in_pos:
                    print(f"      • {param}: {repr(pos.get(param))}")

        print(
            f"\n📊 Итого позиций с проблемами: {missing_count}/{len(positions)} ({missing_count/len(positions)*100:.1f}%)"
        )

        if empty_params:
            print(f"\nПараметры с пропусками:")
            for param, count in sorted(
                empty_params.items(), key=lambda x: x[1], reverse=True
            ):
                pct = count / len(positions) * 100
                print(f"  {param}: {count} ({pct:.1f}%)")

        return missing_count, empty_params

    def analyze_mtf_parameter(self):
        """Анализирует MTF параметр в сигналах и позициях"""
        print("\n" + "=" * 80)
        print("🔍 АНАЛИЗ MTF ПАРАМЕТРА")
        print("=" * 80)

        signals = [d for d in self.csv_data if d.get("record_type") == "signals"]
        positions = [
            d for d in self.csv_data if d.get("record_type") == "positions_open"
        ]

        # Проверка MTF в фильтрах
        mtf_issues = {
            "missing": 0,
            "empty": 0,
            "signals_with_mtf": 0,
            "signals_without_mtf": [],
        }

        print(f"\nВсего сигналов: {len(signals)}")
        print(f"Всего позиций: {len(positions)}\n")

        print("Поиск MTF в фильтрах сигналов...")
        for sig in signals:
            filters = sig.get("filters_passed", "")
            if "MTF" not in filters:
                mtf_issues["signals_without_mtf"].append(
                    {
                        "timestamp": sig.get("timestamp"),
                        "symbol": sig.get("symbol"),
                        "filters": filters,
                    }
                )

        print(f"Сигналов БЕЗ MTF в фильтрах: {len(mtf_issues['signals_without_mtf'])}")
        if mtf_issues["signals_without_mtf"][:3]:
            print("Примеры:")
            for sig in mtf_issues["signals_without_mtf"][:3]:
                print(f"  • {sig['timestamp']} {sig['symbol']}: {sig['filters']}")

        # Проверка MTF в других полях
        print("\nПоиск MTF-related параметров в других полях CSV...")

        # Посмотрим какие поля есть в CSV
        if positions:
            print("\nПоля в позициях:")
            for key in sorted(positions[0].keys())[:15]:
                print(f"  • {key}")

    def analyze_none_and_na_values(self):
        """Анализирует None и N/A значения во всех записях"""
        print("\n" + "=" * 80)
        print("🔍 АНАЛИЗ ПУСТЫХ ЗНАЧЕНИЙ (None, N/A, пусто)")
        print("=" * 80)

        none_stats = defaultdict(lambda: {"count": 0, "records": []})

        for record_type in ["signals", "orders", "positions_open", "trades"]:
            records = [d for d in self.csv_data if d.get("record_type") == record_type]

            print(f"\n{record_type.upper()}: {len(records)} записей")

            for i, record in enumerate(records):
                for field, value in record.items():
                    if value == "" or value == "None" or value == "N/A":
                        key = f"{record_type}::{field}"
                        none_stats[key]["count"] += 1
                        if len(none_stats[key]["records"]) < 2:  # Сохраняем примеры
                            none_stats[key]["records"].append(
                                {
                                    "timestamp": record.get("timestamp"),
                                    "index": i,
                                }
                            )

        # Вывод результатов
        if none_stats:
            print("\n📊 Поля с пустыми значениями:")
            for key in sorted(
                none_stats.keys(), key=lambda x: none_stats[x]["count"], reverse=True
            )[:20]:
                count = none_stats[key]["count"]
                pct = count / len(self.csv_data) * 100
                record_type, field = key.split("::")
                print(f"  {field} ({record_type}): {count} ({pct:.2f}%)")
                # Показать примеры
                for ex in none_stats[key]["records"][:1]:
                    print(f"    └─ Пример: {ex['timestamp']}")
        else:
            print("✓ Явных пустых значений не найдено")

    def search_error_log_for_parameter_issues(self):
        """Ищет в логах ошибок проблемы с параметрами"""
        print("\n" + "=" * 80)
        print("🔍 ПОИСК В ЛОГАХ ОШИБОК: ПРОБЛЕМЫ С ПАРАМЕТРАМИ")
        print("=" * 80)

        patterns = [
            (r"NoneType|None parameter|param.*None", "None параметр"),
            (r"KeyError|missing key", "Недостающий ключ"),
            (r"MTF|mtf", "MTF параметры"),
            (r"parameter.*not found|undefined param", "Параметр не найден"),
            (r"ValueError.*param|invalid.*param", "Неверное значение параметра"),
            (r"has no attribute", "Отсутствует атрибут"),
            (r"IndexError|index out", "Ошибка индекса"),
        ]

        results = defaultdict(list)

        for i, line in enumerate(self.error_lines):
            for pattern, description in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    results[description].append(
                        {
                            "line_num": i,
                            "content": line.strip()[:150],
                        }
                    )

        print(f"\nВсего строк в логе ошибок: {len(self.error_lines)}\n")

        for description in sorted(results.keys()):
            issues = results[description]
            print(f"🔴 {description}: {len(issues)} occurrences")

            # Показать уникальные примеры
            unique = {}
            for issue in issues[:3]:
                content = issue["content"]
                if content not in unique:
                    unique[content] = issue["line_num"]

            for content, line_num in sorted(unique.items()):
                print(f"    Строка {line_num}: {content}")

    def check_filter_params_transmission(self):
        """Проверяет передачу параметров фильтра от сигналов к позициям"""
        print("\n" + "=" * 80)
        print("🔍 ПРОВЕРКА ПЕРЕДАЧИ ПАРАМЕТРОВ ФИЛЬТРОВ")
        print("=" * 80)

        signals = [d for d in self.csv_data if d.get("record_type") == "signals"]
        positions = [
            d for d in self.csv_data if d.get("record_type") == "positions_open"
        ]

        print(f"\nВсего сигналов: {len(signals)}")
        print(f"Всего позиций: {len(positions)}\n")

        # Для каждой позиции найти соответствующий сигнал
        param_mismatches = []

        for pos in positions[:20]:  # Первые 20 позиций для анализа
            symbol = pos.get("symbol")
            timestamp = pos.get("timestamp")
            order_id = pos.get("order_id")
            regime = pos.get("regime")

            # Найти сигнал с тем же символом и временем до открытия позиции
            matching_signal = None
            for sig in signals:
                if (
                    sig.get("symbol") == symbol
                    and sig.get("timestamp") <= timestamp
                    and sig.get("order_id") == order_id
                ):
                    matching_signal = sig
                    break

            if matching_signal:
                # Сравнить параметры
                sig_filters = matching_signal.get("filters_passed", "")
                sig_regime = matching_signal.get("regime", "")
                sig_strength = matching_signal.get("strength", "")

                pos_regime = pos.get("regime", "")

                if sig_regime != pos_regime:
                    param_mismatches.append(
                        {
                            "symbol": symbol,
                            "timestamp": timestamp,
                            "signal_regime": sig_regime,
                            "position_regime": pos_regime,
                            "type": "regime_mismatch",
                        }
                    )

                if not sig_filters or sig_filters == "":
                    param_mismatches.append(
                        {
                            "symbol": symbol,
                            "timestamp": timestamp,
                            "filters": "EMPTY",
                            "type": "empty_filters",
                        }
                    )
            else:
                # Сигнал не найден
                param_mismatches.append(
                    {
                        "symbol": symbol,
                        "timestamp": timestamp,
                        "type": "signal_not_found",
                    }
                )

        if param_mismatches:
            print(f"🔴 Найдено несоответствий в параметрах: {len(param_mismatches)}\n")

            # Группировать по типу
            by_type = defaultdict(list)
            for mismatch in param_mismatches:
                by_type[mismatch["type"]].append(mismatch)

            for mtype, items in by_type.items():
                print(f"{mtype}: {len(items)}")
                for item in items[:2]:
                    print(f"  • {item['symbol']} {item['timestamp']}")
        else:
            print("✓ Несоответствий параметров не найдено")

    def generate_detailed_report(self):
        """Генерирует подробный отчет"""
        print("\n" + "=" * 80)
        print("📝 ГЕНЕРАЦИЯ ПОДРОБНОГО ОТЧЕТА")
        print("=" * 80)

        report = {
            "timestamp": datetime.now().isoformat(),
            "total_issues_found": len(self.issues),
            "issues": self.issues[:100],  # Первые 100 проблем
            "analysis_summary": {
                "total_csv_records": len(self.csv_data),
                "total_error_lines": len(self.error_lines),
            },
        }

        report_path = Path("docs/analysis/missing_parameters_audit_2026-01-08.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        print(f"✓ Подробный отчет: {report_path}")

    def run(self):
        """Запуск полного анализа"""
        print("🤖 АНАЛИЗ НЕДОСТАЮЩИХ И ПУСТЫХ ПАРАМЕТРОВ")
        print(f"Дата: {datetime.now().isoformat()}\n")

        self.load_data()

        if not self.csv_data:
            print("❌ Не загружены данные!")
            return

        self.analyze_positions_with_missing_params()
        self.analyze_mtf_parameter()
        self.analyze_none_and_na_values()
        self.search_error_log_for_parameter_issues()
        self.check_filter_params_transmission()
        self.generate_detailed_report()

        print("\n" + "=" * 80)
        print("✅ АНАЛИЗ ЗАВЕРШЕН")
        print("=" * 80)


if __name__ == "__main__":
    auditor = ParameterAuditor()
    auditor.run()
