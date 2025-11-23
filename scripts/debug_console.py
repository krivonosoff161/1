#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔬 ИНТЕРАКТИВНАЯ DEBUG КОНСОЛЬ

Интерактивная консоль для отладки торгового бота в реальном времени.
Позволяет:
- Проверять состояние бота
- Просматривать открытые позиции
- Анализировать сигналы
- Проверять параметры конфигурации
- Мониторить логи в реальном времени
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from src.config import BotConfig, load_config


class DebugConsole:
    """Интерактивная консоль для отладки"""
    
    def __init__(self):
        self.config: Optional[BotConfig] = None
        self.running = True
        
    def print_header(self):
        """Печать заголовка"""
        print("\n" + "="*80)
        print("🔬 ИНТЕРАКТИВНАЯ DEBUG КОНСОЛЬ".center(80))
        print("="*80)
        print("\nДоступные команды:")
        print("  1. config      - Показать конфигурацию")
        print("  2. check       - Проверить конфигурацию")
        print("  3. positions   - Показать открытые позиции")
        print("  4. signals     - Проверить сигналы")
        print("  5. params      - Показать параметры для символа")
        print("  6. logs        - Показать последние логи")
        print("  7. balance     - Проверить баланс")
        print("  8. help        - Показать справку")
        print("  9. exit        - Выход")
        print("\n" + "-"*80 + "\n")
    
    def load_config(self):
        """Загрузка конфигурации"""
        try:
            self.config = load_config()
            print("✅ Конфигурация загружена успешно")
            return True
        except Exception as e:
            print(f"❌ Ошибка загрузки конфигурации: {e}")
            return False
    
    def show_config(self):
        """Показать конфигурацию"""
        if not self.config:
            print("⚠️ Конфигурация не загружена. Используйте команду 'config' для загрузки.")
            return
        
        print("\n📋 КОНФИГУРАЦИЯ:")
        print("-"*80)
        
        if hasattr(self.config, 'scalping'):
            scalping = self.config.scalping
            print(f"✅ Scalping enabled: {getattr(scalping, 'enabled', 'N/A')}")
            print(f"✅ Symbols: {getattr(scalping, 'symbols', [])}")
            print(f"✅ Leverage: {getattr(scalping, 'leverage', 'N/A')}")
            print(f"✅ TP: {getattr(scalping, 'tp_percent', 'N/A')}%")
            print(f"✅ SL: {getattr(scalping, 'sl_percent', 'N/A')}%")
        
        print("-"*80)
    
    def check_config(self):
        """Проверить конфигурацию"""
        if not self.config:
            print("⚠️ Конфигурация не загружена.")
            return
        
        print("\n🔍 ПРОВЕРКА КОНФИГУРАЦИИ:")
        print("-"*80)
        
        issues = []
        
        # Проверка основных параметров
        if hasattr(self.config, 'scalping'):
            scalping = self.config.scalping
            if not getattr(scalping, 'enabled', False):
                issues.append("⚠️ Scalping отключен")
            
            symbols = getattr(scalping, 'symbols', [])
            if not symbols:
                issues.append("❌ Символы не настроены")
            else:
                print(f"✅ Символы: {', '.join(symbols)}")
            
            tp = getattr(scalping, 'tp_percent', None)
            sl = getattr(scalping, 'sl_percent', None)
            if tp is None:
                issues.append("⚠️ TP не настроен")
            else:
                print(f"✅ TP: {tp}%")
            
            if sl is None:
                issues.append("⚠️ SL не настроен")
            else:
                print(f"✅ SL: {sl}%")
        
        # Проверка API
        if hasattr(self.config, 'api'):
            api = self.config.api
            if 'okx' in api:
                okx = api['okx']
                sandbox = okx.get('sandbox', True)
                print(f"✅ OKX API: {'Sandbox' if sandbox else 'Production'}")
        
        if issues:
            print("\n⚠️ Обнаружены проблемы:")
            for issue in issues:
                print(f"  {issue}")
        else:
            print("\n✅ Конфигурация в порядке!")
        
        print("-"*80)
    
    def show_positions(self):
        """Показать открытые позиции"""
        print("\n📍 ОТКРЫТЫЕ ПОЗИЦИИ:")
        print("-"*80)
        print("⚠️ Для просмотра позиций нужен запущенный бот")
        print("   Используйте логи или WebSocket для получения актуальных данных")
        print("-"*80)
    
    async def check_signals(self):
        """Проверить сигналы"""
        print("\n📊 ПРОВЕРКА СИГНАЛОВ:")
        print("-"*80)
        print("⚠️ Для проверки сигналов нужен запущенный бот")
        print("   Используйте логи или запустите bot_full_simulator.py")
        print("-"*80)
    
    def show_params(self, symbol: str = None):
        """Показать параметры для символа"""
        if not symbol:
            symbol = input("Введите символ (например, BTC-USDT): ").strip()
        
        if not self.config:
            print("⚠️ Конфигурация не загружена.")
            return
        
        print(f"\n⚙️ ПАРАМЕТРЫ ДЛЯ {symbol}:")
        print("-"*80)
        
        # Здесь можно добавить логику получения параметров из конфига
        print("⚠️ Функция в разработке")
        print("   Используйте config_futures.yaml для просмотра параметров")
        print("-"*80)
    
    def show_logs(self, lines: int = 50):
        """Показать последние логи"""
        print(f"\n📝 ПОСЛЕДНИЕ {lines} СТРОК ЛОГОВ:")
        print("-"*80)
        
        log_files = list(Path("logs/futures").glob("*.log"))
        if not log_files:
            print("⚠️ Логи не найдены")
            return
        
        # Берем последний лог файл
        latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
        
        try:
            with open(latest_log, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                print(''.join(last_lines))
        except Exception as e:
            print(f"❌ Ошибка чтения логов: {e}")
        
        print("-"*80)
    
    async def check_balance(self):
        """Проверить баланс"""
        print("\n💰 ПРОВЕРКА БАЛАНСА:")
        print("-"*80)
        print("⚠️ Для проверки баланса нужен запущенный бот")
        print("   Используйте: python tests/debug/check_balance.py")
        print("-"*80)
    
    def show_help(self):
        """Показать справку"""
        print("\n📖 СПРАВКА:")
        print("-"*80)
        print("""
Доступные команды:

1. config      - Загрузить и показать конфигурацию
2. check       - Проверить конфигурацию на ошибки
3. positions   - Показать открытые позиции (требует запущенный бот)
4. signals     - Проверить сигналы (требует запущенный бот)
5. params      - Показать параметры для символа
6. logs        - Показать последние логи
7. balance     - Проверить баланс (требует запущенный бот)
8. help        - Показать эту справку
9. exit        - Выход из консоли

Дополнительные инструменты:
- python tests/debug/bot_full_simulator.py  - Полная симуляция бота
- python tests/debug/check_balance.py       - Проверка баланса
- python scripts/validate_configs.py        - Валидация конфигов
- python scripts/deep_config_analysis.py   - Глубокий анализ конфигов
        """)
        print("-"*80)
    
    async def run(self):
        """Запуск интерактивной консоли"""
        self.print_header()
        
        # Автоматически загружаем конфигурацию
        if not self.load_config():
            print("⚠️ Продолжаем без конфигурации...")
        
        while self.running:
            try:
                command = input("🔬 debug> ").strip().lower()
                
                if not command:
                    continue
                
                if command == "exit" or command == "quit" or command == "q":
                    print("\n👋 До свидания!")
                    self.running = False
                    break
                
                elif command == "config":
                    self.load_config()
                    self.show_config()
                
                elif command == "check":
                    self.check_config()
                
                elif command == "positions":
                    self.show_positions()
                
                elif command == "signals":
                    await self.check_signals()
                
                elif command == "params":
                    self.show_params()
                
                elif command == "logs":
                    self.show_logs()
                
                elif command == "balance":
                    await self.check_balance()
                
                elif command == "help" or command == "h":
                    self.show_help()
                
                else:
                    print(f"❌ Неизвестная команда: {command}")
                    print("   Введите 'help' для справки")
            
            except KeyboardInterrupt:
                print("\n\n👋 Выход по Ctrl+C")
                self.running = False
                break
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                logger.exception("Ошибка в debug консоли")


async def main():
    """Главная функция"""
    console = DebugConsole()
    await console.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Выход")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        logger.exception("Критическая ошибка")

