# Layer 0: Инфраструктура и поток данных — АУДИТ

## Дата: 2026-02-22

---

## 🔴 L0-1: WS reconnect — возможен race condition при восстановлении подписок

**Severity:** 🔴 Высокая

**Файл:** `src/strategies/scalping/futures/websocket_manager.py:26-75`

**Root cause:** 
- `ensure_fresh_connection()` и `force_reconnect()` не блокируют торговый цикл во время reconnect
- `_handle_disconnect()` вызывается, но нет гарантии что подписки восстановлены перед возобновлением торговли

**Код:**
```python
async def ensure_fresh_connection(self):
    time_since_heartbeat = time.time() - self.last_heartbeat
    if not self.connected or time_since_heartbeat > self.heartbeat_interval * 2:
        await self._handle_disconnect()  # ← Нет ожидания восстановления подписок!
        return False
    return True
```

**Влияние на PnL:** 
- При reconnect торговля может возобновиться с неполными данными
- Сигналы на основе stale индикаторов → ложные входы/выходы
- Оценка: до 0.5% на сделку при reconnect

**Доказательство из логов:** Нет (требуется проверка логов на наличие "WS reconnect" сразу перед сигналами)

**Предложение:** Добавить флаг `_reconnecting` и блокировать генерацию сигналов до `on_reconnect_complete`

---

## 🟡 L0-2: DataRegistry — частичное обновление данных возможно

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/core/data_registry.py:244-267`

**Root cause:**
- `update_market_data()` использует `.update()` — частичное обновление словаря
- Если WS пришлёт только price без best_bid/best_ask — старые bid/ask останутся

**Код:**
```python
async def update_market_data(self, symbol: str, data: Dict[str, Any]) -> None:
    async with self._lock:
        if symbol not in self._market_data:
            self._market_data[symbol] = {}
        self._market_data[symbol].update(data)  # ← Частичное обновление!
        self._market_data[symbol]["updated_at"] = datetime.now()
```

**Влияние на PnL:**
- Устаревшие best_bid/best_ask при расчёте спреда
- Неправильные цены входа/выхода
- Оценка: 0.1-0.3% проскальзывания

**Доказательство из кода:**
- `websocket_coordinator.py:580-599` — обновляет все поля разом
- Но если тикер пришёл без полей — они не сбрасываются

**Предложение:** Добавить TTL на каждое поле отдельно или атомарное обновление всего snapshot

---

## 🟢 L0-3: DataRegistry — нет отдельного last_update_ts по типам данных

**Severity:** 🟢 Низкая

**Файл:** `src/strategies/scalping/futures/core/data_registry.py:76-99`

**Root cause:**
- Единое поле `updated_at` для всего market_data
- Невозможно определить: цена свежая, но индикаторы старые

**Код:**
```python
self._market_data[symbol]["updated_at"] = datetime.now()  # ← Общий timestamp
```

**Влияние на PnL:** Минимальное — индикаторы обновляются вместе с ценой

**Предложение:** Добавить `price_updated_at`, `indicators_updated_at`, `regime_updated_at`

---

## 🟡 L0-4: PositionSync — интервал 30-60 секунд может быть долгим для скальпинга

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/core/position_sync.py:88-109`

**Root cause:**
- `sync_positions_with_exchange()` вызывается раз в 30 секунд (по умолчанию)
- При скальпинге сделки длятся 1-5 минут — 30 секунд это значительная часть сделки

**Код:**
```python
base_interval_min = 0.5  # 30 секунд
sync_interval = base_interval_min * 60.0  # 30 сек

if not force and (now - self._last_positions_sync) < sync_interval:
    return  # ← Пропускаем синхронизацию
```

**Влияние на PnL:**
- DRIFT_ADD позиция может быть не обнаружена 30 секунд
- DRIFT_REMOVE — позиция закрыта, но бот думает что открыта
- Оценка: убыток от "слепой" торговли до 1%

**Доказательство из логов:** Нужно проверить наличие DRIFT_ADD/DRIFT_REMOVE с задержкой > 10 сек

**Предложение:** Уменьшить интервал до 5-10 секунд для активных позиций

---

## 🔴 L0-5: PositionSync — при рассинхроне нет emergency stop

**Severity:** 🔴 Высокая

**Файл:** `src/strategies/scalping/futures/core/position_sync.py:192-299`

**Root cause:**
- DRIFT_ADD/DRIFT_REMOVE логируются, но нет агрессивного действия
- Если позиция закрылась на бирже, но осталась в реестре — бот может открыть противоположную

**Код:**
```python
if is_drift_add:
    logger.warning(f"⚠️ DRIFT_ADD {symbol}: Позиция найдена на бирже, но отсутствует в локальном реестре...")
    # Регистрируем позицию, но не проверяем почему дрифт произошёл
```

**Влияние на PnL:** 
- "Призрачная" позиция в реестре → повторный вход в ту же сторону
- Двойной риск, двойная маржа
- Оценка: до 2% убытка при ложном входе

**Предложение:** При DRIFT_REMOVE с прибылью/убытком — немедленный пересчёт всех позиций

---

## 🟡 L0-6: Private WS — нет fallback на REST при потере соединения

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/private_websocket_manager.py:78-85`

**Root cause:**
- Есть reconnect логика, но нет явного fallback на REST polling
- Если private WS не восстанавливается — позиции не обновляются

**Код:**
```python
self._reconnect_attempts = 0
self._max_reconnect_attempts = 10
# Нет fallback на REST!
```

**Влияние на PnL:**
- Потеря обновлений позиций и ордеров
- Задержка в обнаружении закрытия позиции
- Оценка: до 0.5% при задержке выхода

**Предложение:** При `_reconnect_attempts > 3` — активировать REST polling fallback

---

## 🟡 L0-7: TCC update_state — баланс обновляется только при REST sync

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/core/trading_control_center.py:570-780`

**Root cause:**
- Баланс обновляется только когда `_rest_due = True` (раз в 5 секунд)
- При чистом WS-режиме баланс может быть stale

**Код:**
```python
if not _rest_due and _ws_pos_age < self._slow_loop_interval:
    # WS positions свежие — пропускаем REST
    # ← Баланс не обновляется!
else:
    positions = await self.client.get_positions()
    # ... обновление баланса
```

**Влияние на PnL:**
- RiskManager использует stale баланс для расчёта размера позиции
- При просадке — размер позиции может быть завышен
- Оценка: до 0.3% при перерасчёте риска

**Предложение:** Обновлять баланс отдельно через account WS или чаще через REST

---

## 🟢 L0-8: TCC — нет проверки полноты данных перед торговлей

**Severity:** 🟢 Низкая

**Файл:** `src/strategies/scalping/futures/core/trading_control_center.py:143-190`

**Root cause:**
- Ожидание `initialization_complete` есть, но нет проверки что все символы имеют данные
- Может начать торговлю с частично инициализированными индикаторами

**Код:**
```python
await asyncio.wait_for(
    orchestrator.initialization_complete.wait(), timeout=60.0
)
# ← Нет проверки что все символы имеют fresh data!
```

**Влияние на PnL:** Минимальное — сигналы фильтруются по freshness

**Предложение:** Добавить проверку `data_registry.is_fresh(symbol)` для всех торгуемых символов

---

## СВОДНАЯ ТАБЛИЦА Layer 0

| ID | Проблема | Severity | Влияние на PnL | Действие |
|----|----------|----------|----------------|----------|
| L0-1 | WS reconnect race condition | 🔴 | До 0.5% | Исправить |
| L0-2 | Частичное обновление DataRegistry | 🟡 | 0.1-0.3% | Исправить |
| L0-3 | Нет отдельных timestamp | 🟢 | Минимальное | Улучшить |
| L0-4 | PositionSync интервал 30с | 🟡 | До 1% | Оптимизировать |
| L0-5 | Нет emergency при DRIFT | 🔴 | До 2% | Исправить |
| L0-6 | Private WS без REST fallback | 🟡 | До 0.5% | Добавить |
| L0-7 | Баланс только при REST | 🟡 | До 0.3% | Исправить |
| L0-8 | Нет проверки полноты данных | 🟢 | Минимальное | Улучшить |

---

## РЕКОМЕНДАЦИИ ПО ПРИОРИТЕТАМ

### P0 (немедленно):
1. **L0-5** — Добавить emergency stop при DRIFT_REMOVE с позицией в убытке
2. **L0-1** — Блокировать сигналы во время reconnect

### P1 (в ближайшем спринте):
3. **L0-4** — Уменьшить интервал PositionSync до 5-10 сек
4. **L0-7** — Обновлять баланс чаще (account WS)
5. **L0-6** — REST fallback для private WS

### P2 (техдолг):
6. **L0-2** — Атомарное обновление DataRegistry
7. **L0-3** — Отдельные timestamp по типам данных
8. **L0-8** — Проверка полноты данных перед стартом
