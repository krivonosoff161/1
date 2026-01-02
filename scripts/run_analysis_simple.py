#!/usr/bin/env python3
"""
Упрощенный скрипт для быстрого запуска анализа
"""
import sys
import os
from pathlib import Path

# Добавляем корневую директорию в путь
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

if __name__ == "__main__":
    try:
        from scripts.analyze_price_after_close import main
        import asyncio
        print("🚀 Запуск анализа движения цены после закрытия позиций...")
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


