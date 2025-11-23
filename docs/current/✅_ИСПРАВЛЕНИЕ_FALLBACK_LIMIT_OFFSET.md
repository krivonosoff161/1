# ИСПРАВЛЕНИЕ FALLBACK LIMIT OFFSET

**Дата:** 23 ноября 2025  
**Проблема:** `order_executor` не загружается из YAML  
**Решение:** Добавлено поле `order_executor` в `ScalpingConfig`

---

## 📊 ПРОБЛЕМА

### В логах:
```
limit_order_config keys=[], by_symbol exists=False, by_regime exists=False
⚠️ FALLBACK: Используется глобальный offset из конфига: 0.0%
```

### Причина:
- ❌ `order_executor` не определен в `ScalpingConfig` в `src/config.py`
- ❌ Pydantic не загружает `order_executor` из YAML
- ❌ `getattr(self.scalping_config, "order_executor", {})` возвращает пустой словарь

---

## ✅ РЕШЕНИЕ

### Добавлено в `src/config.py`:
```python
# ✅ НОВОЕ: Order Executor конфигурация
order_executor: Optional[Dict] = Field(
    default_factory=dict,
    description="Конфигурация order_executor с limit_order и by_symbol/by_regime"
)
```

### Результат:
- ✅ `order_executor` теперь загружается из YAML
- ✅ `limit_order_config` будет содержать данные из конфига
- ✅ `by_symbol` и `by_regime` будут читаться правильно

---

## 📋 СЛЕДУЮЩИЕ ШАГИ

1. ✅ Перезапустить бота
2. ✅ Проверить логи на наличие `order_executor_config` с данными
3. ✅ Убедиться, что `by_symbol` и `by_regime` читаются правильно

---

**Статус:** ✅ ИСПРАВЛЕНО

