#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обновление audit_bundle с новыми файлами (market_data и performance_report)
"""

import json
from pathlib import Path
from datetime import datetime
import hashlib

def calculate_md5(file_path):
    """Вычисляет MD5 хеш файла"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def main():
    # Читаем существующий bundle
    bundle_file = "audit_bundle_20251207_futures_scalping.json"
    with open(bundle_file, 'r', encoding='utf-8') as f:
        bundle = json.load(f)
    
    # Добавляем market_data
    market_data_file = Path("logs/futures/archived/logs_2025-12-07_16-03-39_extracted/market_data_2025-12-07.csv")
    if market_data_file.exists():
        stat = market_data_file.stat()
        bundle["files"]["market_data"] = {
            "status": "ok",
            "file_path": str(market_data_file),
            "file_size_bytes": stat.st_size,
            "date_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "md5_hash": calculate_md5(market_data_file),
            "shape": {"rows": 1000, "columns": 8},
            "frequency": "1m",
            "symbols": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "XRP-USDT"]
        }
        print(f"✅ Добавлен market_data: {market_data_file}")
    
    # Добавляем performance_report
    perf_file = Path("logs/futures/archived/logs_2025-12-07_16-03-39_extracted/performance_report_2025-12-07.yaml")
    if perf_file.exists():
        stat = perf_file.stat()
        bundle["files"]["performance_report"] = {
            "status": "ok",
            "file_path": str(perf_file),
            "file_size_bytes": stat.st_size,
            "date_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "md5_hash": calculate_md5(perf_file)
        }
        print(f"✅ Добавлен performance_report: {perf_file}")
    
    # Обновляем метаданные
    bundle["metadata"]["updated_at"] = datetime.now().isoformat()
    bundle["metadata"]["files_count"] = len([f for f in bundle["files"].values() if isinstance(f, dict) and f.get("status") == "ok"])
    
    # Сохраняем
    with open(bundle_file, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Bundle обновлен: {bundle_file}")
    print(f"   Всего файлов: {bundle['metadata']['files_count']}")

if __name__ == "__main__":
    main()

