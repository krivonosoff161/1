#!/usr/bin/env python3
"""Анализ влияния округления на прибыль для всех торговых пар"""


def round_to_step(value: float, step: float) -> float:
    """Округление до шага (как в futures_client.py)"""
    if step == 0:
        return value
    return round(value / step) * step


# Конфигурация пар (реальные данные OKX)
pairs = {
    "BTC-USDT": {"price": 93500, "tick": 0.1, "min_size": 0.001},
    "ETH-USDT": {"price": 3270, "tick": 0.01, "min_size": 0.01},
    "SOL-USDT": {"price": 138, "tick": 0.01, "min_size": 0.1},
    "DOGE-USDT": {"price": 0.15, "tick": 0.0001, "min_size": 1},
    "XRP-USDT": {"price": 2.35, "tick": 0.001, "min_size": 0.1},
}

tp_values = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]  # Разные TP%
commission_pct = 0.2  # Maker 0.02% × 2 × leverage 5x

print("=" * 110)
print("АНАЛИЗ ВЛИЯНИЯ ОКРУГЛЕНИЯ НА ПРИБЫЛЬ ДЛЯ ВСЕХ ПАР")
print("=" * 110)

for symbol, data in pairs.items():
    price = data["price"]
    tick = data["tick"]

    print(f"\n{symbol:15} (Цена: ${price:>10}, Tick: ${tick:>8})")
    print("-" * 110)
    print(
        f'{"TP%":<8} {"TP exact":<18} {"TP rounded":<18} {"TP% real":<12} {"Потеря %":<12} {"Net profit":<12} {"Статус":<15}'
    )
    print("-" * 110)

    for tp_pct in tp_values:
        # Расчет
        tp_exact = price * (1 + tp_pct / 100)
        tp_rounded = round_to_step(tp_exact, tick)
        tp_pct_real = ((tp_rounded - price) / price) * 100
        loss_pct = tp_pct - tp_pct_real
        net_profit = tp_pct_real - commission_pct

        # Статус
        if net_profit > 0.8:
            status = "✅ ОТЛИЧНО"
        elif net_profit > 0.5:
            status = "✔️ ХОРОШО"
        elif net_profit > 0.3:
            status = "⚠️ МАРЖИНАЛЬНО"
        else:
            status = "❌ НЕ РЕКОМЕНДУЕТСЯ"

        print(
            f"{tp_pct:<8.2f} ${tp_exact:<17.8f} ${tp_rounded:<17.8f} "
            f"{tp_pct_real:<11.6f}% {loss_pct:<11.6f}% {net_profit:<11.6f}% {status:<15}"
        )

print("\n" + "=" * 110)
print("ЛЕГЕНДА:")
print("  ✅ ОТЛИЧНО: Net profit >0.8% - идеально для скальпинга")
print("  ✔️ ХОРОШО: Net profit 0.5-0.8% - приемлемо")
print("  ⚠️ МАРЖИНАЛЬНО: Net profit 0.3-0.5% - требует осторожности")
print("  ❌ НЕ РЕКОМЕНДУЕТСЯ: Net profit <0.3% - высокий риск убытка")
print("=" * 110)

# Специфичные рекомендации
print("\nРЕКОМЕНДАЦИИ ПО ПАРАМ:")
print("-" * 110)

for symbol, data in pairs.items():
    price = data["price"]
    tick = data["tick"]

    # Находим минимальный TP для net >0.5%
    min_tp = 0.0
    for tp in [i * 0.1 for i in range(5, 100)]:  # От 0.5% до 10%
        tp_rounded = round_to_step(price * (1 + tp / 100), tick)
        tp_real = ((tp_rounded - price) / price) * 100
        net = tp_real - commission_pct
        if net >= 0.5:
            min_tp = tp
            break

    # Потеря на типичный TP 1.5%
    tp_1_5_exact = price * 1.015
    tp_1_5_rounded = round_to_step(tp_1_5_exact, tick)
    loss_1_5 = 1.5 - ((tp_1_5_rounded - price) / price) * 100

    print(
        f"{symbol:15} | Min TP для net >0.5%: {min_tp:.2f}% | Потеря на TP 1.5%: {loss_1_5:.4f}%"
    )

print("=" * 110)
