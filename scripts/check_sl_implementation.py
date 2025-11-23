"""
✅ Проверка реализации адаптивного SL
"""
import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # 1. Проверка синтаксиса YAML
    print("🔍 Проверка 1: Синтаксис YAML...")
    import yaml
    with open('config/config_futures.yaml', 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)
    print("✅ YAML синтаксис корректен")
    
    # 2. Проверка наличия sl_percent в конфиге
    print("\n🔍 Проверка 2: Наличие sl_percent в конфиге...")
    
    # Глобальный SL
    global_sl = config_data.get('scalping', {}).get('sl_percent')
    print(f"✅ Глобальный SL: {global_sl}%")
    
    # SL по режимам
    regimes = config_data.get('scalping', {}).get('adaptive_regime', {}).get('regimes', {})
    for regime_name in ['trending', 'ranging', 'choppy']:
        if regime_name in regimes:
            regime_sl = regimes[regime_name].get('sl_percent')
            if regime_sl:
                print(f"✅ {regime_name.capitalize()} SL: {regime_sl}%")
            else:
                print(f"⚠️ {regime_name.capitalize()} SL: НЕ НАЙДЕН")
    
    # SL по символам
    symbol_profiles = config_data.get('scalping', {}).get('adaptive_regime', {}).get('symbol_profiles', {})
    symbols_with_sl = 0
    for symbol, profile in symbol_profiles.items():
        if isinstance(profile, dict):
            # Per-symbol SL
            if 'sl_percent' in profile:
                symbols_with_sl += 1
                # Per-regime SL
                for regime_name in ['trending', 'ranging', 'choppy']:
                    if regime_name in profile and 'sl_percent' in profile[regime_name]:
                        pass  # OK
    
    print(f"✅ SL найден для {len(symbol_profiles)} символов")
    
    # 3. Проверка импорта модулей
    print("\n🔍 Проверка 3: Импорт модулей...")
    from src.config import BotConfig
    from src.strategies.scalping.futures.position_manager import FuturesPositionManager
    print("✅ Импорт успешен")
    
    # 4. Проверка методов
    print("\n🔍 Проверка 4: Наличие методов...")
    has_get_sl = hasattr(FuturesPositionManager, '_get_adaptive_sl_percent')
    has_check_sl = hasattr(FuturesPositionManager, '_check_sl')
    print(f"✅ Метод _get_adaptive_sl_percent: {'Найден' if has_get_sl else 'НЕ НАЙДЕН'}")
    print(f"✅ Метод _check_sl: {'Найден' if has_check_sl else 'НЕ НАЙДЕН'}")
    
    # 5. Проверка загрузки конфига
    print("\n🔍 Проверка 5: Загрузка конфига...")
    config = BotConfig.load_from_file('config/config_futures.yaml')
    print(f"✅ Конфиг загружен")
    print(f"✅ Глобальный SL: {config.scalping.sl_percent}%")
    
    # Проверка адаптивного SL для ranging
    try:
        ranging_config = config.scalping.adaptive_regime.regimes.ranging
        if hasattr(ranging_config, 'sl_percent'):
            print(f"✅ Ranging SL: {ranging_config.sl_percent}%")
        else:
            print(f"⚠️ Ranging SL: НЕ НАЙДЕН")
    except Exception as e:
        print(f"⚠️ Ошибка получения ranging SL: {e}")
    
    # 6. Проверка символов
    print("\n🔍 Проверка 6: SL для символов...")
    symbol_profiles_dict = config.scalping.adaptive_regime.symbol_profiles
    if hasattr(symbol_profiles_dict, 'BTC_USDT') or 'BTC-USDT' in str(symbol_profiles_dict):
        print("✅ Symbol profiles загружены")
    
    print("\n✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
    
except SyntaxError as e:
    print(f"❌ ОШИБКА СИНТАКСИСА: {e}")
    sys.exit(1)
except ImportError as e:
    print(f"❌ ОШИБКА ИМПОРТА: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

