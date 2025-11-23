# ИСПРАВЛЕНИЯ FALLBACK И ЛИМИТНОЙ ЦЕНЫ

**Дата:** 23 ноября 2025  
**Исправления:**
1. Fallback для BTC-USDT - исправлено чтение `by_symbol`
2. Лимитная цена вне диапазона - исправлен расчет `min_sell_price`

---

## ✅ ИСПРАВЛЕНИЕ #1: FALLBACK ДЛЯ BTC-USDT

### Проблема:
- Настройки `by_symbol` не читались из конфига
- Fallback использовался вместо per-symbol+regime настроек

### Причина:
- `order_executor_config` и `limit_order_config` могли быть объектами Pydantic, а не dict
- Метод `.get()` не работал на объектах

### Исправление:
- Добавлено преобразование объектов в dict перед использованием `.get()`
- Поддержка Pydantic v1 (`dict()`) и v2 (`model_dump()`)

**Код:**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
if not isinstance(order_executor_config, dict):
    if hasattr(order_executor_config, "dict"):
        order_executor_config = order_executor_config.dict()
    elif hasattr(order_executor_config, "model_dump"):
        order_executor_config = order_executor_config.model_dump()
    elif hasattr(order_executor_config, "__dict__"):
        order_executor_config = dict(order_executor_config.__dict__)
    else:
        order_executor_config = {}
```

---

## ✅ ИСПРАВЛЕНИЕ #2: ЛИМИТНАЯ ЦЕНА ВНЕ ДИАПАЗОНА

### Проблема:
- `get_price_limits` возвращал неправильные лимиты
- `min_sell_price = best_bid * 0.9995` был слишком низким
- Биржа требовала `min_sell_price = 85,905.7`, а мы рассчитали `85,866.80`

### Причина:
- OKX использует динамические лимиты, которые могут быть строже
- Расчет на основе `best_bid * 0.9995` не учитывал реальные лимиты биржи

### Исправление:
1. **Улучшен расчет `min_sell_price` в `get_price_limits`:**
   - Используем `best_bid - (spread * 0.5)` вместо `best_bid * 0.9995`
   - Добавлена защита от слишком больших отклонений (не более 1% от best_bid)

2. **Улучшена обработка ошибки 51006:**
   - Используем реальные лимиты из ошибки API
   - Корректируем цену с небольшим offset (0.1%) для гарантии прохождения
   - Для SELL: `corrected_price = min_sell_from_error * 1.001` (0.1% выше лимита)

**Код:**
```python
# В get_price_limits:
if spread > 0:
    max_buy_price = best_ask + (spread * 0.5)  # 50% от спреда выше best_ask
    min_sell_price = best_bid - (spread * 0.5)  # 50% от спреда ниже best_bid
    # Защита от слишком больших отклонений
    if max_buy_price > best_ask * 1.01:  # Не более 1% выше best_ask
        max_buy_price = best_ask * 1.01
    if min_sell_price < best_bid * 0.99:  # Не более 1% ниже best_bid
        min_sell_price = best_bid * 0.99

# В обработке ошибки 51006:
elif side.lower() == "sell" and min_sell_from_error:
    if price < min_sell_from_error:
        corrected_price = min_sell_from_error * 1.001  # 0.1% выше лимита
```

---

## ✅ РЕЗУЛЬТАТ

1. ✅ Настройки `by_symbol` теперь правильно читаются из конфига
2. ✅ Лимитная цена рассчитывается более точно
3. ✅ Ошибка 51006 обрабатывается с использованием реальных лимитов биржи

---

**Статус:** ✅ ИСПРАВЛЕНО

