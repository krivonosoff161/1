"""Debug OCO для SHORT."""
import asyncio
import json
from src.config import load_config
from src.models import OrderSide, OrderType
from src.okx_client import OKXClient

async def test():
    config = load_config("config.yaml")
    client = OKXClient(config.get_okx_config())
    
    symbol = "SOL-USDT"
    ticker = await client.get_ticker(symbol)
    price = float(ticker["last"])
    
    target = 43.0
    qty = round(target / price, 8)
    
    atr = price * 0.01
    tp = price - (atr * 1.5)
    sl = price + (atr * 2.5)
    
    print(f"\n{symbol} SHORT:")
    print(f"Qty: {qty:.8f} SOL")
    print(f"Entry: ${qty * price:.2f}")
    print(f"TP: ${tp:.2f} (${qty * tp:.2f})")
    print(f"SL: ${sl:.2f} (${qty * sl:.2f})")
    
    # Основной SHORT
    print(f"\n1. MAIN SHORT:")
    main_data = {
        "instId": symbol,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": str(qty),
        "tgtCcy": "base_ccy",
    }
    print(f"   {json.dumps(main_data, indent=3)}")
    
    main = await client.place_order(symbol, OrderSide.SELL, OrderType.MARKET, qty)
    if main:
        print(f"   ✅ ID: {main.id}")
    else:
        print(f"   ❌ Провал")
        await client.session.close()
        return
    
    await asyncio.sleep(0.5)
    
    # OCO ордер
    print(f"\n2. OCO ОРДЕР:")
    oco_data = {
        "instId": symbol,
        "tdMode": "cash",
        "side": "buy",  # Закрываем SHORT = покупаем обратно
        "ordType": "oco",
        "sz": str(qty),  # ← КОЛИЧЕСТВО В SOL
        "tpTriggerPx": f"{tp:.6f}",
        "tpOrdPx": "-1",
        "slTriggerPx": f"{sl:.6f}",
        "slOrdPx": "-1",
    }
    
    print(f"   {json.dumps(oco_data, indent=3)}")
    print(f"\n   ⚠️ ВОПРОС: Может для OCO нужен tgtCcy?")
    print(f"   Или sz должен быть в USDT для закрытия SHORT?")
    
    try:
        result = await client._make_request("POST", "/trade/order-algo", data=oco_data)
        if result.get("code") == "0":
            print(f"\n   ✅ OCO: {result['data'][0].get('algoId')}")
            print(f"   📋 ПРОВЕРЬ НА БИРЖЕ:")
            print(f"      Количество показано в SOL или USDT?")
        else:
            print(f"\n   ❌ OCO: {result.get('msg')}")
    except Exception as e:
        print(f"\n   ❌ OCO: {e}")
    
    await client.session.close()

asyncio.run(test())

