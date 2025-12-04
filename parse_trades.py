#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсинг сделок с биржи OKX за определенный период времени

ИСПОЛЬЗОВАНИЕ:
    python parse_trades.py

НАСТРОЙКИ (в функции main()):
    - symbol: Символ для фильтрации (например "BTC-USDT") или None для всех
    - days_back: За сколько дней назад получать сделки
    - Или укажите точные start_time и end_time

РЕЗУЛЬТАТ:
    - JSON файл: trades_{symbol}_{timestamp}.json
    - CSV файл: trades_{symbol}_{timestamp}.csv
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Добавляем корень проекта
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.clients.futures_client import OKXFuturesClient


class TradesParser:
    """Парсер сделок с биржи OKX"""
    
    def __init__(self):
        self.client = None
        self.config = None
        self.all_trades = []
    
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
    
    async def get_fills(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Получить исполненные сделки (fills) за период
        
        Args:
            symbol: Символ (например, "BTC-USDT"), если None - все символы
            start_time: Начало периода
            end_time: Конец периода
            limit: Максимальное количество (OKX ограничивает 100 за запрос)
        
        Returns:
            Список сделок
        """
        print(f"\n📊 Загружаю fills (исполненные сделки)...")
        
        if symbol:
            print(f"   Символ: {symbol}")
        else:
            print(f"   Все символы")
        
        if start_time:
            print(f"   С: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        if end_time:
            print(f"   По: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        params = {
            "instType": "SWAP",  # Фьючерсы
            "limit": str(limit)
        }
        
        if symbol:
            params["instId"] = f"{symbol}-SWAP"
        
        if start_time:
            params["begin"] = str(int(start_time.timestamp() * 1000))
        
        if end_time:
            params["end"] = str(int(end_time.timestamp() * 1000))
        
        try:
            response = await self.client._make_request(
                "GET",
                "/api/v5/trade/fills",
                params=params
            )
            
            if response and response.get("code") == "0":
                fills = response.get("data", [])
                print(f"✅ Получено {len(fills)} fills")
                return fills
            else:
                error_msg = response.get("msg", "Unknown error")
                print(f"❌ Ошибка API: {error_msg}")
                return []
                
        except Exception as e:
            print(f"❌ Ошибка получения fills: {e}")
            return []
    
    async def get_all_fills_period(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Получить ВСЕ fills за период (с пагинацией)
        
        OKX ограничивает 100 записей за раз, поэтому делаем несколько запросов
        """
        all_fills = []
        current_end = end_time or datetime.now()
        limit = 100
        
        print(f"\n🔄 Загружаю все fills с пагинацией...")
        
        while True:
            # Получаем fills от текущего конца периода назад
            fills = await self.get_fills(
                symbol=symbol,
                start_time=start_time,
                end_time=current_end,
                limit=limit
            )
            
            if not fills:
                break
            
            all_fills.extend(fills)
            
            # Если получили меньше limit, значит это последняя страница
            if len(fills) < limit:
                break
            
            # Обновляем end_time на время самой старой сделки
            oldest_fill = min(fills, key=lambda x: int(x.get("ts", 0)))
            oldest_time = int(oldest_fill.get("ts", 0)) / 1000
            current_end = datetime.fromtimestamp(oldest_time)
            
            # Небольшая задержка для rate limiting
            await asyncio.sleep(0.2)
        
        # Сортируем по времени (от старых к новым)
        all_fills.sort(key=lambda x: int(x.get("ts", 0)))
        
        print(f"\n✅ Всего получено {len(all_fills)} fills")
        return all_fills
    
    def format_trade(self, fill: Dict) -> Dict:
        """Форматирует сделку в удобный формат"""
        timestamp = int(fill.get("ts", 0)) / 1000
        dt = datetime.fromtimestamp(timestamp)
        
        return {
            "timestamp": dt.isoformat(),
            "symbol": fill.get("instId", "").replace("-SWAP", ""),
            "side": fill.get("side", ""),  # buy или sell
            "price": float(fill.get("fillPx", 0)),
            "size": float(fill.get("fillSz", 0)),
            "fee": float(fill.get("fee", 0)),
            "fee_currency": fill.get("feeCcy", ""),
            "order_id": fill.get("ordId", ""),
            "trade_id": fill.get("tradeId", ""),
            "pos_side": fill.get("posSide", ""),  # long или short
            "pnl": float(fill.get("fillPnl", 0)) if fill.get("fillPnl") and fill.get("fillPnl") != "0" else None,
        }
    
    def save_to_json(self, trades: List[Dict], filename: str):
        """Сохраняет сделки в JSON файл"""
        output_path = Path(filename)
        output_path.write_text(
            json.dumps(trades, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        print(f"\n💾 Сделки сохранены в {output_path}")
    
    def save_to_csv(self, trades: List[Dict], filename: str):
        """Сохраняет сделки в CSV файл"""
        import csv
        
        if not trades:
            print("⚠️ Нет данных для сохранения")
            return
        
        output_path = Path(filename)
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        
        print(f"💾 Сделки сохранены в {output_path}")
    
    def print_summary(self, trades: List[Dict]):
        """Выводит сводку по сделкам"""
        if not trades:
            print("\n⚠️ Нет сделок для анализа")
            return
        
        print("\n" + "=" * 80)
        print("📊 СВОДКА ПО СДЕЛКАМ")
        print("=" * 80)
        
        # Группировка по символам
        by_symbol = {}
        for trade in trades:
            symbol = trade.get("symbol", "UNKNOWN")
            if symbol not in by_symbol:
                by_symbol[symbol] = []
            by_symbol[symbol].append(trade)
        
        print(f"\nВсего сделок: {len(trades)}")
        print(f"Символов: {len(by_symbol)}")
        
        # Статистика по каждому символу
        for symbol, symbol_trades in sorted(by_symbol.items()):
            buys = [t for t in symbol_trades if t.get("side") == "buy"]
            sells = [t for t in symbol_trades if t.get("side") == "sell"]
            
            total_fee = sum(abs(float(t.get("fee", 0) or 0)) for t in symbol_trades)
            total_pnl = sum(float(t.get("pnl") or 0) for t in symbol_trades if t.get("pnl") is not None)
            
            print(f"\n{symbol}:")
            print(f"  Всего: {len(symbol_trades)} (покупок: {len(buys)}, продаж: {len(sells)})")
            print(f"  Комиссия: {total_fee:.4f}")
            if total_pnl != 0:
                print(f"  PnL: {total_pnl:.4f}")
        
        # Временной диапазон
        if trades:
            first_time = trades[0].get("timestamp", "")
            last_time = trades[-1].get("timestamp", "")
            print(f"\nПериод: {first_time} - {last_time}")


async def main():
    """Главная функция"""
    print("=" * 80)
    print("💰 ПАРСЕР СДЕЛОК С БИРЖИ OKX")
    print("=" * 80)
    
    parser = TradesParser()
    await parser.connect()
    
    # ===== НАСТРОЙКИ =====
    # Получаем все сделки за 02.12.2025 и 03.12.2025
    
    symbol = None  # Все символы
    
    # Точный период: 02.12.2025 с 00:00:00 по 03.12.2025 23:59:59
    start_time = datetime(2025, 12, 2, 0, 0, 0)
    end_time = datetime(2025, 12, 3, 23, 59, 59)
    
    # ===== ПОЛУЧЕНИЕ СДЕЛОК =====
    trades = await parser.get_all_fills_period(
        symbol=symbol,
        start_time=start_time,
        end_time=end_time
    )
    
    if not trades:
        print("\n❌ Сделки не найдены")
        return
    
    # Форматируем
    formatted_trades = [parser.format_trade(fill) for fill in trades]
    
    # Выводим сводку
    parser.print_summary(formatted_trades)
    
    # Сохраняем
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    symbol_str = symbol or "all"
    
    json_file = f"trades_{symbol_str}_{timestamp}.json"
    csv_file = f"trades_{symbol_str}_{timestamp}.csv"
    
    parser.save_to_json(formatted_trades, json_file)
    parser.save_to_csv(formatted_trades, csv_file)
    
    # Закрываем соединение
    await parser.client.close()
    
    print("\n" + "=" * 80)
    print("✅ ПАРСИНГ ЗАВЕРШЕН")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

