# 🔍 Руководство по DEBUG LOGGER

## Обзор

`DebugLogger` - централизованный модуль логирования для полного трейсирования торговли.

**Расположение:** `src/strategies/modules/debug_logger.py`  
**Правила:** Следует PROJECT_RULES.md  
**CSV экспорт:** Да, автоматически в `logs/futures/debug/` (внутри папки futures)

---

## Быстрый старт

### 1. Инициализация

```python
from src.strategies.modules.debug_logger import DebugLogger

# В orchestrator.__init__()
self.debug_logger = DebugLogger(
    enabled=True,           # Включить логирование
    csv_export=True,        # Экспортировать в CSV
    verbose=True            # DEBUG уровень (True) или WARNING (False)
)
```

### 2. Логирование событий

```python
# Начало обработки тика
self.debug_logger.log_tick(
    symbol="BTC-USDT",
    regime="ranging",
    price=84329.1,
    minutes_running=0.5
)

# Загруженная конфигурация
self.debug_logger.log_config_loaded(
    symbol="BTC-USDT",
    regime="ranging",
    params={
        "min_holding_minutes": 40,
        "timeout_minutes": 90,
        "loss_cut_percent": 1.5,
        ...
    }
)

# Создание TSL
self.debug_logger.log_tsl_created(
    symbol="BTC-USDT",
    regime="ranging",
    entry_price=84329.1,
    side="long",
    min_holding=40,
    timeout=90
)
```

### 3. Критичные точки - TSL проверка

```python
# В trailing_stop_loss.py: should_close_position()

# Проверка min_holding БЛОКИРУЕТ закрытие
if effective_min_holding is not None and minutes_in_position < effective_min_holding:
    logger.debug(f"BLOCKED by min_holding: {minutes_in_position} < {effective_min_holding}")
    # ДОБАВИТЬ:
    self.debug_logger.log_tsl_min_holding_block(
        symbol=symbol,
        minutes_in_position=minutes_in_position,
        min_holding=effective_min_holding,
        profit_pct=profit_pct
    )
    return False

# Проверка loss_cut
if profit_pct <= -loss_cut_from_price:
    will_close = True
    # ДОБАВИТЬ:
    self.debug_logger.log_tsl_loss_cut_check(
        symbol=symbol,
        profit_pct=profit_pct,
        loss_cut_from_price=loss_cut_from_price,
        will_close=will_close
    )
    return True

# Проверка timeout
if minutes_in_position >= timeout_minutes and profit_pct <= -timeout_loss_from_price:
    will_close = True
    # ДОБАВИТЬ:
    self.debug_logger.log_tsl_timeout_check(
        symbol=symbol,
        minutes_in_position=minutes_in_position,
        timeout_minutes=timeout_minutes,
        profit_pct=profit_pct,
        will_close=will_close
    )
    return True
```

### 4. Открытие/закрытие позиций

```python
# Открытие
self.debug_logger.log_position_open(
    symbol="BTC-USDT",
    side="long",
    entry_price=84329.1,
    size=0.0017,
    regime="ranging"
)

# Закрытие
self.debug_logger.log_position_close(
    symbol="BTC-USDT",
    exit_price=84066.7,
    pnl_usd=-0.59,
    pnl_pct=-0.0206,
    time_in_position_minutes=4.78,
    reason="loss_cut"  # или "tsl", "tp", "timeout", etc.
)
```

---

## Примеры вывода

### Консоль (при verbose=True)

```
09:35:04.102 🔄 TICK: BTC-USDT | regime=ranging | price=84329.1 | minutes=0.5
09:35:04.103 ⚙️  CONFIG: BTC-USDT | regime=ranging | min_hold=40.0 | timeout=90 | loss_cut=1.5
09:35:04.104 ✨ TSL CREATE: BTC-USDT | regime=ranging | entry=84329.1 | side=long | min_hold=40.0 | timeout=90
📤 OPEN: BTC-USDT | side=long | price=84329.1 | size=0.0017 | regime=ranging

09:36:05.234 🔍 TSL CHECK: BTC-USDT | minutes=1.0 | profit=-0.5% | price=84200.0 | sl=83984.0 | close=False
09:36:05.235 🔍 TSL CHECK: BTC-USDT | check=min_holding_BLOCKED | minutes=1.0 | min_hold=40.0 | profit=-0.5%
09:36:05.236 🔍 TSL CHECK: BTC-USDT | check=loss_cut | profit=-0.5% | loss_cut=0.3% | close=False

09:39:51.789 ❌ CLOSE: BTC-USDT | exit=84066.7 | pnl_usd=-0.59 | pnl_pct=-2.06% | time_min=4.78 | reason=loss_cut
```

### CSV (logs/futures/debug/debug_20251122_093500.csv)

```
timestamp,event_type,symbol,data
09:35:04.102,tick,BTC-USDT,regime=ranging | price=84329.1 | minutes=0.5
09:35:04.103,config,BTC-USDT,regime=ranging | min_hold=40.0 | timeout=90 | loss_cut=1.5 | timeout_loss=1.0
09:35:04.104,tsl_create,BTC-USDT,regime=ranging | entry=84329.1 | side=long | min_hold=40.0 | timeout=90
09:35:04.105,open,BTC-USDT,side=long | price=84329.1 | size=0.0017 | regime=ranging
09:36:05.234,tsl_check,BTC-USDT,minutes=1.0 | profit=-0.005 | price=84200.0 | sl=83984.0 | close=False
09:39:51.789,close,BTC-USDT,exit=84066.7 | pnl_usd=-0.59 | pnl_pct=-0.0206 | time_min=4.78 | reason=loss_cut
```

---

## Где добавлять логи

### КРИТИЧНЫЕ точки (обязательно):

1. **orchestrator.py - главный цикл**
   - `log_tick()` в начале обработки символа
   - `log_position_open()` при открытии
   - `log_position_close()` при закрытии

2. **trailing_stop_loss.py - should_close_position()**
   - `log_tsl_min_holding_block()` - защита min_holding
   - `log_tsl_loss_cut_check()` - проверка loss_cut
   - `log_tsl_timeout_check()` - проверка timeout
   - `log_tsl_check()` - финальная проверка

3. **config_manager.py - get_trailing_sl_params()**
   - `log_config_loaded()` - какие параметры загружены

4. **position_manager.py - методы закрытия**
   - `log_tp_check()` - проверка TP
   - `log_position_manager_action()` - действия PM

---

## Анализ CSV в Excel

1. Откройте `logs/futures/debug/debug_YYYYMMDD_HHMMSS.csv` в Excel
2. Отфильтруйте по `event_type` (close) - все закрытия
3. Отсортируйте по `timestamp`
4. Найдите закрытия с `time_min < 5` (быстрые закрытия!)
5. Проверьте `reason` - что вызвало закрытие?
6. Сравните с `symbol` - все ли символы закрываются быстро?

---

## Отключение

```python
# Отключить логирование
self.debug_logger = DebugLogger(enabled=False)

# Или сохранить в памяти, но не в CSV
self.debug_logger = DebugLogger(
    enabled=True,
    csv_export=False,
    verbose=False
)
```

---

## Интеграция в код

### Шаг 1: Добавить в orchestrator.__init__()

```python
self.debug_logger = DebugLogger(
    enabled=True,
    csv_export=True,
    verbose=True
)
```

### Шаг 2: Передать в TSL Manager

```python
self.tsl_manager = TSLManager(
    config_manager=self.config_manager,
    debug_logger=self.debug_logger  # ← ДОБАВИТЬ
)
```

### Шаг 3: Использовать в TrailingStopLoss

```python
class TrailingStopLoss:
    def __init__(self, ..., debug_logger=None):
        self.debug_logger = debug_logger
    
    def should_close_position(self, ...):
        if self.debug_logger:
            self.debug_logger.log_tsl_check(...)
```

---

## Контрольный список

- [ ] `debug_logger` инициализирован в orchestrator
- [ ] Добавлены логи в все КРИТИЧНЫЕ точки
- [ ] CSV файлы создаются в `logs/futures/debug/`
- [ ] Консоль показывает детальные логи
- [ ] Тестирование с 5-10 сделками
- [ ] Анализ CSV - найдены причины быстрых закрытий

---

## Вопросы?

После добавления всех логов у вас будет **полная видимость** того, что происходит в боте!

**CSV файл покажет точно:**
- Когда открыли позицию
- Какие параметры используются
- Когда закрыли
- Почему закрыли (reason)
- Сколько времени жила позиция

**И мы найдем ТОЧНУЮ причину проблемы!** 🎯

