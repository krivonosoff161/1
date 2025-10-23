"""
Проверка заемных средств на OKX
"""

import asyncio
import sys

from loguru import logger

sys.path.append(".")

from src.config import load_config
from src.okx_client import OKXClient


async def check_borrowed_funds():
    """Проверяем заемные средства"""
    config = load_config()
    okx_config = config.api["okx"]

    logger.info("🔍 ПРОВЕРКА ЗАЕМНЫХ СРЕДСТВ...")

    async with OKXClient(okx_config) as client:
        try:
            # Проверяем заемные средства для BTC
            borrowed_balance_btc = await client.get_borrowed_balance("BTC")
            logger.info(f"📊 Заемные средства BTC: {borrowed_balance_btc}")

            # Проверяем заемные средства для USDT
            borrowed_balance_usdt = await client.get_borrowed_balance("USDT")
            logger.info(f"📊 Заемные средства USDT: {borrowed_balance_usdt}")

            # Проверяем баланс
            balance = await client.get_balance_all()
            if balance and balance["data"]:
                total_equity = float(balance["data"][0]["totalEq"])
                logger.info(f"💰 Общий баланс: ${total_equity:.2f} USDT")

                for detail in balance["data"][0]["details"]:
                    if float(detail["eq"]) > 0:
                        logger.info(
                            f"   - {detail['ccy']}: {float(detail['availBal']):.4f} (Доступно), {float(detail['eq']):.4f} (Всего)"
                        )
                        if float(detail["liab"]) > 0:
                            logger.warning(
                                f"   ⚠️ ЗАЕМНЫЕ СРЕДСТВА: {detail['ccy']} = {float(detail['liab']):.4f}"
                            )

        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(check_borrowed_funds())
