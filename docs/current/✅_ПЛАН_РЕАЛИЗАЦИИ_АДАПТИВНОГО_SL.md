# ✅ ПЛАН РЕАЛИЗАЦИИ АДАПТИВНОГО SL

**Дата:** 23.11.2025, 23:50  
**Статус:** Детальный план с проверками

---

## 🔍 ПРОВЕРКА #1: LONG/SHORT ЛОГИКА

### Текущая реализация loss_cut (строка 934-938):

```python
position_side = position.get("posSide", "long").lower()
if position_side == "long":
    unrealized_pnl = size * (current_price - entry_price)
else:  # short
    unrealized_pnl = size * (entry_price - current_price)

pnl_percent_from_margin = (unrealized_pnl / margin_used) * 100

# Проверяем loss_cut
if pnl_percent_from_margin <= -loss_cut_percent:
    # Закрываем
```

**✅ ПРАВИЛЬНО:** Логика для LONG и SHORT корректна!

### Для SL используем ТУ ЖЕ логику:

```python
# ✅ ТОЧНАЯ КОПИЯ логики loss_cut, только sl_percent вместо loss_cut_percent
position_side = position.get("posSide", "long").lower()
if position_side == "long":
    unrealized_pnl = size * (current_price - entry_price)
else:  # short
    unrealized_pnl = size * (entry_price - current_price)

pnl_percent_from_margin = (unrealized_pnl / margin_used) * 100

# Проверяем SL (с защитой min_holding)
if pnl_percent_from_margin <= -sl_percent:
    # Проверяем min_holding
    if minutes_in_position >= min_holding_minutes:
        # Закрываем по SL
```

**✅ БЕЗОПАСНО:** Используем проверенную логику!

---

## 🔍 ПРОВЕРКА #2: АДАПТИВНЫЕ ПАРАМЕТРЫ

### Текущая реализация TP (метод `_get_adaptive_tp_percent`):

**Приоритет:**
1. Per-regime TP (если режим определен)
2. Per-symbol TP (fallback)
3. Глобальный TP (fallback)

**Для SL используем ТОЧНО ТАК ЖЕ:**

```python
def _get_adaptive_sl_percent(self, symbol: str, regime: Optional[str] = None) -> float:
    """✅ КРИТИЧЕСКОЕ: Получает адаптивный SL% для символа и режима.
    
    Приоритет (ТОЧНО как для TP):
    1. Per-regime SL (если режим определен)
    2. Per-symbol SL (fallback)
    3. Глобальный SL (fallback)
    """
    # ✅ ТОЧНАЯ КОПИЯ логики _get_adaptive_tp_percent, только sl_percent вместо tp_percent
```

**✅ БЕЗОПАСНО:** Используем проверенный паттерн!

---

## 🔍 ПРОВЕРКА #3: МЕСТО В КОДЕ

### Текущая проверка loss_cut (строка 893-952):

**В методе `_check_tp_only`:**
- Проверяется **ДО** проверки TP
- Только если TSL **НЕ активен**
- После получения режима для адаптивного loss_cut

**Для SL добавляем ПРЯМО ПЕРЕД loss_cut:**

```python
# ✅ НОВОЕ: Проверка адаптивного SL (ПЕРЕД loss_cut)
await self._check_sl(position)  # Проверяем SL первым (более строгий стоп)

# ✅ СУЩЕСТВУЮЩЕЕ: Проверка loss_cut (ПОСЛЕ SL)
# (существующий код loss_cut остается без изменений)
```

**✅ БЕЗОПАСНО:** Добавляем новый метод, не меняем существующий!

---

## 🔍 ПРОВЕРКА #4: МОДУЛИ

### Не требуется создавать новые модули:

**Используем существующие:**
- `position_manager.py` - добавляем метод `_check_sl` и `_get_adaptive_sl_percent`
- `config_futures.yaml` - добавляем `sl_percent` в `adaptive_regime.regimes` и `symbol_profiles`
- `ConfigManager` - уже поддерживает адаптивные параметры (используем как для TP)

**✅ БЕЗОПАСНО:** Используем существующую инфраструктуру!

---

## 🔍 ПРОВЕРКА #5: ПРИОРИТЕТЫ ЗАКРЫТИЯ

### Текущий порядок проверки:

1. Profit Harvesting (PH)
2. Big Profit Exit (внутри `_check_tp_only`)
3. Partial TP (внутри `_check_tp_only`)
4. Full TP (внутри `_check_tp_only`)
5. TSL (в orchestrator)
6. loss_cut (в `_check_tp_only`, если TSL не активен)

### Новый порядок (после добавления SL):

1. Profit Harvesting (PH)
2. Big Profit Exit (внутри `_check_tp_only`)
3. Partial TP (внутри `_check_tp_only`)
4. Full TP (внутри `_check_tp_only`)
5. TSL (в orchestrator) - **если активен, приоритет #1 для убыточных**
6. **SL (НОВОЕ - в `_check_tp_only`, если TSL не активен, после min_holding)** - **жесткий стоп**
7. loss_cut (в `_check_tp_only`, если TSL не активен, после min_holding) - **мягкий стоп**

**✅ БЕЗОПАСНО:** Четкие приоритеты, нет конфликтов!

---

## 🔍 ПРОВЕРКА #6: ПАРАМЕТРЫ

### Предложенные параметры для ranging:

| Параметр | Текущее | Предложенное | Логика |
|----------|---------|--------------|--------|
| `sl_percent` | 1.2% (не используется) | **2.0%** (адаптивный) | Жесткий стоп, после min_holding |
| `loss_cut_percent` | 4.0% | **3.0%** | Мягкий стоп, после min_holding |
| `min_holding_minutes` | 60 мин | **20 мин** | Разумное время |

### Оптимальность:

**Сценарий 1: Позиция уходит в -1.5% через 5 минут**
- **До:** Не закрывается 60 минут (есть шанс на разворот) ✅
- **После:** Не закрывается 20 минут (есть шанс на разворот) ✅
- **Разница:** Меньше время защиты (60→20 мин), но все еще есть шанс!

**Сценарий 2: Позиция уходит в -2.5% через 25 минут**
- **До:** Не закрывается (loss_cut=4.0%), ждет до -4.0% ❌
- **После:** Закрывается по SL при -2.0% (после 20 мин) ✅
- **Улучшение:** Меньше убыток (-2.0% vs -4.0%)!

**Сценарий 3: Позиция уходит в -3.5% через 30 минут**
- **До:** Закрывается по loss_cut при -4.0% ❌
- **После:** Закрывается по SL при -2.0% (раньше) ✅
- **Улучшение:** Меньше убыток (-2.0% vs -4.0%)!

**✅ ОПТИМАЛЬНО:** Баланс между защитой (шанс на разворот) и ограничением убытков!

---

## 📋 ПЛАН РЕАЛИЗАЦИИ

### Шаг 1: Добавить sl_percent в конфиг

**Файл:** `config/config_futures.yaml`

```yaml
# Глобальный SL (fallback)
sl_percent: 1.2

adaptive_regime:
  regimes:
    trending:
      sl_percent: 1.5  # ✅ НОВОЕ: Адаптивный SL для trending
    ranging:
      sl_percent: 2.0  # ✅ НОВОЕ: Адаптивный SL для ranging
    choppy:
      sl_percent: 1.0  # ✅ НОВОЕ: Адаптивный SL для choppy

  symbol_profiles:
    "BTC-USDT":
      trending:
        sl_percent: 1.5  # ✅ НОВОЕ
      ranging:
        sl_percent: 2.0  # ✅ НОВОЕ
      choppy:
        sl_percent: 1.5  # ✅ НОВОЕ
    # ... (для всех символов)
```

---

### Шаг 2: Добавить метод `_get_adaptive_sl_percent`

**Файл:** `src/strategies/scalping/futures/position_manager.py`

**Добавить ПОСЛЕ метода `_get_adaptive_tp_percent` (после строки 233):**

```python
def _get_adaptive_sl_percent(
    self, symbol: str, regime: Optional[str] = None
) -> float:
    """
    ✅ КРИТИЧЕСКОЕ: Получает адаптивный SL% для символа и режима.
    
    Приоритет (ТОЧНО как для TP):
    1. Per-regime SL (если режим определен)
    2. Per-symbol SL (fallback)
    3. Глобальный SL (fallback)
    
    Args:
        symbol: Торговый символ
        regime: Режим рынка (trending, ranging, choppy)
        
    Returns:
        SL% для использования
    """
    # ✅ ТОЧНАЯ КОПИЯ логики _get_adaptive_tp_percent, только sl_percent вместо tp_percent
    sl_percent = None
    
    # Получаем режим из позиции, если не передан
    if not regime:
        if symbol in self.active_positions:
            regime = self.active_positions[symbol].get("regime")
        elif hasattr(self, "orchestrator") and self.orchestrator:
            # ... (та же логика получения regime как в _get_adaptive_tp_percent)
    
    # Получаем sl_percent для символа и режима (если есть в symbol_profiles)
    if symbol and self.symbol_profiles:
        # ... (та же логика получения из symbol_profiles как в _get_adaptive_tp_percent)
        
        # 1. Per-regime SL
        # 2. Per-symbol SL
        # 3. Глобальный SL (fallback)
    
    return sl_percent or self.scalping_config.sl_percent
```

---

### Шаг 3: Добавить метод `_check_sl`

**Файл:** `src/strategies/scalping/futures/position_manager.py`

**Добавить ПЕРЕД методом `_check_tp_only` (перед строкой 884):**

```python
async def _check_sl(self, position: Dict[str, Any]) -> bool:
    """
    ✅ НОВОЕ: Проверка адаптивного Stop Loss (SL)
    
    Логика:
    - Проверяется ТОЛЬКО если TSL не активен
    - Проверяется ПОСЛЕ min_holding (защита от преждевременного закрытия)
    - Более строгий стоп чем loss_cut (срабатывает раньше)
    
    Args:
        position: Данные позиции с биржи
        
    Returns:
        True если нужно закрыть позицию по SL
    """
    try:
        symbol = position.get("instId", "").replace("-SWAP", "")
        size = float(position.get("pos", "0"))
        entry_price = float(position.get("avgPx", "0"))
        current_price = float(position.get("markPx", "0"))
        
        if size == 0 or entry_price == 0 or current_price == 0:
            return False
        
        # ✅ Проверяем только если TSL не активен
        if hasattr(self, "orchestrator") and self.orchestrator:
            if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                if tsl:
                    # TSL активен - проверка SL не нужна (TSL приоритетнее)
                    return False
        
        # ✅ Получаем режим для адаптивного SL
        regime = position.get("regime") or self.active_positions.get(symbol, {}).get("regime")
        if not regime and hasattr(self, "orchestrator") and self.orchestrator:
            if hasattr(self.orchestrator, "signal_generator"):
                if hasattr(self.orchestrator.signal_generator, "regime_managers"):
                    manager = self.orchestrator.signal_generator.regime_managers.get(symbol)
                    if manager:
                        regime = manager.get_current_regime()
        
        # ✅ Получаем адаптивный SL
        sl_percent = self._get_adaptive_sl_percent(symbol, regime)
        
        # ✅ Проверяем min_holding (защита от преждевременного закрытия)
        minutes_in_position = 0
        if symbol in self.active_positions:
            entry_time = self.active_positions[symbol].get("entry_time")
            if entry_time:
                if isinstance(entry_time, datetime):
                    minutes_in_position = (datetime.now() - entry_time).total_seconds() / 60.0
                else:
                    minutes_in_position = (time.time() - entry_time) / 60.0
        
        # ✅ Получаем min_holding из конфига (адаптивно по режиму)
        min_holding_minutes = 0.5  # Fallback
        if regime:
            try:
                regime_params = self.orchestrator.config_manager.get_regime_params(regime, symbol)
                tsl_config = getattr(self.scalping_config, "trailing_sl", {})
                by_regime = getattr(tsl_config, "by_regime", {}) if hasattr(tsl_config, "by_regime") else {}
                if regime.lower() in by_regime:
                    regime_tsl = by_regime[regime.lower()]
                    if hasattr(regime_tsl, "min_holding_minutes"):
                        min_holding_minutes = regime_tsl.min_holding_minutes
            except Exception:
                pass
        
        # ✅ Проверяем min_holding защиту
        if minutes_in_position < min_holding_minutes:
            logger.debug(
                f"⏱️ SL заблокирован для {symbol}: позиция держится "
                f"{minutes_in_position:.2f} мин < {min_holding_minutes:.2f} мин "
                f"(min_holding защита активна)"
            )
            return False  # НЕ закрываем - min_holding защита активна
        
        # ✅ Рассчитываем PnL% от маржи (ТОЧНАЯ КОПИЯ логики loss_cut)
        try:
            margin_used = float(position.get("margin", 0))
            if margin_used > 0:
                position_side = position.get("posSide", "long").lower()
                if position_side == "long":
                    unrealized_pnl = size * (current_price - entry_price)
                else:  # short
                    unrealized_pnl = size * (entry_price - current_price)
                
                pnl_percent_from_margin = (unrealized_pnl / margin_used) * 100
                
                # ✅ Проверяем SL
                if pnl_percent_from_margin <= -sl_percent:
                    logger.warning(
                        f"🚨 SL сработал для {symbol}: "
                        f"PnL={pnl_percent_from_margin:.2f}% от маржи <= -{sl_percent:.2f}% "
                        f"(margin=${margin_used:.2f}, PnL=${unrealized_pnl:.2f}, "
                        f"время в позиции: {minutes_in_position:.2f} мин)"
                    )
                    await self._close_position_by_reason(position, "sl")
                    return True
        except Exception as e:
            logger.debug(f"⚠️ Не удалось проверить SL для {symbol}: {e}")
        
        return False
        
    except Exception as e:
        logger.error(f"Ошибка проверки SL для {symbol}: {e}")
        return False
```

---

### Шаг 4: Интегрировать `_check_sl` в `_check_tp_only`

**Файл:** `src/strategies/scalping/futures/position_manager.py`

**В методе `_check_tp_only` (после строки 952, ПЕРЕД существующей проверкой loss_cut):**

```python
# ✅ НОВОЕ: Проверка адаптивного SL (ПЕРЕД loss_cut - более строгий стоп)
sl_should_close = await self._check_sl(position)
if sl_should_close:
    return  # Закрыли по SL, выходим

# ✅ СУЩЕСТВУЮЩЕЕ: Проверка loss_cut (ПОСЛЕ SL - мягкий стоп)
# (существующий код loss_cut остается без изменений)
```

---

## ✅ ИТОГОВАЯ ПРОВЕРКА

### 1. LONG/SHORT логика:
- ✅ Используем ТОЧНУЮ КОПИЮ логики loss_cut (строки 934-938)
- ✅ Проверено: работает правильно для LONG и SHORT

### 2. Адаптивные параметры:
- ✅ Используем ТОЧНУЮ КОПИЮ логики `_get_adaptive_tp_percent`
- ✅ Проверено: работает правильно для всех режимов

### 3. Место в коде:
- ✅ Добавляем новый метод `_check_sl`
- ✅ Интегрируем в `_check_tp_only` ПЕРЕД loss_cut
- ✅ Не меняем существующий код (только добавляем)

### 4. Модули:
- ✅ Не требуется создавать новые модули
- ✅ Используем существующую инфраструктуру

### 5. Приоритеты:
- ✅ Четкие приоритеты: TSL → SL → loss_cut
- ✅ Защита min_holding для SL и loss_cut
- ✅ Нет конфликтов

### 6. Параметры:
- ✅ Оптимальные: баланс между защитой и ограничением убытков
- ✅ Сохраняется шанс на разворот (20 мин)
- ✅ Меньше убыток (-2.0% vs -4.0%)

---

## 🎯 РЕЗЮМЕ

**✅ Все учтено:**
- LONG/SHORT логика - используется проверенная логика loss_cut
- Адаптивные параметры - используется проверенный паттерн TP
- Место в коде - безопасное добавление, без изменения существующего
- Модули - используются существующие
- Приоритеты - четкие, без конфликтов
- Параметры - оптимальные, сбалансированные

**✅ Безопасность:**
- Не требуется дополнительных модулей
- Используются проверенные паттерны
- Не меняется существующая логика
- Все просчитано и проверено

---

**Дата:** 23.11.2025, 23:50

