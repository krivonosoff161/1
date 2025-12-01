"""
Скрипт анализа логов торговой сессии.
Извлекает и собирает информацию о закрытиях позиций из всех архивов.
"""

import os
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Путь к извлечённым логам
EXTRACTED_DIR = Path(
    r"C:\Users\krivo\simple trading bot okx\logs\futures\archived\extracted_2025-12-01_21-39-44"
)
OUTPUT_FILE = EXTRACTED_DIR / "ANALYSIS_REPORT.txt"


def extract_all_zips():
    """Распаковка всех zip архивов"""
    extracted_logs_dir = EXTRACTED_DIR / "all_logs"
    extracted_logs_dir.mkdir(exist_ok=True)

    zip_files = list(EXTRACTED_DIR.glob("*.zip"))
    print(f"Найдено {len(zip_files)} архивов для распаковки...")

    for i, zip_path in enumerate(zip_files):
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.namelist():
                    # Извлекаем с уникальным именем
                    content = zf.read(member)
                    out_name = f"{i:03d}_{Path(member).name}"
                    out_path = extracted_logs_dir / out_name
                    out_path.write_bytes(content)
        except Exception as e:
            print(f"Ошибка распаковки {zip_path.name}: {e}")

    return extracted_logs_dir


def analyze_logs(logs_dir):
    """Анализ всех логов"""
    results = {
        "closes": [],  # Все закрытия позиций
        "opens": [],  # Все открытия
        "errors": defaultdict(int),  # Счётчик ошибок по типам
        "pnl_total": 0.0,
        "trades_count": 0,
        "symbols_stats": defaultdict(lambda: {"opens": 0, "closes": 0, "pnl": 0.0}),
    }

    # Паттерны для поиска
    patterns = {
        # Закрытие через position_manager
        "close_pm": re.compile(r"💰 ПОЗИЦИЯ ЗАКРЫТА: (\S+) (LONG|SHORT)"),
        "close_success": re.compile(
            r"✅ Позиция (\S+) успешно закрыта по причине: (\S+).*?Net PnL: \$([+-]?\d+\.?\d*)"
        ),
        "close_entry": re.compile(r"Entry price: \$(\d+\.?\d*)"),
        "close_exit": re.compile(r"Exit price: \$(\d+\.?\d*)"),
        "close_gross_pnl": re.compile(r"Gross PnL: \$([+-]?\d+\.?\d*)"),
        "close_net_pnl": re.compile(r"Net PnL: \$([+-]?\d+\.?\d*)"),
        "close_duration": re.compile(r"Длительность удержания: ([+-]?\d+\.?\d*) сек"),
        "close_reason": re.compile(r"Причина закрытия: (\S+)"),
        # Закрытие через trailing_sl
        "close_tsl": re.compile(r"📊 Закрываем (\S+) по причине: (\S+)"),
        # Очистка позиции (закрыта на бирже)
        "close_sync": re.compile(r"♻️ Позиция (\S+) отсутствует на бирже"),
        # Открытие позиции
        "open": re.compile(r"✅ Позиция (\S+) открыта: (LONG|SHORT|long|short)"),
        "open_alt": re.compile(r"📤 Позиция открыта: (\S+)"),
        # Ошибки
        "error_timezone": re.compile(r"name 'timezone' is not defined"),
        "error_51006": re.compile(r"51006.*Order price is not within the price limit"),
        "error_already_open": re.compile(r"Позиция (\S+) уже открыта"),
        "error_502": re.compile(r"Status: 502"),
    }

    log_files = sorted(logs_dir.glob("*.log"))
    print(f"Анализируем {len(log_files)} файлов логов...")

    current_close = {}  # Для сборки информации о текущем закрытии

    for log_file in log_files:
        try:
            content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            for line in lines:
                # Закрытие через position_manager (детальный лог)
                match = patterns["close_pm"].search(line)
                if match:
                    symbol, side = match.groups()
                    current_close = {
                        "symbol": symbol,
                        "side": side,
                        "source": "position_manager",
                    }
                    continue

                # Собираем детали закрытия
                if current_close:
                    if "Entry price" in line:
                        m = patterns["close_entry"].search(line)
                        if m:
                            current_close["entry_price"] = float(m.group(1))
                    elif "Exit price" in line:
                        m = patterns["close_exit"].search(line)
                        if m:
                            current_close["exit_price"] = float(m.group(1))
                    elif "Gross PnL" in line:
                        m = patterns["close_gross_pnl"].search(line)
                        if m:
                            current_close["gross_pnl"] = float(m.group(1))
                    elif "Net PnL" in line and "Gross" not in line:
                        m = patterns["close_net_pnl"].search(line)
                        if m:
                            current_close["net_pnl"] = float(m.group(1))
                    elif "Длительность" in line:
                        m = patterns["close_duration"].search(line)
                        if m:
                            current_close["duration_sec"] = float(m.group(1))
                    elif "Причина закрытия" in line:
                        m = patterns["close_reason"].search(line)
                        if m:
                            current_close["reason"] = m.group(1)
                            # Закрытие завершено, сохраняем
                            if "symbol" in current_close:
                                results["closes"].append(current_close.copy())
                                symbol = current_close["symbol"]
                                results["symbols_stats"][symbol]["closes"] += 1
                                if "net_pnl" in current_close:
                                    results["pnl_total"] += current_close["net_pnl"]
                                    results["symbols_stats"][symbol][
                                        "pnl"
                                    ] += current_close["net_pnl"]
                                results["trades_count"] += 1
                            current_close = {}

                # Закрытие через trailing_sl
                match = patterns["close_tsl"].search(line)
                if match:
                    symbol, reason = match.groups()
                    results["closes"].append(
                        {"symbol": symbol, "reason": reason, "source": "trailing_sl"}
                    )
                    results["symbols_stats"][symbol]["closes"] += 1

                # Очистка позиции (закрыта на бирже)
                match = patterns["close_sync"].search(line)
                if match:
                    symbol = match.group(1)
                    results["closes"].append(
                        {
                            "symbol": symbol,
                            "reason": "sync_removed",
                            "source": "exchange_sync",
                        }
                    )
                    results["symbols_stats"][symbol]["closes"] += 1

                # Открытие позиции
                match = patterns["open"].search(line)
                if match:
                    symbol, side = match.groups()
                    results["opens"].append({"symbol": symbol, "side": side.upper()})
                    results["symbols_stats"][symbol]["opens"] += 1

                match = patterns["open_alt"].search(line)
                if match:
                    symbol = match.group(1)
                    results["opens"].append({"symbol": symbol, "side": "unknown"})
                    results["symbols_stats"][symbol]["opens"] += 1

                # Ошибки
                if patterns["error_timezone"].search(line):
                    results["errors"]["timezone"] += 1
                if patterns["error_51006"].search(line):
                    results["errors"]["price_limit_51006"] += 1
                if patterns["error_already_open"].search(line):
                    results["errors"]["position_already_open"] += 1
                if patterns["error_502"].search(line):
                    results["errors"]["api_502"] += 1

        except Exception as e:
            print(f"Ошибка чтения {log_file.name}: {e}")

    return results


def generate_report(results):
    """Генерация отчёта"""
    report = []
    report.append("=" * 80)
    report.append("📊 ОТЧЁТ ПО ТОРГОВОЙ СЕССИИ 2025-12-01")
    report.append("=" * 80)
    report.append("")

    # Общая статистика
    report.append("📈 ОБЩАЯ СТАТИСТИКА:")
    report.append(f"   Всего открытий позиций: {len(results['opens'])}")
    report.append(f"   Всего закрытий позиций: {len(results['closes'])}")
    report.append(f"   Сделок с PnL данными: {results['trades_count']}")
    report.append(f"   Общий Net PnL: ${results['pnl_total']:.4f} USDT")
    report.append("")

    # Ошибки
    report.append("❌ ОШИБКИ:")
    for error_type, count in sorted(results["errors"].items(), key=lambda x: -x[1]):
        report.append(f"   {error_type}: {count}")
    report.append("")

    # Статистика по символам
    report.append("📊 СТАТИСТИКА ПО СИМВОЛАМ:")
    report.append("-" * 60)
    report.append(f"{'Символ':<15} {'Открытий':<10} {'Закрытий':<10} {'PnL ($)':<15}")
    report.append("-" * 60)

    for symbol, stats in sorted(results["symbols_stats"].items()):
        report.append(
            f"{symbol:<15} {stats['opens']:<10} {stats['closes']:<10} {stats['pnl']:+.4f}"
        )
    report.append("-" * 60)
    report.append("")

    # Детали закрытий с PnL
    report.append("💰 ДЕТАЛИ ЗАКРЫТИЙ (с данными PnL):")
    report.append("-" * 80)

    closes_with_pnl = [c for c in results["closes"] if "net_pnl" in c]
    for i, close in enumerate(closes_with_pnl[:100], 1):  # Первые 100
        symbol = close.get("symbol", "?")
        side = close.get("side", "?")
        reason = close.get("reason", "?")
        entry = close.get("entry_price", 0)
        exit_p = close.get("exit_price", 0)
        net_pnl = close.get("net_pnl", 0)
        duration = close.get("duration_sec", 0)

        report.append(
            f"{i:3d}. {symbol:<12} {side:<6} | Entry: ${entry:.4f} → Exit: ${exit_p:.4f} | "
            f"PnL: ${net_pnl:+.4f} | Reason: {reason} | Duration: {duration:.0f}s"
        )

    if len(closes_with_pnl) > 100:
        report.append(f"... и ещё {len(closes_with_pnl) - 100} закрытий")

    report.append("")
    report.append("=" * 80)
    report.append(f"Отчёт сгенерирован: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 80)

    return "\n".join(report)


def main():
    print("🔍 Начинаем анализ логов сессии...")
    print("")

    # Шаг 1: Распаковка всех архивов
    print("📦 Шаг 1: Распаковка архивов...")
    logs_dir = extract_all_zips()
    print(f"   Распаковано в: {logs_dir}")
    print("")

    # Шаг 2: Анализ логов
    print("🔍 Шаг 2: Анализ логов...")
    results = analyze_logs(logs_dir)
    print(f"   Найдено открытий: {len(results['opens'])}")
    print(f"   Найдено закрытий: {len(results['closes'])}")
    print(f"   Общий PnL: ${results['pnl_total']:.4f}")
    print("")

    # Шаг 3: Генерация отчёта
    print("📝 Шаг 3: Генерация отчёта...")
    report = generate_report(results)

    # Сохраняем отчёт
    OUTPUT_FILE.write_text(report, encoding="utf-8")
    print(f"   Отчёт сохранён: {OUTPUT_FILE}")
    print("")

    # Выводим отчёт
    print(report)


if __name__ == "__main__":
    main()
