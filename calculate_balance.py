#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Расчет баланса на начало 2 декабря и конец 3 декабря 2025
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent))

from src.config import load_config
from src.clients.futures_client import OKXFuturesClient


class BalanceCalculator:
    """Калькулятор баланса"""
    
    def __init__(self):
        self.client = None
        self.config = None
    
    async def connect(self):
        """Подключение к OKX"""
        print("🔌 Подключаюсь к OKX API...")
        
        self.config = load_config("config.yaml")
        api_config = self.config.get_okx_config()
        
        self.client = OKXFuturesClient(
            api_key=api_config.api_key,
            secret_key=api_config.api_secret,
            passphrase=api_config.passphrase,
            sandbox=api_config.sandbox
        )
        
        print("✅ Подключено к OKX!")
    
    async def get_current_balance(self) -> float:
        """Получает текущий баланс в USDT"""
        try:
            balance = await self.client.get_balance()
            return balance
        except Exception as e:
            print(f"⚠️ Ошибка получения баланса: {e}")
            return 0.0
    
    def load_trades(self, filepath: Path) -> List[Dict]:
        """Загружает сделки из JSON файла"""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def calculate_balance_at_start(self, trades: List[Dict], current_balance: float) -> float:
        """
        Рассчитывает баланс на начало периода, откатывая все сделки
        
        Для каждой сделки:
        - Если это закрытие позиции (sell для long или buy для short) - вычитаем PnL
        - Если это открытие позиции - ничего не меняем (маржинальная торговля)
        - Вычитаем комиссию
        """
        # Начинаем с текущего баланса
        balance = current_balance
        
        # Идем по сделкам в обратном порядке (от последней к первой)
        for trade in reversed(trades):
            # Вычитаем комиссию (возвращаем ее обратно)
            fee = float(trade.get("fee", 0) or 0)
            balance += abs(fee)  # Комиссия всегда отрицательная, возвращаем
            
            # Если есть PnL (реализованная прибыль/убыток), откатываем его
            pnl = trade.get("pnl")
            if pnl is not None:
                pnl_value = float(pnl)
                balance -= pnl_value  # Откатываем PnL (если был +, вычитаем, если был -, добавляем)
        
        return balance
    
    def analyze_trades(self, trades: List[Dict]) -> Dict:
        """Анализирует сделки и возвращает статистику"""
        total_fee = 0.0
        total_pnl = 0.0
        
        for trade in trades:
            fee = float(trade.get("fee", 0) or 0)
            total_fee += abs(fee)
            
            pnl = trade.get("pnl")
            if pnl is not None:
                total_pnl += float(pnl)
        
        return {
            "total_fee": total_fee,
            "total_pnl": total_pnl,
            "net_change": total_pnl - total_fee
        }


async def main():
    """Главная функция"""
    print("=" * 80)
    print("💰 РАСЧЕТ БАЛАНСА НА 2 И 3 ДЕКАБРЯ 2025")
    print("=" * 80)
    
    calculator = BalanceCalculator()
    await calculator.connect()
    
    # Получаем текущий баланс (на конец 3 декабря, если данные актуальны)
    print("\n📊 Получаю текущий баланс с биржи...")
    current_balance = await calculator.get_current_balance()
    print(f"✅ Текущий баланс: ${current_balance:.2f} USDT")
    
    # Загружаем сделки - используем последний файл с полным периодом
    # Ищем файл с данными за 2-3 число
    trade_files = list(Path(".").glob("trades_all_*.json"))
    
    if not trade_files:
        print("\n❌ Не найден файл со сделками!")
        return
    
    # Берем последний файл (должен быть с полным периодом 2-3 число)
    trade_file = sorted(trade_files, key=lambda x: x.stat().st_mtime, reverse=True)[0]
    print(f"\n📂 Использую файл: {trade_file.name}")
    
    print(f"\n📂 Загружаю сделки из {trade_file.name}...")
    trades = calculator.load_trades(trade_file)
    print(f"✅ Загружено {len(trades)} сделок")
    
    # Анализируем сделки
    stats = calculator.analyze_trades(trades)
    print(f"\n📊 Статистика по сделкам:")
    print(f"   Общая комиссия: ${stats['total_fee']:.2f}")
    print(f"   Общий PnL: ${stats['total_pnl']:.2f}")
    print(f"   Чистое изменение: ${stats['net_change']:.2f}")
    
    # Рассчитываем баланс на начало 2 декабря
    print(f"\n🔄 Рассчитываю баланс на начало 2 декабря...")
    balance_at_start = calculator.calculate_balance_at_start(trades, current_balance)
    
    # Баланс на конец 3 декабря = текущий баланс (если данные актуальны)
    # Или можно рассчитать: баланс на начало + чистое изменение
    balance_at_end = balance_at_start + stats['net_change']
    
    # Выводим результаты
    print("\n" + "=" * 80)
    print("📊 РЕЗУЛЬТАТЫ")
    print("=" * 80)
    print(f"\n💰 Баланс на начало 2 декабря 2025: ${balance_at_start:.2f} USDT")
    print(f"💰 Баланс на конец 3 декабря 2025: ${balance_at_end:.2f} USDT")
    print(f"💰 Текущий баланс (с биржи): ${current_balance:.2f} USDT")
    
    change = balance_at_end - balance_at_start
    change_percent = (change / balance_at_start * 100) if balance_at_start > 0 else 0
    
    print(f"\n📈 Изменение за период:")
    print(f"   Абсолютное: ${change:.2f} USDT")
    print(f"   Процентное: {change_percent:.2f}%")
    
    # Закрываем соединение
    await calculator.client.close()
    
    print("\n" + "=" * 80)
    print("✅ РАСЧЕТ ЗАВЕРШЕН")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

