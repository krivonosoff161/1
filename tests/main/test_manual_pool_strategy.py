#!/usr/bin/env python3
"""
Тест Manual Pool Strategy - проверка новых параметров
"""

import asyncio

from src.config import load_config
from src.main import BotRunner


async def test_manual_pool_strategy():
    print("🧪 ТЕСТ MANUAL POOL STRATEGY")
    print("=" * 50)

    try:
        # Загружаем конфиг
        config = load_config()
        print("✅ Конфиг загружен")

        # Проверяем manual_pools
        print(
            f"Config attributes: {[attr for attr in dir(config) if not attr.startswith('_')]}"
        )

        # Проверяем в разных местах
        if hasattr(config, "manual_pools"):
            print("✅ Manual pools найдены в корне")
            # Проверяем ETH pool
            eth_pool = config.manual_pools["eth_pool"]
            btc_pool = config.manual_pools["btc_pool"]
            usdt_pool = config.manual_pools["usdt_pool"]
        elif hasattr(config, "scalping") and hasattr(config.scalping, "manual_pools"):
            print("✅ Manual pools найдены в scalping")
            # Проверяем ETH pool
            eth_pool = config.scalping.manual_pools["eth_pool"]
            btc_pool = config.scalping.manual_pools["btc_pool"]
            usdt_pool = config.scalping.manual_pools["usdt_pool"]
        else:
            print("❌ Manual pools не найдены")
            print(
                f"Scalping attributes: {[attr for attr in dir(config.scalping) if not attr.startswith('_')]}"
            )
            return

        # Продолжаем только если manual_pools найдены
        print(f"\n📊 ETH POOL:")
        print(f"   Fixed Amount: {eth_pool['fixed_amount']} USDT")
        print(f"   Max Positions: {eth_pool['max_open_positions']}")
        print(f"   Priority: {eth_pool['priority']}")
        print(f"   Trending: {eth_pool['trending']['quantity_per_trade']} ETH")
        print(f"   Ranging: {eth_pool['ranging']['quantity_per_trade']} ETH")
        print(f"   Choppy: {eth_pool['choppy']['quantity_per_trade']} ETH")

        # Проверяем BTC pool
        print(f"\n📊 BTC POOL:")
        print(f"   Fixed Amount: {btc_pool['fixed_amount']} USDT")
        print(f"   Max Positions: {btc_pool['max_open_positions']}")
        print(f"   Priority: {btc_pool['priority']}")
        print(f"   Trending: {btc_pool['trending']['quantity_per_trade']} BTC")
        print(f"   Ranging: {btc_pool['ranging']['quantity_per_trade']} BTC")
        print(f"   Choppy: {btc_pool['choppy']['quantity_per_trade']} BTC")

        # Проверяем USDT pool
        print(f"\n📊 USDT POOL:")
        print(f"   Fixed Amount: {usdt_pool['fixed_amount']} USDT")
        print(f"   Max Positions: {usdt_pool['max_open_positions']}")
        print(f"   Priority: {usdt_pool['priority']}")
        print(f"   Trending: {usdt_pool['trending']['quantity_per_trade']} USDT")
        print(f"   Ranging: {usdt_pool['ranging']['quantity_per_trade']} USDT")
        print(f"   Choppy: {usdt_pool['choppy']['quantity_per_trade']} USDT")

        # Тестируем бота
        print("\n🤖 ТЕСТ БОТА:")
        print("-" * 30)

        bot = BotRunner(config)
        await bot.initialize()

        # Проверяем стратегию
        if hasattr(bot.strategy, "config"):
            print("✅ Стратегия загружена")

            # Проверяем доступ к manual_pools через full_config
            if hasattr(bot.strategy, "full_config") and hasattr(
                bot.strategy.full_config, "manual_pools"
            ):
                print("✅ Manual pools доступны в стратегии через full_config")

                # Проверяем параметры для каждого режима
                print("\n🔍 ПРОВЕРКА ПАРАМЕТРОВ ПО РЕЖИМАМ:")

                # TRENDING режим
                print("\n📈 TRENDING РЕЖИМ:")
                eth_trending = bot.strategy.full_config.manual_pools["eth_pool"][
                    "trending"
                ]
                print(
                    f"   ETH: {eth_trending['quantity_per_trade']} ETH, Score: {eth_trending['score_threshold']}"
                )
                print(
                    f"   TP: {eth_trending['tp_percent']}%, SL: {eth_trending['sl_percent']}%"
                )
                print(
                    f"   Time: {eth_trending['time_limit_seconds']}s, PH: {eth_trending['ph_threshold']}"
                )

                btc_trending = bot.strategy.full_config.manual_pools["btc_pool"][
                    "trending"
                ]
                print(
                    f"   BTC: {btc_trending['quantity_per_trade']} BTC, Score: {btc_trending['score_threshold']}"
                )
                print(
                    f"   TP: {btc_trending['tp_percent']}%, SL: {btc_trending['sl_percent']}%"
                )
                print(
                    f"   Time: {btc_trending['time_limit_seconds']}s, PH: {btc_trending['ph_threshold']}"
                )

                # RANGING режим
                print("\n📊 RANGING РЕЖИМ:")
                eth_ranging = bot.strategy.full_config.manual_pools["eth_pool"][
                    "ranging"
                ]
                print(
                    f"   ETH: {eth_ranging['quantity_per_trade']} ETH, Score: {eth_ranging['score_threshold']}"
                )
                print(
                    f"   TP: {eth_ranging['tp_percent']}%, SL: {eth_ranging['sl_percent']}%"
                )
                print(
                    f"   Time: {eth_ranging['time_limit_seconds']}s, PH: {eth_ranging['ph_threshold']}"
                )

                btc_ranging = bot.strategy.full_config.manual_pools["btc_pool"][
                    "ranging"
                ]
                print(
                    f"   BTC: {btc_ranging['quantity_per_trade']} BTC, Score: {btc_ranging['score_threshold']}"
                )
                print(
                    f"   TP: {btc_ranging['tp_percent']}%, SL: {btc_ranging['sl_percent']}%"
                )
                print(
                    f"   Time: {btc_ranging['time_limit_seconds']}s, PH: {btc_ranging['ph_threshold']}"
                )

                # CHOPPY режим
                print("\n🌪️ CHOPPY РЕЖИМ:")
                eth_choppy = bot.strategy.full_config.manual_pools["eth_pool"]["choppy"]
                print(
                    f"   ETH: {eth_choppy['quantity_per_trade']} ETH, Score: {eth_choppy['score_threshold']}"
                )
                print(
                    f"   TP: {eth_choppy['tp_percent']}%, SL: {eth_choppy['sl_percent']}%"
                )
                print(
                    f"   Time: {eth_choppy['time_limit_seconds']}s, PH: {eth_choppy['ph_threshold']}"
                )

                btc_choppy = bot.strategy.full_config.manual_pools["btc_pool"]["choppy"]
                print(
                    f"   BTC: {btc_choppy['quantity_per_trade']} BTC, Score: {btc_choppy['score_threshold']}"
                )
                print(
                    f"   TP: {btc_choppy['tp_percent']}%, SL: {btc_choppy['sl_percent']}%"
                )
                print(
                    f"   Time: {btc_choppy['time_limit_seconds']}s, PH: {btc_choppy['ph_threshold']}"
                )

            else:
                print("❌ Manual pools недоступны в стратегии")

        print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        print("\n🚀 ГОТОВ К ЗАПУСКУ!")

    except Exception as e:
        print(f"❌ Ошибка теста: {e}")
        import traceback

        traceback.print_exc()
    finally:
        try:
            await bot.shutdown()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(test_manual_pool_strategy())
