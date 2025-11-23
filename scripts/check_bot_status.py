#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка статуса бота и времени работы
"""

import sys
from pathlib import Path
from datetime import datetime
import re

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def analyze_bot_status():
    """Анализ статуса бота"""
    log_file = Path("logs/futures/futures_main_2025-11-23.log")
    
    if not log_file.exists():
        print("❌ Лог файл не найден")
        return
    
    lines = log_file.read_text(encoding='utf-8').splitlines()
    
    # Время запуска
    first_line = lines[0] if lines else ''
    start_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', first_line)
    
    # Время последней записи
    last_line = lines[-1] if lines else ''
    last_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', last_line)
    
    if start_match and last_match:
        start_time = datetime.strptime(start_match.group(1), '%Y-%m-%d %H:%M:%S')
        last_time = datetime.strptime(last_match.group(1), '%Y-%m-%d %H:%M:%S')
        uptime = last_time - start_time
        
        hours = uptime.total_seconds() / 3600
        minutes = (uptime.total_seconds() % 3600) / 60
        
        print("="*80)
        print("📊 СТАТУС БОТА")
        print("="*80)
        print(f"\n⏰ ВРЕМЯ РАБОТЫ:")
        print(f"   Запуск: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Последняя активность: {last_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Время работы: {int(hours)}ч {int(minutes)}мин ({uptime})")
    
    # Статистика
    errors = [l for l in lines if 'ERROR' in l or 'CRITICAL' in l]
    warnings = [l for l in lines if 'WARNING' in l]
    
    # Открытые позиции
    opened = [l for l in lines if 'позиция' in l.lower() and 'открыт' in l.lower() and '✅' in l]
    closed = [l for l in lines if 'позиция' in l.lower() and 'закрыт' in l.lower() and ('✅' in l or '❌' in l)]
    
    # Активные позиции
    active_positions = []
    for line in reversed(lines[-500:]):  # Проверяем последние 500 строк
        if 'УЖЕ ОТКРЫТА' in line or 'активных позиций' in line.lower():
            active_positions.append(line)
            if len(active_positions) >= 5:
                break
    
    print(f"\n📈 СТАТИСТИКА:")
    print(f"   Всего строк в логе: {len(lines)}")
    print(f"   Ошибок (ERROR/CRITICAL): {len(errors)}")
    print(f"   Предупреждений (WARNING): {len(warnings)}")
    print(f"   Позиций открыто: {len(opened)}")
    print(f"   Позиций закрыто: {len(closed)}")
    
    # Критические ошибки
    critical_errors = [e for e in errors if 'CRITICAL' in e or 'Exception' in e or 'Traceback' in e]
    if critical_errors:
        print(f"\n🔴 КРИТИЧЕСКИЕ ОШИБКИ: {len(critical_errors)}")
        for err in critical_errors[:5]:
            print(f"   {err[:150]}")
    else:
        print(f"\n✅ Критических ошибок не обнаружено")
    
    # Частые ошибки
    error_types = {}
    for err in errors:
        if 'Partial TP' in err:
            error_types['Partial TP ошибки'] = error_types.get('Partial TP ошибки', 0) + 1
        elif 'Размер позиции' in err:
            error_types['Размер позиции'] = error_types.get('Размер позиции', 0) + 1
    
    if error_types:
        print(f"\n⚠️ ЧАСТЫЕ ОШИБКИ:")
        for err_type, count in error_types.items():
            print(f"   {err_type}: {count}")
    
    # Активные позиции
    if active_positions:
        print(f"\n📍 АКТИВНЫЕ ПОЗИЦИИ (последние записи):")
        for pos in active_positions[:3]:
            print(f"   {pos[:150]}")
    
    print("\n" + "="*80)
    
    # Оценка
    if len(critical_errors) == 0 and len(errors) < 20:
        print("✅ СТАТУС: БОТ РАБОТАЕТ СТАБИЛЬНО")
    elif len(critical_errors) == 0:
        print("⚠️ СТАТУС: ЕСТЬ НЕКРИТИЧЕСКИЕ ОШИБКИ")
    else:
        print("🔴 СТАТУС: ОБНАРУЖЕНЫ КРИТИЧЕСКИЕ ОШИБКИ")
    
    print("="*80)

if __name__ == "__main__":
    analyze_bot_status()

