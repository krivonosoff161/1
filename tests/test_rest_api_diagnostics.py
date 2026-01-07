#!/usr/bin/env python3
"""
🔍 REST API Диагностика - проверка подключения к OKX
Тестирует различные endpoints и методы подключения
"""

import asyncio
import sys
import time
from pathlib import Path

import aiohttp
from loguru import logger

# Добавляем src в path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from clients.futures_client import OKXFuturesClient
from config import BotConfig

# Логирование с красивым форматом
logger.remove()
logger.add(
    sys.stdout,
    format="<level>{time:HH:mm:ss}</level> | <level>{level: <8}</level> | {message}",
    colorize=True,
)

# ==================== ТЕСТОВЫЕ ХОСТЫ ====================
TEST_ENDPOINTS = {
    "www": "https://www.okx.com/api/v5",
    "api": "https://api.okx.com/api/v5",
    "aws": "https://aws.okx.com/api/v5",
}

TEST_METHODS = {
    "system_status": "/system/status",
    "leverage_info": "/public/instruments",
    "market_data": "/market/tickers",
    "account_info": "/account/balance",
    "positions": "/account/positions",
}

# ==================== БАЗОВЫЕ ТЕСТЫ ====================


async def test_raw_http_connection(
    url: str, method: str = "GET", timeout: int = 10
) -> dict:
    """Сырое HTTP подключение без OKX клиента"""
    logger.info(f"🔗 Тест сырого HTTP: {url}")

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(url) as response:
                status = response.status
                try:
                    data = await response.json()
                    logger.success(f"✅ Ответ {status}: {type(data).__name__}")
                    return {"status": status, "data": data, "error": None}
                except Exception as e:
                    text = await response.text()
                    logger.warning(f"⚠️ Ответ {status}: текст ({len(text)} байт)")
                    return {"status": status, "data": text[:100], "error": None}
    except asyncio.TimeoutError:
        logger.error(f"❌ TIMEOUT: {url} (>{timeout}s)")
        return {"status": None, "data": None, "error": f"Timeout {timeout}s"}
    except aiohttp.ClientConnectorError as e:
        logger.error(f"❌ CONNECT: {str(e)[:80]}")
        return {
            "status": None,
            "data": None,
            "error": f"Connect error: {type(e).__name__}",
        }
    except Exception as e:
        logger.error(f"❌ ERROR: {type(e).__name__}: {str(e)[:80]}")
        return {
            "status": None,
            "data": None,
            "error": f"{type(e).__name__}: {str(e)[:50]}",
        }


async def test_system_status(host: str, timeout: int = 5) -> dict:
    """Проверка статуса системы OKX (public, не требует auth)"""
    url = f"{host}/system/status"
    logger.info(f"📊 System Status: {url}")

    result = await test_raw_http_connection(url, timeout=timeout)
    if result["status"] == 200:
        logger.success(f"✅ System OK")
    return result


async def test_instruments(
    host: str, inst_type: str = "SWAP", timeout: int = 5
) -> dict:
    """Получение инструментов (public)"""
    url = f"{host}/public/instruments?instType={inst_type}"
    logger.info(f"🎯 Instruments: {url}")

    result = await test_raw_http_connection(url, timeout=timeout)
    if result["status"] == 200:
        logger.success(f"✅ Instruments OK")
    return result


async def test_leverage_info(
    client: OKXFuturesClient, symbol: str = "ETH-USDT"
) -> dict:
    """Через OKX клиент - информация о leverage"""
    logger.info(f"💰 Leverage Info для {symbol} через клиент")

    try:
        info = await client.get_instrument_leverage_info(symbol)
        logger.success(f"✅ Leverage: {info.get('max_leverage')}x")
        return {"status": 200, "data": info, "error": None}
    except Exception as e:
        logger.error(f"❌ {type(e).__name__}: {str(e)[:80]}")
        return {"status": None, "data": None, "error": str(e)}


async def test_account_balance(client: OKXFuturesClient) -> dict:
    """Через OKX клиент - баланс аккаунта"""
    logger.info(f"💳 Account Balance через клиент")

    try:
        balance = await client.get_balance()
        logger.success(f"✅ Balance: {balance}")
        return {"status": 200, "data": balance, "error": None}
    except Exception as e:
        logger.error(f"❌ {type(e).__name__}: {str(e)[:80]}")
        return {"status": None, "data": None, "error": str(e)}


async def test_positions(client: OKXFuturesClient) -> dict:
    """Через OKX клиент - открытые позиции"""
    logger.info(f"📈 Positions через клиент")

    try:
        positions = await client.get_positions()
        logger.success(f"✅ Positions: {len(positions)} открытых")
        return {"status": 200, "data": positions, "error": None}
    except Exception as e:
        logger.error(f"❌ {type(e).__name__}: {str(e)[:80]}")
        return {"status": None, "data": None, "error": str(e)}


# ==================== КОМПЛЕКСНЫЕ ТЕСТЫ ====================


async def test_all_hosts() -> dict:
    """Тест всех хостов для базовых endpoints"""
    logger.info(f"\n{'='*80}")
    logger.info(f"🌐 ТЕСТ ВСЕХ ХОСТОВ")
    logger.info(f"{'='*80}\n")

    results = {}

    for host_name, host_url in TEST_ENDPOINTS.items():
        logger.info(f"\n📍 Хост: {host_name} ({host_url})")
        logger.info(f"{'-'*60}")

        host_results = {}

        # System Status
        logger.info(f"\n  1️⃣  System Status")
        result = await test_system_status(host_url, timeout=5)
        host_results["system_status"] = result

        await asyncio.sleep(0.5)  # Задержка между запросами

        # Instruments
        logger.info(f"\n  2️⃣  Instruments (SWAP)")
        result = await test_instruments(host_url, inst_type="SWAP", timeout=5)
        host_results["instruments_swap"] = result

        await asyncio.sleep(0.5)

        # Market Tickers (публичный)
        logger.info(f"\n  3️⃣  Market Tickers (публичный)")
        url = f"{host_url}/market/tickers?instType=SWAP"
        result = await test_raw_http_connection(url, timeout=5)
        host_results["market_tickers"] = result

        results[host_name] = host_results

        await asyncio.sleep(1)  # Пауза между хостами

    return results


async def test_client_methods(config: BotConfig) -> dict:
    """Тест методов OKX клиента"""
    logger.info(f"\n{'='*80}")
    logger.info(f"🔐 ТЕСТ МЕТОДОВ OKX КЛИЕНТА (с auth)")
    logger.info(f"{'='*80}\n")

    api_config = config.get_okx_config()
    client = OKXFuturesClient(
        api_key=api_config.api_key,
        secret_key=api_config.secret_key,
        passphrase=api_config.passphrase,
    )

    results = {}

    try:
        # 1. Leverage Info
        logger.info(f"\n1️⃣  Leverage Info (публичный endpoint)")
        result = await test_leverage_info(client, "ETH-USDT")
        results["leverage_eth"] = result

        await asyncio.sleep(0.5)

        # 2. Account Balance
        logger.info(f"\n2️⃣  Account Balance (приватный endpoint)")
        result = await test_account_balance(client)
        results["account_balance"] = result

        await asyncio.sleep(0.5)

        # 3. Positions
        logger.info(f"\n3️⃣  Positions (приватный endpoint)")
        result = await test_positions(client)
        results["positions"] = result

    finally:
        await client.close()

    return results


# ==================== СРАВНЕНИЕ REST vs WebSocket ====================


async def test_network_diagnostics() -> dict:
    """Диагностика сети"""
    logger.info(f"\n{'='*80}")
    logger.info(f"🌐 ДИАГНОСТИКА СЕТИ")
    logger.info(f"{'='*80}\n")

    import platform
    import socket

    diagnostics = {}

    # Проверка DNS
    logger.info(f"🔍 DNS Resolution")
    try:
        ip = socket.gethostbyname("www.okx.com")
        logger.success(f"  ✅ www.okx.com → {ip}")
        diagnostics["dns_www_okx"] = ip
    except Exception as e:
        logger.error(f"  ❌ Ошибка DNS: {e}")
        diagnostics["dns_www_okx"] = None

    try:
        ip = socket.gethostbyname("api.okx.com")
        logger.success(f"  ✅ api.okx.com → {ip}")
        diagnostics["dns_api_okx"] = ip
    except Exception as e:
        logger.error(f"  ❌ Ошибка DNS: {e}")
        diagnostics["dns_api_okx"] = None

    # Проверка ping
    logger.info(f"\n🔗 Ping Tests")
    for host in ["www.okx.com", "api.okx.com"]:
        try:
            import subprocess

            if platform.system() == "Windows":
                result = subprocess.run(
                    ["ping", "-n", "1", host], capture_output=True, timeout=5, text=True
                )
            else:
                result = subprocess.run(
                    ["ping", "-c", "1", host], capture_output=True, timeout=5, text=True
                )

            if result.returncode == 0:
                logger.success(f"  ✅ {host} доступен (ping OK)")
                diagnostics[f"ping_{host}"] = "OK"
            else:
                logger.warning(f"  ⚠️  {host} не ответил на ping")
                diagnostics[f"ping_{host}"] = "NO RESPONSE"
        except Exception as e:
            logger.error(f"  ❌ Ошибка ping {host}: {e}")
            diagnostics[f"ping_{host}"] = "ERROR"

    return diagnostics


# ==================== ГЛАВНЫЙ ТЕСТ ====================


async def main():
    """Главная функция тестирования"""

    print("\n")
    logger.info(f"{'='*80}")
    logger.info(f"🚀 REST API ДИАГНОСТИКА OKX TRADING BOT")
    logger.info(f"{'='*80}\n")

    # 1. Диагностика сети
    logger.info(f"ЭТАП 1: Диагностика сети")
    network_results = await test_network_diagnostics()

    await asyncio.sleep(2)

    # 2. Сырые HTTP тесты (все хосты)
    logger.info(f"\nЭТАП 2: Сырые HTTP тесты всех хостов")
    http_results = await test_all_hosts()

    await asyncio.sleep(2)

    # 3. Тесты через клиент OKX (с авторизацией)
    logger.info(f"\nЭТАП 3: Тесты через OKX клиент")
    try:
        config = BotConfig.load_from_file("config/config_futures.yaml")
        client_results = await test_client_methods(config)
    except Exception as e:
        logger.error(f"❌ Не удалось загрузить config: {e}")
        client_results = None

    # ==================== ИТОГОВЫЙ ОТЧЕТ ====================

    logger.info(f"\n{'='*80}")
    logger.info(f"📋 ИТОГОВЫЙ ОТЧЕТ")
    logger.info(f"{'='*80}\n")

    # Сеть
    logger.info(f"🌐 СЕТЬ:")
    if network_results.get("dns_www_okx"):
        logger.success(f"  ✅ DNS разрешён (www.okx.com)")
    else:
        logger.error(f"  ❌ DNS не работает")

    if network_results.get("ping_www.okx.com") == "OK":
        logger.success(f"  ✅ Ping работает (www.okx.com)")
    else:
        logger.warning(f"  ⚠️  Ping проблема (www.okx.com)")

    # HTTP тесты
    logger.info(f"\n📡 HTTP ТЕСТЫ:")
    for host_name, results in http_results.items():
        success_count = sum(1 for r in results.values() if r.get("status") == 200)
        total = len(results)
        logger.info(f"  {host_name}: {success_count}/{total} успешных")

    # Клиент тесты
    if client_results:
        logger.info(f"\n🔐 OKX КЛИЕНТ:")

        leverage = client_results.get("leverage_eth", {})
        if leverage.get("status") == 200:
            logger.success(f"  ✅ Leverage Info (публичный) - OK")
        else:
            logger.error(f"  ❌ Leverage Info - {leverage.get('error')}")

        balance = client_results.get("account_balance", {})
        if balance.get("status") == 200:
            logger.success(f"  ✅ Account Balance (приватный) - OK")
        else:
            logger.error(f"  ❌ Account Balance - {balance.get('error')}")

        positions = client_results.get("positions", {})
        if positions.get("status") == 200:
            logger.success(f"  ✅ Positions (приватный) - OK")
        else:
            logger.error(f"  ❌ Positions - {positions.get('error')}")

    logger.info(f"\n{'='*80}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning(f"\n⏹️  Прервано пользователем")
    except Exception as e:
        logger.error(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback

        traceback.print_exc()
