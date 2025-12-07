#!/usr/bin/env python3
"""
Анализ максимальной прибыли по позициям из архивов
"""

import re
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def extract_pnl_from_log(log_file):
    """Извлечение PnL из лога"""
    positions_pnl = defaultdict(list)  # symbol -> [(time, pnl, pnl_percent), ...]

    # Паттерны для поиска PnL
    patterns = [
        r"PnL=([-+]?\d+\.?\d*)",
        r"PnL%?=([-+]?\d+\.?\d*)",
        r"pnl=([-+]?\d+\.?\d*)",
        r"ADL для (\w+-USDT).*PnL=([-+]?\d+\.?\d*)",
        r"(\w+-USDT).*PnL=([-+]?\d+\.?\d*)",
    ]

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            # Извлекаем время
            time_match = re.match(
                r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)", line
            )
            if not time_match:
                continue

            time_str = time_match.group(1)

            # Ищем PnL для каждого символа
            for symbol in ["SOL-USDT", "DOGE-USDT", "BTC-USDT", "XRP-USDT", "ETH-USDT"]:
                if symbol in line:
                    # Ищем PnL значение
                    for pattern in patterns:
                        match = re.search(pattern, line, re.IGNORECASE)
                        if match:
                            try:
                                pnl = float(
                                    match.group(1)
                                    if len(match.groups()) == 1
                                    else match.group(2)
                                )
                                positions_pnl[symbol].append((time_str, pnl))
                            except:
                                pass
                            break

    return positions_pnl


def analyze_zip_archive(zip_path):
    """Анализ zip архива"""
    print(f"\n📦 Анализ архива: {zip_path.name}")

    max_profits = defaultdict(
        lambda: {"max": -999999, "time": None, "min": 999999, "min_time": None}
    )

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            for file_info in z.namelist():
                if file_info.endswith(".log"):
                    with z.open(file_info) as f:
                        content = f.read().decode("utf-8", errors="ignore")

                        # Ищем PnL для каждого символа
                        for symbol in [
                            "SOL-USDT",
                            "DOGE-USDT",
                            "BTC-USDT",
                            "XRP-USDT",
                            "ETH-USDT",
                        ]:
                            # Паттерн для поиска PnL
                            pattern = rf"{symbol}.*?PnL=([-+]?\d+\.?\d*)"
                            matches = re.finditer(pattern, content, re.IGNORECASE)

                            for match in matches:
                                try:
                                    pnl = float(match.group(1))

                                    # Ищем время в строке
                                    line_start = max(0, match.start() - 200)
                                    line_end = min(len(content), match.end() + 200)
                                    line = content[line_start:line_end]

                                    time_match = re.search(
                                        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)",
                                        line,
                                    )
                                    time_str = (
                                        time_match.group(1) if time_match else "N/A"
                                    )

                                    if pnl > max_profits[symbol]["max"]:
                                        max_profits[symbol]["max"] = pnl
                                        max_profits[symbol]["time"] = time_str

                                    if pnl < max_profits[symbol]["min"]:
                                        max_profits[symbol]["min"] = pnl
                                        max_profits[symbol]["min_time"] = time_str

                                except:
                                    pass
    except Exception as e:
        print(f"⚠️ Ошибка чтения архива: {e}")

    return max_profits


def main():
    print("=" * 80)
    print("📊 АНАЛИЗ МАКСИМАЛЬНОЙ ПРИБЫЛИ ПО ПОЗИЦИЯМ")
    print("=" * 80)

    logs_dir = Path("logs/futures")

    # Анализируем текущие логи
    print("\n📄 Анализ текущих логов...")
    current_log = logs_dir / "info_2025-11-29.log"
    if current_log.exists():
        positions_pnl = extract_pnl_from_log(current_log)

        print("\n📈 Максимальная прибыль в текущих логах:")
        for symbol, pnl_list in positions_pnl.items():
            if pnl_list:
                max_pnl = max(pnl_list, key=lambda x: x[1])
                min_pnl = min(pnl_list, key=lambda x: x[1])
                print(f"\n{symbol}:")
                print(f"  Максимум: {max_pnl[1]:.4f} USDT в {max_pnl[0]}")
                print(f"  Минимум: {min_pnl[1]:.4f} USDT в {min_pnl[0]}")
                print(f"  Текущий: {pnl_list[-1][1]:.4f} USDT в {pnl_list[-1][0]}")
                if max_pnl[1] > 0:
                    loss = max_pnl[1] - pnl_list[-1][1]
                    print(f"  ⚠️ Упущенная прибыль: {loss:.4f} USDT")

    # Анализируем архивы
    print("\n📦 Анализ архивов...")
    zip_files = sorted(
        logs_dir.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True
    )

    all_max_profits = defaultdict(
        lambda: {"max": -999999, "time": None, "archives": []}
    )

    for zip_file in zip_files[:10]:  # Последние 10 архивов
        max_profits = analyze_zip_archive(zip_file)

        for symbol, data in max_profits.items():
            if data["max"] > all_max_profits[symbol]["max"]:
                all_max_profits[symbol]["max"] = data["max"]
                all_max_profits[symbol]["time"] = data["time"]
                all_max_profits[symbol]["archives"] = [zip_file.name]
            elif data["max"] == all_max_profits[symbol]["max"]:
                all_max_profits[symbol]["archives"].append(zip_file.name)

    print("\n" + "=" * 80)
    print("📊 ИТОГОВАЯ СТАТИСТИКА МАКСИМАЛЬНОЙ ПРИБЫЛИ")
    print("=" * 80)

    for symbol in ["SOL-USDT", "DOGE-USDT", "BTC-USDT", "XRP-USDT", "ETH-USDT"]:
        if symbol in all_max_profits and all_max_profits[symbol]["max"] > -999999:
            data = all_max_profits[symbol]
            print(f"\n{symbol}:")
            print(f"  Максимальная прибыль: {data['max']:.4f} USDT")
            print(f"  Время: {data['time']}")
            print(f"  Найдено в архивах: {len(data['archives'])}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
