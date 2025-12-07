#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ данных для аудита согласно CURSOR_AUDIT_BUNDLE_TASK.md
"""

import json
import hashlib
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
import yaml

def calculate_md5(file_path):
    """Вычисляет MD5 хеш файла"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def redact_secrets(content, keys_to_redact):
    """Удаляет секреты перед вычислением хеша"""
    for key in keys_to_redact:
        # Простая замена ключей в тексте
        import re
        patterns = [
            rf'{key}:\s*["\']?[^"\'\s]+["\']?',
            rf'"{key}":\s*["\']?[^"\'\s]+["\']?',
            rf'{key}\s*=\s*["\']?[^"\'\s]+["\']?',
        ]
        for pattern in patterns:
            content = re.sub(pattern, f'{key}: ***', content, flags=re.IGNORECASE)
    return content

def analyze_file(file_path, required_columns=None):
    """Анализирует файл и возвращает метаданные"""
    file_path = Path(file_path)
    if not file_path.exists():
        return {"status": "missing", "error": "File not found"}
    
    try:
        # Метаданные файла
        stat = file_path.stat()
        file_size = stat.st_size
        
        if file_size == 0:
            return {"status": "missing", "error": "Zero-byte file"}
        
        # Читаем содержимое для хеша (с редактированием секретов)
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Редактируем секреты перед хешем
        secrets = ['api_key', 'secret', 'passphrase', 'private_key']
        content_redacted = redact_secrets(content, secrets)
        md5_hash = hashlib.md5(content_redacted.encode('utf-8')).hexdigest()
        md5_hash_original = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        # Правильный относительный путь
        try:
            rel_path = str(file_path.relative_to(Path.cwd()))
        except ValueError:
            # Если не получается относительно, используем путь как есть
            rel_path = str(file_path).replace(str(Path.cwd()), "").lstrip("\\/")
        
        result = {
            "status": "ok",
            "file_path": rel_path,
            "absolute_path": str(file_path.absolute()),
            "file_size_bytes": file_size,
            "date_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "md5_hash": md5_hash,
            "md5_hash_original": md5_hash_original,
        }
        
        # Если это CSV или можно прочитать как таблицу
        if file_path.suffix.lower() in ['.csv', '.parquet']:
            try:
                if file_path.suffix.lower() == '.csv':
                    try:
                        df = pd.read_csv(file_path, encoding='utf-8')
                    except UnicodeDecodeError:
                        # Пробуем другие кодировки
                        for enc in ['utf-8-sig', 'cp1251', 'koi8-r']:
                            try:
                                df = pd.read_csv(file_path, encoding=enc)
                                break
                            except:
                                continue
                        else:
                            raise
                else:
                    df = pd.read_parquet(file_path)
                
                result["shape"] = {"rows": len(df), "columns": len(df.columns)}
                result["columns"] = list(df.columns)
                
                # Словарь колонок
                columns_dict = {}
                for col in df.columns:
                    col_type = str(df[col].dtype)
                    columns_dict[col] = {
                        "type": col_type,
                        "description": f"Column {col}",
                        "sample_values": df[col].head(3).tolist() if len(df) > 0 else []
                    }
                result["columns_dict"] = columns_dict
                
                # Проверка обязательных колонок
                if required_columns:
                    missing = [col for col in required_columns if col not in df.columns]
                    if missing:
                        result["status"] = "error"
                        result["error"] = f"Missing required columns: {missing}"
                        result["missing_columns"] = missing
                
            except Exception as e:
                result["status"] = "error"
                result["error"] = f"Failed to read as table: {str(e)}"
        
        return result
        
    except Exception as e:
        return {"status": "error", "error": str(e)}

def main():
    """Основная функция анализа"""
    print("📋 АНАЛИЗ ДАННЫХ ДЛЯ АУДИТА")
    print("=" * 60)
    
    bundle = {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "strategy_name": "futures_scalping",
            "version": "1.2"
        },
        "files": {},
        "integrity_errors": []
    }
    
    # 1. Конфигурация
    print("\n1. Конфигурационные файлы...")
    config_files = [
        "config/config_futures.yaml",
        "config.yaml"
    ]
    
    for config_file in config_files:
        if Path(config_file).exists():
            print(f"   ✅ {config_file}")
            bundle["files"]["config"] = analyze_file(config_file)
            break
    
    # 2. Strategy файл
    print("\n2. Файл стратегии...")
    strategy_files = [
        "src/strategies/scalping/futures/orchestrator.py",
        "src/strategies/scalping/futures/signal_generator.py"
    ]
    
    for strategy_file in strategy_files:
        if Path(strategy_file).exists():
            print(f"   ✅ {strategy_file}")
            bundle["files"]["strategy"] = analyze_file(strategy_file)
            break
    
    # 3. Trades CSV
    print("\n3. Файлы сделок...")
    target_folder = Path("logs/futures/archived/logs_2025-12-07_16-03-39")
    trades_file = target_folder / "trades_2025-12-07.csv"
    
    if trades_file.exists():
        print(f"   ✅ {trades_file}")
        required_columns = [
            "trade_id", "timestamp_open", "timestamp_close", 
            "side", "qty", "price_open", "price_close", 
            "fee", "symbol"
        ]
        bundle["files"]["trades"] = analyze_file(trades_file, required_columns)
    else:
        print(f"   ⚠️ {trades_file} не найден")
        bundle["integrity_errors"].append({
            "file": "trades_2025-12-07.csv",
            "error": "File not found",
            "severity": "critical"
        })
    
    # 4. Orders CSV
    print("\n4. Файлы ордеров...")
    orders_files = list(Path("logs/futures").glob("orders_*.csv"))
    if orders_files:
        latest_orders = max(orders_files, key=lambda p: p.stat().st_mtime)
        print(f"   ✅ {latest_orders}")
        required_columns = [
            "order_id", "timestamp_submit", "timestamp_fill",
            "side", "type", "qty", "price", "status"
        ]
        bundle["files"]["orders"] = analyze_file(latest_orders, required_columns)
    else:
        print("   ⚠️ orders_*.csv не найден")
    
    # 5. Positions Open CSV
    print("\n5. Файлы открытых позиций...")
    positions_files = list(Path("logs/futures").glob("positions_open_*.csv"))
    if positions_files:
        latest_positions = max(positions_files, key=lambda p: p.stat().st_mtime)
        print(f"   ✅ {latest_positions}")
        bundle["files"]["positions_open"] = analyze_file(latest_positions)
    else:
        print("   ⚠️ positions_open_*.csv не найден")
    
    # 6. Signals CSV
    print("\n6. Файлы сигналов...")
    signals_files = list(Path("logs/futures").glob("signals_*.csv"))
    if signals_files:
        latest_signals = max(signals_files, key=lambda p: p.stat().st_mtime)
        print(f"   ✅ {latest_signals}")
        bundle["files"]["signals"] = analyze_file(latest_signals)
    else:
        print("   ⚠️ signals_*.csv не найден")
    
    # Сохраняем результат
    output_file = f"audit_bundle_{datetime.now().strftime('%Y%m%d')}_futures_scalping.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Результат сохранен в: {output_file}")
    print(f"\n📊 Статистика:")
    print(f"   Файлов обработано: {len([f for f in bundle['files'].values() if f.get('status') == 'ok'])}")
    print(f"   Ошибок: {len(bundle['integrity_errors'])}")
    
    return bundle

if __name__ == "__main__":
    main()

