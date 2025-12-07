"""
Скрипт анализа логов v2 - ПРАВИЛЬНЫЙ парсинг каждой сделки.
"""

import os
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

EXTRACTED_DIR = Path(
    r"C:\Users\krivo\simple trading bot okx\logs\futures\archived\extracted_2025-12-01_21-39-44"
)
OUTPUT_FILE = EXTRACTED_DIR / "ANALYSIS_REPORT_V2.txt"


def extract_all_zips():
    """Распаковка всех zip архивов"""
    extracted_logs_dir = EXTRACTED_DIR / "all_logs"
    extracted_logs_dir.mkdir(exist_ok=True)

    zip_files = list(EXTRACTED_DIR.glob("*.zip"))
    print(f"Найдено {len(zip_files)} архивов...")

    for i, zip_path in enumerate(zip_files):
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.namelist():
                    content = zf.read(member)
                    out_name = f"{i:03d}_{Path(member).name}"
                    out_path = extracted_logs_dir / out_name
                    out_path.write_bytes(content)
        except Exception as e:
            print(f"Ошибка: {zip_path.name}: {e}")

    return extracted_logs_dir


def parse_trades_from_logs(logs_dir):
    """
    Парсинг РЕАЛЬНЫХ сделок из логов.
    Ищем блоки:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    💰 ПОЗИЦИЯ ЗАКРЫТА: SYMBOL SIDE
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ⏰ Время закрытия: ...
       📊 Entry price: $...
       📊 Exit price: $...
       📦 Size: ...
       ⏱️  Длительность удержания: ...
       💵 Gross PnL: $...
       💵 Net PnL: $...
       💸 Комиссия вход: ...
       💸 Комиссия выход: ...
       💸 Комиссия общая: ...
       🎯 Причина закрытия: ...
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """

    trades = []
    log_files = sorted(logs_dir.glob("*.log"))
    print(f"Анализируем {len(log_files)} файлов...")

    # Паттерн для поиска блока закрытия
    close_header_pattern = re.compile(r"💰 ПОЗИЦИЯ ЗАКРЫТА: (\S+) (LONG|SHORT)")

    for log_file in log_files:
        try:
            content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            i = 0
            while i < len(lines):
                line = lines[i]

                # Ищем начало блока закрытия
                match = close_header_pattern.search(line)
                if match:
                    symbol, side = match.groups()
                    trade = {
                        "symbol": symbol,
                        "side": side,
                        "entry_price": None,
                        "exit_price": None,
                        "size": None,
                        "gross_pnl": None,
                        "net_pnl": None,
                        "commission": None,
                        "reason": None,
                        "duration_sec": None,
                        "close_time": None,
                    }

                    # Читаем следующие 15 строк для парсинга деталей
                    for j in range(i + 1, min(i + 20, len(lines))):
                        detail_line = lines[j]

                        # Время закрытия
                        if "Время закрытия:" in detail_line:
                            m = re.search(
                                r"Время закрытия: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
                                detail_line,
                            )
                            if m:
                                trade["close_time"] = m.group(1)

                        # Entry price
                        if "Entry price:" in detail_line:
                            m = re.search(r"Entry price: \$(\d+\.?\d*)", detail_line)
                            if m:
                                trade["entry_price"] = float(m.group(1))

                        # Exit price
                        if "Exit price:" in detail_line:
                            m = re.search(r"Exit price: \$(\d+\.?\d*)", detail_line)
                            if m:
                                trade["exit_price"] = float(m.group(1))

                        # Size
                        if "Size:" in detail_line:
                            m = re.search(r"Size: (\d+\.?\d*)", detail_line)
                            if m:
                                trade["size"] = float(m.group(1))

                        # Gross PnL
                        if "Gross PnL:" in detail_line:
                            m = re.search(r"Gross PnL: \$([+-]?\d+\.?\d*)", detail_line)
                            if m:
                                trade["gross_pnl"] = float(m.group(1))

                        # Net PnL (не Gross)
                        if "Net PnL:" in detail_line and "Gross" not in detail_line:
                            m = re.search(r"Net PnL: \$([+-]?\d+\.?\d*)", detail_line)
                            if m:
                                trade["net_pnl"] = float(m.group(1))

                        # Комиссия общая
                        if "Комиссия общая:" in detail_line:
                            m = re.search(r"Комиссия общая: \$(\d+\.?\d*)", detail_line)
                            if m:
                                trade["commission"] = float(m.group(1))

                        # Причина закрытия
                        if "Причина закрытия:" in detail_line:
                            m = re.search(r"Причина закрытия: (\S+)", detail_line)
                            if m:
                                trade["reason"] = m.group(1)

                        # Длительность
                        if "Длительность удержания:" in detail_line:
                            m = re.search(
                                r"Длительность удержания: ([+-]?\d+\.?\d*) сек",
                                detail_line,
                            )
                            if m:
                                trade["duration_sec"] = float(m.group(1))

                        # Конец блока
                        if "━━━━━" in detail_line and j > i + 2:
                            break

                    # Сохраняем только если есть PnL данные
                    if trade["net_pnl"] is not None:
                        trades.append(trade)

                i += 1

        except Exception as e:
            print(f"Ошибка чтения {log_file.name}: {e}")

    return trades


def generate_report(trades):
    """Генерация детального отчёта"""
    report = []
    report.append("=" * 100)
    report.append("📊 ДЕТАЛЬНЫЙ АНАЛИЗ ТОРГОВОЙ СЕССИИ 2025-12-01")
    report.append("=" * 100)
    report.append("")

    if not trades:
        report.append("❌ Сделки не найдены!")
        return "\n".join(report)

    # Общая статистика
    total_net_pnl = sum(t["net_pnl"] for t in trades if t["net_pnl"] is not None)
    total_gross_pnl = sum(t["gross_pnl"] for t in trades if t["gross_pnl"] is not None)
    total_commission = sum(
        t["commission"] for t in trades if t["commission"] is not None
    )

    wins = [t for t in trades if t["net_pnl"] and t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] and t["net_pnl"] < 0]

    report.append("📈 ОБЩАЯ СТАТИСТИКА:")
    report.append(f"   Всего сделок: {len(trades)}")
    report.append(f"   Прибыльных: {len(wins)} ({len(wins)/len(trades)*100:.1f}%)")
    report.append(f"   Убыточных: {len(losses)} ({len(losses)/len(trades)*100:.1f}%)")
    report.append(f"   Win Rate: {len(wins)/len(trades)*100:.1f}%")
    report.append("")
    report.append(f"   💰 Gross PnL: ${total_gross_pnl:+.4f} USDT")
    report.append(f"   💸 Комиссии: ${total_commission:.4f} USDT")
    report.append(f"   💵 NET PnL: ${total_net_pnl:+.4f} USDT")
    report.append("")

    if wins:
        avg_win = sum(t["net_pnl"] for t in wins) / len(wins)
        max_win = max(t["net_pnl"] for t in wins)
        report.append(f"   Средняя прибыль: ${avg_win:+.4f}")
        report.append(f"   Макс. прибыль: ${max_win:+.4f}")

    if losses:
        avg_loss = sum(t["net_pnl"] for t in losses) / len(losses)
        max_loss = min(t["net_pnl"] for t in losses)
        report.append(f"   Средний убыток: ${avg_loss:+.4f}")
        report.append(f"   Макс. убыток: ${max_loss:+.4f}")

    report.append("")

    # Статистика по символам
    report.append("📊 СТАТИСТИКА ПО СИМВОЛАМ:")
    report.append("-" * 100)
    report.append(
        f"{'Символ':<15} {'Сделок':<10} {'Win':<8} {'Loss':<8} {'WinRate':<10} {'Net PnL':<15} {'Комиссии':<12}"
    )
    report.append("-" * 100)

    symbols_stats = defaultdict(lambda: {"trades": [], "net_pnl": 0, "commission": 0})
    for t in trades:
        symbol = t["symbol"]
        symbols_stats[symbol]["trades"].append(t)
        if t["net_pnl"]:
            symbols_stats[symbol]["net_pnl"] += t["net_pnl"]
        if t["commission"]:
            symbols_stats[symbol]["commission"] += t["commission"]

    for symbol, stats in sorted(
        symbols_stats.items(), key=lambda x: x[1]["net_pnl"], reverse=True
    ):
        trades_list = stats["trades"]
        wins_s = len([t for t in trades_list if t["net_pnl"] and t["net_pnl"] > 0])
        losses_s = len([t for t in trades_list if t["net_pnl"] and t["net_pnl"] < 0])
        win_rate = wins_s / len(trades_list) * 100 if trades_list else 0
        report.append(
            f"{symbol:<15} {len(trades_list):<10} {wins_s:<8} {losses_s:<8} {win_rate:<10.1f}% ${stats['net_pnl']:+.4f}      ${stats['commission']:.4f}"
        )

    report.append("-" * 100)
    report.append("")

    # Статистика по причинам закрытия
    report.append("🎯 СТАТИСТИКА ПО ПРИЧИНАМ ЗАКРЫТИЯ:")
    report.append("-" * 80)

    reasons_stats = defaultdict(lambda: {"count": 0, "net_pnl": 0})
    for t in trades:
        reason = t.get("reason", "unknown")
        reasons_stats[reason]["count"] += 1
        if t["net_pnl"]:
            reasons_stats[reason]["net_pnl"] += t["net_pnl"]

    report.append(f"{'Причина':<25} {'Сделок':<10} {'Net PnL':<15}")
    report.append("-" * 50)
    for reason, stats in sorted(reasons_stats.items(), key=lambda x: -x[1]["count"]):
        report.append(f"{reason:<25} {stats['count']:<10} ${stats['net_pnl']:+.4f}")

    report.append("")

    # Статистика по направлениям
    report.append("📈📉 СТАТИСТИКА ПО НАПРАВЛЕНИЯМ:")
    report.append("-" * 60)

    longs = [t for t in trades if t["side"] == "LONG"]
    shorts = [t for t in trades if t["side"] == "SHORT"]

    long_pnl = sum(t["net_pnl"] for t in longs if t["net_pnl"]) if longs else 0
    short_pnl = sum(t["net_pnl"] for t in shorts if t["net_pnl"]) if shorts else 0

    long_wins = len([t for t in longs if t["net_pnl"] and t["net_pnl"] > 0])
    short_wins = len([t for t in shorts if t["net_pnl"] and t["net_pnl"] > 0])

    report.append(
        f"LONG:  {len(longs)} сделок, Win: {long_wins}, WinRate: {long_wins/len(longs)*100 if longs else 0:.1f}%, PnL: ${long_pnl:+.4f}"
    )
    report.append(
        f"SHORT: {len(shorts)} сделок, Win: {short_wins}, WinRate: {short_wins/len(shorts)*100 if shorts else 0:.1f}%, PnL: ${short_pnl:+.4f}"
    )
    report.append("")

    # Топ прибыльных сделок
    report.append("🏆 ТОП-20 ПРИБЫЛЬНЫХ СДЕЛОК:")
    report.append("-" * 100)
    sorted_wins = sorted(
        [t for t in trades if t["net_pnl"] and t["net_pnl"] > 0],
        key=lambda x: -x["net_pnl"],
    )[:20]
    for i, t in enumerate(sorted_wins, 1):
        report.append(
            f"{i:2d}. {t['symbol']:<12} {t['side']:<6} Entry: ${t['entry_price']:.4f} → Exit: ${t['exit_price']:.4f} | Net PnL: ${t['net_pnl']:+.4f} | {t['reason']}"
        )
    report.append("")

    # Топ убыточных сделок
    report.append("💀 ТОП-20 УБЫТОЧНЫХ СДЕЛОК:")
    report.append("-" * 100)
    sorted_losses = sorted(
        [t for t in trades if t["net_pnl"] and t["net_pnl"] < 0],
        key=lambda x: x["net_pnl"],
    )[:20]
    for i, t in enumerate(sorted_losses, 1):
        report.append(
            f"{i:2d}. {t['symbol']:<12} {t['side']:<6} Entry: ${t['entry_price']:.4f} → Exit: ${t['exit_price']:.4f} | Net PnL: ${t['net_pnl']:+.4f} | {t['reason']}"
        )
    report.append("")

    # ВСЕ сделки
    report.append("📋 ВСЕ СДЕЛКИ (хронологически):")
    report.append("-" * 120)
    report.append(
        f"{'#':<5} {'Время':<20} {'Символ':<12} {'Side':<6} {'Entry':<12} {'Exit':<12} {'Net PnL':<12} {'Причина':<20}"
    )
    report.append("-" * 120)

    for i, t in enumerate(trades, 1):
        close_time = t.get("close_time", "?")
        entry = f"${t['entry_price']:.4f}" if t["entry_price"] else "?"
        exit_p = f"${t['exit_price']:.4f}" if t["exit_price"] else "?"
        pnl = f"${t['net_pnl']:+.4f}" if t["net_pnl"] else "?"
        reason = t.get("reason", "?")
        report.append(
            f"{i:<5} {close_time:<20} {t['symbol']:<12} {t['side']:<6} {entry:<12} {exit_p:<12} {pnl:<12} {reason:<20}"
        )

    report.append("")
    report.append("=" * 100)
    report.append(f"Отчёт сгенерирован: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 100)

    return "\n".join(report)


def main():
    print("🔍 Анализ логов v2 - ПРАВИЛЬНЫЙ парсинг...")
    print("")

    logs_dir = EXTRACTED_DIR / "all_logs"
    if not logs_dir.exists():
        print("📦 Распаковка архивов...")
        logs_dir = extract_all_zips()

    print("🔍 Парсинг сделок...")
    trades = parse_trades_from_logs(logs_dir)
    print(f"   Найдено сделок: {len(trades)}")

    if trades:
        total_pnl = sum(t["net_pnl"] for t in trades if t["net_pnl"])
        print(f"   Общий Net PnL: ${total_pnl:+.4f}")
    print("")

    print("📝 Генерация отчёта...")
    report = generate_report(trades)

    OUTPUT_FILE.write_text(report, encoding="utf-8")
    print(f"   Сохранено: {OUTPUT_FILE}")
    print("")
    print(report)


if __name__ == "__main__":
    main()
