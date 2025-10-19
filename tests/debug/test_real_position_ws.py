#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 ПОЛНЫЙ ТЕСТ: Реальная позиция + WebSocket + PH
ВНИМАНИЕ: Открывает РЕАЛЬНУЮ позицию на OKX DEMO!
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp

# Добавляем корень проекта
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.okx_client import OKXClient


class RealPositionWebSocketTest:
    """Тест с реальной позицией и WebSocket мониторингом"""

    def __init__(self):
        self.config = None
        self.client = None
        self.ws = None
        self.ws_session = None

        # Позиция
        self.position = None
        self.entry_price = None
        self.position_size = None
        self.order_id = None
        self.oco_id = None
        self.tp_price = None
        self.sl_price = None
        self.open_time = None

        # PH параметры
        self.ph_threshold = 0.03  # $0.03 для теста
        self.ph_time_limit = 90  # 90 секунд

        # Статистика
        self.ph_checks = 0
        self.price_updates = 0
        self.position_closed = False

    async def setup(self):
        """Подключение к OKX REST + WebSocket"""
        print("\n" + "=" * 100)
        print("🚀 НАСТРОЙКА ТЕСТА")
        print("=" * 100 + "\n")

        # 1. Загружаем конфигурацию
        print("📋 Загрузка конфигурации...")
        self.config = load_config("config.yaml")
        okx_config = self.config.get_okx_config()

        # 2. Подключаем REST API клиент
        print("🔌 Подключение к OKX REST API...")
        self.client = OKXClient(okx_config)
        await self.client.connect()

        # Проверяем баланс
        balance = await self.client.get_balance("USDT")
        print(f"✅ REST API подключен | Баланс: ${balance:.2f}")

        if balance < 100:
            print(f"⚠️  НИЗКИЙ БАЛАНС: ${balance:.2f}")
            return False

        # 3. Подключаем WebSocket
        print("🔌 Подключение к OKX WebSocket...")
        self.ws_session = aiohttp.ClientSession()

        ws_url = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"
        self.ws = await self.ws_session.ws_connect(ws_url, heartbeat=20)

        print(f"✅ WebSocket подключен: {ws_url}")
        print()

        return True

    async def open_position(self, symbol: str, side: str, size_usd: float = 70.0):
        """Открывает РЕАЛЬНУЮ позицию"""
        print("=" * 100)
        print(f"📈 ОТКРЫТИЕ ПОЗИЦИИ: {symbol} {side}")
        print("=" * 100 + "\n")

        try:
            # 1. Получаем текущую цену (get_ticker уже возвращает первый элемент!)
            ticker = await self.client.get_ticker(symbol)

            if not ticker or "last" not in ticker:
                print(f"❌ Не удалось получить тикер: {ticker}")
                return False

            current_price = float(ticker["last"])

            print(f"💰 Текущая цена: ${current_price:.2f}")

            # 2. Рассчитываем размер позиции
            if "BTC" in symbol:
                position_size = size_usd / current_price
            else:  # ETH
                position_size = size_usd / current_price

            print(f"📦 Размер позиции: {position_size:.6f} (${size_usd})")

            # 3. Размещаем ордер
            print(f"🔄 Размещаю {side} ордер...")

            from src.models import OrderSide, OrderType

            order_side = OrderSide.BUY if side == "LONG" else OrderSide.SELL

            order_result = await self.client.place_order(
                symbol=symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=position_size,
            )

            if not order_result:
                print(f"❌ Ошибка открытия позиции")
                return False

            self.order_id = order_result.id
            self.entry_price = current_price
            self.position_size = position_size
            self.open_time = datetime.utcnow()

            print(f"✅ Позиция открыта!")
            print(f"   Order ID: {self.order_id}")
            print(f"   Entry: ${self.entry_price:.2f}")
            print(f"   Size: {self.position_size:.6f}")

            # 4. Ставим OCO (TP/SL)
            print(f"\n🎯 Размещаю OCO ордер...")

            # Простые TP/SL для теста
            if side == "LONG":
                self.tp_price = current_price * 1.005  # +0.5%
                self.sl_price = current_price * 0.995  # -0.5%
            else:  # SHORT
                self.tp_price = current_price * 0.995  # -0.5%
                self.sl_price = current_price * 1.005  # +0.5%

            print(
                f"   TP: ${self.tp_price:.2f} ({((self.tp_price/current_price-1)*100):+.2f}%)"
            )
            print(
                f"   SL: ${self.sl_price:.2f} ({((self.sl_price/current_price-1)*100):+.2f}%)"
            )

            # Размещаем OCO
            oco_side = OrderSide.SELL if side == "LONG" else OrderSide.BUY

            oco_result = await self.client.place_oco_order(
                symbol=symbol,
                side=oco_side,
                quantity=position_size,
                tp_trigger_price=self.tp_price,
                sl_trigger_price=self.sl_price,
            )

            if oco_result:  # Возвращает algo_id напрямую
                self.oco_id = oco_result
                print(f"✅ OCO размещен: {self.oco_id}")
            else:
                print(f"⚠️  OCO не размещен")

            print()
            return True

        except Exception as e:
            print(f"❌ Ошибка открытия позиции: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def monitor_position_ws(self, symbol: str, duration: int = 90):
        """Мониторит позицию через WebSocket"""
        print("=" * 100)
        print(f"👁️  МОНИТОРИНГ ПОЗИЦИИ ЧЕРЕЗ WEBSOCKET")
        print(f"   Символ: {symbol}")
        print(f"   Длительность: {duration}s")
        print(f"   PH Threshold: ${self.ph_threshold}")
        print(f"   PH Time Limit: {self.ph_time_limit}s")
        print("=" * 100 + "\n")

        # Подписываемся на тикер
        subscribe_msg = {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instId": symbol}],
        }
        await self.ws.send_json(subscribe_msg)

        start_time = time.time()
        last_print = time.time()

        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)

                    if "event" in data and data["event"] == "subscribe":
                        print(f"✅ Подписка активна\n")
                        continue

                    if "data" in data:
                        for ticker in data["data"]:
                            current_price = float(ticker.get("last", 0))

                            if current_price > 0:
                                self.price_updates += 1

                                # Проверяем PH
                                should_close, reason = await self.check_ph(
                                    current_price
                                )

                                # Выводим раз в секунду
                                now = time.time()
                                if now - last_print >= 1.0:
                                    elapsed = now - start_time
                                    self.print_status(current_price, elapsed)
                                    last_print = now

                                # Закрываем если PH сработал
                                if should_close:
                                    await self.close_position(
                                        symbol, current_price, reason
                                    )
                                    return True

                # Проверяем время
                if time.time() - start_time >= duration:
                    print(f"\n⏰ Время мониторинга истекло ({duration}s)")

                    # Закрываем позицию вручную
                    current_price = float(ticker.get("last", self.entry_price))
                    await self.close_position(symbol, current_price, "timeout")
                    return False

        except asyncio.CancelledError:
            print("\n⚠️  Мониторинг прерван")
            return False

    async def check_ph(self, current_price: float) -> tuple[bool, str]:
        """Проверяет условия Profit Harvesting"""
        self.ph_checks += 1

        if not self.entry_price:
            return False, ""

        # Время с открытия
        time_since_open = (datetime.utcnow() - self.open_time).total_seconds()

        # Расчет PnL (как в реальном боте!)
        pnl_usd = (current_price - self.entry_price) * self.position_size

        # Условия PH
        if pnl_usd >= self.ph_threshold and time_since_open < self.ph_time_limit:
            return True, "PROFIT_HARVESTING"

        # Также проверяем OCO
        if current_price >= self.tp_price:
            return True, "TAKE_PROFIT"

        if current_price <= self.sl_price:
            return True, "STOP_LOSS"

        return False, ""

    def print_status(self, current_price: float, elapsed: float):
        """Печатает статус позиции"""
        time_since_open = (datetime.utcnow() - self.open_time).total_seconds()
        pnl_usd = (current_price - self.entry_price) * self.position_size
        pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100

        # Прогресс до TP/SL
        dist_to_tp = self.tp_price - current_price
        dist_to_sl = current_price - self.sl_price

        # Прогресс PH
        ph_progress = (pnl_usd / self.ph_threshold * 100) if pnl_usd > 0 else 0
        ph_bar = "█" * int(ph_progress / 10)

        status = "📈" if pnl_usd > 0 else "📉"

        print(
            f"\n{status} [{elapsed:.0f}s] Price: ${current_price:.2f} | "
            f"PnL: ${pnl_usd:.4f} ({pnl_pct:+.3f}%)"
        )
        print(f"   🎯 PH: {ph_bar:<10} {ph_progress:.0f}% (порог ${self.ph_threshold})")
        print(f"   ⬆️  TP: ${dist_to_tp:+.2f} до ${self.tp_price:.2f}")
        print(f"   ⬇️  SL: ${dist_to_sl:+.2f} до ${self.sl_price:.2f}")
        print(f"   ⏱️  Time: {time_since_open:.0f}s / {self.ph_time_limit}s")

    async def close_position(self, symbol: str, current_price: float, reason: str):
        """Закрывает позицию"""
        print("\n" + "🔥" * 50)
        print("🏁 ЗАКРЫТИЕ ПОЗИЦИИ")
        print("🔥" * 50 + "\n")

        # Расчет финального PnL
        gross_pnl = (current_price - self.entry_price) * self.position_size
        # Примерная комиссия
        commission = (self.entry_price * self.position_size * 0.001) + (
            current_price * self.position_size * 0.001
        )
        net_pnl = gross_pnl - commission

        time_held = (datetime.utcnow() - self.open_time).total_seconds()

        print(f"📊 ДЕТАЛИ:")
        print(f"   Символ: {symbol}")
        print(f"   Entry: ${self.entry_price:.2f}")
        print(f"   Exit: ${current_price:.2f}")
        print(f"   Size: {self.position_size:.6f}")
        print(f"   Время удержания: {time_held:.0f}s ({time_held/60:.1f}min)")
        print(f"\n💰 PnL:")
        print(f"   Gross: ${gross_pnl:.4f}")
        print(f"   Commission: ${commission:.4f}")
        print(f"   Net: ${net_pnl:.4f}")
        print(f"\n🎯 Причина: {reason}")

        try:
            # Закрываем MARKET ордером
            print(f"\n🔄 Закрываю позицию MARKET ордером...")

            from src.models import OrderSide, OrderType

            close_result = await self.client.place_order(
                symbol=symbol,
                side=OrderSide.SELL,  # Закрываем LONG
                order_type=OrderType.MARKET,
                quantity=self.position_size,
            )

            if close_result:
                print(f"✅ Позиция закрыта! Order ID: {close_result.id}")
            else:
                print(f"⚠️  Ошибка закрытия")

            # Отменяем OCO если он есть
            if self.oco_id:
                print(f"\n🔄 Отменяю OCO ордер {self.oco_id}...")

                cancel_result = await self.client._make_request(
                    "POST",
                    "/trade/cancel-algos",
                    data=[{"algoId": self.oco_id, "instId": symbol}],
                )

                if cancel_result and cancel_result.get("code") == "0":
                    print(f"✅ OCO отменен")
                else:
                    print(
                        f"⚠️  OCO не отменен (возможно уже сработал): {cancel_result}"
                    )

            self.position_closed = True

        except Exception as e:
            print(f"❌ Ошибка закрытия: {e}")
            import traceback

            traceback.print_exc()

        print("\n" + "=" * 100)

    async def run_test(self, symbol: str = "ETH-USDT"):
        """Запуск полного теста"""

        print("\n" + "=" * 100)
        print("🧪 ПОЛНЫЙ ТЕСТ ЖИЗНЕННОГО ЦИКЛА ПОЗИЦИИ")
        print("=" * 100)
        print(f"\nСимвол: {symbol}")
        print(f"PH Threshold: ${self.ph_threshold}")
        print(f"PH Time Limit: {self.ph_time_limit}s")
        print("\n⚠️  ВНИМАНИЕ: Будет открыта РЕАЛЬНАЯ позиция на OKX DEMO!")
        print("⚠️  Позиция будет закрыта автоматически через PH, TP/SL или timeout")
        print("=" * 100 + "\n")

        # Настройка
        if not await self.setup():
            print("❌ Ошибка настройки")
            return

        # Открываем позицию
        if not await self.open_position(symbol, "LONG", size_usd=70.0):
            print("❌ Ошибка открытия позиции")
            return

        # Даем 2 секунды на исполнение ордера
        print("⏳ Ожидание исполнения ордера...")
        await asyncio.sleep(2)

        # Мониторим через WebSocket
        print("\n🎬 НАЧИНАЮ МОНИТОРИНГ...\n")

        await self.monitor_position_ws(symbol, duration=self.ph_time_limit + 30)

        # Итоги
        self.print_final_stats()

    def print_final_stats(self):
        """Печатает финальную статистику"""
        print("\n" + "=" * 100)
        print("📊 ФИНАЛЬНАЯ СТАТИСТИКА ТЕСТА")
        print("=" * 100 + "\n")

        print(f"📡 WebSocket обновлений: {self.price_updates}")
        print(f"🔍 PH проверок: {self.ph_checks}")
        print(f"✅ Позиция закрыта: {'ДА' if self.position_closed else 'НЕТ'}")

        print("\n💡 ВЫВОДЫ:")
        print("=" * 100)

        if self.price_updates > 0:
            avg_freq = self.price_updates / self.ph_time_limit
            print(f"• WebSocket дает {avg_freq:.2f} обновлений/сек")
            print(f"• Это в {avg_freq / 0.2:.0f}x БЫСТРЕЕ чем REST (0.2 обновл/сек)")

        print(f"• PH имел {self.ph_checks} шансов сработать")
        print(f"• С REST было бы только {self.ph_time_limit // 5} шансов")

        if self.position_closed:
            print("\n✅ ПОЗИЦИЯ УСПЕШНО ОТКРЫТА И ЗАКРЫТА!")
        else:
            print("\n⚠️  Позиция не закрыта - проверь на бирже вручную!")

        print("=" * 100 + "\n")

    async def cleanup(self):
        """Закрытие соединений"""
        if self.ws:
            await self.ws.close()
        if self.ws_session:
            await self.ws_session.close()
        if self.client:
            await self.client.session.close()


async def main():
    """Главная функция"""

    tester = RealPositionWebSocketTest()

    try:
        await tester.run_test(symbol="ETH-USDT")

    except KeyboardInterrupt:
        print("\n\n⚠️  ТЕСТ ПРЕРВАН! Закрываю позицию...")

        if tester.position and not tester.position_closed:
            # Получаем текущую цену и закрываем
            try:
                ticker = await tester.client.get_ticker("ETH-USDT")
                current_price = float(ticker["data"][0]["last"])
                await tester.close_position("ETH-USDT", current_price, "interrupted")
            except:
                print("❌ Не удалось закрыть автоматически - ЗАКРОЙ ВРУЧНУЮ НА БИРЖЕ!")

    finally:
        await tester.cleanup()

    print("\n👋 Тест завершен!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Выход...")
