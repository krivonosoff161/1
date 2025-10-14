"""
ФИНАЛЬНЫЙ ТЕСТ: OCO MARKET + tgtCcy='base_ccy'

Проверяем минимумы для ВСЕХ пар с правильным параметром!
"""
import asyncio
from src.config import load_config
from src.models import OrderSide, OrderType
from src.okx_client import OKXClient

async def test_oco_with_tgtccy(client, symbol, side, position_usd):
    """Тест OCO с tgtCcy."""
    
    ticker = await client.get_ticker(symbol)
    price = float(ticker["last"])
    
    qty = round(position_usd / price, 8)
    atr = price * 0.01
    
    if side == "LONG":
        order_side = OrderSide.BUY
        close_side = "sell"
        tp = price + (atr * 1.5)
        sl = price - (atr * 2.5)
    else:
        order_side = OrderSide.SELL
        close_side = "buy"
        tp = price - (atr * 1.5)
        sl = price + (atr * 2.5)
    
    print(f"\n{'─'*60}")
    print(f"{symbol} {side} ${position_usd:.0f}")
    print(f"  Entry: {qty:.8f} = ${qty * price:.2f}")
    print(f"  TP: ${qty * tp:.2f} | SL: ${qty * sl:.2f}")
    
    # Основная позиция
    main = await client.place_order(symbol, order_side, OrderType.MARKET, qty)
    if not main:
        print(f"  ❌ MAIN")
        return False
    print(f"  ✅ MAIN: {main.id}")
    
    await asyncio.sleep(0.3)
    
    # OCO с tgtCcy!
    oco_data = {
        "instId": symbol,
        "tdMode": "cash",
        "side": close_side,
        "ordType": "oco",
        "sz": str(qty),
        "tgtCcy": "base_ccy",  # ← КЛЮЧЕВОЙ ПАРАМЕТР!
        "tpTriggerPx": f"{tp:.6f}",
        "tpOrdPx": "-1",
        "slTriggerPx": f"{sl:.6f}",
        "slOrdPx": "-1",
    }
    
    try:
        result = await client._make_request("POST", "/trade/order-algo", data=oco_data)
        if result.get("code") == "0":
            print(f"  ✅ OCO: {result['data'][0].get('algoId')}")
            return True
        else:
            print(f"  ❌ OCO: {result.get('msg')}")
            return False
    except Exception as e:
        print(f"  ❌ OCO: {e}")
        return False

async def main():
    config = load_config("config.yaml")
    client = OKXClient(config.get_okx_config())
    
    print(f"\n{'='*60}")
    print("ФИНАЛЬНЫЙ ТЕСТ: OCO+MARKET+tgtCcy")
    print("="*60)
    
    tests = [
        ("BTC-USDT", "LONG", 30),
        ("BTC-USDT", "SHORT", 43),
        ("ETH-USDT", "LONG", 30),
        ("ETH-USDT", "SHORT", 43),
        ("SOL-USDT", "LONG", 30),
        ("SOL-USDT", "SHORT", 43),
    ]
    
    results = []
    
    for symbol, side, size in tests:
        success = await test_oco_with_tgtccy(client, symbol, side, size)
        results.append((symbol, side, size, success))
        await asyncio.sleep(1)
    
    # ИТОГИ
    print(f"\n{'='*60}")
    print("РЕЗУЛЬТАТЫ:")
    print("="*60)
    
    for symbol, side, size, success in results:
        status = "✅" if success else "❌"
        print(f"{status} {symbol:12} {side:5} ${size}")
    
    success_count = sum(1 for _, _, _, s in results if s)
    print(f"\nУСПЕШНО: {success_count}/{len(tests)}")
    
    if success_count == len(tests):
        print(f"\n🎉 ВСЕ РАБОТАЕТ!")
        print(f"✅ LONG: минимум $30")
        print(f"✅ SHORT: минимум $43")
        print(f"✅ Средняя позиция: $36.50")
        print(f"\n🚀 ПЕРЕДЕЛЫВАЕМ БОТ НА OCO+MARKET+tgtCcy!")
    else:
        print(f"\n⚠️ Есть проблемы...")
    
    print("="*60)
    
    await client.session.close()

asyncio.run(main())

