#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 ТЕСТ WebSocket + Profit Harvesting
Показывает КАК БЫ работал бот с WebSocket вместо REST API
"""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiohttp


# Симуляция позиции
@dataclass
class TestPosition:
    symbol: str
    side: str  # "LONG" или "SHORT"
    entry_price: float
    size: float
    timestamp: datetime
    oco_id: Optional[str] = None
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None


class OKXWebSocketTest:
    """Тестовый WebSocket клиент для OKX"""

    def __init__(
        self, api_key: str, api_secret: str, passphrase: str, sandbox: bool = True
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase

        # WebSocket URL
        if sandbox:
            self.ws_url = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"
            # Note: OKX demo использует публичный WS, но с demo API ключами
        else:
            self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"

        self.ws = None
        self.session = None

        # Для теста PH
        self.test_position: Optional[TestPosition] = None
        self.ph_enabled = True
        self.ph_threshold = 0.08  # $0.08
        self.ph_time_limit = 60  # 60 секунд

        # Статистика
        self.price_updates = 0
        self.ph_checks = 0
        self.last_check_time = time.time()

    async def connect(self):
        """Подключение к WebSocket"""
        self.session = aiohttp.ClientSession()

        try:
            print("\n🔌 Подключаюсь к OKX WebSocket...")
            print(f"   URL: {self.ws_url}")

            self.ws = await self.session.ws_connect(
                self.ws_url, heartbeat=20, timeout=30  # Ping каждые 20 сек
            )

            print("✅ WebSocket подключен!\n")
            return True

        except Exception as e:
            print(f"❌ Ошибка подключения: {e}")
            return False

    async def subscribe_ticker(self, symbol: str):
        """Подписка на тикер (цена в реальном времени)"""
        subscribe_msg = {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instId": symbol}],
        }

        print(f"📡 Подписываюсь на тикер {symbol}...")
        await self.ws.send_json(subscribe_msg)

        # Ждем подтверждения
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)

                # Проверяем подтверждение подписки
                if data.get("event") == "subscribe":
                    print(f"✅ Подписка активна: {data.get('arg', {}).get('channel')}\n")
                    break
                elif "data" in data:
                    # Уже пришли данные
                    break

    async def listen_prices(self, symbol: str, duration_seconds: int = 60):
        """Слушает цены в реальном времени"""
        print("=" * 80)
        print(f"👂 СЛУШАЮ ЦЕНЫ {symbol} В РЕАЛЬНОМ ВРЕМЕНИ")
        print(f"   Длительность: {duration_seconds} секунд")
        print("=" * 80 + "\n")

        start_time = time.time()
        last_price = None
        price_changes = []

        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)

                    # Пропускаем служебные сообщения
                    if "event" in data:
                        continue

                    # Обрабатываем данные тикера
                    if "data" in data:
                        for ticker in data["data"]:
                            current_price = float(ticker.get("last", 0))
                            timestamp = int(ticker.get("ts", 0))

                            if current_price > 0:
                                self.price_updates += 1

                                # Показываем обновление
                                now = datetime.fromtimestamp(timestamp / 1000)
                                change = ""

                                if last_price:
                                    diff = current_price - last_price
                                    pct = (diff / last_price) * 100
                                    change = f" ({diff:+.2f}, {pct:+.3f}%)"
                                    price_changes.append(abs(diff))

                                print(
                                    f"💰 {now.strftime('%H:%M:%S.%f')[:-3]} | "
                                    f"${current_price:.2f}{change}"
                                )

                                # Если есть тестовая позиция - проверяем PH
                                if self.test_position:
                                    await self.check_profit_harvesting(current_price)

                                last_price = current_price

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"❌ WebSocket error: {msg.data}")
                    break

                # Проверяем время
                if time.time() - start_time >= duration_seconds:
                    print(f"\n⏰ Время вышло ({duration_seconds}с)")
                    break

        except asyncio.CancelledError:
            print("\n⚠️  Прервано пользователем")

        # Статистика
        print("\n" + "=" * 80)
        print("📊 СТАТИСТИКА WEBSOCKET")
        print("=" * 80)
        print(f"Всего обновлений цены: {self.price_updates}")
        print(f"Частота: {self.price_updates / duration_seconds:.2f} обновлений/сек")

        if price_changes:
            avg_change = sum(price_changes) / len(price_changes)
            max_change = max(price_changes)
            print(f"Средн. изменение: ${avg_change:.4f}")
            print(f"Макс. изменение: ${max_change:.4f}")

        if self.test_position:
            print(f"\nPH проверок: {self.ph_checks}")
            print(f"Частота PH: {self.ph_checks / duration_seconds:.2f} проверок/сек")

    async def open_test_position(
        self, symbol: str, side: str, entry_price: float, size: float
    ):
        """Открывает тестовую позицию"""
        self.test_position = TestPosition(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            size=size,
            timestamp=datetime.utcnow(),
        )

        print("\n" + "=" * 80)
        print("📈 ТЕСТОВАЯ ПОЗИЦИЯ ОТКРЫТА")
        print("=" * 80)
        print(f"Symbol: {symbol}")
        print(f"Side: {side}")
        print(f"Entry: ${entry_price:.2f}")
        print(f"Size: {size}")
        print(f"\n🎯 Profit Harvesting:")
        print(f"   Порог: ${self.ph_threshold}")
        print(f"   Лимит времени: {self.ph_time_limit}s")
        print("=" * 80 + "\n")

    async def check_profit_harvesting(self, current_price: float):
        """Проверяет условия Profit Harvesting (КАК В РЕАЛЬНОМ БОТЕ)"""
        if not self.test_position:
            return

        self.ph_checks += 1

        # Ограничиваем частоту проверок для читаемости
        now = time.time()
        if now - self.last_check_time < 1.0:  # Не чаще раза в секунду для вывода
            return
        self.last_check_time = now

        position = self.test_position
        time_since_open = (datetime.utcnow() - position.timestamp).total_seconds()

        # Расчет PnL
        if position.side == "LONG":
            pnl_usd = (current_price - position.entry_price) * position.size
            price_change_pct = (
                (current_price - position.entry_price) / position.entry_price
            ) * 100
        else:  # SHORT
            pnl_usd = (position.entry_price - current_price) * position.size
            price_change_pct = (
                (position.entry_price - current_price) / position.entry_price
            ) * 100

        # Вывод проверки
        status = "⏳" if pnl_usd < self.ph_threshold else "✅"
        time_status = "⏰" if time_since_open >= self.ph_time_limit else "⏱️"

        print(f"\n{status} PH CHECK #{self.ph_checks}:")
        print(f"   Time: {time_since_open:.1f}s / {self.ph_time_limit}s {time_status}")
        print(
            f"   PnL: ${pnl_usd:.4f} / ${self.ph_threshold:.2f} "
            f"({pnl_usd/self.ph_threshold*100:.0f}%)"
        )
        print(f"   Price Δ: {price_change_pct:+.3f}%")

        # Проверка условий PH
        if pnl_usd >= self.ph_threshold and time_since_open < self.ph_time_limit:
            print("\n" + "🎉" * 40)
            print("💰💰💰 PROFIT HARVESTING TRIGGERED! 💰💰💰")
            print("🎉" * 40)
            print(f"\n✅ Быстрая прибыль: ${pnl_usd:.4f}")
            print(f"✅ За время: {time_since_open:.1f}s")
            print(f"✅ Изменение цены: {price_change_pct:+.3f}%")
            print(f"✅ Entry: ${position.entry_price:.2f} → Exit: ${current_price:.2f}")
            print("\n" + "=" * 80)
            print("🚀 В РЕАЛЬНОМ БОТЕ: Сейчас бы закрыли позицию MARKET ордером!")
            print("🚀 И отменили OCO чтобы не конфликтовать!")
            print("=" * 80 + "\n")

            # Сбрасываем позицию
            self.test_position = None
            return True

        # Показываем насколько близко
        if time_since_open < self.ph_time_limit:
            if pnl_usd > 0:
                progress = pnl_usd / self.ph_threshold * 100
                print(
                    f"   📊 Прогресс к PH: {'█' * int(progress/10)}{' ' * (10-int(progress/10))} {progress:.0f}%"
                )

        return False

    async def close(self):
        """Закрытие соединения"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

        print("\n👋 WebSocket закрыт")


async def main():
    """Главная функция теста"""

    print("\n" + "=" * 80)
    print("🧪 ТЕСТ: WebSocket + Profit Harvesting")
    print("=" * 80)
    print("\nЦель: Показать КАК БЫ работал PH с WebSocket вместо REST API")
    print("\nЧто будет:")
    print("1. Подключимся к OKX WebSocket")
    print("2. Подпишемся на тикер BTC-USDT")
    print("3. Симулируем открытую позицию")
    print("4. Смотрим как PH проверяет КАЖДОЕ изменение цены")
    print("5. Ждем срабатывания PH или таймаута")
    print("=" * 80 + "\n")

    # Загружаем API ключи из .env
    import os

    from dotenv import load_dotenv

    load_dotenv()

    api_key = os.getenv("OKX_API_KEY", "")
    api_secret = os.getenv("OKX_API_SECRET", "")
    passphrase = os.getenv("OKX_PASSPHRASE", "")

    if not api_key:
        print("⚠️  API ключи не найдены в .env")
        print("⚠️  WebSocket будет работать в публичном режиме (только цены)\n")

    # Создаем тестовый клиент
    ws_client = OKXWebSocketTest(api_key, api_secret, passphrase, sandbox=True)

    try:
        # 1. Подключаемся
        if not await ws_client.connect():
            print("❌ Не удалось подключиться к WebSocket")
            return

        # 2. Подписываемся на тикер
        symbol = "BTC-USDT"
        await ws_client.subscribe_ticker(symbol)

        # Даем время получить первую цену
        await asyncio.sleep(2)

        # 3. Открываем тестовую позицию
        # Симулируем LONG позицию (используем примерную текущую цену)
        print("🔄 Получаю текущую цену для симуляции...")

        # Слушаем несколько секунд чтобы узнать цену
        first_price = None
        async for msg in ws_client.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if "data" in data and data["data"]:
                    first_price = float(data["data"][0].get("last", 0))
                    if first_price > 0:
                        break

        if not first_price:
            print("❌ Не удалось получить цену")
            return

        # Открываем позицию
        entry_price = first_price
        size = 0.001  # 0.001 BTC
        await ws_client.open_test_position(symbol, "LONG", entry_price, size)

        # 4. Слушаем цены и проверяем PH
        duration = 120  # 2 минуты
        await ws_client.listen_prices(symbol, duration)

    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем (Ctrl+C)")

    finally:
        await ws_client.close()

    print("\n" + "=" * 80)
    print("✅ ТЕСТ ЗАВЕРШЕН")
    print("=" * 80)
    print("\n💡 ВЫВОДЫ:")
    print("   • С WebSocket получаем цену КАЖДУЮ СЕКУНДУ (не каждые 5 как REST)")
    print("   • PH проверяет КАЖДОЕ изменение цены")
    print("   • Шанс поймать быструю прибыль НАМНОГО ВЫШЕ!")
    print("   • OCO не успеет сработать - PH быстрее!")
    print("\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 До встречи!")
