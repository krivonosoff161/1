#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы анализатора цен
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.analyze_price_after_close import PriceMovementAnalyzer
from loguru import logger


async def test_analyzer():
    """Тестируем анализатор на одной позиции"""
    analyzer = PriceMovementAnalyzer()
    
    # Тестовая позиция
    test_positions = [
        {
            "symbol": "BTC-USDT",
            "time": "11:42:28",
            "side": "LONG",
            "entry": 88955.7,
            "exit": 88907.6,
            "reason": "sl_reached",
        }
    ]
    
    logger.info("🧪 Тестирование анализатора на одной позиции...")
    
    # Тестируем парсинг времени
    try:
        close_time = analyzer.parse_position_time("11:42:28")
        logger.info(f"✅ Парсинг времени: {close_time}")
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга времени: {e}")
        return
    
    # Тестируем получение исторических данных
    try:
        start_time = close_time
        end_time = close_time + timedelta(minutes=15)
        
        candles = await analyzer.get_historical_candles(
            symbol="BTC-USDT",
            start_time=start_time,
            end_time=end_time,
            timeframe="1m",
        )
        
        logger.info(f"✅ Получено {len(candles)} свечей")
        
        if candles:
            logger.info(f"   Первая свеча: {candles[0]}")
            logger.info(f"   Последняя свеча: {candles[-1]}")
    except Exception as e:
        logger.error(f"❌ Ошибка получения свечей: {e}", exc_info=True)
        return
    
    logger.info("✅ Тест завершен успешно!")


if __name__ == "__main__":
    from datetime import timedelta
    asyncio.run(test_analyzer())


