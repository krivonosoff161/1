#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полный анализ всех логов и архивов с начала дня
"""

import os
import re
import zipfile
from datetime import datetime
from collections import defaultdict
from pathlib import Path

def extract_from_zip(zip_path):
    """Извлекает логи из zip архива"""
    logs = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            for name in z.namelist():
                if name.endswith('.log'):
                    content = z.read(name).decode('utf-8', errors='ignore')
                    logs.append(content)
    except Exception as e:
        print(f"⚠️ Ошибка чтения {zip_path}: {e}")
    return logs

def analyze_log_content(content, log_source):
    """Анализирует содержимое лога"""
    stats = {
        'positions_opened': [],
        'positions_closed': [],
        'signals': 0,
        'profit_drawdown_closes': [],
        'profit_harvesting_closes': [],
        'tp_closes': [],
        'sl_closes': [],
        'max_pnl': defaultdict(lambda: {'max': float('-inf'), 'time': None, 'min': float('inf')}),
        'current_pnl': {},
        'errors': [],
        'warnings': 0,
    }
    
    lines = content.split('\n')
    for line in lines:
        # Открытие позиций
        if 'открыта' in line.lower() and 'позиция' in line.lower() and 'entrymanager' in line.lower():
            match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if match:
                symbol_match = re.search(r'([A-Z]+-USDT)', line)
                if symbol_match:
                    stats['positions_opened'].append({
                        'time': match.group(1),
                        'symbol': symbol_match.group(1),
                        'source': log_source
                    })
        
        # Закрытие позиций
        if 'позиция.*закрыта' in line.lower() or 'closed' in line.lower():
            match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if match:
                symbol_match = re.search(r'([A-Z]+-USDT)', line)
                reason_match = re.search(r'(profit_drawdown|profit_harvesting|take_profit|stop_loss|sl|tp)', line, re.I)
                if symbol_match:
                    stats['positions_closed'].append({
                        'time': match.group(1),
                        'symbol': symbol_match.group(1),
                        'reason': reason_match.group(1) if reason_match else 'unknown',
                        'source': log_source
                    })
        
        # Profit Drawdown
        if 'profit drawdown triggered' in line.lower():
            match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            symbol_match = re.search(r'([A-Z]+-USDT)', line)
            if match and symbol_match:
                stats['profit_drawdown_closes'].append({
                    'time': match.group(1),
                    'symbol': symbol_match.group(1),
                    'source': log_source
                })
        
        # Profit Harvesting
        if 'profit harvesting triggered' in line.lower():
            match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            symbol_match = re.search(r'([A-Z]+-USDT)', line)
            if match and symbol_match:
                stats['profit_harvesting_closes'].append({
                    'time': match.group(1),
                    'symbol': symbol_match.group(1),
                    'source': log_source
                })
        
        # PnL обновления
        pnl_match = re.search(r'PnL=([-\d.]+)', line)
        if pnl_match:
            symbol_match = re.search(r'([A-Z]+-USDT)', line)
            time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if symbol_match and time_match:
                symbol = symbol_match.group(1)
                pnl = float(pnl_match.group(1))
                time_str = time_match.group(1)
                
                if pnl > stats['max_pnl'][symbol]['max']:
                    stats['max_pnl'][symbol]['max'] = pnl
                    stats['max_pnl'][symbol]['time'] = time_str
                
                if pnl < stats['max_pnl'][symbol]['min']:
                    stats['max_pnl'][symbol]['min'] = pnl
                
                # Обновляем текущий PnL (последний в логе)
                stats['current_pnl'][symbol] = {
                    'pnl': pnl,
                    'time': time_str
                }
        
        # Сигналы
        if 'реальный сигнал' in line.lower() or 'real signal' in line.lower():
            stats['signals'] += 1
        
        # Ошибки
        if 'error' in line.lower() or '❌' in line:
            stats['errors'].append(line.strip())
        
        # Предупреждения
        if 'warning' in line.lower() or '⚠️' in line:
            stats['warnings'] += 1
    
    return stats

def main():
    log_dir = Path('logs/futures')
    
    print("=" * 80)
    print("📊 ПОЛНЫЙ АНАЛИЗ ВСЕХ ЛОГОВ С 6:30 УТРА")
    print("=" * 80)
    print()
    
    all_stats = {
        'positions_opened': [],
        'positions_closed': [],
        'signals': 0,
        'profit_drawdown_closes': [],
        'profit_harvesting_closes': [],
        'max_pnl': defaultdict(lambda: {'max': float('-inf'), 'time': None, 'min': float('inf')}),
        'current_pnl': {},
        'errors': [],
        'warnings': 0,
        'sources': []
    }
    
    # Анализируем текущие логи
    current_logs = [
        'info_2025-11-29.log',
        'futures_main_2025-11-29.log'
    ]
    
    for log_file in current_logs:
        log_path = log_dir / log_file
        if log_path.exists():
            print(f"📄 Анализ: {log_file}")
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                stats = analyze_log_content(content, log_file)
                
                all_stats['positions_opened'].extend(stats['positions_opened'])
                all_stats['positions_closed'].extend(stats['positions_closed'])
                all_stats['signals'] += stats['signals']
                all_stats['profit_drawdown_closes'].extend(stats['profit_drawdown_closes'])
                all_stats['profit_harvesting_closes'].extend(stats['profit_harvesting_closes'])
                all_stats['warnings'] += stats['warnings']
                all_stats['errors'].extend(stats['errors'])
                all_stats['sources'].append(log_file)
                
                for symbol, pnl_data in stats['max_pnl'].items():
                    if pnl_data['max'] > all_stats['max_pnl'][symbol]['max']:
                        all_stats['max_pnl'][symbol] = pnl_data
                
                all_stats['current_pnl'].update(stats['current_pnl'])
    
    # Анализируем архивы (начиная с 06:30)
    zip_files = sorted([f for f in log_dir.glob('*.zip') if '06-3' in f.name or 
                       int(f.name.split('_')[2].split('-')[3]) >= 6])
    
    print(f"\n📦 Анализ архивов (найдено {len(zip_files)} архивов)...")
    
    for zip_file in zip_files:
        print(f"   📦 {zip_file.name}")
        logs = extract_from_zip(zip_file)
        for log_content in logs:
            stats = analyze_log_content(log_content, zip_file.name)
            
            all_stats['positions_opened'].extend(stats['positions_opened'])
            all_stats['positions_closed'].extend(stats['positions_closed'])
            all_stats['signals'] += stats['signals']
            all_stats['profit_drawdown_closes'].extend(stats['profit_drawdown_closes'])
            all_stats['profit_harvesting_closes'].extend(stats['profit_harvesting_closes'])
            all_stats['warnings'] += stats['warnings']
            all_stats['errors'].extend(stats['errors'])
            all_stats['sources'].append(zip_file.name)
            
            for symbol, pnl_data in stats['max_pnl'].items():
                if pnl_data['max'] > all_stats['max_pnl'][symbol]['max']:
                    all_stats['max_pnl'][symbol] = pnl_data
            
            all_stats['current_pnl'].update(stats['current_pnl'])
    
    # Выводим результаты
    print("\n" + "=" * 80)
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 80)
    
    print(f"\n💼 Позиции:")
    print(f"   Открыто: {len(all_stats['positions_opened'])}")
    print(f"   Закрыто: {len(all_stats['positions_closed'])}")
    
    if all_stats['positions_opened']:
        first_open = min(p['time'] for p in all_stats['positions_opened'])
        last_open = max(p['time'] for p in all_stats['positions_opened'])
        print(f"   Первое открытие: {first_open}")
        print(f"   Последнее открытие: {last_open}")
    
    print(f"\n🔔 Сигналы:")
    print(f"   Всего: {all_stats['signals']}")
    
    print(f"\n💰 Закрытия:")
    print(f"   По Profit Drawdown: {len(all_stats['profit_drawdown_closes'])}")
    print(f"   По Profit Harvesting: {len(all_stats['profit_harvesting_closes'])}")
    
    print(f"\n📈 Максимальная прибыль по символам:")
    for symbol in sorted(all_stats['max_pnl'].keys()):
        pnl_data = all_stats['max_pnl'][symbol]
        if pnl_data['max'] != float('-inf'):
            current = all_stats['current_pnl'].get(symbol, {}).get('pnl', 0)
            missed = pnl_data['max'] - current if current < pnl_data['max'] else 0
            print(f"   {symbol}:")
            print(f"      Максимум: {pnl_data['max']:.4f} USDT ({pnl_data['time']})")
            print(f"      Минимум: {pnl_data['min']:.4f} USDT")
            print(f"      Текущий: {current:.4f} USDT")
            if missed > 0:
                print(f"      ⚠️ Упущенная прибыль: {missed:.4f} USDT")
    
    print(f"\n❌ Ошибки: {len(all_stats['errors'])}")
    if all_stats['errors']:
        print("   Последние 5:")
        for err in all_stats['errors'][-5:]:
            print(f"      {err[:100]}")
    
    print(f"\n⚠️ Предупреждения: {all_stats['warnings']}")
    
    print(f"\n📁 Проанализировано источников: {len(set(all_stats['sources']))}")

if __name__ == '__main__':
    main()

