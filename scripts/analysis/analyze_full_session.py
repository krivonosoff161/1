"""
Полный анализ торговой сессии по распакованным логам.
"""

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(
    r"C:\Users\krivo\simple trading bot okx\logs\futures\archived\logs_2025-12-01_21-39-44"
)
OUTPUT_FILE = LOGS_DIR / "FULL_ANALYSIS.txt"


def find_all_logs(base_dir: Path):
    """Находит все LOG файлы рекурсивно"""
    return list(base_dir.rglob("*.log"))


def parse_trade_block(lines, start_idx):
    """
    Парсит блок закрытия позиции.
    Возвращает словарь с данными сделки и индекс конца блока.
    """
    trade = {}
    i = start_idx

    while i < len(lines) and i < start_idx + 25:
        line = lines[i]

        # Заголовок закрытия
        m = re.search(r"💰 ПОЗИЦИЯ ЗАКРЫТА: (\S+) (LONG|SHORT)", line)
        if m:
            trade["symbol"] = m.group(1)
            trade["side"] = m.group(2)

        # Время закрытия
        m = re.search(r"Время закрытия: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if m:
            trade["close_time"] = m.group(1)

        # Entry price
        m = re.search(r"Entry price: \$(\d+\.?\d*)", line)
        if m:
            trade["entry_price"] = float(m.group(1))

        # Exit price
        m = re.search(r"Exit price: \$(\d+\.?\d*)", line)
        if m:
            trade["exit_price"] = float(m.group(1))

        # Size
        m = re.search(r"Size: (\d+\.?\d*)", line)
        if m:
            trade["size"] = float(m.group(1))

        # Gross PnL
        m = re.search(r"Gross PnL: \$([+-]?\d+\.?\d*)", line)
        if m:
            trade["gross_pnl"] = float(m.group(1))

        # Net PnL
        if "Net PnL:" in line and "Gross" not in line:
            m = re.search(r"Net PnL: \$([+-]?\d+\.?\d*)", line)
            if m:
                trade["net_pnl"] = float(m.group(1))

        # Комиссия общая
        m = re.search(r"Комиссия общая: \$(\d+\.?\d*)", line)
        if m:
            trade["commission"] = float(m.group(1))

        # Причина закрытия
        m = re.search(r"Причина закрытия: (\S+)", line)
        if m:
            trade["reason"] = m.group(1)
            # Конец блока
            return trade, i + 1

        # Конец блока по разделителю
        if "━━━━━" in line and "symbol" in trade and i > start_idx + 3:
            return trade, i + 1

        i += 1

    return trade, i


def parse_all_trades(logs_dir: Path):
    """Парсит все сделки из всех логов"""
    all_trades = []
    seen_trades = set()  # Для дедупликации

    log_files = find_all_logs(logs_dir)
    print(f"📂 Найдено LOG файлов: {len(log_files)}")

    for log_file in log_files:
        try:
            content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            i = 0
            while i < len(lines):
                if "💰 ПОЗИЦИЯ ЗАКРЫТА:" in lines[i]:
                    trade, next_i = parse_trade_block(lines, i)

                    if trade.get("net_pnl") is not None and trade.get("symbol"):
                        # Создаём уникальный ключ для дедупликации
                        trade_key = (
                            trade.get("close_time", ""),
                            trade.get("symbol", ""),
                            trade.get("side", ""),
                            trade.get("entry_price", 0),
                            trade.get("net_pnl", 0),
                        )

                        if trade_key not in seen_trades:
                            seen_trades.add(trade_key)
                            all_trades.append(trade)

                    i = next_i
                else:
                    i += 1

        except Exception as e:
            pass  # Пропускаем файлы с ошибками

    # Сортируем по времени
    all_trades.sort(key=lambda x: x.get("close_time", ""))

    return all_trades


def generate_report(trades):
    """Генерация отчёта"""
    report = []

    report.append("=" * 100)
    report.append("📊 ПОЛНЫЙ АНАЛИЗ ТОРГОВОЙ СЕССИИ 2025-12-01")
    report.append("=" * 100)
    report.append("")

    if not trades:
        report.append("❌ Сделки не найдены!")
        return "\n".join(report)

    # Подсчёт статистики
    total_net = sum(t["net_pnl"] for t in trades if t.get("net_pnl"))
    total_gross = sum(t["gross_pnl"] for t in trades if t.get("gross_pnl"))
    total_comm = sum(t["commission"] for t in trades if t.get("commission"))

    wins = [t for t in trades if t.get("net_pnl", 0) > 0]
    losses = [t for t in trades if t.get("net_pnl", 0) < 0]

    report.append("📈 ОБЩАЯ СТАТИСТИКА:")
    report.append(f"   Всего УНИКАЛЬНЫХ сделок: {len(trades)}")
    report.append(f"   Прибыльных: {len(wins)} ({len(wins)/len(trades)*100:.1f}%)")
    report.append(f"   Убыточных: {len(losses)} ({len(losses)/len(trades)*100:.1f}%)")
    report.append(f"   Win Rate: {len(wins)/len(trades)*100:.1f}%")
    report.append("")
    report.append(f"   💰 Gross PnL: ${total_gross:+.2f} USDT")
    report.append(f"   💸 Комиссии: ${total_comm:.2f} USDT")
    report.append(f"   💵 NET PnL: ${total_net:+.2f} USDT")
    report.append("")

    if wins:
        avg_win = sum(t["net_pnl"] for t in wins) / len(wins)
        max_win = max(t["net_pnl"] for t in wins)
        report.append(f"   Средняя прибыль: ${avg_win:+.2f}")
        report.append(f"   Макс. прибыль: ${max_win:+.2f}")

    if losses:
        avg_loss = sum(t["net_pnl"] for t in losses) / len(losses)
        max_loss = min(t["net_pnl"] for t in losses)
        report.append(f"   Средний убыток: ${avg_loss:.2f}")
        report.append(f"   Макс. убыток: ${max_loss:.2f}")

    report.append("")

    # По символам
    report.append("📊 ПО СИМВОЛАМ:")
    report.append("-" * 90)
    report.append(
        f"{'Символ':<12} {'Сделок':<8} {'Win':<6} {'Loss':<6} {'WinRate':<10} {'Net PnL':<15} {'Комиссии':<12}"
    )
    report.append("-" * 90)

    by_symbol = defaultdict(list)
    for t in trades:
        by_symbol[t["symbol"]].append(t)

    for symbol in sorted(
        by_symbol.keys(),
        key=lambda s: sum(t.get("net_pnl", 0) for t in by_symbol[s]),
        reverse=True,
    ):
        tlist = by_symbol[symbol]
        w = len([t for t in tlist if t.get("net_pnl", 0) > 0])
        l = len([t for t in tlist if t.get("net_pnl", 0) < 0])
        pnl = sum(t.get("net_pnl", 0) for t in tlist)
        comm = sum(t.get("commission", 0) for t in tlist)
        wr = w / len(tlist) * 100 if tlist else 0
        report.append(
            f"{symbol:<12} {len(tlist):<8} {w:<6} {l:<6} {wr:<10.1f}% ${pnl:+.2f}       ${comm:.2f}"
        )

    report.append("-" * 90)
    report.append("")

    # По направлениям
    report.append("📈📉 ПО НАПРАВЛЕНИЯМ:")
    report.append("-" * 70)

    longs = [t for t in trades if t.get("side") == "LONG"]
    shorts = [t for t in trades if t.get("side") == "SHORT"]

    long_pnl = sum(t.get("net_pnl", 0) for t in longs)
    short_pnl = sum(t.get("net_pnl", 0) for t in shorts)
    long_wins = len([t for t in longs if t.get("net_pnl", 0) > 0])
    short_wins = len([t for t in shorts if t.get("net_pnl", 0) > 0])

    report.append(
        f"LONG:  {len(longs)} сделок, Win: {long_wins}, WinRate: {long_wins/len(longs)*100 if longs else 0:.1f}%, PnL: ${long_pnl:+.2f}"
    )
    report.append(
        f"SHORT: {len(shorts)} сделок, Win: {short_wins}, WinRate: {short_wins/len(shorts)*100 if shorts else 0:.1f}%, PnL: ${short_pnl:+.2f}"
    )
    report.append("")

    # По причинам
    report.append("🎯 ПО ПРИЧИНАМ ЗАКРЫТИЯ:")
    report.append("-" * 60)

    by_reason = defaultdict(list)
    for t in trades:
        by_reason[t.get("reason", "unknown")].append(t)

    for reason in sorted(by_reason.keys(), key=lambda r: -len(by_reason[r])):
        tlist = by_reason[reason]
        pnl = sum(t.get("net_pnl", 0) for t in tlist)
        report.append(f"   {reason:<25} {len(tlist):<6} сделок, PnL: ${pnl:+.2f}")

    report.append("")

    # Топ прибыльных
    report.append("🏆 ТОП-15 ПРИБЫЛЬНЫХ:")
    report.append("-" * 100)
    for i, t in enumerate(sorted(wins, key=lambda x: -x.get("net_pnl", 0))[:15], 1):
        report.append(
            f"{i:2d}. {t['symbol']:<10} {t['side']:<6} ${t.get('entry_price',0):.2f} → ${t.get('exit_price',0):.2f} | PnL: ${t['net_pnl']:+.2f} | {t.get('reason','?')}"
        )

    report.append("")

    # Топ убыточных
    report.append("💀 ТОП-15 УБЫТОЧНЫХ:")
    report.append("-" * 100)
    for i, t in enumerate(sorted(losses, key=lambda x: x.get("net_pnl", 0))[:15], 1):
        report.append(
            f"{i:2d}. {t['symbol']:<10} {t['side']:<6} ${t.get('entry_price',0):.2f} → ${t.get('exit_price',0):.2f} | PnL: ${t['net_pnl']:+.2f} | {t.get('reason','?')}"
        )

    report.append("")
    report.append("=" * 100)
    report.append(f"Отчёт: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 100)

    return "\n".join(report)


def main():
    print("=" * 60)
    print("📊 ПОЛНЫЙ АНАЛИЗ СЕССИИ")
    print("=" * 60)
    print("")

    print("🔍 Парсинг сделок из всех логов...")
    trades = parse_all_trades(LOGS_DIR)
    print(f"   ✅ Найдено уникальных сделок: {len(trades)}")

    if trades:
        total = sum(t.get("net_pnl", 0) for t in trades)
        print(f"   💵 Общий Net PnL: ${total:+.2f}")
    print("")

    print("📝 Генерация отчёта...")
    report = generate_report(trades)

    OUTPUT_FILE.write_text(report, encoding="utf-8")
    print(f"   ✅ Сохранено: {OUTPUT_FILE}")
    print("")
    print(report)


if __name__ == "__main__":
    main()
