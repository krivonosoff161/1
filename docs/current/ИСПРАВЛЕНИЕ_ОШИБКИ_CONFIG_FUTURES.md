# ✅ ИСПРАВЛЕНИЕ ОШИБКИ config.futures

**Дата:** 2025-10-31  
**Ошибка:** `'BotConfig' object has no attribute 'futures'`

---

## 🐛 **ПРОБЛЕМА:**

В методе `_calculate_liquidation_risk` использовался несуществующий атрибут `config.futures`:
```python
leverage = self.config.futures.get("leverage", 3)  # ❌ НЕПРАВИЛЬНО
```

Но в `BotConfig` нет атрибута `futures`. Leverage должен браться из `scalping_config.leverage` или использовать дефолт 3x для Futures.

---

## ✅ **ИСПРАВЛЕНИЕ:**

Изменил в `src/strategies/scalping/futures/signal_generator.py`:
```python
# Было:
leverage = self.config.futures.get("leverage", 3)

# Стало:
leverage = getattr(self.scalping_config, "leverage", 3)
if leverage is None:
    leverage = 3  # Дефолт для Futures
```

---

## ✅ **СТАТУС:**

Ошибка исправлена, бот должен работать без повторяющихся ошибок в логах!


