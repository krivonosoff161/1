"""
Скрипт для проверки статуса OCO ордеров на бирже.

Проверяет:
- Активные OCO ордера
- Исполненные OCO ордера
- Детали закрытия (TP/SL/отменён)
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Добавляем путь к проекту
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from src.config import BotConfig
from src.okx_client import OKXClient


async def check_active_oco_orders(client: OKXClient):
    """Проверить активные OCO ордера"""
    try:
        logger.info("🔍 Checking ACTIVE OCO orders...")
        
        # API endpoint для активных algo-ордеров
        # ⚠️ БЕЗ PARAMS! (Invalid Sign с params)
        result = await client._make_request(
            "GET",
            "/trade/orders-algo-pending?ordType=conditional&instType=SPOT"
        )
        
        if result.get("code") != "0":
            logger.error(f"❌ API error: {result}")
            return []
        
        active_orders = result.get("data", [])
        
        logger.info(f"📊 Found {len(active_orders)} active OCO orders")
        
        for order in active_orders:
            logger.info(
                f"  📍 {order['instId']} | "
                f"AlgoId: {order['algoId']} | "
                f"TP: ${float(order.get('tpTriggerPx', 0)):.2f} | "
                f"SL: ${float(order.get('slTriggerPx', 0)):.2f} | "
                f"State: {order.get('state')}"
            )
        
        return active_orders
    
    except Exception as e:
        logger.error(f"❌ Error checking active OCO: {e}")
        return []


async def check_oco_history(client: OKXClient, symbol: str = None):
    """Проверить историю OCO ордеров (исполненные/отменённые)"""
    try:
        logger.info("🔍 Checking OCO HISTORY (closed orders)...")
        
        # ⚠️ БЕЗ PARAMS! (Invalid Sign)
        endpoint = "/trade/orders-algo-history?ordType=conditional&instType=SPOT&state=filled"
        
        result = await client._make_request("GET", endpoint)
        
        if result.get("code") != "0":
            logger.error(f"❌ API error: {result}")
            return []
        
        history = result.get("data", [])
        
        logger.info(f"📊 Found {len(history)} closed OCO orders")
        
        for order in history[:10]:  # Показываем последние 10
            # Время триггера (может быть пустым!)
            trigger_ts = order.get('triggerTime', '') or order.get('cTime', '0')
            if trigger_ts and trigger_ts != '0':
                trigger_time = datetime.fromtimestamp(int(trigger_ts) / 1000)
                time_str = trigger_time.strftime('%H:%M:%S')
            else:
                time_str = "N/A"
            
            # Определяем что сработало (TP или SL)
            actual_px = float(order.get('actualPx', 0)) if order.get('actualPx') else 0
            tp_px = float(order.get('tpTriggerPx', 0)) if order.get('tpTriggerPx') else 0
            sl_px = float(order.get('slTriggerPx', 0)) if order.get('slTriggerPx') else 0
            
            if actual_px > 0:
                if tp_px > 0 and abs(actual_px - tp_px) < abs(actual_px - sl_px):
                    trigger_type = "✅ TAKE PROFIT"
                elif sl_px > 0:
                    trigger_type = "❌ STOP LOSS"
                else:
                    trigger_type = "⚪ UNKNOWN"
            else:
                trigger_type = "⚫ CANCELLED"
            
            logger.info(
                f"  {trigger_type} | {order['instId']} | "
                f"Time: {time_str} | "
                f"Price: ${actual_px:.2f} | "
                f"TP: ${tp_px:.2f} | SL: ${sl_px:.2f} | "
                f"State: {order.get('state')}"
            )
        
        return history
    
    except Exception as e:
        logger.error(f"❌ Error checking OCO history: {e}")
        return []


async def get_fills_summary(client: OKXClient, symbol: str):
    """Получить сводку по fills"""
    try:
        logger.info(f"🔍 Checking FILLS for {symbol}...")
        
        fills = await client.get_recent_fills(symbol, limit=50)
        
        logger.info(f"📊 Found {len(fills)} fills for {symbol}")
        
        # Группируем по ордерам
        orders = {}
        for fill in fills:
            order_id = fill["ordId"]  # ✅ dict, а не объект
            if order_id not in orders:
                orders[order_id] = []
            orders[order_id].append(fill)
        
        logger.info(f"📦 Unique orders: {len(orders)}")
        
        # Показываем последние 5 ордеров
        for i, (order_id, fills_list) in enumerate(list(orders.items())[:5]):
            first_fill = fills_list[0]
            total_size = sum(float(f["fillSz"]) for f in fills_list)
            total_fee = sum(abs(float(f["fee"])) for f in fills_list)
            
            fill_time = datetime.fromtimestamp(int(first_fill["ts"]) / 1000)
            
            logger.info(
                f"  {i+1}. {first_fill['side'].upper()} @ ${float(first_fill['fillPx']):.2f} | "
                f"Qty: {total_size:.6f} | "
                f"Fee: ${total_fee:.4f} | "
                f"Time: {fill_time.strftime('%H:%M:%S')}"
            )
        
        return fills
    
    except Exception as e:
        logger.error(f"❌ Error getting fills: {e}")
        return []


async def main():
    """Основная функция"""
    
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("🔬 OCO STATUS CHECKER")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Загружаем конфиг
    config = BotConfig.load_from_file("config.yaml")
    okx_config = config.get_okx_config()
    
    # Создаём клиент
    client = OKXClient(okx_config)
    
    try:
        # 1. Активные OCO
        logger.info("\n" + "="*60)
        active = await check_active_oco_orders(client)
        
        # 2. История OCO
        logger.info("\n" + "="*60)
        history = await check_oco_history(client)
        
        # 3. Fills для BTC
        logger.info("\n" + "="*60)
        btc_fills = await get_fills_summary(client, "BTC-USDT")
        
        # 4. Fills для ETH
        logger.info("\n" + "="*60)
        eth_fills = await get_fills_summary(client, "ETH-USDT")
        
        # ИТОГОВАЯ СВОДКА
        logger.info("\n" + "="*60)
        logger.info("📊 ИТОГОВАЯ СВОДКА:")
        logger.info("="*60)
        logger.info(f"  Активных OCO: {len(active)}")
        logger.info(f"  Закрытых OCO: {len(history)}")
        logger.info(f"  BTC fills: {len(btc_fills)}")
        logger.info(f"  ETH fills: {len(eth_fills)}")
        
    finally:
        await client.session.close()
    
    logger.success("✅ Analysis complete!")


if __name__ == "__main__":
    asyncio.run(main())

