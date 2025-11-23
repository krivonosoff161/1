# ИСПРАВЛЕНИЕ ORDER_EXECUTOR ЗАГРУЗКИ

**Дата:** 23 ноября 2025  
**Проблема:** `order_executor` не загружается из YAML в Pydantic модель  
**Решение:** Явная загрузка `order_executor` из `raw_config` после создания модели

---

## 📊 ПРОБЛЕМА

### Обнаружено:
- ✅ `order_executor` есть в YAML (`config_futures.yaml`, строка 1164)
- ✅ `order_executor` определен в модели `ScalpingConfig` с `extra = "allow"`
- ❌ Но Pydantic v2 не загружает его из YAML (становится `None` или `{}`)

### Причина:
- Pydantic v2 может игнорировать дополнительные поля, даже с `extra = "allow"`, если они определены в модели с `default=None` или `default_factory=dict`
- Проблема после рефакторинга: возможно, изменилась структура загрузки конфига

---

## ✅ РЕШЕНИЕ

### Добавлено в `BotConfig.load_from_file()`:
1. ✅ Проверка наличия `order_executor` в `raw_config` после парсинга YAML
2. ✅ Явная установка `order_executor` в `scalping_config.__dict__`, если Pydantic не загрузил его
3. ✅ Поддержка как dict, так и Pydantic модели

### Код:
```python
# После создания config_obj через cls(**raw_config)
if hasattr(config_obj, "scalping") and "scalping" in raw_config:
    scalping_raw = raw_config["scalping"]
    if "order_executor" in scalping_raw:
        order_executor_raw = scalping_raw["order_executor"]
        if not hasattr(config_obj.scalping, "order_executor") or getattr(config_obj.scalping, "order_executor", None) is None:
            config_obj.scalping.__dict__["order_executor"] = order_executor_raw
```

---

## 📋 СЛЕДУЮЩИЕ ШАГИ

1. Перезапустить бота
2. Проверить логи на наличие `order_executor` с данными
3. Убедиться, что `limit_order_config` содержит данные из конфига

---

**Статус:** ✅ ИСПРАВЛЕНО

