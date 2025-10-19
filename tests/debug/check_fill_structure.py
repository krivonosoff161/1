"""
Проверка структуры fills - есть ли algoId?
"""

import asyncio
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from src.config import BotConfig
from src.okx_client import OKXClient


async def main():
    config = BotConfig.load_from_file("config.yaml")
    client = OKXClient(config.get_okx_config())
    
    try:
        # Получаем fills для BTC
        fills = await client.get_recent_fills("BTC-USDT", limit=5)
        
        logger.info(f"📊 Got {len(fills)} fills for BTC-USDT")
        
        # Смотрим структуру первого fill
        if fills:
            first_fill = fills[0]
            logger.info("\n" + "="*60)
            logger.info("📋 FILL STRUCTURE (первый fill):")
            logger.info("="*60)
            logger.info(json.dumps(first_fill, indent=2, ensure_ascii=False))
            
            # Проверяем наличие ключевых полей
            logger.info("\n" + "="*60)
            logger.info("🔍 КЛЮЧЕВЫЕ ПОЛЯ:")
            logger.info("="*60)
            logger.info(f"  ordId: {first_fill.get('ordId')}")
            logger.info(f"  algoId: {first_fill.get('algoId', 'НЕТ!')}")
            logger.info(f"  side: {first_fill.get('side')}")
            logger.info(f"  fillPx: {first_fill.get('fillPx')}")
            logger.info(f"  fillSz: {first_fill.get('fillSz')}")
            logger.info(f"  fee: {first_fill.get('fee')}")
            logger.info(f"  execType: {first_fill.get('execType', 'НЕТ!')}")
            logger.info(f"  ts: {first_fill.get('ts')}")
    
    finally:
        await client.session.close()


if __name__ == "__main__":
    asyncio.run(main())


