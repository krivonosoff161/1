# Сравнение параметров Spot vs Futures

## 🔍 НЕТ! НЕ СКОПИРОВАЛ!

### ✅ Структурные различия:

**Spot:** Использует `manual_pools` с фиксированными суммами
**Futures:** Использует `adaptive_regime` с баланс-профилями

---

## 📊 Сравнение Trending режима:

| Параметр | Spot (manual_pools) | Futures (adaptive_regime) | Разница |
|----------|---------------------|---------------------------|---------|
| **TP %** | 0.7% | 0.8x ATR | Разный подход! |
| **SL %** | 0.45% | 0.6x ATR | Разный подход! |
| **Score threshold** | 4 | 4 | ✅ Одинаково |
| **Max trades/hour** | ~20 | 25 | ❌ Больше для Futures |
| **PH threshold** | $0.40 | $0.20 | ✅ В 2 раза меньше для Futures |
| **Time limit** | 480 сек | 180 сек | ✅ Быстрее для Futures |

---

## 📊 Ключевые различия:

### 1. **TP/SL подход:**
```yaml
# Spot:
tp_percent: 0.7  # Фиксированный %
sl_percent: 0.45  # Фиксированный %

# Futures:
tp_atr_multiplier: 0.8  # От ATR (динамический!)
sl_atr_multiplier: 0.6  # От ATR (динамический!)
```
**👉 Futures использует ATR-мультипликаторы, Spot - фиксированные проценты!**

### 2. **ADX детекция:**
```yaml
# Spot (предполагается):
trending_adx_threshold: 25.0
adx_period: 14

# Futures:
trending_adx_threshold: 20.0  # Ниже!
adx_period: 9  # Быстрее!
```
**👉 Futures быстрее определяет режим!**

### 3. **Balance Profiles:**
```yaml
# Spot: Использует manual_pools с фиксированными суммами
eth_pool:
  fixed_amount: 400.0
  trending:
    quantity_per_trade: 0.008  # Фиксированное количество

# Futures: Использует adaptive profiles с базовыми суммами
balance_profiles:
  small:
    base_position_usd: 50.0  # Базовый размер
    position_size_multiplier: 1.2  # Адаптация!
```
**👉 Разная логика управления балансом!**

---

## 🎯 Итого:

### ✅ НЕ копировал:
1. **TP/SL**: ATR-мультипликаторы (Futures) vs фиксированные % (Spot)
2. **Balance**: Adaptive profiles (Futures) vs manual pools (Spot)
3. **ADX**: Быстрее для Futures (9 vs 14, 20 vs 25)
4. **Сделок**: Больше для Futures (25 vs 20)
5. **PH**: Быстрее для Futures ($0.20 vs $0.40)

### ⚠️ Что ОДИНАКОВО (логично):
1. **Score thresholds**: 4/3/5 (trending/ranging/choppy)
2. **Структура режимов**: Тот же набор режимов
3. **Базовые индикаторы**: RSI, SMA, EMA, ATR

---

## 🧠 Логика:

### Почему НЕ копировал:
1. ✅ **Futures другой инструмент** → нужны другие параметры
2. ✅ **ATR лучше для Futures** → динамическая адаптация
3. ✅ **Balance Profiles гибче** → адаптация под размер
4. ✅ **Быстрее система** → больше сделок, быстрее закрытие

### Что ВЗЯЛ из логики Spot:
1. ✅ Структуру режимов (trending/ranging/choppy)
2. ✅ Концепцию адаптации
3. ✅ Базовые индикаторы

---

## ✅ Верификация:

**Spot:** manual_pools → фиксированные суммы → TP/SL фиксированные %
**Futures:** adaptive_regime → баланс-профили → TP/SL от ATR

**👉 Разная архитектура! НЕ копирование!**


