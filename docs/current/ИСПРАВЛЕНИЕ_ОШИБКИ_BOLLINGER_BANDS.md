# ✅ ИСПРАВЛЕНИЕ ОШИБКИ BollingerBands

**Дата:** 2025-10-31  
**Ошибка:** `BollingerBands.__init__() got an unexpected keyword argument 'std_dev'`

---

## 🐛 **ПРОБЛЕМА:**

В `signal_generator.py` использовался неправильный параметр для инициализации `BollingerBands`:
```python
BollingerBands(period=20, std_dev=2)  # ❌ НЕПРАВИЛЬНО
```

Но в `BollingerBands.__init__()` используется параметр `std_multiplier`, а не `std_dev`:
```python
def __init__(self, period: int = 20, std_multiplier: float = 2.0):
```

---

## ✅ **ИСПРАВЛЕНИЕ:**

Изменил в `src/strategies/scalping/futures/signal_generator.py`:
```python
# Было:
self.indicator_manager.add_indicator("BollingerBands", BollingerBands(period=20, std_dev=2))

# Стало:
self.indicator_manager.add_indicator("BollingerBands", BollingerBands(period=20, std_multiplier=2.0))
```

---

## ✅ **СТАТУС:**

Ошибка исправлена, бот готов к запуску!


