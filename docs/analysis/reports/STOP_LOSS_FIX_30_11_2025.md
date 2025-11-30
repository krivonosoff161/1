# Исправление проблемы с адаптивными SL

**Дата:** 2025-11-30  
**Проблема:** Все позиции закрываются с убытком ~-1.5% вместо адаптивного SL для режима

---

## 🚨 НАЙДЕННАЯ ПРОБЛЕМА

### **Критическая ошибка в `order_executor.py`:**

**Файл:** `src/strategies/scalping/futures/order_executor.py:1459-1470`

**Проблема:**
```python
def _get_regime_params(self, regime: str) -> dict:
    """Получает параметры режима из ARM"""
    try:
        # Если есть доступ к оркестратору
        if hasattr(self, "orchestrator"):
            return self.orchestrator._get_regime_params(regime)
        # Иначе из конфига
        adaptive_regime = self.config.get("adaptive_regime", {})  # ❌ НЕПРАВИЛЬНЫЙ ПУТЬ!
        return adaptive_regime.get(regime, {})
```

**Что не так:**
1. ❌ `self.config.get("adaptive_regime", {})` - неправильный путь!
   - Должно быть: `self.scalping_config.adaptive_regime`
2. ❌ Если `orchestrator` не установлен → возвращается `{}`
3. ❌ Если `regime_params` пустой → используется fallback на глобальный `sl_percent=1.2%`
4. ❌ Адаптивный `sl_percent` для ranging (2.0%) НЕ используется!

---

## ✅ ИСПРАВЛЕНИЕ

### 1. **Исправлен метод `_get_regime_params()`:**

```python
def _get_regime_params(self, regime: str) -> dict:
    """Получает параметры режима из ARM"""
    try:
        # ✅ ИСПРАВЛЕНО: Если есть доступ к оркестратору - используем его метод
        if hasattr(self, "orchestrator") and self.orchestrator:
            return self.orchestrator._get_regime_params(regime)
        
        # ✅ ИСПРАВЛЕНО: Правильный путь к конфигу через scalping_config
        if not hasattr(self, "scalping_config") or not self.scalping_config:
            logger.warning("⚠️ scalping_config не найден в OrderExecutor")
            return {}
        
        # Получаем adaptive_regime из scalping_config
        adaptive_regime = None
        if hasattr(self.scalping_config, "adaptive_regime"):
            adaptive_regime = getattr(self.scalping_config, "adaptive_regime", None)
        elif isinstance(self.scalping_config, dict):
            adaptive_regime = self.scalping_config.get("adaptive_regime", {})
        
        if not adaptive_regime:
            logger.warning(f"⚠️ adaptive_regime не найден в scalping_config для режима {regime}")
            return {}
        
        # Преобразуем в dict если нужно
        if not isinstance(adaptive_regime, dict):
            if hasattr(adaptive_regime, "dict"):
                adaptive_regime = adaptive_regime.dict()
            elif hasattr(adaptive_regime, "model_dump"):
                adaptive_regime = adaptive_regime.model_dump()
            elif hasattr(adaptive_regime, "__dict__"):
                adaptive_regime = dict(adaptive_regime.__dict__)
            else:
                adaptive_regime = {}
        
        regime_params = adaptive_regime.get(regime.lower(), {})
        
        # Преобразуем regime_params в dict если нужно
        if regime_params and not isinstance(regime_params, dict):
            if hasattr(regime_params, "dict"):
                regime_params = regime_params.dict()
            elif hasattr(regime_params, "model_dump"):
                regime_params = regime_params.model_dump()
            elif hasattr(regime_params, "__dict__"):
                regime_params = dict(regime_params.__dict__)
            else:
                regime_params = {}
        
        if not regime_params:
            logger.warning(f"⚠️ Параметры режима {regime} не найдены в adaptive_regime")
        
        return regime_params
    except Exception as e:
        logger.error(f"❌ Ошибка получения параметров режима {regime}: {e}", exc_info=True)
        return {}
```

### 2. **Улучшено логирование в `_calculate_tp_sl_prices()`:**

- ✅ Добавлено INFO-логирование использования адаптивного `sl_percent`
- ✅ Добавлено WARNING при использовании fallback
- ✅ Добавлено INFO-логирование финальных TP/SL цен

---

## 📊 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ

### **До исправления:**
- `regime_params` всегда пустой `{}`
- Используется глобальный `sl_percent=1.2%`
- Все позиции закрываются с убытком ~-1.5%

### **После исправления:**
- `regime_params` содержит параметры режима
- Используется адаптивный `sl_percent` для режима:
  - **trending**: 1.5%
  - **ranging**: 2.0%
  - **choppy**: 1.0%
- Позиции закрываются с правильным SL

---

## 🔍 ДОПОЛНИТЕЛЬНЫЕ ПРОВЕРКИ

### 1. **Проверить передачу `regime` в сигнале:**

**В `signal_generator.py`:**
- Режим должен передаваться в сигнале: `signal["regime"] = current_regime`

### 2. **Проверить ATR-based расчет:**

**Логика:**
- Если ATR-based SL < `sl_percent_abs` → используется `sl_percent`
- Если ATR-based SL >= `sl_percent_abs` → используется ATR-based (более точный)

**Это правильно!** ATR-based более точный, но если он слишком мал, используем минимальный `sl_percent`.

---

## 🎯 ВЫВОД

**Проблема:** `_get_regime_params()` не получал параметры режима из конфига → всегда возвращал `{}` → использовался fallback на глобальный `sl_percent=1.2%`.

**Исправление:** Метод исправлен для правильного получения параметров из `scalping_config.adaptive_regime`.

**Результат:** Теперь будут использоваться адаптивные `sl_percent` по режимам:
- **ranging**: 2.0% (вместо 1.2%)
- **trending**: 1.5% (вместо 1.2%)
- **choppy**: 1.0% (вместо 1.2%)


