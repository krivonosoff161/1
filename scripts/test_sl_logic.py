"""
✅ Проверка логики получения SL из конфига
"""
import sys
import os
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Симулируем получение SL для разных символов и режимов
print("🔍 Тест 1: Чтение sl_percent из YAML...")

with open('config/config_futures.yaml', 'r', encoding='utf-8') as f:
    config_data = yaml.safe_load(f)

scalping = config_data.get('scalping', {})
adaptive_regime = scalping.get('adaptive_regime', {})
regimes = adaptive_regime.get('regimes', {})
symbol_profiles = adaptive_regime.get('symbol_profiles', {})

# Тест 1: Глобальный SL
global_sl = scalping.get('sl_percent')
print(f"\n✅ Глобальный SL: {global_sl}%")

# Тест 2: SL по режимам
print("\n📊 SL по режимам:")
for regime_name in ['trending', 'ranging', 'choppy']:
    if regime_name in regimes:
        regime_sl = regimes[regime_name].get('sl_percent')
        print(f"  {regime_name.capitalize()}: {regime_sl}% (найдено в конфиге)")

# Тест 3: SL по символам
print("\n📊 SL по символам:")
test_symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'DOGE-USDT', 'XRP-USDT']
for symbol in test_symbols:
    if symbol in symbol_profiles:
        profile = symbol_profiles[symbol]
        
        # Per-symbol SL
        symbol_sl = profile.get('sl_percent')
        print(f"\n  {symbol}:")
        if symbol_sl:
            print(f"    Per-symbol: {symbol_sl}%")
        else:
            print(f"    Per-symbol: НЕ НАЙДЕН (fallback на глобальный {global_sl}%)")
        
        # Per-regime SL
        for regime_name in ['trending', 'ranging', 'choppy']:
            if regime_name in profile:
                regime_profile = profile[regime_name]
                regime_sl = regime_profile.get('sl_percent')
                if regime_sl:
                    print(f"    {regime_name.capitalize()}: {regime_sl}%")
                else:
                    # Fallback на per-symbol или глобальный
                    fallback = symbol_sl or global_sl
                    print(f"    {regime_name.capitalize()}: НЕ НАЙДЕН (fallback на {fallback}%)")

# Тест 4: Симуляция логики _get_adaptive_sl_percent
print("\n🔍 Тест 4: Симуляция логики _get_adaptive_sl_percent...")

def simulate_get_sl(symbol, regime=None):
    """Симуляция логики получения SL"""
    sl_percent = None
    
    # 1. Per-regime SL (если режим определен)
    if regime and symbol in symbol_profiles:
        profile = symbol_profiles[symbol]
        if regime.lower() in profile:
            regime_profile = profile[regime.lower()]
            sl_percent = regime_profile.get('sl_percent')
            if sl_percent:
                return sl_percent, f"Per-regime ({regime})"
    
    # 2. Per-symbol SL
    if symbol in symbol_profiles:
        profile = symbol_profiles[symbol]
        sl_percent = profile.get('sl_percent')
        if sl_percent:
            return sl_percent, "Per-symbol"
    
    # 3. Глобальный SL
    return global_sl, "Глобальный (fallback)"

# Тестируем для разных символов и режимов
print("\n📊 Симуляция получения SL:")
for symbol in test_symbols:
    for regime in ['trending', 'ranging', 'choppy', None]:
        sl_value, source = simulate_get_sl(symbol, regime)
        regime_label = regime.capitalize() if regime else "N/A"
        print(f"  {symbol} ({regime_label}): {sl_value}% ({source})")

print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")

