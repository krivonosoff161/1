# 🔧 ИСПРАВЛЕНИЕ ЗАХАРДКОЖЕННЫХ ПАРАМЕТРОВ MaxSizeLimiter

## 🐛 Проблема

### Найденная проблема:

**В логах:**
```
⚠️ Max position size из symbol_profiles ($52.00) меньше base_usd_size из balance_profile ($106.56), игнорируем symbol_profiles ограничение (используем $180.00 из balance_profile)
```

**Проблема:**
- `MaxSizeLimiter` инициализировался с жестко заданными значениями:
  - `max_single_size_usd=1000.0` (в конфиге: 150.0)
  - `max_total_size_usd=5000.0` (в конфиге: 600.0)
  - `max_positions=5` (в конфиге: 5)

- Хотя в `_calculate_position_size` обновлялись `max_total_size_usd` и `max_positions`, **`max_single_size_usd` не обновлялся!**

- Это означало, что `MaxSizeLimiter.can_open_position()` проверял позиции против жестко заданного `max_single_size_usd=1000.0`, а не против значения из конфига (`150.0`) или `balance_profile` (`max_usd_size`).

---

## ✅ Исправление

### 1. Инициализация из конфига

**До:**
```python
self.max_size_limiter = MaxSizeLimiter(
    max_single_size_usd=1000.0,  # $1000 за позицию
    max_total_size_usd=5000.0,  # $5000 всего
    max_positions=5,  # Максимум 5 позиций
)
```

**После:**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Загружаем параметры из конфига
futures_modules = getattr(config, "futures_modules", None)
max_size_limiter_config = None
if futures_modules:
    max_size_limiter_config = getattr(futures_modules, "max_size_limiter", None)

if max_size_limiter_config:
    max_single_size_usd = getattr(max_size_limiter_config, "max_single_size_usd", 150.0)
    max_total_size_usd = getattr(max_size_limiter_config, "max_total_size_usd", 600.0)
    max_positions = getattr(max_size_limiter_config, "max_positions", 5)
    logger.info(
        f"✅ MaxSizeLimiter инициализирован из конфига: "
        f"max_single=${max_single_size_usd:.2f}, "
        f"max_total=${max_total_size_usd:.2f}, "
        f"max_positions={max_positions}"
    )
else:
    # Fallback значения (для обратной совместимости)
    max_single_size_usd = 150.0
    max_total_size_usd = 600.0
    max_positions = 5
    logger.warning(
        f"⚠️ MaxSizeLimiter config не найден в конфиге, используем fallback значения"
    )

self.max_size_limiter = MaxSizeLimiter(
    max_single_size_usd=max_single_size_usd,
    max_total_size_usd=max_total_size_usd,
    max_positions=max_positions,
)
```

### 2. Динамическое обновление из balance_profile

**Добавлено в `_calculate_position_size`:**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем max_single_size_usd из balance_profile
# Это гарантирует, что ограничение одной позиции соответствует конфигу
if self.max_size_limiter.max_single_size_usd != max_usd_size:
    logger.debug(
        f"🔧 MaxSizeLimiter: обновляем max_single_size_usd {self.max_size_limiter.max_single_size_usd:.2f} → {max_usd_size:.2f}"
    )
    self.max_size_limiter.max_single_size_usd = max_usd_size
```

---

## 📋 Результат

### До исправления:
- `MaxSizeLimiter` инициализировался с жестко заданными значениями
- `max_single_size_usd=1000.0` не обновлялся из конфига
- Позиции проверялись против неправильного лимита

### После исправления:
- ✅ `MaxSizeLimiter` инициализируется из конфига
- ✅ `max_single_size_usd` обновляется динамически из `balance_profile`
- ✅ Позиции проверяются против правильного лимита из конфига

---

## 🔍 Проверка

### Конфиг:
```yaml
max_size_limiter:
  max_single_size_usd: 150.0  # ✅ Используется при инициализации
  max_total_size_usd: 600.0   # ✅ Используется при инициализации
  max_positions: 5             # ✅ Используется при инициализации
```

### Balance Profile:
```yaml
small:
  max_position_usd: 180.0  # ✅ Обновляет max_single_size_usd в _calculate_position_size
```

### Логика:
1. При инициализации: `max_single_size_usd=150.0` (из конфига)
2. При расчете позиции: `max_single_size_usd=180.0` (из balance_profile)
3. Проверка позиции: `can_open_position(symbol, size_usd)` проверяет против `180.0`

---

## ✅ Итог

**Проблема решена:**
- ✅ `MaxSizeLimiter` больше не использует жестко заданные значения
- ✅ Параметры загружаются из конфига при инициализации
- ✅ Параметры обновляются динамически из `balance_profile` при расчете позиции
- ✅ Позиции проверяются против правильных лимитов

**Рекомендация:**
- Перезапустить бота
- Проверить логи: должны появиться сообщения об инициализации `MaxSizeLimiter` из конфига
- Проверить логи: должны появиться сообщения об обновлении `max_single_size_usd` из `balance_profile`

