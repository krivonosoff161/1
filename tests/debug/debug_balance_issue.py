"""
Диагностика проблемы с балансом и займами
"""

import asyncio
import sys

from loguru import logger

sys.path.append(".")

from src.config import load_config
from src.okx_client import OKXClient


async def debug_balance_issue():
    """Диагностируем проблему с балансом"""
    config = load_config()
    okx_config = config.api["okx"]

    logger.info("🔍 ДИАГНОСТИКА ПРОБЛЕМЫ С БАЛАНСОМ")
    logger.info("=" * 50)

    async with OKXClient(okx_config) as client:
        try:
            # 1. Проверяем общий баланс
            logger.info("1️⃣ ПРОВЕРКА ОБЩЕГО БАЛАНСА:")
            balance_data = await client.get_balance("USDT")
            logger.info(f"   USDT Balance: {balance_data}")

            # 2. Проверяем заемные средства
            logger.info("\n2️⃣ ПРОВЕРКА ЗАЕМНЫХ СРЕДСТВ:")
            borrowed_btc = await client.get_borrowed_balance("BTC")
            borrowed_usdt = await client.get_borrowed_balance("USDT")
            logger.info(f"   BTC Borrowed: {borrowed_btc}")
            logger.info(f"   USDT Borrowed: {borrowed_usdt}")

            # 3. Проверяем детальный баланс
            logger.info("\n3️⃣ ДЕТАЛЬНЫЙ БАЛАНС:")
            try:
                # Получаем полный баланс аккаунта
                result = await client._make_request("GET", "/account/balance")
                if result and result.get("data"):
                    for account in result["data"]:
                        logger.info(f"   Account: {account.get('totalEq', 'N/A')} USDT")
                        for detail in account.get("details", []):
                            if float(detail.get("eq", 0)) > 0:
                                logger.info(
                                    f"     {detail['ccy']}: {detail['eq']} (Available: {detail['availBal']})"
                                )
                                if float(detail.get("liab", 0)) > 0:
                                    logger.warning(
                                        f"     ⚠️ LIABILITY: {detail['liab']}"
                                    )
            except Exception as e:
                logger.error(f"   Ошибка получения детального баланса: {e}")

            # 4. Проверяем режим торговли
            logger.info("\n4️⃣ РЕЖИМ ТОРГОВЛИ:")
            try:
                result = await client._make_request("GET", "/account/config")
                if result and result.get("data"):
                    for config_item in result["data"]:
                        logger.info(
                            f"   Account Level: {config_item.get('acctLv', 'N/A')}"
                        )
                        logger.info(
                            f"   Position Mode: {config_item.get('posMode', 'N/A')}"
                        )
                        logger.info(
                            f"   Auto Loan: {config_item.get('autoLoan', 'N/A')}"
                        )
            except Exception as e:
                logger.error(f"   Ошибка получения конфигурации: {e}")

            # 5. Проверяем последние ордера
            logger.info("\n5️⃣ ПОСЛЕДНИЕ ОРДЕРА:")
            try:
                result = await client._make_request(
                    "GET",
                    "/trade/orders-history",
                    params={"instType": "SPOT", "limit": 5},
                )
                if result and result.get("data"):
                    for order in result["data"]:
                        logger.info(
                            f"   {order['instId']} {order['side']} {order['sz']} @ {order.get('avgPx', 'N/A')} - {order['state']}"
                        )
            except Exception as e:
                logger.error(f"   Ошибка получения истории ордеров: {e}")

        except Exception as e:
            logger.error(f"❌ Ошибка диагностики: {e}")


if __name__ == "__main__":
    asyncio.run(debug_balance_issue())
