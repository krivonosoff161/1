"""
Комплексный анализ торговой сессии.
Анализирует баланс, сделки, логи и выдает детальный отчет.
"""

import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Путь к логам
LOGS_DIR = Path("logs/futures/archived/logs_2026-01-02_22-38-51")
CSV_FILE = LOGS_DIR / "all_data_2026-01-02.csv"


def parse_balance_from_logs() -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """Парсит баланс из логов при старте и в конце."""
    start_balance = None
    end_balance = None
    start_time = None
    end_time = None
    
    # Ищем первый лог файл
    first_log = sorted(LOGS_DIR.glob("futures_main_*.log"))[0] if list(LOGS_DIR.glob("futures_main_*.log")) else None
    last_log = sorted(LOGS_DIR.glob("futures_main_*.log"))[-1] if list(LOGS_DIR.glob("futures_main_*.log")) else None
    
    # Паттерны для поиска баланса
    balance_patterns = [
        r"Начальный баланс:\s*\$?([\d.]+)",
        r"Доступный баланс:\s*([\d.]+)\s*USDT",
        r"Баланс:\s*([\d.]+)\s*USDT",
        r"balance[:\s]+([\d.]+)",
    ]
    
    if first_log:
        with open(first_log, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                for pattern in balance_patterns:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        try:
                            balance = float(match.group(1))
                            if 100 < balance < 100000:  # Разумный диапазон
                                if start_balance is None:
                                    start_balance = balance
                                    time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                                    if time_match:
                                        start_time = time_match.group(1)
                                    break
                        except:
                            pass
    
    # Ищем последний баланс в последнем логе
    if last_log:
        with open(last_log, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            for line in reversed(lines):  # Идем с конца
                for pattern in balance_patterns:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        try:
                            balance = float(match.group(1))
                            if 100 < balance < 100000:
                                if end_balance is None:
                                    end_balance = balance
                                    time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                                    if time_match:
                                        end_time = time_match.group(1)
                                    break
                        except:
                            pass
    
    return start_balance, end_balance, start_time, end_time


def analyze_trades() -> Dict:
    """Анализирует сделки из CSV."""
    trades = []
    signals = []
    orders = []
    positions_open = []
    
    if not CSV_FILE.exists():
        return {"error": "CSV файл не найден"}
    
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record_type = row.get("record_type", "").lower()
            
            if record_type == "trades":
                try:
                    trade = {
                        "timestamp": row.get("timestamp", ""),
                        "symbol": row.get("symbol", ""),
                        "side": row.get("side", ""),
                        "entry_price": float(row.get("entry_price", 0)) if row.get("entry_price") else 0,
                        "exit_price": float(row.get("exit_price", 0)) if row.get("exit_price") else 0,
                        "size": float(row.get("size", 0)) if row.get("size") else 0,
                        "gross_pnl": float(row.get("gross_pnl", 0)) if row.get("gross_pnl") else 0,
                        "commission": float(row.get("commission", 0)) if row.get("commission") else 0,
                        "net_pnl": float(row.get("net_pnl", 0)) if row.get("net_pnl") else 0,
                        "duration_sec": float(row.get("duration_sec", 0)) if row.get("duration_sec") else 0,
                        "reason": row.get("reason", ""),
                        "win_rate": float(row.get("win_rate", 0)) if row.get("win_rate") else 0,
                        "regime": row.get("regime", ""),
                    }
                    trades.append(trade)
                except Exception as e:
                    print(f"Ошибка парсинга сделки: {e}, строка: {row}")
            
            elif record_type == "signals":
                signals.append(row)
            elif record_type == "orders":
                orders.append(row)
            elif record_type == "positions_open":
                positions_open.append(row)
    
    # Анализ сделок
    total_trades = len(trades)
    positive_trades = [t for t in trades if t["net_pnl"] > 0]
    negative_trades = [t for t in trades if t["net_pnl"] < 0]
    
    total_pnl = sum(t["net_pnl"] for t in trades)
    positive_pnl = sum(t["net_pnl"] for t in positive_trades)
    negative_pnl = sum(t["net_pnl"] for t in negative_trades)
    
    # Группировка по символам
    trades_by_symbol = defaultdict(list)
    for trade in trades:
        trades_by_symbol[trade["symbol"]].append(trade)
    
    # Группировка положительных и отрицательных по символам
    positive_by_symbol = defaultdict(list)
    negative_by_symbol = defaultdict(list)
    
    for trade in positive_trades:
        positive_by_symbol[trade["symbol"]].append(trade)
    
    for trade in negative_trades:
        negative_by_symbol[trade["symbol"]].append(trade)
    
    return {
        "total_trades": total_trades,
        "positive_trades": len(positive_trades),
        "negative_trades": len(negative_trades),
        "positive_pnl": positive_pnl,
        "negative_pnl": negative_pnl,
        "total_pnl": total_pnl,
        "trades": trades,
        "positive_trades_list": positive_trades,
        "negative_trades_list": negative_trades,
        "trades_by_symbol": dict(trades_by_symbol),
        "positive_by_symbol": dict(positive_by_symbol),
        "negative_by_symbol": dict(negative_by_symbol),
        "signals_count": len(signals),
        "orders_count": len(orders),
        "positions_open_count": len(positions_open),
    }


def analyze_negative_trade(trade: Dict, logs_dir: Path) -> Dict:
    """Детальный анализ одной отрицательной сделки."""
    symbol = trade["symbol"]
    entry_time = trade["timestamp"]
    
    analysis = {
        "symbol": symbol,
        "entry_time": entry_time,
        "entry_price": trade["entry_price"],
        "exit_price": trade["exit_price"],
        "net_pnl": trade["net_pnl"],
        "reason": trade["reason"],
        "regime": trade["regime"],
        "duration_sec": trade["duration_sec"],
        "signal_info": {},
        "entry_info": {},
        "monitoring_info": {},
        "exit_info": {},
    }
    
    # Ищем информацию о сигнале в логах
    # Это упрощенная версия - в реальности нужно искать по времени и символу
    # Здесь мы просто возвращаем структуру для дальнейшего анализа
    
    return analysis


def generate_report():
    """Генерирует полный отчет."""
    import sys
    import io
    
    # Настройка кодировки для Windows
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print("=" * 100)
    print("КОМПЛЕКСНЫЙ АНАЛИЗ ТОРГОВОЙ СЕССИИ")
    print("=" * 100)
    print()
    
    # 1. Баланс
    print("1. АНАЛИЗ БАЛАНСА")
    print("-" * 100)
    start_balance, end_balance, start_time, end_time = parse_balance_from_logs()
    
    if start_balance:
        print(f"[OK] Начальный баланс: ${start_balance:.2f} USDT ({start_time})")
    else:
        print("[ERROR] Начальный баланс не найден в логах")
    
    if end_balance:
        print(f"[OK] Конечный баланс: ${end_balance:.2f} USDT ({end_time})")
    else:
        print("[ERROR] Конечный баланс не найден в логах")
    
    if start_balance and end_balance:
        change = end_balance - start_balance
        change_pct = (change / start_balance) * 100
        print(f"📊 Изменение баланса: ${change:+.2f} USDT ({change_pct:+.2f}%)")
    print()
    
    # 2. Статистика сделок
    print("2. СТАТИСТИКА СДЕЛОК")
    print("-" * 100)
    trades_data = analyze_trades()
    
    if "error" in trades_data:
        print(f"[ERROR] Ошибка: {trades_data['error']}")
        return
    
    print(f"[INFO] Всего сделок: {trades_data['total_trades']}")
    if trades_data['total_trades'] > 0:
        print(f"[OK] Положительных: {trades_data['positive_trades']} ({trades_data['positive_trades'] / trades_data['total_trades'] * 100:.1f}%)")
        print(f"[FAIL] Отрицательных: {trades_data['negative_trades']} ({trades_data['negative_trades'] / trades_data['total_trades'] * 100:.1f}%)")
    else:
        print("[OK] Положительных: 0")
        print("[FAIL] Отрицательных: 0")
    print(f"[INFO] Общий PnL: ${trades_data['total_pnl']:.2f} USDT")
    print(f"[OK] Прибыль от положительных: ${trades_data['positive_pnl']:.2f} USDT")
    print(f"[FAIL] Убыток от отрицательных: ${trades_data['negative_pnl']:.2f} USDT")
    print()
    
    # 3. Сравнение по парам
    print("3. СРАВНЕНИЕ ПОЛОЖИТЕЛЬНЫХ И ОТРИЦАТЕЛЬНЫХ СДЕЛОК ПО ПАРАМ")
    print("-" * 100)
    
    all_symbols = set(trades_data['positive_by_symbol'].keys()) | set(trades_data['negative_by_symbol'].keys())
    
    for symbol in sorted(all_symbols):
        pos_trades = trades_data['positive_by_symbol'].get(symbol, [])
        neg_trades = trades_data['negative_by_symbol'].get(symbol, [])
        
        print(f"\n[INFO] {symbol}:")
        print(f"   [OK] Положительных: {len(pos_trades)}")
        print(f"   [FAIL] Отрицательных: {len(neg_trades)}")
        
        if pos_trades and neg_trades:
            # Сравниваем средние значения
            avg_pos_pnl = sum(t["net_pnl"] for t in pos_trades) / len(pos_trades)
            avg_neg_pnl = sum(t["net_pnl"] for t in neg_trades) / len(neg_trades)
            avg_pos_duration = sum(t["duration_sec"] for t in pos_trades) / len(pos_trades)
            avg_neg_duration = sum(t["duration_sec"] for t in neg_trades) / len(neg_trades)
            
            print(f"   [INFO] Средний PnL положительных: ${avg_pos_pnl:.2f} USDT")
            print(f"   [INFO] Средний PnL отрицательных: ${avg_neg_pnl:.2f} USDT")
            print(f"   [INFO] Средняя длительность положительных: {avg_pos_duration:.1f} сек")
            print(f"   [INFO] Средняя длительность отрицательных: {avg_neg_duration:.1f} сек")
            
            # Сравниваем причины закрытия
            pos_reasons = [t["reason"] for t in pos_trades]
            neg_reasons = [t["reason"] for t in neg_trades]
            
            print(f"   [INFO] Причины закрытия положительных: {', '.join(set(pos_reasons))}")
            print(f"   [INFO] Причины закрытия отрицательных: {', '.join(set(neg_reasons))}")
    print()
    
    # 4. Детальный анализ отрицательных сделок
    print("4. ДЕТАЛЬНЫЙ АНАЛИЗ ОТРИЦАТЕЛЬНЫХ ПОЗИЦИЙ")
    print("-" * 100)
    
    for i, trade in enumerate(trades_data['negative_trades_list'], 1):
        print(f"\n[FAIL] Отрицательная сделка #{i}: {trade['symbol']} {trade['side'].upper()}")
        print(f"   Время входа: {trade['timestamp']}")
        print(f"   Цена входа: ${trade['entry_price']:.4f}")
        print(f"   Цена выхода: ${trade['exit_price']:.4f}")
        print(f"   Размер: {trade['size']:.6f}")
        pnl_pct = (trade['net_pnl'] / (trade['entry_price'] * trade['size'])) * 100 if trade['entry_price'] * trade['size'] > 0 else 0
        print(f"   Net PnL: ${trade['net_pnl']:.2f} USDT ({pnl_pct:.2f}%)")
        print(f"   Длительность: {trade['duration_sec']:.1f} сек ({trade['duration_sec'] / 60:.1f} мин)")
        print(f"   Причина закрытия: {trade['reason']}")
        print(f"   Режим рынка: {trade['regime']}")
        print(f"   Win Rate на момент закрытия: {trade['win_rate']:.1f}%")
    print()
    
    # 5. Проверка логирования
    print("5. ПРОВЕРКА ЛОГИРОВАНИЯ")
    print("-" * 100)
    
    print(f"[INFO] Сигналов сгенерировано: {trades_data['signals_count']}")
    print(f"[INFO] Ордеров размещено: {trades_data['orders_count']}")
    print(f"[INFO] Позиций открыто: {trades_data['positions_open_count']}")
    print(f"[INFO] Сделок закрыто: {trades_data['total_trades']}")
    
    # Проверяем полноту логирования
    if trades_data['positions_open_count'] > 0 and trades_data['total_trades'] > 0:
        conversion_rate = (trades_data['total_trades'] / trades_data['positions_open_count']) * 100
        print(f"[INFO] Конверсия открытий в закрытия: {conversion_rate:.1f}%")
    
    if trades_data['signals_count'] > 0 and trades_data['orders_count'] > 0:
        execution_rate = (trades_data['orders_count'] / trades_data['signals_count']) * 100
        print(f"[INFO] Конверсия сигналов в ордера: {execution_rate:.1f}%")
    print()
    
    # 6. Итоговый вердикт
    print("6. ИТОГОВЫЙ ВЕРДИКТ")
    print("-" * 100)
    
    if start_balance and end_balance:
        change = end_balance - start_balance
        if change > 0:
            print(f"[OK] Сессия прибыльная: +${change:.2f} USDT")
        elif change < 0:
            print(f"[FAIL] Сессия убыточная: ${change:.2f} USDT")
        else:
            print(f"[INFO] Сессия безубыточная: $0.00")
    
    if trades_data['total_trades'] > 0:
        win_rate = (trades_data['positive_trades'] / trades_data['total_trades']) * 100
        print(f"[INFO] Win Rate: {win_rate:.1f}%")
        
        if win_rate >= 50:
            print("[OK] Win Rate выше 50% - стратегия показывает положительные результаты")
        else:
            print("[WARNING] Win Rate ниже 50% - требуется оптимизация стратегии")
    
    print()
    print("=" * 100)


if __name__ == "__main__":
    generate_report()

