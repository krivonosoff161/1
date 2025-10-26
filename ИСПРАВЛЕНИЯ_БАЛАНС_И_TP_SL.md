# Исправления: Balance & TP/SL

## ✅ Исправлено:

### 1. Balance — учёт силы сигнала

**Было:** Фиксированный размер позиции
```python
position_size = balance * risk_percent
```

**Стало:** Адаптивный размер по силе сигнала
```python
# Очень сильный (>0.8): 1.5x → +50%
# Хороший (0.6-0.8): 1.2x → +20%
# Средний (0.4-0.6): 1.0x → Стандарт
# Слабый (<0.4): 0.8x → -20%

strength_multiplier = get_strength_multiplier(signal_strength)
base_usd_size *= strength_multiplier
```

**Работает как в Spot:**
- Сильный сигнал → больше позиция
- Слабый сигнал → минимум позиции

---

### 2. TP/SL — на бирже через OCO

**Было:** market ордер БЕЗ TP/SL
```python
signal = {"type": "market"}  # ❌ Нет TP/SL!
```

**Стало:** OCO ордер с TP/SL
```python
signal = {"type": "oco"}  # ✅ OCO с TP/SL!

# На бирже устанавливается:
- TP на +0.3%
- SL на -0.2%
```

**Теперь на бирже:**
- ✅ TP/SL ставятся через OCO
- ✅ Позиция закрывается автоматически
- ✅ Не висит в боковике бесконечно

---

## 🎯 Как это работает:

### Balance + Signal Strength:
```python
# Пример для $500 баланса в small profile:
base_usd = $50

# Trending режим:
regime_multiplier = 1.2
$50 * 1.2 = $60

# Сильный сигнал (strength=0.9):
strength_multiplier = 1.5
$60 * 1.5 = $90

# Weak сигнал (strength=0.3):
strength_multiplier = 0.8
$60 * 0.8 = $48
```

### TP/SL через OCO:
```python
# При открытии позиции:
if signal.type == "oco":
    tp_price = entry_price * (1 + 0.3 / 100)  # +0.3%
    sl_price = entry_price * (1 - 0.2 / 100)  # -0.2%
    
    # ОКX получает OCO ордер:
    place_oco_order(
        symbol="ETH-USDT-SWAP",
        side="buy",
        size=0.01,
        tp_price=tp_price,
        sl_price=sl_price
    )
    
    # ✅ На бирже автоматически:
    # - TP срабатывает при +0.3%
    # - SL срабатывает при -0.2%
```

---

## 🔍 Почему позиция висит в боковике?

**Проблема:** Тестовая позиция открыта БЕЗ TP/SL (тип "market")

**Решение:** Изменил на "oco" → теперь TP/SL ставятся!

---

## 📊 Итоговая логика:

### 1. Размер позиции:
```
balance_profile → regime_multiplier → strength_multiplier → final_size
```

### 2. TP/SL:
```
signal.type = "oco" → OCO ордер → TP/SL на бирже
```

**✅ Теперь всё работает правильно!**


