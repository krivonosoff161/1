#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полный анализ данных для аудита согласно CURSOR_AUDIT_BUNDLE_TASK.md v1.2
"""

import json
import hashlib
import os
import sys
import re
from pathlib import Path
from datetime import datetime
import pandas as pd
import yaml
import platform

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
        patterns = [
            rf'{key}:\s*["\']?[^"\'\s]+["\']?',
            rf'"{key}":\s*["\']?[^"\'\s]+["\']?',
            rf'{key}\s*=\s*["\']?[^"\'\s]+["\']?',
        ]
        for pattern in patterns:
            content = re.sub(pattern, f'{key}: ***', content, flags=re.IGNORECASE)
    return content

def analyze_trades_csv(file_path):
    """Анализирует trades.csv с проверкой целостности"""
    file_path = Path(file_path)
    result = {
        "file_path": str(file_path),
        "status": "ok"
    }
    
    try:
        # Читаем CSV
        df = pd.read_csv(file_path)
        result["shape"] = {"rows": len(df), "columns": len(df.columns)}
        result["columns"] = list(df.columns)
        
        # Проверка обязательных колонок (маппинг наших колонок на требуемые)
        column_mapping = {
            "timestamp": "timestamp_close",
            "entry_price": "price_open",
            "exit_price": "price_close",
            "size": "qty",
            "commission": "fee"
        }
        
        # Проверка дубликатов
        if "timestamp" in df.columns and "symbol" in df.columns:
            duplicates = df[df.duplicated(subset=["timestamp", "symbol"], keep=False)]
            if len(duplicates) > 0:
                result["integrity_errors"] = result.get("integrity_errors", {})
                result["integrity_errors"]["duplicates"] = {
                    "count": len(duplicates),
                    "lines": duplicates.index.tolist()
                }
        
        # Проверка пропусков
        missing_values = {}
        for col in df.columns:
            null_count = df[col].isnull().sum()
            if null_count > 0:
                missing_values[col] = {
                    "count": int(null_count),
                    "lines": df[df[col].isnull()].index.tolist()
                }
        if missing_values:
            result["integrity_errors"] = result.get("integrity_errors", {})
            result["integrity_errors"]["missing_values"] = missing_values
        
        # Проверка знаков qty/size
        if "side" in df.columns and "size" in df.columns:
            violations = []
            for idx, row in df.iterrows():
                side = str(row["side"]).lower()
                size = float(row["size"]) if pd.notna(row["size"]) else 0
                if side == "long" and size < 0:
                    violations.append({"line": int(idx), "side": side, "size": size})
                elif side == "short" and size > 0:
                    violations.append({"line": int(idx), "side": side, "size": size})
            if violations:
                result["integrity_errors"] = result.get("integrity_errors", {})
                result["integrity_errors"]["qty_signs"] = {"violations": violations}
        
        # Статистика
        result["total_trades"] = len(df)
        if "net_pnl" in df.columns:
            winning = df[df["net_pnl"] > 0]
            losing = df[df["net_pnl"] < 0]
            result["winning_trades"] = len(winning)
            result["losing_trades"] = len(losing)
            result["total_pnl"] = float(df["net_pnl"].sum())
        
        if "symbol" in df.columns:
            result["symbols"] = df["symbol"].unique().tolist()
        
        if "timestamp" in df.columns:
            result["date_range"] = {
                "start": str(df["timestamp"].min()),
                "end": str(df["timestamp"].max())
            }
        
        return result
        
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result

def main():
    """Основная функция анализа"""
    print("=" * 70)
    print("📋 ПОЛНЫЙ АНАЛИЗ ДАННЫХ ДЛЯ АУДИТА")
    print("   Согласно CURSOR_AUDIT_BUNDLE_TASK.md v1.2")
    print("=" * 70)
    
    bundle = {
        "metadata": {
            "bundle_id": f"audit_bundle_{datetime.now().strftime('%Y%m%d')}_futures_scalping",
            "created_at": datetime.now().isoformat(),
            "created_by": "Cursor AI",
            "strategy_name": "futures_scalping",
            "strategy_version": "1.0",
            "project_root": str(Path.cwd())
        },
        "environment": {
            "python_version": sys.version.split()[0],
            "os": platform.system() + " " + platform.release(),
            "platform": platform.platform()
        },
        "timezone": {
            "exchange": "UTC",
            "strategy": "UTC",
            "note": "All timestamps in logs are UTC"
        },
        "trading_mode": {
            "type": "live",
            "sandbox": True,
            "description": "Live trading on OKX sandbox (demo account)"
        },
        "files": {},
        "integrity_errors": []
    }
    
    # 1. Конфигурация
    print("\n1️⃣ Конфигурационные файлы...")
    config_file = Path("config/config_futures.yaml")
    if config_file.exists():
        print(f"   ✅ {config_file}")
        stat = config_file.stat()
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
        content_redacted = redact_secrets(content, ['api_key', 'secret', 'passphrase'])
        bundle["files"]["config"] = {
            "status": "ok",
            "file_path": str(config_file),
            "file_size_bytes": stat.st_size,
            "date_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "md5_hash": hashlib.md5(content_redacted.encode()).hexdigest(),
            "md5_hash_original": hashlib.md5(content.encode()).hexdigest()
        }
    else:
        print(f"   ⚠️ {config_file} не найден")
        bundle["integrity_errors"].append({"file": "config", "error": "File not found"})
    
    # 2. Strategy файл
    print("\n2️⃣ Файл стратегии...")
    strategy_file = Path("src/strategies/scalping/futures/orchestrator.py")
    if strategy_file.exists():
        print(f"   ✅ {strategy_file}")
        stat = strategy_file.stat()
        bundle["files"]["strategy"] = {
            "status": "ok",
            "file_path": str(strategy_file),
            "file_size_bytes": stat.st_size,
            "date_modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
        }
    else:
        print(f"   ⚠️ {strategy_file} не найден")
    
    # 3. Trades CSV
    print("\n3️⃣ Файлы сделок...")
    trades_file = Path("logs/futures/archived/logs_2025-12-07_16-03-39/trades_2025-12-07.csv")
    if trades_file.exists():
        print(f"   ✅ {trades_file}")
        stat = trades_file.stat()
        analysis = analyze_trades_csv(trades_file)
        analysis["file_size_bytes"] = stat.st_size
        analysis["date_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        analysis["md5_hash"] = calculate_md5(trades_file)
        bundle["files"]["trades"] = analysis
    else:
        print(f"   ⚠️ {trades_file} не найден")
        bundle["integrity_errors"].append({"file": "trades", "error": "File not found", "severity": "critical"})
    
    # 4. Orders CSV
    print("\n4️⃣ Файлы ордеров...")
    # Ищем в активной папке, затем в архиве, затем в распакованном архиве
    orders_files = list(Path("logs/futures").glob("orders_*.csv"))
    if not orders_files:
        orders_files = list(Path("logs/futures/archived/logs_2025-12-07_16-03-39").glob("orders_*.csv"))
    if not orders_files:
        orders_files = list(Path("logs/futures/archived/logs_2025-12-07_16-03-39_extracted").glob("orders_*.csv"))
    if orders_files:
        latest_orders = max(orders_files, key=lambda p: p.stat().st_mtime)
        print(f"   ✅ {latest_orders}")
        stat = latest_orders.stat()
        bundle["files"]["orders"] = {
            "status": "ok",
            "file_path": str(latest_orders),
            "file_size_bytes": stat.st_size,
            "date_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "md5_hash": calculate_md5(latest_orders)
        }
    else:
        print("   ⚠️ orders_*.csv не найден")
        bundle["files"]["orders"] = {"status": "missing", "reason": "File not found"}
    
    # 5. Positions Open CSV
    print("\n5️⃣ Файлы открытых позиций...")
    positions_files = list(Path("logs/futures").glob("positions_open_*.csv"))
    if not positions_files:
        positions_files = list(Path("logs/futures/archived/logs_2025-12-07_16-03-39").glob("positions_open_*.csv"))
    if not positions_files:
        positions_files = list(Path("logs/futures/archived/logs_2025-12-07_16-03-39_extracted").glob("positions_open_*.csv"))
    if positions_files:
        latest_positions = max(positions_files, key=lambda p: p.stat().st_mtime)
        print(f"   ✅ {latest_positions}")
        stat = latest_positions.stat()
        bundle["files"]["positions_open"] = {
            "status": "ok",
            "file_path": str(latest_positions),
            "file_size_bytes": stat.st_size,
            "date_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "md5_hash": calculate_md5(latest_positions)
        }
    else:
        print("   ⚠️ positions_open_*.csv не найден")
        bundle["files"]["positions_open"] = {"status": "missing", "reason": "File not found"}
    
    # 6. Signals CSV
    print("\n6️⃣ Файлы сигналов...")
    signals_files = list(Path("logs/futures").glob("signals_*.csv"))
    if not signals_files:
        signals_files = list(Path("logs/futures/archived/logs_2025-12-07_16-03-39").glob("signals_*.csv"))
    if not signals_files:
        signals_files = list(Path("logs/futures/archived/logs_2025-12-07_16-03-39_extracted").glob("signals_*.csv"))
    if signals_files:
        latest_signals = max(signals_files, key=lambda p: p.stat().st_mtime)
        print(f"   ✅ {latest_signals}")
        stat = latest_signals.stat()
        bundle["files"]["signals"] = {
            "status": "ok",
            "file_path": str(latest_signals),
            "file_size_bytes": stat.st_size,
            "date_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "md5_hash": calculate_md5(latest_signals)
        }
    else:
        print("   ⚠️ signals_*.csv не найден")
        bundle["files"]["signals"] = {"status": "missing", "reason": "File not found"}
    
    # Сохраняем результат
    output_file = f"audit_bundle_{datetime.now().strftime('%Y%m%d')}_futures_scalping.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'=' * 70}")
    print(f"✅ Результат сохранен в: {output_file}")
    print(f"\n📊 Статистика:")
    ok_files = len([f for f in bundle['files'].values() if isinstance(f, dict) and f.get('status') == 'ok'])
    missing_files = len([f for f in bundle['files'].values() if isinstance(f, dict) and f.get('status') == 'missing'])
    errors = len(bundle['integrity_errors'])
    print(f"   ✅ Файлов обработано: {ok_files}")
    print(f"   ⚠️ Файлов не найдено: {missing_files}")
    print(f"   ❌ Ошибок целостности: {errors}")
    
    if bundle.get('files', {}).get('trades', {}).get('total_trades'):
        print(f"\n📈 Статистика сделок:")
        trades = bundle['files']['trades']
        print(f"   Всего сделок: {trades.get('total_trades', 0)}")
        print(f"   Прибыльных: {trades.get('winning_trades', 0)}")
        print(f"   Убыточных: {trades.get('losing_trades', 0)}")
        print(f"   Общий PnL: {trades.get('total_pnl', 0):.4f} USDT")
    
    print(f"{'=' * 70}\n")
    
    return bundle

if __name__ == "__main__":
    main()

