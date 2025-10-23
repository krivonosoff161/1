import numpy as np
import pandas as pd

# Читаем CSV файл
df = pd.read_csv("logs/trades_2025-10-22.csv")

print("📊 АНАЛИЗ ТОРГОВЫХ РЕЗУЛЬТАТОВ")
print("=" * 50)

print(f"📈 Всего сделок: {len(df)}")
print(f'💰 Общий PnL: ${df["net_pnl"].sum():.2f}')
print(f'📊 Win Rate: {df["win_rate"].iloc[-1]:.1f}%')

print("\n📋 ДЕТАЛЬНАЯ СТАТИСТИКА:")
print(f'  💚 Прибыльных: {len(df[df["net_pnl"] > 0])}')
print(f'  💔 Убыточных: {len(df[df["net_pnl"] < 0])}')
if len(df[df["net_pnl"] > 0]) > 0:
    print(f'  📈 Средняя прибыль: ${df[df["net_pnl"] > 0]["net_pnl"].mean():.2f}')
if len(df[df["net_pnl"] < 0]) > 0:
    print(f'  📉 Средний убыток: ${df[df["net_pnl"] < 0]["net_pnl"].mean():.2f}')

print("\n⏱️ ВРЕМЯ УДЕРЖАНИЯ:")
print(f'  📊 Среднее: {df["duration_sec"].mean()/60:.1f} минут')
print(f'  ⚡ Минимальное: {df["duration_sec"].min()/60:.1f} минут')
print(f'  🐌 Максимальное: {df["duration_sec"].max()/60:.1f} минут')

print("\n🎯 ПРИЧИНЫ ЗАКРЫТИЯ:")
reasons = df["reason"].value_counts()
for reason, count in reasons.items():
    print(f"  {reason}: {count} ({count/len(df)*100:.1f}%)")

print("\n💱 ПО СИМВОЛАМ:")
symbols = df["symbol"].value_counts()
for symbol, count in symbols.items():
    symbol_pnl = df[df["symbol"] == symbol]["net_pnl"].sum()
    print(f"  {symbol}: {count} сделок, PnL: ${symbol_pnl:.2f}")

print("\n📊 ПОСЛЕДНИЕ 5 СДЕЛОК:")
print(
    df[["timestamp", "symbol", "side", "net_pnl", "reason"]]
    .tail()
    .to_string(index=False)
)
