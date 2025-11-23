#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полный анализ ВСЕХ логов: текущих, архивных, zip и CSV
"""

import sys
import zipfile
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import re

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def extract_zip_log(zip_path):
    """Извлечь и прочитать лог из zip архива"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_name in zip_ref.namelist():
                if file_name.endswith('.log'):
                    content = zip_ref.read(file_name).decode('utf-8', errors='ignore')
                    return content.splitlines()
    except Exception as e:
        print(f"⚠️ Ошибка чтения {zip_path}: {e}")
    return []

def analyze_log_content(lines, source_name):
    """Анализ содержимого лога"""
    stats = {
        'source': source_name,
        'total_lines': len(lines),
        'errors': [],
        'warnings': [],
        'opened': [],
        'closed': [],
        'start_time': None,
        'end_time': None,
    }
    
    for line in lines:
        # Время
        time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        if time_match:
            if not stats['start_time']:
                stats['start_time'] = time_match.group(1)
            stats['end_time'] = time_match.group(1)
        
        # Ошибки
        if 'ERROR' in line or 'CRITICAL' in line:
            stats['errors'].append(line)
        
        # Предупреждения
        if 'WARNING' in line:
            stats['warnings'].append(line)
        
        # Открытия позиций
        if ('открыт' in line.lower() or 'open' in line.lower()) and '✅' in line:
            stats['opened'].append(line)
        
        # Закрытия позиций
        if ('закрыт' in line.lower() or 'close' in line.lower()) and ('✅' in line or '❌' in line):
            stats['closed'].append(line)
    
    return stats

def analyze_csv(csv_path):
    """Анализ CSV файла"""
    stats = {
        'source': csv_path.name,
        'total_events': 0,
        'opens': 0,
        'closes': 0,
        'tsl_creates': 0,
        'last_close': None,
    }
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                stats['total_events'] += 1
                event_type = row.get('event_type', '')
                if event_type == 'open':
                    stats['opens'] += 1
                elif event_type == 'close':
                    stats['closes'] += 1
                    stats['last_close'] = row
                elif event_type == 'tsl_create':
                    stats['tsl_creates'] += 1
    except Exception as e:
        print(f"⚠️ Ошибка чтения CSV {csv_path}: {e}")
    
    return stats

def main():
    """Главная функция"""
    print("="*80)
    print("📊 ПОЛНЫЙ АНАЛИЗ ВСЕХ ЛОГОВ")
    print("="*80)
    
    futures_dir = Path("logs/futures")
    if not futures_dir.exists():
        print("❌ Папка logs/futures не найдена")
        return
    
    # Собираем все файлы
    all_stats = []
    
    # 1. Текущий лог файл
    current_log = futures_dir / "futures_main_2025-11-23.log"
    if current_log.exists():
        print(f"\n📄 Анализ текущего лога: {current_log.name}")
        lines = current_log.read_text(encoding='utf-8', errors='ignore').splitlines()
        stats = analyze_log_content(lines, current_log.name)
        all_stats.append(stats)
        print(f"   Строк: {stats['total_lines']}, Ошибок: {len(stats['errors'])}, Открытий: {len(stats['opened'])}, Закрытий: {len(stats['closed'])}")
    
    # 2. ZIP архивы в основной папке
    zip_files = sorted(futures_dir.glob("*.zip"))
    print(f"\n📦 Найдено ZIP архивов в основной папке: {len(zip_files)}")
    
    for zip_file in zip_files:
        print(f"   Анализ: {zip_file.name}")
        lines = extract_zip_log(zip_file)
        if lines:
            stats = analyze_log_content(lines, zip_file.name)
            all_stats.append(stats)
            print(f"      Строк: {stats['total_lines']}, Ошибок: {len(stats['errors'])}, Открытий: {len(stats['opened'])}, Закрытий: {len(stats['closed'])}")
    
    # 3. Архивные логи
    archived_dir = futures_dir / "archived" / "logs_2025-11-23_18-26-46"
    if archived_dir.exists():
        archived_zips = sorted(archived_dir.glob("*.zip"))
        print(f"\n📦 Найдено ZIP архивов в архиве: {len(archived_zips)}")
        
        for zip_file in archived_zips[:5]:  # Первые 5 для примера
            print(f"   Анализ: {zip_file.name}")
            lines = extract_zip_log(zip_file)
            if lines:
                stats = analyze_log_content(lines, zip_file.name)
                all_stats.append(stats)
    
    # 4. Debug CSV
    debug_csv = futures_dir / "debug" / "debug_20251123_182710.csv"
    if debug_csv.exists():
        print(f"\n📊 Анализ Debug CSV: {debug_csv.name}")
        csv_stats = analyze_csv(debug_csv)
        print(f"   Всего событий: {csv_stats['total_events']}")
        print(f"   Открытий: {csv_stats['opens']}")
        print(f"   Закрытий: {csv_stats['closes']}")
        print(f"   TSL создано: {csv_stats['tsl_creates']}")
    
    # Итоговая статистика
    print("\n" + "="*80)
    print("📈 ИТОГОВАЯ СТАТИСТИКА")
    print("="*80)
    
    total_lines = sum(s['total_lines'] for s in all_stats)
    total_errors = sum(len(s['errors']) for s in all_stats)
    total_warnings = sum(len(s['warnings']) for s in all_stats)
    total_opened = sum(len(s['opened']) for s in all_stats)
    total_closed = sum(len(s['closed']) for s in all_stats)
    
    print(f"\nВсего проанализировано файлов: {len(all_stats)}")
    print(f"Всего строк: {total_lines:,}")
    print(f"Ошибок: {total_errors}")
    print(f"Предупреждений: {total_warnings:,}")
    print(f"Открытий позиций: {total_opened}")
    print(f"Закрытий позиций: {total_closed}")
    
    # Время работы
    if all_stats:
        first_start = min(s['start_time'] for s in all_stats if s['start_time'])
        last_end = max(s['end_time'] for s in all_stats if s['end_time'])
        
        if first_start and last_end:
            try:
                start_dt = datetime.strptime(first_start, '%Y-%m-%d %H:%M:%S')
                end_dt = datetime.strptime(last_end, '%Y-%m-%d %H:%M:%S')
                uptime = end_dt - start_dt
                hours = uptime.total_seconds() / 3600
                print(f"\n⏰ ВРЕМЯ РАБОТЫ:")
                print(f"   Первый запуск: {first_start}")
                print(f"   Последняя активность: {last_end}")
                print(f"   Общее время: {int(hours)}ч {int((uptime.total_seconds() % 3600) / 60)}мин")
            except:
                pass
    
    # Типы ошибок
    error_types = defaultdict(int)
    for stats in all_stats:
        for err in stats['errors']:
            if 'Partial TP' in err:
                error_types['Partial TP'] += 1
            elif 'Размер позиции' in err:
                error_types['Размер позиции'] += 1
            elif 'Exception' in err or 'Traceback' in err:
                error_types['Exception'] += 1
    
    if error_types:
        print(f"\n⚠️ ТИПЫ ОШИБОК:")
        for err_type, count in error_types.items():
            print(f"   {err_type}: {count}")
    
    print("\n" + "="*80)
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print("="*80)

if __name__ == "__main__":
    main()

