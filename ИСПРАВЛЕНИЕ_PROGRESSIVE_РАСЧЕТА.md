# ✅ ИСПРАВЛЕНИЕ PROGRESSIVE РАСЧЕТА

## 🐛 ПРОБЛЕМА

Progressive расчет не работал, потому что `config_manager.get_balance_profile()` не возвращал параметры `progressive`, `size_at_min`, `size_at_max` в словаре.

Когда `risk_manager.py` проверял `balance_profile.get("progressive", False)`, он получал `False`, потому что этот ключ отсутствовал в словаре.

## ✅ ИСПРАВЛЕНИЕ

### Файл: `src/strategies/scalping/futures/config/config_manager.py`

Добавлены параметры progressive в возвращаемый словарь:

```python
# ✅ ИСПРАВЛЕНО: Возвращаем параметры progressive для risk_manager
result = {
    "name": profile_name,
    "base_position_usd": base_pos_usd,
    "min_position_usd": min_pos_usd,
    "max_position_usd": max_pos_usd,
    "max_open_positions": max_open_positions,
    "max_position_percent": max_position_percent,
    "progressive": progressive,  # ✅ ДОБАВЛЕНО
}

# Добавляем параметры progressive, если они есть
if progressive:
    if min_balance is not None and size_at_min is not None and size_at_max is not None:
        result["size_at_min"] = size_at_min      # ✅ ДОБАВЛЕНО
        result["size_at_max"] = size_at_max      # ✅ ДОБАВЛЕНО
        result["min_balance"] = min_balance       # ✅ ДОБАВЛЕНО
        if profile_name == "large":
            result["max_balance"] = getattr(profile_config, "max_balance", 999999.0)
        else:
            result["threshold"] = getattr(profile_config, "threshold", None)

return result
```

## 📊 РЕЗУЛЬТАТ

### До исправления:
- `balance_profile.get("progressive")` → `None` (ключ отсутствует)
- Progressive расчет не выполнялся
- Использовался фиксированный `base_position_usd`

### После исправления:
- `balance_profile.get("progressive")` → `True` (для micro, small, medium, large)
- Progressive расчет выполняется
- Размер позиции интерполируется между `size_at_min` и `size_at_max`

## 🔍 ПРИМЕР ДЛЯ МИКРО ПРОФИЛЯ

### Баланс: $459.96
### Профиль: micro

### Progressive расчет:
```
interpolated_size = 30.0 + (50.0 - 30.0) * (459.96 - 100.0) / (500.0 - 100.0)
interpolated_size = 30.0 + 20.0 * 359.96 / 400.0
interpolated_size = 30.0 + 17.998 = 47.998 ≈ 48.0 USDT
```

### В логах теперь будет:
```
📊 Прогрессивный расчет размера для баланса $459.96: 
$30.00 → $50.00 (range: $100.00-$500.00) 
→ base_size=$48.00
```

## ✅ ПРОВЕРКА

После перезапуска бота:
1. В логах появятся сообщения о прогрессивном расчете
2. Размер позиции будет интерполироваться по балансу
3. Плавный рост размера без прыжков

---

**Дата**: 2025-12-07
**Версия**: 1.0



