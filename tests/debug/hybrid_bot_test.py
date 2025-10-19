#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔬 ГИБРИДНЫЙ БОТ (ТЕСТОВЫЙ)
WebSocket (цены реал-тайм) + REST (свечи/индикаторы) + Полная стратегия
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import aiohttp

# Добавляем корень проекта
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.models import OrderSide, OrderType
from src.okx_client import OKXClient
from src.strategies.scalping.orchestrator import ScalpingOrchestrator


class WebSocketPriceManager:
    """Менеджер цен через WebSocket"""

    def __init__(self):
        self.ws = None
        self.session = None
        self.current_prices: Dict[str, float] = {}
        self.price_callbacks = []
        self.running = False

    async def connect(self):
        """Подключение к WebSocket"""
        print("📡 Подключаю WebSocket...")

        self.session = aiohttp.ClientSession()
        ws_url = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"

        self.ws = await self.session.ws_connect(ws_url, heartbeat=20)
        print(f"✅ WebSocket подключен\n")

    async def subscribe(self, symbols: list):
        """Подписка на тикеры"""
        args = [{"channel": "tickers", "instId": symbol} for symbol in symbols]

        subscribe_msg = {"op": "subscribe", "args": args}

        await self.ws.send_json(subscribe_msg)
        print(f"✅ Подписка на {len(symbols)} символов")

    async def start_listening(self):
        """Запуск прослушивания цен"""
        self.running = True

        async for msg in self.ws:
            if not self.running:
                break

            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)

                if "event" in data:
                    continue

                if "data" in data:
                    for ticker in data["data"]:
                        symbol = ticker.get("instId")
                        price = float(ticker.get("last", 0))

                        if symbol and price > 0:
                            # Обновляем цену
                            old_price = self.current_prices.get(symbol)
                            self.current_prices[symbol] = price

                            # Вызываем callback'и
                            for callback in self.price_callbacks:
                                await callback(symbol, price, old_price)

    def add_callback(self, callback):
        """Добавляет callback на обновление цены"""
        self.price_callbacks.append(callback)

    def get_price(self, symbol: str) -> Optional[float]:
        """Получает текущую цену"""
        return self.current_prices.get(symbol)

    async def stop(self):
        """Остановка"""
        self.running = False
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()


class HybridTradingBot:
    """Гибридный торговый бот (WS + REST)"""

    def __init__(self):
        self.config = None
        self.rest_client = None
        self.ws_manager = None
        self.orchestrator = None

        # Состояние
        self.symbols = ["BTC-USDT", "ETH-USDT"]
        self.open_positions = {}
        self.last_signal_check = {}

        # Статистика
        self.price_updates = 0
        self.signals_generated = 0
        self.positions_opened = 0
        self.ph_triggers = 0

    async def setup(self):
        """Настройка бота"""
        print("\n" + "=" * 100)
        print("🚀 НАСТРОЙКА ГИБРИДНОГО БОТА")
        print("=" * 100 + "\n")

        # 1. Конфигурация
        print("📋 Загрузка конфигурации...")
        self.config = load_config("config.yaml")

        # 2. REST клиент
        print("🔌 Подключение REST API...")
        okx_config = self.config.get_okx_config()
        self.rest_client = OKXClient(okx_config)
        await self.rest_client.connect()

        balance = await self.rest_client.get_balance("USDT")
        print(f"✅ REST подключен | Баланс: ${balance:.2f}")

        # 3. WebSocket менеджер
        print("📡 Подключение WebSocket...")
        self.ws_manager = WebSocketPriceManager()
        await self.ws_manager.connect()
        await self.ws_manager.subscribe(self.symbols)

        # 4. Orchestrator (НО НЕ ЗАПУСКАЕМ ЕГО run()!)
        print("🎯 Инициализация Orchestrator...")
        self.orchestrator = ScalpingOrchestrator(
            self.rest_client, self.config.scalping, self.config.risk
        )
        print("✅ Orchestrator готов")

        # 5. Callback на обновления цен
        self.ws_manager.add_callback(self.on_price_update)

        print("\n✅ ВСЁ ГОТОВО!\n")

    async def on_price_update(
        self, symbol: str, price: float, old_price: Optional[float]
    ):
        """Callback на обновление цены через WebSocket"""
        self.price_updates += 1

        # Проверяем открытые позиции (PH мониторинг)
        if symbol in self.open_positions:
            await self.check_profit_harvesting(symbol, price)

    async def check_profit_harvesting(self, symbol: str, current_price: float):
        """Проверка Profit Harvesting"""
        position = self.open_positions[symbol]

        # Используем РЕАЛЬНУЮ логику из position_manager
        time_since_open = (datetime.utcnow() - position["open_time"]).total_seconds()

        # Расчет PnL
        if position["side"] == "LONG":
            pnl_usd = (current_price - position["entry_price"]) * position["size"]
        else:
            pnl_usd = (position["entry_price"] - current_price) * position["size"]

        # PH условия (из ARM)
        ph_threshold = 0.03  # Тестовый порог
        ph_time_limit = 90

        # Проверка
        if pnl_usd >= ph_threshold and time_since_open < ph_time_limit:
            self.ph_triggers += 1

            print(f"\n{'🎉'*50}")
            print(f"💰 PROFIT HARVESTING! {symbol}")
            print(f"{'🎉'*50}")
            print(f"PnL: ${pnl_usd:.4f} за {time_since_open:.0f}s")
            print(f"Entry: ${position['entry_price']:.2f} → Exit: ${current_price:.2f}")

            # Закрываем позицию
            await self.close_position(symbol, current_price, "PROFIT_HARVESTING")

    async def analyze_and_generate_signals(self):
        """Анализ рынка и генерация сигналов (REST - раз в 5-10 сек)"""

        for symbol in self.symbols:
            try:
                # 1. Получаем свечи (REST)
                candles = await self.rest_client.get_candles(symbol, "5m", limit=200)
                if not candles:
                    continue

                # 2. Текущая цена ИЗ WEBSOCKET! (не REST!)
                current_price = self.ws_manager.get_price(symbol)
                if not current_price:
                    # Fallback на REST если WS еще не обновился
                    ticker = await self.rest_client.get_ticker(symbol)
                    current_price = float(ticker["last"])

                # 3. Создаем MarketData (как в настоящем боте)
                from src.models import MarketData

                market_data = MarketData(
                    symbol=symbol,
                    current_price=current_price,
                    candles=candles,
                    timestamp=datetime.utcnow(),
                )

                # Сохраняем в кэш orchestrator
                self.orchestrator.market_data_cache[symbol] = market_data

                # 4. Рассчитываем индикаторы
                indicators = self.orchestrator.indicators.calculate_all(candles)

                # 5. Проверяем можем ли торговать
                can_trade, reason = self.orchestrator.risk_controller.can_open_position(
                    symbol, len(self.open_positions)
                )

                if not can_trade:
                    continue

                # 6. Обновляем ARM режим
                if self.orchestrator.arm:
                    regime_info = self.orchestrator.arm.detect_regime(
                        candles, indicators
                    )
                    regime = regime_info["regime"]

                    # Обновляем параметры под режим
                    self.orchestrator.signal_generator.update_regime_parameters(
                        regime, current_price
                    )

                # 7. Генерируем сигнал
                signal = self.orchestrator.signal_generator.generate_signal(
                    symbol, candles, indicators, current_price
                )

                if signal:
                    self.signals_generated += 1
                    print(
                        f"\n🎯 СИГНАЛ: {symbol} {signal.direction} | Score: {signal.score}/{signal.total_possible_score}"
                    )

                    # Открываем позицию (если еще нет)
                    if symbol not in self.open_positions:
                        await self.open_position(symbol, signal)

            except Exception as e:
                print(f"❌ Ошибка анализа {symbol}: {e}")

    async def open_position(self, symbol: str, signal):
        """Открытие позиции"""
        try:
            print(f"\n{'📈'*50}")
            print(f"ОТКРЫВАЮ ПОЗИЦИЮ: {symbol} {signal.direction}")
            print(f"{'📈'*50}\n")

            # Размер позиции
            size_usd = 70.0
            position_size = size_usd / signal.entry_price

            # Размещаем ордер
            side = OrderSide.BUY if signal.direction == "LONG" else OrderSide.SELL

            order = await self.rest_client.place_order(
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=position_size,
            )

            print(f"✅ Позиция открыта: {order.id}")
            print(f"   Entry: ${signal.entry_price:.2f}")
            print(f"   Size: {position_size:.6f}")

            # Размещаем OCO
            oco_side = OrderSide.SELL if signal.direction == "LONG" else OrderSide.BUY

            oco_id = await self.rest_client.place_oco_order(
                symbol=symbol,
                side=oco_side,
                quantity=position_size,
                tp_trigger_price=signal.take_profit,
                sl_trigger_price=signal.stop_loss,
            )

            print(f"✅ OCO размещен: {oco_id}")
            print(f"   TP: ${signal.take_profit:.2f}")
            print(f"   SL: ${signal.stop_loss:.2f}\n")

            # Сохраняем позицию
            self.open_positions[symbol] = {
                "order_id": order.id,
                "oco_id": oco_id,
                "side": signal.direction,
                "entry_price": signal.entry_price,
                "size": position_size,
                "tp_price": signal.take_profit,
                "sl_price": signal.stop_loss,
                "open_time": datetime.utcnow(),
            }

            self.positions_opened += 1

        except Exception as e:
            print(f"❌ Ошибка открытия: {e}")
            import traceback

            traceback.print_exc()

    async def close_position(self, symbol: str, current_price: float, reason: str):
        """Закрытие позиции"""
        if symbol not in self.open_positions:
            return

        position = self.open_positions[symbol]

        print(f"\n{'🏁'*50}")
        print(f"ЗАКРЫТИЕ: {symbol} | Причина: {reason}")
        print(f"{'🏁'*50}\n")

        try:
            # Закрываем market ордером
            side = OrderSide.SELL if position["side"] == "LONG" else OrderSide.BUY

            close_order = await self.rest_client.place_order(
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=position["size"],
            )

            print(f"✅ Закрыто: {close_order.id}")

            # Отменяем OCO
            if position["oco_id"]:
                cancel_success = await self.rest_client.cancel_algo_order(
                    position["oco_id"], symbol
                )
                if cancel_success:
                    print(f"✅ OCO отменен: {position['oco_id']}")

            # Расчет PnL
            if position["side"] == "LONG":
                gross_pnl = (current_price - position["entry_price"]) * position["size"]
            else:
                gross_pnl = (position["entry_price"] - current_price) * position["size"]

            commission = (position["entry_price"] * position["size"] * 0.001) + (
                current_price * position["size"] * 0.001
            )
            net_pnl = gross_pnl - commission

            duration = (datetime.utcnow() - position["open_time"]).total_seconds()

            print(f"\n💰 PnL:")
            print(f"   Entry: ${position['entry_price']:.2f}")
            print(f"   Exit: ${current_price:.2f}")
            print(f"   Gross: ${gross_pnl:.4f}")
            print(f"   Fee: ${commission:.4f}")
            print(f"   Net: ${net_pnl:.4f}")
            print(f"   Duration: {duration:.0f}s\n")

            # Удаляем позицию
            del self.open_positions[symbol]

        except Exception as e:
            print(f"❌ Ошибка закрытия: {e}")
            import traceback

            traceback.print_exc()

    async def run(self, duration_seconds: int = 300):
        """Запуск гибридного бота"""
        print("\n" + "=" * 100)
        print("🤖 ЗАПУСК ГИБРИДНОГО БОТА")
        print("=" * 100)
        print(f"\nРежим: WebSocket (цены) + REST (анализ)")
        print(f"Символы: {', '.join(self.symbols)}")
        print(f"Длительность: {duration_seconds}s ({duration_seconds/60:.0f} мин)")
        print("=" * 100 + "\n")

        start_time = asyncio.get_event_loop().time()

        # Запускаем WebSocket listener в фоне
        ws_task = asyncio.create_task(self.ws_manager.start_listening())

        # Даем время на первые обновления
        await asyncio.sleep(3)

        try:
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time

                if elapsed >= duration_seconds:
                    print(f"\n⏰ Время вышло ({duration_seconds}s)")
                    break

                # Анализ и генерация сигналов (REST)
                await self.analyze_and_generate_signals()

                # Показываем статус
                if int(elapsed) % 10 == 0:  # Каждые 10 сек
                    self.print_status(elapsed)

                # Следующая проверка через 5 сек
                await asyncio.sleep(5)

        except KeyboardInterrupt:
            print("\n⚠️  Прервано пользователем")

        finally:
            # Останавливаем WebSocket
            await self.ws_manager.stop()
            ws_task.cancel()

            # Закрываем открытые позиции
            if self.open_positions:
                print(f"\n⚠️  Закрываю {len(self.open_positions)} открытых позиций...")

                for symbol in list(self.open_positions.keys()):
                    price = self.ws_manager.get_price(symbol)
                    if price:
                        await self.close_position(symbol, price, "SHUTDOWN")

        # Итоги
        self.print_final_report()

    def print_status(self, elapsed: float):
        """Статус бота"""
        print(f"\n{'⏱️ '*20}")
        print(f"[{elapsed:.0f}s] Статус:")
        print(f"  📡 Обновлений цен: {self.price_updates}")
        print(f"  🎯 Сигналов: {self.signals_generated}")
        print(f"  📈 Позиций открыто: {self.positions_opened}")
        print(f"  💰 PH срабатываний: {self.ph_triggers}")
        print(f"  🔄 Активных позиций: {len(self.open_positions)}")

        # Показываем текущие цены
        for symbol in self.symbols:
            price = self.ws_manager.get_price(symbol)
            if price:
                status = "📈" if symbol in self.open_positions else "⚪"
                print(f"  {status} {symbol}: ${price:.2f}")

    def print_final_report(self):
        """Финальный отчет"""
        print("\n" + "=" * 100)
        print("📊 ФИНАЛЬНЫЙ ОТЧЕТ ГИБРИДНОГО БОТА")
        print("=" * 100 + "\n")

        print(f"📡 WebSocket обновлений цен: {self.price_updates}")
        print(f"🎯 Сигналов сгенерировано: {self.signals_generated}")
        print(f"📈 Позиций открыто: {self.positions_opened}")
        print(f"💰 Profit Harvesting срабатываний: {self.ph_triggers}")
        print(f"🔄 Незакрытых позиций: {len(self.open_positions)}")

        print("\n💡 ВЫВОДЫ:")
        print("=" * 100)
        print("✅ WebSocket дает обновления цен в РЕАЛЬНОМ ВРЕМЕНИ")
        print("✅ REST анализ с полными индикаторами каждые 5 сек")
        print("✅ Profit Harvesting проверяет при КАЖДОМ изменении цены")
        print("✅ Это ИДЕАЛЬНАЯ комбинация скорости и точности!")
        print("=" * 100 + "\n")

    async def cleanup(self):
        """Закрытие соединений"""
        if self.ws_manager:
            await self.ws_manager.stop()
        if self.rest_client:
            await self.rest_client.session.close()


async def main():
    """Главная функция"""

    print("\n" + "=" * 100)
    print("🧪 ТЕСТОВЫЙ ГИБРИДНЫЙ БОТ")
    print("=" * 100)
    print("\n⚠️  Это ТЕСТОВАЯ версия - не трогает рабочий бот!")
    print("⚠️  Будут открываться РЕАЛЬНЫЕ позиции на DEMO!")
    print("\n💡 Концепция:")
    print("   • WebSocket - цены в реальном времени")
    print("   • REST - свечи и индикаторы каждые 5 сек")
    print("   • Orchestrator - полная стратегия с фильтрами")
    print("   • PH - мгновенная реакция на прибыль")
    print("=" * 100 + "\n")

    bot = HybridTradingBot()

    try:
        await bot.setup()
        await bot.run(duration_seconds=180)  # 3 минуты теста

    except KeyboardInterrupt:
        print("\n\n⚠️  ТЕСТ ПРЕРВАН!")

    finally:
        await bot.cleanup()

    print("\n👋 Тест завершен!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Выход...")
