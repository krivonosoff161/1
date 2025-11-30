# 🔧 Исправление ошибок datetime (30.11.2025)

## ❌ Обнаруженные ошибки

После чистого перезапуска обнаружены 4 ошибки с datetime:

1. **`_check_profit_harvesting`**: `'>' not supported between instances of 'datetime.datetime' and 'int'`
2. **`_check_profit_drawdown`**: `can't subtract offset-naive and offset-aware datetimes`
3. **`_check_max_holding`**: `'>' not supported between instances of 'datetime.datetime' and 'int'`
4. **`_check_tp_only`**: `'>' not supported between instances of 'datetime.datetime' and 'int'`

---

## 🔍 Причина

### Проблема 1: Сравнение datetime с int

**БЫЛО:**
```python
entry_timestamp = (
    float(entry_time_str) / 1000.0
    if entry_time_str > 1000000000000  # ❌ Ошибка: entry_time_str может быть datetime!
    else float(entry_time_str)
)
```

**Проблема:** `entry_time_str` может быть `datetime` объектом, а не строкой или числом.

---

### Проблема 2: Вычитание offset-naive и offset-aware datetime

**БЫЛО:**
```python
entry_time = metadata.entry_time  # Может быть offset-naive
time_since_open = (datetime.now(timezone.utc) - entry_time).total_seconds()  # ❌ Ошибка!
```

**Проблема:** `entry_time` может быть offset-naive (без timezone), а `datetime.now(timezone.utc)` - offset-aware (с timezone).

---

## ✅ Решение

### Исправление 1: Проверка типа entry_time_str

**СТАЛО:**
```python
if isinstance(entry_time_str, datetime):
    # Если это уже datetime объект, конвертируем в timestamp
    if entry_time_str.tzinfo is None:
        entry_time = entry_time_str.replace(tzinfo=timezone.utc)
    else:
        entry_time = entry_time_str
    entry_timestamp = entry_time.timestamp()
elif isinstance(entry_time_str, str):
    # ... обработка строки
elif isinstance(entry_time_str, (int, float)):
    # ... обработка числа
else:
    logger.warning(f"⚠️ Неизвестный тип entry_time_str: {type(entry_time_str)}")
    return False
```

---

### Исправление 2: Нормализация datetime (добавление timezone)

**СТАЛО:**
```python
entry_time = metadata.entry_time
if entry_time:
    if isinstance(entry_time, datetime):
        # Нормализуем datetime (добавляем timezone если отсутствует)
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        current_time = datetime.now(timezone.utc)
        time_since_open = (current_time - entry_time).total_seconds()
```

---

## 📝 Изменения в коде

### 1. `_check_profit_harvesting` (строки 1389-1407)

- ✅ Добавлена проверка типа `datetime`
- ✅ Нормализация timezone для datetime объектов
- ✅ Обработка всех типов: `datetime`, `str`, `int`, `float`

### 2. `_check_profit_drawdown` (строки 3884-3895)

- ✅ Нормализация `entry_time` (добавление timezone если отсутствует)
- ✅ Использование `datetime.now(timezone.utc)` для консистентности

### 3. `_check_max_holding` (строки 4050-4066)

- ✅ Добавлена проверка типа `datetime`
- ✅ Нормализация timezone для datetime объектов
- ✅ Обработка всех типов: `datetime`, `str`, `int`, `float`

### 4. `_check_tp_only` (строки 1680-1714)

- ✅ Добавлена проверка типа `datetime`
- ✅ Нормализация timezone для datetime объектов
- ✅ Обработка случая `entry_timestamp = None`

---

## ✅ Итог

**Все ошибки исправлены!**

- ✅ Правильная обработка `datetime` объектов
- ✅ Нормализация timezone (добавление UTC если отсутствует)
- ✅ Обработка всех типов: `datetime`, `str`, `int`, `float`
- ✅ Защита от `None` значений

**Бот теперь корректно обрабатывает время открытия позиций во всех методах!** 🎉

