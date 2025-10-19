#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ позиций из логов - что с ними случилось?
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def parse_positions_from_logs():
    """Парсит все позиции из логов"""

    logs_dir = Path("logs/temp_analysis")

    if not logs_dir.exists():
        print("❌ Папка logs/temp_analysis не найдена!")
        return

    positions = []

    for log_file in sorted(logs_dir.glob("*.log")):
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Ищем открытые позиции
        opened_pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*POSITION OPENED: (\w+-\w+) (\w+)"
        for match in re.finditer(opened_pattern, content):
            timestamp = match.group(1)
            symbol = match.group(2)
            side = match.group(3)

            # Ищем детали позиции
            # Order ID, Entry price, OCO ID
            lines = content[match.start() : match.start() + 2000].split("\n")

            order_id = None
            entry_price = None
            oco_id = None
            tp_price = None
            sl_price = None

            for line in lines[:20]:
                if "Order ID:" in line:
                    match_id = re.search(r"Order ID: (\d+)", line)
                    if match_id:
                        order_id = match_id.group(1)

                if "position size" in line:
                    match_price = re.search(r"@ \$?([\d.]+)", line)
                    if match_price:
                        entry_price = float(match_price.group(1))

                if "OCO order placed:" in line:
                    match_oco = re.search(r"placed: (\d+)", line)
                    if match_oco:
                        oco_id = match_oco.group(1)

                    match_tp_sl = re.search(r"TP @ \$?([\d.]+), SL @ \$?([\d.]+)", line)
                    if match_tp_sl:
                        tp_price = float(match_tp_sl.group(1))
                        sl_price = float(match_tp_sl.group(2))

            positions.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "side": side,
                    "order_id": order_id,
                    "entry_price": entry_price,
                    "oco_id": oco_id,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "status": "OPENED",
                    "close_reason": None,
                    "close_timestamp": None,
                    "exit_price": None,
                }
            )

    # Ищем закрытые позиции
    for log_file in sorted(logs_dir.glob("*.log")):
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Ищем паттерны закрытия
        closed_patterns = [
            r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*POSITION CLOSED.*(\w+-\w+)",
            r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*Позиция закрыта.*(\w+-\w+)",
            r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*closed by (time|tp|sl|ph).*(\w+-\w+)",
        ]

        for pattern in closed_patterns:
            for match in re.finditer(pattern, content):
                timestamp = match.group(1)
                symbol = match.group(2) if len(match.groups()) >= 2 else None

                # Ищем причину закрытия
                lines = content[match.start() - 500 : match.start() + 500].split("\n")
                reason = None
                exit_price = None

                for line in lines:
                    if "Reason:" in line or "closed by" in line:
                        if "time" in line.lower():
                            reason = "TIME_LIMIT"
                        elif "tp" in line.lower() or "take profit" in line.lower():
                            reason = "TAKE_PROFIT"
                        elif "sl" in line.lower() or "stop loss" in line.lower():
                            reason = "STOP_LOSS"
                        elif (
                            "ph" in line.lower() or "profit harvesting" in line.lower()
                        ):
                            reason = "PROFIT_HARVESTING"

                    if "@ $" in line:
                        match_price = re.search(r"@ \$?([\d.]+)", line)
                        if match_price:
                            exit_price = float(match_price.group(1))

                # Обновляем соответствующую позицию
                for pos in positions:
                    if pos["symbol"] == symbol and pos["status"] == "OPENED":
                        pos["status"] = "CLOSED"
                        pos["close_reason"] = reason
                        pos["close_timestamp"] = timestamp
                        pos["exit_price"] = exit_price
                        break

    return positions


def print_report(positions: List[Dict]):
    """Печатает отчет по позициям"""

    print("\n" + "=" * 120)
    print("📊 АНАЛИЗ ПОЗИЦИЙ ИЗ ЛОГОВ")
    print("=" * 120 + "\n")

    if not positions:
        print("❌ Позиций не найдено в логах!")
        return

    # Группируем по статусу
    opened = [p for p in positions if p["status"] == "OPENED"]
    closed = [p for p in positions if p["status"] == "CLOSED"]

    print(f"✅ Открыто позиций: {len(opened)}")
    print(f"🏁 Закрыто позиций: {len(closed)}")
    print()

    # Детали открытых позиций
    if opened:
        print("=" * 120)
        print("📈 ОТКРЫТЫЕ ПОЗИЦИИ (БОТ ДУМАЕТ ЧТО ОНИ ОТКРЫТЫ):")
        print("=" * 120 + "\n")

        for i, pos in enumerate(opened, 1):
            print(f"{i}. {pos['symbol']} {pos['side']}")
            print(f"   Время открытия: {pos['timestamp']}")
            print(f"   Order ID: {pos['order_id']}")
            print(
                f"   Entry: ${pos['entry_price']:.2f}"
                if pos["entry_price"]
                else "   Entry: N/A"
            )
            print(f"   OCO ID: {pos['oco_id']}")
            print(f"   TP: ${pos['tp_price']:.2f}" if pos["tp_price"] else "   TP: N/A")
            print(f"   SL: ${pos['sl_price']:.2f}" if pos["sl_price"] else "   SL: N/A")
            print()

    # Детали закрытых позиций
    if closed:
        print("=" * 120)
        print("🏁 ЗАКРЫТЫЕ ПОЗИЦИИ (В ЛОГАХ ЕСТЬ ЗАПИСЬ О ЗАКРЫТИИ):")
        print("=" * 120 + "\n")

        for i, pos in enumerate(closed, 1):
            print(f"{i}. {pos['symbol']} {pos['side']}")
            print(f"   Открыта: {pos['timestamp']}")
            print(f"   Закрыта: {pos['close_timestamp']}")
            print(
                f"   Entry: ${pos['entry_price']:.2f}"
                if pos["entry_price"]
                else "   Entry: N/A"
            )
            print(
                f"   Exit: ${pos['exit_price']:.2f}"
                if pos["exit_price"]
                else "   Exit: N/A"
            )
            print(f"   Причина: {pos['close_reason']}")

            # Расчет PnL если есть цены
            if pos["entry_price"] and pos["exit_price"]:
                diff = pos["exit_price"] - pos["entry_price"]
                pct = (diff / pos["entry_price"]) * 100
                print(f"   PnL: ${diff:.2f} ({pct:+.2f}%)")
            print()

    # Анализ причин закрытия
    if closed:
        print("=" * 120)
        print("📉 АНАЛИЗ ПРИЧИН ЗАКРЫТИЯ:")
        print("=" * 120 + "\n")

        reasons = {}
        for pos in closed:
            reason = pos["close_reason"] or "UNKNOWN"
            reasons[reason] = reasons.get(reason, 0) + 1

        for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
            print(f"  {reason}: {count} позиций")

    print("\n" + "=" * 120)
    print("⚠️  ВАЖНО!")
    print("=" * 120)
    print()
    print("Если позиции OPENED в логах, но на бирже они закрыты:")
    print("  → Это ДЕСИНХРОНИЗАЦИЯ бота с биржей!")
    print("  → Бот не отслеживает реальное состояние OCO ордеров")
    print("  → Нужно добавить проверку статуса позиций через API")
    print()
    print("Если позиции закрыты 'by market' на бирже:")
    print("  → Это либо TIME_LIMIT (бот закрыл по времени)")
    print("  → Либо OCO сработал (TP/SL)")
    print()


def main():
    positions = parse_positions_from_logs()
    print_report(positions)


if __name__ == "__main__":
    main()
