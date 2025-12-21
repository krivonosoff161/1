# ИСПРАВЛЕНИЕ: TrailingStopLoss - расчет от маржи

**Дата:** 2025-12-18  
**Статус:** ✅ ИСПРАВЛЕНИЯ ПРИМЕНЕНЫ

---

## 🔍 НАЙДЕННАЯ ПРОБЛЕМА

**Проблема:** TrailingStopLoss вызывался БЕЗ передачи `margin_used` и `unrealized_pnl`, поэтому всегда использовался fallback расчет от цены вместо правильного расчета от маржи!

---

## ✅ ПРИМЕНЕННЫЕ ИСПРАВЛЕНИЯ

### 1. Метод `update()` ✅

**Файл:** `trailing_stop_loss.py:update()` (строки 213-227)

**Изменения:**
- Добавлены параметры `margin_used` и `unrealized_pnl`
- Передаются в `get_profit_pct()` для правильного расчета от маржи

**Код:**
```python
def update(
    self,
    current_price: float,
    margin_used: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
) -> Optional[float]:
    # ...
    profit_pct_total = self.get_profit_pct(
        current_price,
        include_fees=True,
        margin_used=margin_used,
        unrealized_pnl=unrealized_pnl,
    )
```

---

### 2. Метод `should_close_position()` ✅

**Файл:** `trailing_stop_loss.py:should_close_position()` (строки 509-540)

**Изменения:**
- Добавлены параметры `margin_used` и `unrealized_pnl`
- Передаются в `get_profit_pct()` для правильного расчета от маржи

**Код:**
```python
def should_close_position(
    self,
    current_price: float,
    min_profit_pct: Optional[float] = None,
    trend_strength: Optional[float] = None,
    market_regime: Optional[str] = None,
    margin_used: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
) -> Tuple[bool, Optional[str]]:
    # ...
    profit_pct = self.get_profit_pct(
        current_price,
        include_fees=True,
        margin_used=margin_used,
        unrealized_pnl=unrealized_pnl,
    )
```

---

### 3. TrailingSLCoordinator.update_trailing_stop_loss() ✅

**Файл:** `trailing_sl_coordinator.py:update_trailing_stop_loss()` (строки 610-635)

**Изменения:**
- Получение `margin_used` и `unrealized_pnl` ПЕРЕД вызовом `update()`
- Передача их в `update()` и `should_close_position()`

**Код:**
```python
# Получаем margin и unrealizedPnl ДО вызова update()
margin_used = None
unrealized_pnl = None
try:
    margin_str = position.get("margin") or position.get("imr") or "0"
    if margin_str and str(margin_str).strip() and str(margin_str) != "0":
        margin_used = float(margin_str)
    upl_str = position.get("upl") or position.get("unrealizedPnl") or "0"
    if upl_str and str(upl_str).strip() and str(upl_str) != "0":
        unrealized_pnl = float(upl_str)
except (ValueError, TypeError) as e:
    logger.debug(f"⚠️ Ошибка получения margin/upl для {symbol}: {e}")

# Передаем в update() для правильного расчета от маржи
tsl.update(
    current_price,
    margin_used=margin_used if margin_used and margin_used > 0 else None,
    unrealized_pnl=unrealized_pnl if unrealized_pnl is not None else None,
)

# Передаем в should_close_position()
should_close_by_sl, close_reason = tsl.should_close_position(
    current_price,
    trend_strength=trend_strength,
    market_regime=market_regime,
    margin_used=margin_used if margin_used and margin_used > 0 else None,
    unrealized_pnl=unrealized_pnl if unrealized_pnl is not None else None,
)
```

---

### 4. PositionManager._check_tp_only() ✅

**Файл:** `position_manager.py:_check_tp_only()` (строки 2456-2460)

**Изменения:**
- Получение `margin_used` и `unrealized_pnl` из position
- Передача их в `get_profit_pct()` для правильного расчета от маржи

**Код:**
```python
# Получаем margin и unrealized_pnl для правильного расчета от маржи
margin_used_tsl = None
unrealized_pnl_tsl = None
try:
    margin_str = position.get("margin") or position.get("imr") or "0"
    if margin_str and str(margin_str).strip() and str(margin_str) != "0":
        margin_used_tsl = float(margin_str)
    upl_str = position.get("upl") or position.get("unrealizedPnl") or "0"
    if upl_str and str(upl_str).strip() and str(upl_str) != "0":
        unrealized_pnl_tsl = float(upl_str)
except (ValueError, TypeError):
    pass

# Передаем в get_profit_pct() для правильного расчета от маржи
profit_pct_net = tsl.get_profit_pct(
    current_price,
    include_fees=True,
    margin_used=margin_used_tsl if margin_used_tsl and margin_used_tsl > 0 else None,
    unrealized_pnl=unrealized_pnl_tsl if unrealized_pnl_tsl is not None else None,
)
```

---

## 📊 РЕЗУЛЬТАТ

**Теперь TrailingStopLoss ВСЕГДА использует правильный расчет от маржи!**

### Логика расчета:

1. ✅ **Приоритет 1:** Если есть `margin_used` и `unrealized_pnl` → считаем от маржи (как на бирже)
2. ✅ **Fallback:** Если нет → считаем от цены и конвертируем через leverage

### Преимущества:

- ✅ Соответствие биржевому расчету PnL%
- ✅ Правильный учет leverage
- ✅ Правильный учет комиссии от маржи

---

## ⚠️ ВАЖНО

**Комиссия в TrailingStopLoss:**
- Уже учитывается правильно: `trading_fee_rate * 100` от маржи
- При leverage 5x: комиссия 0.1% от номинала = 0.5% от маржи (учитывается через fallback конвертацию)

---

## 🎯 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ

**Правильный расчет PnL% от маржи во всех местах!**

- TrailingStopLoss теперь считает от маржи (как на бирже)
- Комиссия учитывается правильно
- Leverage учитывается правильно

---

**Все исправления применены и готовы к тестированию!** ✅
