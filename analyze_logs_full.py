#!/usr/bin/env python3
"""
Полный анализ логов бота за 29.11.2025
"""

import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

def parse_log_line(line: str) -> dict:
    """Парсинг строки лога"""
    pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*\|\s*(\w+)\s*\|\s*([^|]+?)\s*\|\s*(.+)"
    match = re.match(pattern, line)
    if match:
        time_str, level, module, message = match.groups()
        try:
            timestamp = datetime.strptime(time_str.split('.')[0], "%Y-%m-%d %H:%M:%S")
            return {
                'timestamp': timestamp,
                'level': level,
                'module': module.strip(),
                'message': message.strip()
            }
        except:
            pass
    return None

def analyze_logs(log_file: Path):
    """Анализ логов"""
    print(f"📊 Анализ логов: {log_file.name}\n")
    
    stats = {
        'total_lines': 0,
        'by_level': defaultdict(int),
        'positions_opened': [],
        'positions_closed': [],
        'signals_generated': [],
        'signals_blocked': [],
        'adx_trends': [],
        'errors': [],
        'warnings': [],
        'tp_extensions': [],
        'pnl_updates': [],
        'margin_checks': [],
        'time_range': {'start': None, 'end': None}
    }
    
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            stats['total_lines'] += 1
            parsed = parse_log_line(line)
            
            if not parsed:
                continue
            
            # Временной диапазон
            if stats['time_range']['start'] is None:
                stats['time_range']['start'] = parsed['timestamp']
            stats['time_range']['end'] = parsed['timestamp']
            
            # Уровни логирования
            stats['by_level'][parsed['level']] += 1
            
            msg = parsed['message']
            
            # Открытие позиций
            if 'POSITION OPENED' in msg or 'Позиция открыта' in msg or 'Открыта позиция' in msg:
                stats['positions_opened'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # Закрытие позиций
            if 'TRADE CLOSED' in msg or 'Позиция закрыта' in msg or 'закрыта по причине' in msg:
                stats['positions_closed'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # Сигналы
            if 'Сгенерирован сигнал' in msg or 'SIGNAL' in msg or 'сигнал для' in msg or 'Основной цикл: сгенерировано' in msg:
                stats['signals_generated'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # Блокировка сигналов
            if 'сигнал ОТМЕНЕН' in msg or 'сигнал заблокирован' in msg or 'БЛОКИРУЕМ' in msg:
                stats['signals_blocked'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # ADX тренды
            if 'ADX тренд' in msg or 'ADX=' in msg or '📊 ADX для' in msg or 'Сохранен ADX' in msg:
                stats['adx_trends'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # Ошибки
            if parsed['level'] in ['ERROR', 'CRITICAL']:
                stats['errors'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # Предупреждения
            if parsed['level'] == 'WARNING':
                stats['warnings'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # Продление TP
            if 'Продление TP' in msg or 'TP для' in msg:
                stats['tp_extensions'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # PnL обновления
            if 'PnL=' in msg or 'PnL%=' in msg or 'PnL:' in msg:
                stats['pnl_updates'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
            
            # Проверки маржи
            if 'margin_ratio=' in msg or 'Проверка безопасности' in msg:
                stats['margin_checks'].append({
                    'time': parsed['timestamp'],
                    'message': msg
                })
    
    return stats

def print_report(stats: dict):
    """Вывод отчета"""
    print("=" * 80)
    print("📊 ПОЛНЫЙ АНАЛИЗ ЛОГОВ")
    print("=" * 80)
    print()
    
    # Временной диапазон
    if stats['time_range']['start']:
        duration = stats['time_range']['end'] - stats['time_range']['start']
        print(f"⏰ Временной диапазон:")
        print(f"   Начало: {stats['time_range']['start']}")
        print(f"   Конец: {stats['time_range']['end']}")
        print(f"   Длительность: {duration}")
        print()
    
    # Общая статистика
    print(f"📈 Общая статистика:")
    print(f"   Всего строк: {stats['total_lines']:,}")
    print(f"   Уровни логирования:")
    for level, count in sorted(stats['by_level'].items()):
        print(f"      {level}: {count:,}")
    print()
    
    # Позиции
    print(f"💼 Позиции:")
    print(f"   Открыто: {len(stats['positions_opened'])}")
    print(f"   Закрыто: {len(stats['positions_closed'])}")
    if stats['positions_opened']:
        print(f"   Первое открытие: {stats['positions_opened'][0]['time']}")
        print(f"   Последнее открытие: {stats['positions_opened'][-1]['time']}")
    if stats['positions_closed']:
        print(f"   Первое закрытие: {stats['positions_closed'][0]['time']}")
        print(f"   Последнее закрытие: {stats['positions_closed'][-1]['time']}")
    print()
    
    # Сигналы
    print(f"🔔 Сигналы:")
    print(f"   Сгенерировано: {len(stats['signals_generated'])}")
    if stats['signals_generated']:
        # Подсчет по циклам
        cycles = [item for item in stats['signals_generated'] if 'Основной цикл' in item['message']]
        if cycles:
            print(f"   Торговых циклов: {len(cycles)}")
            # Извлечение количества сигналов
            total_signals = 0
            for item in cycles:
                match = re.search(r'сгенерировано (\d+)', item['message'])
                if match:
                    total_signals += int(match.group(1))
            print(f"   Всего сигналов в циклах: {total_signals}")
    print(f"   Заблокировано: {len(stats['signals_blocked'])}")
    if stats['signals_blocked']:
        # Анализ причин блокировки
        reasons = defaultdict(int)
        for item in stats['signals_blocked']:
            msg = item['message']
            if 'ADX' in msg:
                reasons['ADX тренд'] += 1
            elif 'V-образный' in msg:
                reasons['V-образный разворот'] += 1
            elif 'УЖЕ ОТКРЫТА' in msg:
                reasons['Позиция уже открыта'] += 1
            else:
                reasons['Другое'] += 1
        print(f"   Причины блокировки:")
        for reason, count in reasons.items():
            print(f"      {reason}: {count}")
    print()
    
    # ADX тренды
    print(f"📊 ADX тренды:")
    print(f"   Всего записей: {len(stats['adx_trends'])}")
    if stats['adx_trends']:
        # Анализ последних ADX значений по символам
        adx_by_symbol = defaultdict(list)
        for item in stats['adx_trends']:
            # Извлечение символа
            symbol_match = re.search(r'(\w+-USDT)', item['message'])
            if symbol_match:
                symbol = symbol_match.group(1)
                adx_by_symbol[symbol].append(item)
        
        print(f"   По символам:")
        for symbol, items in sorted(adx_by_symbol.items()):
            print(f"      {symbol}: {len(items)} записей")
            # Последнее значение ADX
            if items:
                last = items[-1]
                # Извлечение ADX значения
                adx_match = re.search(r'ADX=([\d.]+)', last['message'])
                if adx_match:
                    print(f"         Последний ADX: {adx_match.group(1)} ({last['time']})")
    print()
    
    # TP продления
    print(f"📈 Take Profit:")
    print(f"   Продлений TP: {len(stats['tp_extensions'])}")
    if stats['tp_extensions']:
        print(f"   Примеры:")
        for item in stats['tp_extensions'][-5:]:
            print(f"      {item['time']}: {item['message']}")
    print()
    
    # PnL обновления
    print(f"💰 PnL обновления:")
    print(f"   Всего: {len(stats['pnl_updates'])}")
    if stats['pnl_updates']:
        # Извлечение последних значений PnL
        print(f"   Последние значения:")
        for item in stats['pnl_updates'][-10:]:
            # Извлечение PnL из сообщения
            pnl_match = re.search(r'PnL[=:]?\s*([-+]?\d+\.?\d*)', item['message'])
            if pnl_match:
                pnl = float(pnl_match.group(1))
                symbol_match = re.search(r'(\w+-USDT)', item['message'])
                symbol = symbol_match.group(1) if symbol_match else 'N/A'
                print(f"      {item['time']} {symbol}: PnL={pnl:.4f}")
    print()
    
    # Проверки маржи
    print(f"🛡️ Проверки безопасности:")
    print(f"   Всего проверок: {len(stats['margin_checks'])}")
    safe_count = sum(1 for item in stats['margin_checks'] if 'safe=True' in item['message'])
    unsafe_count = sum(1 for item in stats['margin_checks'] if 'safe=False' in item['message'])
    print(f"   Безопасных: {safe_count}")
    print(f"   Небезопасных: {unsafe_count}")
    print()
    
    # Ошибки
    print(f"❌ Ошибки:")
    print(f"   Всего: {len(stats['errors'])}")
    if stats['errors']:
        print(f"   Последние ошибки:")
        for item in stats['errors'][-10:]:
            print(f"      {item['time']}: {item['message'][:150]}")
    print()
    
    # Предупреждения
    print(f"⚠️ Предупреждения:")
    print(f"   Всего: {len(stats['warnings'])}")
    if stats['warnings']:
        # Группировка по типам
        warning_types = defaultdict(int)
        for item in stats['warnings']:
            msg = item['message']
            if 'сигнал ОТМЕНЕН' in msg:
                warning_types['Сигналы отменены'] += 1
            elif 'ПОДОЗРИТЕЛЬНОЕ' in msg:
                warning_types['Подозрительные состояния'] += 1
            elif 'УЖЕ ОТКРЫТА' in msg:
                warning_types['Позиции уже открыты'] += 1
            else:
                warning_types['Другое'] += 1
        print(f"   По типам:")
        for wtype, count in warning_types.items():
            print(f"      {wtype}: {count}")
    print()
    
    print("=" * 80)

if __name__ == '__main__':
    log_file = Path('logs/futures/info_2025-11-29.log')
    
    if not log_file.exists():
        print(f"❌ Файл не найден: {log_file}")
        exit(1)
    
    stats = analyze_logs(log_file)
    print_report(stats)

