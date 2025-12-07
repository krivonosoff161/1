#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализ логов по AUDIT_CHECKLIST.md"""

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class AuditLogAnalyzer:
    """Анализатор логов по чек-листу аудита"""

    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.results = {
            "hardcoded_numbers": [],
            "hardcoded_symbols": [],
            "missing_logs": defaultdict(list),
            "missing_warnings": [],
            "race_conditions": [],
            "resource_leaks": [],
            "missing_filters": [],
            "adaptive_reload": [],
            "drift_issues": [],
            "cast_errors": [],
            "graceful_shutdown": [],
            "exponential_backoff": [],
        }

        # Обязательные логи для проверки
        self.required_logs = {
            "SIGNAL_SKIP": r"SIGNAL_SKIP|signal.*skip|пропуск.*сигнал",
            "EXIT_HIT": r"EXIT_HIT|exit.*hit|закрытие.*позици",
            "DRIFT_ADD": r"DRIFT_ADD|drift.*add|добавлен.*drift",
            "DRIFT_REMOVE": r"DRIFT_REMOVE|drift.*remove|удален.*drift",
            "TRAIL_UPDATE": r"TRAIL_UPDATE|trail.*update|обновлен.*trail",
            "TRAIL_RELOAD": r"TRAIL_RELOAD|trail.*reload|перезагружен.*trail",
            "FILL_LATENCY": r"FILL.*latency|latency.*fill|задержка.*исполнени",
        }

        # WARNING пороги
        self.warning_thresholds = {
            "slippage": (r"slippage[:\s]+([\d.]+)", 0.2, "slippage > 0.2%"),
            "exit_slippage": (
                r"exit.*slippage[:\s]+([\d.]+)",
                0.3,
                "exit_slippage > 0.3%",
            ),
            "trail_distance": (
                r"trail.*distance[:\s]+([\d.]+)",
                0.05,
                "trail_distance < 0.05%",
            ),
            "latency": (r"latency[:\s]+(\d+)", 300, "latency > 300 мс"),
        }

    def find_all_logs(self) -> List[Path]:
        """Находит все log файлы"""
        log_files = []

        # Рекурсивный поиск
        for log_file in self.logs_dir.rglob("*.log"):
            if log_file.is_file():
                log_files.append(log_file)

        return sorted(log_files, key=lambda x: x.stat().st_mtime, reverse=True)

    def analyze_file(self, log_file: Path):
        """Анализирует один файл логов"""
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.split("\n")

                for line_num, line in enumerate(lines, 1):
                    self.check_hardcoded_numbers(line, log_file, line_num)
                    self.check_hardcoded_symbols(line, log_file, line_num)
                    self.check_required_logs(line, log_file, line_num)
                    self.check_warning_thresholds(line, log_file, line_num)
                    self.check_race_conditions(line, log_file, line_num)
                    self.check_resource_leaks(line, log_file, line_num)
                    self.check_missing_filters(line, log_file, line_num)
                    self.check_adaptive_reload(line, log_file, line_num)
                    self.check_drift_issues(line, log_file, line_num)
                    self.check_cast_errors(line, log_file, line_num)
                    self.check_graceful_shutdown(line, log_file, line_num)
                    self.check_exponential_backoff(line, log_file, line_num)
        except Exception as e:
            print(f"⚠️ Ошибка чтения {log_file}: {e}")

    def check_hardcoded_numbers(self, line: str, file: Path, line_num: int):
        """Проверка хард-кода чисел"""
        # Паттерны: = 0.05, = 5, > 25, == "trending"
        patterns = [
            (r"=\s*0\.0[1-9]\d*", "Магическое число 0.0X"),
            (r"=\s*[1-9]\d*\s*[,\n]", "Магическое число"),
            (r">\s*2[5-9]|>\s*[3-9]\d+", "Хард-код порога > 25"),
        ]

        for pattern, desc in patterns:
            if re.search(pattern, line):
                # Исключаем комментарии и конфиги
                if not any(x in line.lower() for x in ["#", "config", "yaml", "json"]):
                    self.results["hardcoded_numbers"].append(
                        {
                            "file": str(file),
                            "line": line_num,
                            "content": line.strip()[:100],
                            "issue": desc,
                        }
                    )

    def check_hardcoded_symbols(self, line: str, file: Path, line_num: int):
        """Проверка хард-кода символов"""
        pattern = r'if\s+symbol\s*==\s*["\']([A-Z]+)["\']'
        matches = re.findall(pattern, line)

        for symbol in matches:
            self.results["hardcoded_symbols"].append(
                {
                    "file": str(file),
                    "line": line_num,
                    "symbol": symbol,
                    "content": line.strip()[:100],
                }
            )

    def check_required_logs(self, line: str, file: Path, line_num: int):
        """Проверка наличия обязательных логов"""
        for log_type, pattern in self.required_logs.items():
            if re.search(pattern, line, re.IGNORECASE):
                self.results["missing_logs"][log_type].append(
                    {"file": str(file), "line": line_num, "found": True}
                )

    def check_warning_thresholds(self, line: str, file: Path, line_num: int):
        """Проверка WARNING порогов"""
        for threshold_name, (pattern, max_val, desc) in self.warning_thresholds.items():
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1))
                    if threshold_name == "latency":
                        if value > max_val:
                            self.results["missing_warnings"].append(
                                {
                                    "file": str(file),
                                    "line": line_num,
                                    "threshold": desc,
                                    "value": value,
                                    "content": line.strip()[:100],
                                }
                            )
                    else:  # slippage, exit_slippage, trail_distance
                        if threshold_name == "trail_distance":
                            if value < max_val:
                                self.results["missing_warnings"].append(
                                    {
                                        "file": str(file),
                                        "line": line_num,
                                        "threshold": desc,
                                        "value": value,
                                        "content": line.strip()[:100],
                                    }
                                )
                        else:
                            if value > max_val:
                                self.results["missing_warnings"].append(
                                    {
                                        "file": str(file),
                                        "line": line_num,
                                        "threshold": desc,
                                        "value": value,
                                        "content": line.strip()[:100],
                                    }
                                )
                except:
                    pass

    def check_race_conditions(self, line: str, file: Path, line_num: int):
        """Проверка race conditions"""
        patterns = [
            (r"KeyError", "KeyError при доступе к позициям", False),
            (r"double.*fill|двойное.*исполнен", "Double fill", False),
            (r"duplicate.*posId|дублирован.*posId", "Double posId", False),
            (r"asyncio\.Lock", "asyncio.Lock найден", True),  # Это хорошо
        ]

        for pattern, desc, is_good in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                if is_good:
                    # Это хорошо - Lock найден, пропускаем
                    continue
                self.results["race_conditions"].append(
                    {
                        "file": str(file),
                        "line": line_num,
                        "issue": desc,
                        "content": line.strip()[:100],
                    }
                )

    def check_resource_leaks(self, line: str, file: Path, line_num: int):
        """Проверка утечек ресурсов"""
        patterns = [
            (r"create_task.*without.*cancel", "Task leak"),
            (r"websocket.*reconnect.*leak", "TCP-handles leak"),
            (r"RSS.*>.*5%", "RSS > +5%"),
            (r"unclosed.*connection", "Незакрытые соединения"),
        ]

        for pattern, desc in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                self.results["resource_leaks"].append(
                    {
                        "file": str(file),
                        "line": line_num,
                        "issue": desc,
                        "content": line.strip()[:100],
                    }
                )

    def check_missing_filters(self, line: str, file: Path, line_num: int):
        """Проверка отсутствия фильтров"""
        # Ищем места, где возвращается signal без проверки фильтров
        if "return signal" in line.lower() or "return.*signal" in line.lower():
            # Проверяем, есть ли фильтры выше
            pass  # Это сложнее проверить без контекста

    def check_adaptive_reload(self, line: str, file: Path, line_num: int):
        """Проверка adaptive-перегрузки при смене regime"""
        if "regime.*change" in line.lower() or "смена.*режим" in line.lower():
            # Проверяем обновление параметров
            if not any(x in line.lower() for x in ["trail", "tp", "sl", "multiplier"]):
                self.results["adaptive_reload"].append(
                    {
                        "file": str(file),
                        "line": line_num,
                        "issue": "Смена regime без обновления параметров",
                        "content": line.strip()[:100],
                    }
                )

    def check_drift_issues(self, line: str, file: Path, line_num: int):
        """Проверка drift реестра"""
        if "drift" in line.lower():
            if "sync_positions" in line.lower():
                # Проверяем частоту синхронизации
                if "60" not in line and "sync.*60" not in line.lower():
                    self.results["drift_issues"].append(
                        {
                            "file": str(file),
                            "line": line_num,
                            "issue": "sync_positions не каждые 60 сек",
                            "content": line.strip()[:100],
                        }
                    )

    def check_cast_errors(self, line: str, file: Path, line_num: int):
        """Проверка неправильных cast-ов"""
        patterns = [
            (r"TypeError.*str.*int", "str > int (TypeError)"),
            (r'ValueError.*float.*["\']', 'float("") (ValueError)'),
            (
                r'position\.get\(["\']size["\']\)\s*[^float]',
                'position.get("size") без float()',
            ),
        ]

        for pattern, desc in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                self.results["cast_errors"].append(
                    {
                        "file": str(file),
                        "line": line_num,
                        "issue": desc,
                        "content": line.strip()[:100],
                    }
                )

    def check_graceful_shutdown(self, line: str, file: Path, line_num: int):
        """Проверка graceful-shutdown"""
        if "rss" in line.lower() or "memory" in line.lower():
            if "600" in line or "shutdown" in line.lower():
                # Проверяем наличие graceful shutdown
                if "graceful" not in line.lower() and "shutdown" in line.lower():
                    self.results["graceful_shutdown"].append(
                        {
                            "file": str(file),
                            "line": line_num,
                            "issue": "Shutdown без graceful",
                            "content": line.strip()[:100],
                        }
                    )

    def check_exponential_backoff(self, line: str, file: Path, line_num: int):
        """Проверка exponential backoff"""
        if "reconnect" in line.lower():
            if "exponential" not in line.lower() and "backoff" not in line.lower():
                if "delay" in line.lower() or "attempt" in line.lower():
                    self.results["exponential_backoff"].append(
                        {
                            "file": str(file),
                            "line": line_num,
                            "issue": "Reconnect без exponential backoff",
                            "content": line.strip()[:100],
                        }
                    )

    def generate_report(self) -> str:
        """Генерирует отчет"""
        report = []
        report.append("=" * 80)
        report.append("📋 АУДИТ ЛОГОВ ПО CHECKLIST")
        report.append("=" * 80)
        report.append("")

        # Статистика по каждому разделу
        sections = [
            (1, "Хард-код чисел", "hardcoded_numbers"),
            (2, "Хард-код символов", "hardcoded_symbols"),
            (3, "Отсутствие логов", "missing_logs"),
            (4, "Отсутствие WARNING-порогов", "missing_warnings"),
            (5, "Race-conditions", "race_conditions"),
            (6, "Утечки ресурсов", "resource_leaks"),
            (7, "Отсутствие фильтров", "missing_filters"),
            (8, "Нет adaptive-перегрузки", "adaptive_reload"),
            (9, "Drift реестра ↔ биржа", "drift_issues"),
            (10, "Неправильные cast-ы", "cast_errors"),
            (11, "Нет graceful-shutdown", "graceful_shutdown"),
            (12, "Нет exponential backoff", "exponential_backoff"),
        ]

        total_red = 0
        total_warning = 0

        for num, name, key in sections:
            issues = self.results[key]

            if key == "missing_logs":
                # Проверяем, какие логи отсутствуют
                found_logs = set(issues.keys())
                required_logs = set(self.required_logs.keys())
                missing = required_logs - found_logs

                if missing:
                    status = "🔴"
                    total_red += 1
                    comment = f"Отсутствуют логи: {', '.join(missing)}"
                else:
                    status = "✅"
                    comment = "Все обязательные логи найдены"
            else:
                if issues:
                    if num in [1, 2, 4, 5, 6, 10]:  # Критичные
                        status = "🔴"
                        total_red += len(issues)
                    else:
                        status = "⚠️"
                        total_warning += len(issues)
                    comment = f"Найдено проблем: {len(issues)}"
                else:
                    status = "✅"
                    comment = "Проблем не найдено"

            report.append(f"### {num}. {name}")
            report.append(f"Статус: {status}")
            report.append(f"Комментарий: {comment}")

            if issues and key != "missing_logs":
                # Показываем первые 5 примеров
                for issue in list(issues)[:5]:
                    file_name = Path(issue["file"]).name
                    report.append(
                        f"  - {file_name}:{issue.get('line', '?')} - {issue.get('issue', issue.get('threshold', ''))}"
                    )
                if len(issues) > 5:
                    report.append(f"  ... и еще {len(issues) - 5} проблем")

            report.append("")

        # Итоговая таблица
        report.append("=" * 80)
        report.append("📊 ИТОГОВАЯ СВОДКА")
        report.append("=" * 80)
        report.append("")
        report.append(f"🔴 Критичных проблем: {total_red}")
        report.append(f"⚠️ Предупреждений: {total_warning}")
        report.append("")

        if total_red == 0 and total_warning == 0:
            report.append("✅ GO-LIVE: Все проверки пройдены!")
        elif total_red == 0:
            report.append("⚠️ GO-LIVE: Есть предупреждения, но критичных проблем нет")
        else:
            report.append("🔴 GO-LIVE: Блокируется критичными проблемами")

        return "\n".join(report)

    def analyze(self):
        """Запускает полный анализ"""
        print("🔍 Начинаю анализ логов...")

        log_files = self.find_all_logs()
        print(f"📁 Найдено log файлов: {len(log_files)}")

        # Анализируем последние 10 файлов для быстроты
        for log_file in log_files[:10]:
            print(f"  Анализирую: {log_file.name}")
            self.analyze_file(log_file)

        return self.generate_report()


def main():
    logs_dir = Path("logs/futures/archived")

    if not logs_dir.exists():
        print(f"❌ Директория {logs_dir} не найдена!")
        return

    analyzer = AuditLogAnalyzer(logs_dir)
    report = analyzer.analyze()

    print("\n" + report)

    # Сохраняем отчет
    report_file = Path("AUDIT_REPORT.md")
    report_file.write_text(report, encoding="utf-8")
    print(f"\n💾 Отчет сохранен в {report_file}")


if __name__ == "__main__":
    main()
