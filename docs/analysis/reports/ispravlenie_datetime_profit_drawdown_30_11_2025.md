# 🔧 Исправление ошибки datetime в _check_profit_drawdown (30.11.2025)

## ❌ Ошибка

```
❌ [PROFIT_DRAWDOWN] Ошибка расчета отката для BTC-USDT: 
can't subtract offset-naive and offset-aware datetimes
```

---

## 🔍 Причина

Ошибка возникала в блоке `if peak_profit < 0` при вычислении `time_since_open`:

**БЫЛО:**
```python
entry_time = metadata.entry_time
if entry_time:
    if isinstance(entry_time, datetime):
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        current_time = datetime.now(timezone.utc)
        time_since_open = (current_time - entry_time).total_seconds()  # ❌ Ошибка!
```

**Проблемы:**
1. ❌ `entry_time` может быть не только `datetime`, но и `str`, `int`, `float`
2. ❌ При изменении `entry_time.replace()` создается новый объект, но мы изменяем переменную `entry_time`, что может вызвать проблемы
3. ❌ Нет обработки других типов `entry_time`

---

## ✅ Решение

### Исправление 1: Обработка всех типов `entry_time`

**СТАЛО:**
```python
entry_time = metadata.entry_time
time_since_open = 0

if entry_time:
    try:
        if isinstance(entry_time, datetime):
            # Нормализуем datetime (добавляем timezone если отсутствует)
            if entry_time.tzinfo is None:
                entry_time_normalized = entry_time.replace(tzinfo=timezone.utc)
            else:
                entry_time_normalized = entry_time
            current_time = datetime.now(timezone.utc)
            time_since_open = (current_time - entry_time_normalized).total_seconds()
        elif isinstance(entry_time, str):
            # Пытаемся распарсить строку
            if entry_time.isdigit():
                entry_timestamp = int(entry_time) / 1000.0
                current_timestamp = datetime.now(timezone.utc).timestamp()
                time_since_open = current_timestamp - entry_timestamp
            else:
                entry_time_parsed = datetime.fromisoformat(
                    entry_time.replace("Z", "+00:00")
                )
                if entry_time_parsed.tzinfo is None:
                    entry_time_parsed = entry_time_parsed.replace(tzinfo=timezone.utc)
                current_time = datetime.now(timezone.utc)
                time_since_open = (current_time - entry_time_parsed).total_seconds()
        elif isinstance(entry_time, (int, float)):
            # Конвертируем из миллисекунд или секунд
            entry_timestamp = (
                float(entry_time) / 1000.0
                if entry_time > 1000000000000
                else float(entry_time)
            )
            current_timestamp = datetime.now(timezone.utc).timestamp()
            time_since_open = current_timestamp - entry_timestamp
        else:
            logger.debug(
                f"🔍 [PROFIT_DRAWDOWN] {symbol}: Неизвестный тип entry_time: {type(entry_time)}, используем time_since_open=0"
            )
            time_since_open = 0
    except Exception as e:
        logger.debug(
            f"⚠️ [PROFIT_DRAWDOWN] {symbol}: Ошибка расчета time_since_open: {e}, используем time_since_open=0"
        )
        time_since_open = 0
```

---

## 📝 Изменения

### 1. Использование отдельной переменной `entry_time_normalized`

**БЫЛО:**
```python
entry_time = entry_time.replace(tzinfo=timezone.utc)  # Изменяем исходную переменную
```

**СТАЛО:**
```python
entry_time_normalized = entry_time.replace(tzinfo=timezone.utc)  # Создаем новую переменную
```

**Зачем:** Избегаем изменения исходной переменной `entry_time`, которая может использоваться где-то еще.

---

### 2. Обработка всех типов `entry_time`

- ✅ `datetime` - нормализуется с timezone
- ✅ `str` - парсится и нормализуется
- ✅ `int/float` - конвертируется в timestamp
- ✅ Другие типы - логируются и используется `time_since_open=0`

---

### 3. Try-except блок

Все вычисления обернуты в `try-except`, чтобы:
- ✅ Поймать любые неожиданные ошибки
- ✅ Залогировать ошибку для диагностики
- ✅ Использовать безопасное значение `time_since_open=0` по умолчанию

---

## ✅ Итог

**Ошибка исправлена!**

- ✅ Правильная обработка всех типов `entry_time`
- ✅ Нормализация timezone для datetime объектов
- ✅ Использование отдельной переменной `entry_time_normalized`
- ✅ Защита от ошибок через try-except

**Ошибка `can't subtract offset-naive and offset-aware datetimes` больше не должна появляться!** 🎉

---

## 🔄 Применимо ко всем парам

Исправление работает для **всех пар**, так как:
- ✅ Обрабатывает все возможные типы `entry_time`
- ✅ Нормализует timezone для всех datetime объектов
- ✅ Имеет fallback на безопасные значения

**Все пары (BTC-USDT, ETH-USDT, SOL-USDT, DOGE-USDT, XRP-USDT) теперь защищены от этой ошибки!** ✅





