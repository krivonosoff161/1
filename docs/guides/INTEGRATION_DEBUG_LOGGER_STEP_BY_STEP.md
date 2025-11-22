# 📝 ИНТЕГРАЦИЯ DEBUG LOGGER - ПОШАГОВО

**Файл:** `src/strategies/modules/debug_logger.py` ✅ ГОТОВ  
**Гайд:** `docs/guides/DEBUGGING_WITH_DEBUG_LOGGER.md` ✅ ГОТОВ  
**Время интеграции:** ~30-40 минут

---

## ШАГИ ИНТЕГРАЦИИ

### ШАГ 1: Инициализация в Orchestrator

**Файл:** `src/strategies/scalping/futures/orchestrator.py`

**Найти:** Строка `def __init__(self, config: BotConfig):`

**После строки:** `self.config_manager = ConfigManager(config)`

**Добавить:**
```python
# ✅ DEBUG LOGGER для полного трейсирования
from src.strategies.modules.debug_logger import DebugLogger

self.debug_logger = DebugLogger(
    enabled=True,           # Включить для диагностики
    csv_export=True,        # Экспортировать в logs/futures/debug/
    csv_dir="logs/futures/debug",  # ✅ Папка внутри futures (как основные логи)
    verbose=True            # DEBUG уровень логирования
)
```

**Результат:**
```python
self.config_manager = ConfigManager(config)
self.debug_logger = DebugLogger(
    enabled=True,
    csv_export=True,
    verbose=True
)
```

---

### ШАГ 2: Передать в TSL Manager

**Файл:** `src/strategies/scalping/futures/orchestrator.py`

**Найти:** Строка `self.tsl_manager = TSLManager(...)`

**Изменить на:**
```python
self.tsl_manager = TSLManager(
    config_manager=self.config_manager,
    debug_logger=self.debug_logger  # ← ДОБАВИТЬ
)
```

---

### ШАГ 3: Обновить TSL Manager

**Файл:** `src/strategies/scalping/futures/tsl_manager.py`

**Найти:** `def __init__(self, config_manager):`

**Изменить на:**
```python
def __init__(self, config_manager, debug_logger=None):
    """
    Args:
        config_manager: ConfigManager для получения параметров
        debug_logger: DebugLogger для логирования ✅ НОВОЕ
    """
    self.config_manager = config_manager
    self.debug_logger = debug_logger  # ← ДОБАВИТЬ
    self.trailing_sl_by_symbol: Dict[str, TrailingStopLoss] = {}
```

**Найти в `create_tsl_for_position`:** Линия `tsl.start(entry_price, side)`

**После добавить:**
```python
# Логируем создание TSL
if self.debug_logger:
    self.debug_logger.log_tsl_created(
        symbol=symbol,
        regime=regime or "unknown",
        entry_price=entry_price,
        side=side,
        min_holding=tsl_params.get("min_holding_minutes"),
        timeout=tsl_params.get("timeout_minutes")
    )
```

---

### ШАГ 4: Передать в TrailingStopLoss

**Файл:** `src/strategies/scalping/futures/tsl_manager.py`

**Найти:** `tsl = TrailingStopLoss(...)`

**Добавить параметр:**
```python
tsl = TrailingStopLoss(
    # ... все остальное ...
    debug_logger=self.debug_logger  # ← ДОБАВИТЬ
)
```

---

### ШАГ 5: Обновить TrailingStopLoss класс

**Файл:** `src/strategies/scalping/futures/indicators/trailing_stop_loss.py`

**Найти:** `def __init__(self, ...)`

**Добавить параметр в конец:**
```python
def __init__(
    self,
    # ... все остальное ...
    debug_logger=None,  # ← ДОБАВИТЬ
):
```

**В теле `__init__` добавить:**
```python
self.debug_logger = debug_logger  # ← ДОБАВИТЬ
```

---

### ШАГ 6: КРИТИЧНЫЕ логи в should_close_position()

**Файл:** `src/strategies/scalping/futures/indicators/trailing_stop_loss.py`

**Метод:** `should_close_position()`

#### ЛОГИРОВАНИЕ #1: min_holding проверка (линия ~466)

**Найти:**
```python
if (
    effective_min_holding is not None
    and minutes_in_position < effective_min_holding
):
    logger.debug(...)
    return False
```

**После `logger.debug(...)` добавить:**
```python
if self.debug_logger:
    self.debug_logger.log_tsl_min_holding_block(
        symbol=getattr(self, '_symbol', 'UNKNOWN'),
        minutes_in_position=minutes_in_position,
        min_holding=effective_min_holding,
        profit_pct=profit_pct
    )
```

**ПРИМЕЧАНИЕ:** Нужно добавить в `start()` метод `self._symbol = symbol`

#### ЛОГИРОВАНИЕ #2: loss_cut проверка (линия ~567)

**Найти:**
```python
if profit_pct <= -loss_cut_from_price:
    loss_from_margin = abs(profit_pct) * self.leverage
    logger.warning(...)
    return True
```

**После `logger.warning(...)` добавить:**
```python
if self.debug_logger:
    self.debug_logger.log_tsl_loss_cut_check(
        symbol=getattr(self, '_symbol', 'UNKNOWN'),
        profit_pct=profit_pct,
        loss_cut_from_price=loss_cut_from_price,
        will_close=True
    )
```

#### ЛОГИРОВАНИЕ #3: timeout проверка (линия ~591)

**Найти:**
```python
if (
    minutes_in_position >= self.timeout_minutes
    and profit_pct <= -timeout_loss_from_price
):
    logger.warning(...)
    return True
```

**После `logger.warning(...)` добавить:**
```python
if self.debug_logger:
    self.debug_logger.log_tsl_timeout_check(
        symbol=getattr(self, '_symbol', 'UNKNOWN'),
        minutes_in_position=minutes_in_position,
        timeout_minutes=self.timeout_minutes,
        profit_pct=profit_pct,
        will_close=True
    )
```

---

### ШАГ 7: Логирование в Orchestrator - цикл

**Файл:** `src/strategies/scalping/futures/orchestrator.py`

**Найти:** Главный цикл обработки символов (метод `_manage_positions` или `run`)

**В начале обработки каждого символа добавить:**
```python
self.debug_logger.log_tick(
    symbol=symbol,
    regime=regime,
    price=current_price,
    minutes_running=elapsed_time
)
```

**При открытии позиции:**
```python
self.debug_logger.log_position_open(
    symbol=symbol,
    side=side,
    entry_price=entry_price,
    size=size,
    regime=regime
)
```

**При закрытии позиции:**
```python
self.debug_logger.log_position_close(
    symbol=symbol,
    exit_price=exit_price,
    pnl_usd=pnl_usd,
    pnl_pct=pnl_pct,
    time_in_position_minutes=time_mins,
    reason=close_reason  # "loss_cut", "tsl", "tp", "timeout"
)
```

---

### ШАГ 8: Логирование конфига

**Файл:** `src/strategies/scalping/futures/orchestrator.py`

**В методе `_initialize_trailing_stop()` после получения параметров:**

```python
# Логируем загруженные параметры
self.debug_logger.log_config_loaded(
    symbol=symbol,
    regime=regime,
    params=params
)
```

---

## ПРОВЕРКА

После интеграции проверить:

```bash
# 1. Синтаксис
python -m py_compile src/strategies/modules/debug_logger.py
python -m py_compile src/strategies/scalping/futures/orchestrator.py

# 2. Импорты
python -c "from src.strategies.modules.debug_logger import DebugLogger; print('✅ OK')"

# 3. Папка логов
ls -la logs/futures/debug/
```

---

## ЗАПУСК С ЛОГАМИ

```bash
# 1. Запустить бота
python run.py

# 2. Сделать 5-10 сделок (20-30 минут)

# 3. Проверить логи
ls -la logs/futures/debug/

# 4. Открыть CSV в Excel
# logs/futures/debug/debug_YYYYMMDD_HHMMSS.csv

# 5. Анализировать:
#    - Ищем "close" события
#    - Смотрим "reason" 
#    - Сравниваем "time_min" с "min_holding_minutes" из конфига
```

---

## ОЖИДАЕМЫЙ РЕЗУЛЬТАТ

После интеграции вы увидите в логах:

```
09:35:04 🔄 TICK: BTC-USDT regime=ranging
09:35:04 ⚙️  CONFIG: BTC-USDT min_hold=40.0 timeout=90
09:35:04 ✨ TSL CREATE: BTC-USDT entry=84329.1 min_hold=40.0
09:35:04 📤 OPEN: BTC-USDT side=long price=84329.1

09:36:05 🔍 TSL CHECK: BTC-USDT minutes=1.0 profit=-0.5%
09:36:05 🔍 TSL CHECK: BTC-USDT check=min_holding_BLOCKED
09:36:05 🔍 TSL CHECK: BTC-USDT check=loss_cut profit=-0.5% close=False

09:39:51 ❌ CLOSE: BTC-USDT reason=loss_cut time_min=4.78 pnl_pct=-2.06%
```

**И CSV файл с полной историей!**

---

## КОГДА ЗАКОНЧИТЬ

После 5-10 сделок с логами:
1. Откройте CSV
2. Найдите все "close" события
3. Посмотрите "reason" - что закрыло позицию?
4. Сравните "time_min" - совпадает ли с min_holding?
5. **Дайте мне CSV - исправим код!**

---

**Примерное время:** 30-40 минут на интеграцию + 20-30 минут тестирования

**Затем:** Полная видимость проблемы! 🔍

