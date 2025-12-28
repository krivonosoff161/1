# ✅ ОТЧЕТ: ИСПРАВЛЕНИЕ ОШИБКИ DATETIME - 26.12.2025

## 🔴 КРИТИЧЕСКАЯ ОШИБКА

**Ошибка:**
```
2025-12-26 16:07:05 | ERROR | trading_control_center:update_state | 
❌ TCC: Ошибка обновления состояния: 
can't compare offset-naive and offset-aware datetimes
```

**Частота:** Постоянно по всем парам

---

## 🔍 ПРИЧИНА

**Проблема:** Сравнение datetime объектов, где один offset-naive (без timezone), а другой offset-aware (с timezone).

**Место возникновения:**
- `src/strategies/scalping/futures/core/trading_control_center.py:509`
- Сравнение `entry_time_from_api < existing_metadata.entry_time`

**Корневая причина:**
1. `dt.fromtimestamp(entry_timestamp_sec)` создает offset-naive datetime
2. `existing_metadata.entry_time` может быть offset-naive (если создан старым кодом)
3. `dt.now(timezone.utc)` создает offset-aware datetime

---

## ✅ ИСПРАВЛЕНИЯ

### 1. ✅ Исправлено в `trading_control_center.py`

**Файл:** `src/strategies/scalping/futures/core/trading_control_center.py`

**Изменения:**
1. **Строка 490:** Добавлен `tz=timezone.utc` в `dt.fromtimestamp()`:
   ```python
   # Было:
   entry_time_from_api = dt.fromtimestamp(entry_timestamp_sec)
   
   # Стало:
   entry_time_from_api = dt.fromtimestamp(entry_timestamp_sec, tz=timezone.utc)
   ```

2. **Строки 501-510:** Добавлена проверка и конвертация `existing_metadata.entry_time` в offset-aware перед сравнением:
   ```python
   # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Убеждаемся, что оба datetime offset-aware перед сравнением
   existing_entry_time = existing_metadata.entry_time
   if existing_entry_time and existing_entry_time.tzinfo is None:
       # Если existing_entry_time offset-naive, конвертируем в offset-aware (UTC)
       existing_entry_time = existing_entry_time.replace(tzinfo=timezone.utc)
   ```

---

### 2. ✅ Исправлено в `position_registry.py`

**Файл:** `src/strategies/scalping/futures/core/position_registry.py`

**Изменения:**
1. **Строка 90:** Добавлена конвертация `entry_time` в offset-aware при создании из словаря:
   ```python
   elif isinstance(data["entry_time"], datetime):
       entry_time = data["entry_time"]
       # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time всегда offset-aware
       if entry_time.tzinfo is None:
           entry_time = entry_time.replace(tzinfo=timezone.utc)
   ```

2. **Строка 103:** Добавлена конвертация `created_at` в offset-aware:
   ```python
   elif isinstance(data["created_at"], datetime):
       created_at = data["created_at"]
       # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Убеждаемся, что created_at всегда offset-aware
       if created_at.tzinfo is None:
           created_at = created_at.replace(tzinfo=timezone.utc)
   ```

3. **Строка 116:** Добавлена конвертация `peak_profit_time` в offset-aware:
   ```python
   elif isinstance(data["peak_profit_time"], datetime):
       peak_profit_time = data["peak_profit_time"]
       # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Убеждаемся, что peak_profit_time всегда offset-aware
       if peak_profit_time and peak_profit_time.tzinfo is None:
           peak_profit_time = peak_profit_time.replace(tzinfo=timezone.utc)
   ```

---

## 📋 ПРОВЕРКА ДРУГИХ МЕСТ

**Проверены следующие файлы:**
- ✅ `entry_manager.py` - уже использует `tz=timezone.utc`
- ✅ `position_manager.py` - уже использует `tz=timezone.utc`
- ✅ `orchestrator.py` - уже использует `tz=timezone.utc`
- ⚠️ `order_coordinator.py` - использует `fromtimestamp` без timezone (но не сравнивается с offset-aware)
- ⚠️ `trailing_stop_loss.py` - использует `fromtimestamp` без timezone (только для логирования)
- ⚠️ `websocket_coordinator.py` - использует `utcfromtimestamp` (deprecated, но не сравнивается)

**Рекомендация:** Эти места не критичны, так как не сравниваются с offset-aware datetime, но можно исправить для единообразия.

---

## ✅ РЕЗУЛЬТАТ

**Все критические места исправлены:**
1. ✅ `entry_time_from_api` теперь всегда offset-aware
2. ✅ `existing_metadata.entry_time` конвертируется в offset-aware перед сравнением
3. ✅ Все datetime в `PositionMetadata.from_dict()` конвертируются в offset-aware

**Ошибка должна быть устранена.**

---

## 🎯 СТАТУС

**✅ ИСПРАВЛЕНО**

**Дата исправления:** 26.12.2025  
**Версия:** 1.2.1



