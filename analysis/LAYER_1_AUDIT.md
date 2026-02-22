# Layer 1: Деньги (PnL, позиции, комиссии) — АУДИТ

## Дата: 2026-02-22

---

## 🟡 L1-1: PnLCalculator — расчет от цены, а не от маржи

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/calculations/pnl_calculator.py:152-163`

**Root cause:**
- PnL рассчитывается от цены: `(exit_price - entry_price) * size_in_coins`
- Нет учета leverage в процентах PnL
- Биржа показывает PnL от маржи (с учетом leverage)

**Код:**
```python
# Расчет Gross PnL
if side.lower() == "long":
    gross_pnl = (exit_price - entry_price) * size_in_coins
else:  # short
    gross_pnl = (entry_price - exit_price) * size_in_coins

# Расчет PnL в процентах от notional (без leverage!)
pnl_percent_from_price = (net_pnl / notional_entry) * 100
```

**Влияние на PnL:**
- Несоответствие с биржевым PnL
- При leverage 10x и движении цены 1%: 
  - Биржа: PnL = 10% от маржи
  - Калькулятор: PnL = 1% от notional
- Путаница в статистике и принятии решений

**Предложение:** Добавить расчет PnL от маржи: `pnl_percent_from_margin = (net_pnl / margin_used) * 100`

---

## 🔴 L1-2: PositionSizer — DEPRECATED, но может использоваться

**Severity:** 🔴 Высокая

**Файл:** `src/strategies/scalping/futures/calculations/position_sizer.py:1-6`

**Root cause:**
- Модуль помечен DEPRECATED с 04.01.2026
- Функциональность перенесена в RiskManager
- Но модуль оставлен для "обратной совместимости"

**Код:**
```python
"""
PositionSizer - Расчет размеров позиций.

✅ DEPRECATED (04.01.2026): Функциональность перенесена в RiskManager.calculate_position_size()
Этот модуль оставлен для обратной совместимости, но рекомендуется использовать RiskManager.
"""
```

**Влияние на PnL:**
- Если где-то вызывается PositionSizer вместо RiskManager — размер позиции будет неправильным
- Разные формулы = разные риски
- Оценка: до 2% при несоответствии размера

**Предложение:** Удалить модуль или добавить `raise DeprecationWarning`

---

## 🟡 L1-3: AdaptiveLeverage — округление leverage не проверяет доступность на бирже

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/risk/adaptive_leverage.py:50-170`

**Root cause:**
- `calculate_leverage()` возвращает leverage (3, 5, 10, 20, 30)
- Но не проверяет, доступен ли этот leverage для конкретного символа
- OKX имеет разные максимальные leverage для разных пар

**Код:**
```python
# Определяем категорию качества сигнала
if adjusted_strength < 0.3:
    category = "very_weak"
# ...
leverage = self.leverage_map.get(category, 5)
# ← Нет проверки max_leverage для символа!
```

**Влияние на PnL:**
- При установке leverage 30x на пару с max 10x — ошибка API
- Fallback на default leverage может быть неоптимальным
- Оценка: задержка входа, потеря сигнала

**Предложение:** Проверять `client.get_max_leverage(symbol)` перед установкой

---

## 🔴 L1-4: LiquidationProtector — safety_threshold 50% слишком консервативен

**Severity:** 🔴 Высокая

**Файл:** `src/strategies/scalping/futures/risk/liquidation_protector.py:41-48`

**Root cause:**
- `safety_threshold = 0.5` (50% от цены до ликвидации)
- При leverage 10x и 50% threshold — позиция закроется при убытке 5%
- Это слишком рано для скальпинга

**Код:**
```python
# Порог безопасности: минимальное расстояние до ликвидации (50% от ликвидационной цены)
self.safety_threshold = self.config.get("safety_threshold", 0.5)  # 50%

# Проверка:
is_safe = distance_pct > safety_threshold_pct  # > 50%
```

**Влияние на PnL:**
- Преждевременное закрытие при нормальной волатильности
- При leverage 10x: закрытие при убытке 5% вместо возможного recovery
- Оценка: потеря 2-3% на ложных закрытиях

**Предложение:** Уменьшить до 20-30% для скальпинга или сделать адаптивным по leverage

---

## 🟡 L1-5: LiquidationProtector — не учитывает funding rate

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/risk/liquidation_protector.py:54-194`

**Root cause:**
- Расчет ликвидации только на основе цены и маржи
- Funding rate может существенно влиять на PnL при удержании позиции
- Нет проверки накопленного funding при длительном удержании

**Код:**
```python
# Рассчитываем цену ликвидации
liquidation_price = self.margin_calculator.calculate_liquidation_price(
    side=position_side,
    entry_price=entry_price,
    position_size=abs(position_size),
    equity=balance,
    leverage=None,
)
# ← Нет учета funding rate!
```

**Влияние на PnL:**
- При негативном funding и удержании > 8 часов — дополнительный убыток
- Оценка: 0.1-0.5% при сильном funding

**Предложение:** Добавить проверку funding rate и накопленного funding

---

## 🟢 L1-6: MaxSizeLimiter — жесткие лимиты без адаптации к балансу

**Severity:** 🟢 Низкая

**Файл:** `src/strategies/scalping/futures/risk/max_size_limiter.py:28-44`

**Root cause:**
- `max_single_size_usd = 1000.0` — фиксированный лимит
- `max_total_size_usd = 5000.0` — фиксированный лимит
- Нет привязки к текущему балансу

**Код:**
```python
def __init__(
    self,
    max_single_size_usd: float = 1000.0,
    max_total_size_usd: float = 5000.0,
    max_positions: int = 5,
):
```

**Влияние на PnL:**
- При балансе $100 и max_single_size $1000 — лимит не работает
- При балансе $10000 — искусственное ограничение прибыльности

**Предложение:** Сделать лимиты процентом от баланса: `max_single_size_pct = 0.10` (10%)

---

## 🟡 L1-7: MarginMonitor — кэш 10 секунд может быть долгим

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/risk/margin_monitor.py:33-37`

**Root cause:**
- `_cache_ttl = 10.0` — 10 секунд кэширования маржи
- При быстром движении рынка — stale данные

**Код:**
```python
# 🔴 BUG #22 FIX: TTL cache для маржи (5-15s TTL)
self._margin_cache: Dict[str, Tuple[float, float, float]] = {}
self._cache_ttl = 10.0  # 10 сек TTL
```

**Влияние на PnL:**
- При резком изменении баланса (закрытие позиции) — 10 секунд stale данных
- RiskManager может отклонить валидную сделку
- Оценка: пропуск сигналов

**Предложение:** Уменьшить TTL до 2-3 секунд или инвалидировать кэш при событиях

---

## 🟡 L1-8: RiskManager — daily_pnl не сбрасывается при новом дне

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/risk_manager.py:89-95`

**Root cause:**
- Есть `daily_pnl_date` для отслеживания дня
- Но нет кода который проверяет и сбрасывает при смене дня

**Код:**
```python
# ✅ НОВОЕ: Отслеживание дневного PnL для max_daily_loss
self.daily_pnl: float = 0.0  # Текущий дневной PnL
self.daily_pnl_date: Optional[str] = None  # Дата текущего дня (YYYY-MM-DD)
self.max_daily_loss_percent: float = (
    getattr(self.risk_config, "max_daily_loss_percent", None) or 5.0
)
self.daily_trading_stopped: bool = False  # Флаг остановки торговли
# ← Нет кода проверки смены дня!
```

**Влияние на PnL:**
- При переходе через полночь — daily_pnl не сбрасывается
- Может ложно сработать остановка торговли
- Оценка: пропуск торговли в новый день

**Предложение:** Добавить проверку в `calculate_position_size()`:
```python
current_date = datetime.now().strftime("%Y-%m-%d")
if self.daily_pnl_date != current_date:
    self.daily_pnl = 0.0
    self.daily_pnl_date = current_date
    self.daily_trading_stopped = False
```

---

## 🟡 L1-9: Комиссии — funding rate не учитывается в расчетах

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/calculations/pnl_calculator.py:35-74`

**Root cause:**
- Есть `maker_fee_rate` и `taker_fee_rate`
- Нет `funding_rate` в расчетах

**Код:**
```python
# ✅ FIX: Комиссии из конфига (не хард-код)
self.maker_fee_rate = 0.0002  # Fallback
self.taker_fee_rate = 0.0005  # Fallback
# ← Нет funding_rate!
```

**Влияние на PnL:**
- При удержании позиции > 8 часов — funding может быть значительным
- Оценка: 0.1-0.3% на сделку при негативном funding

**Предложение:** Добавить учет funding rate в PnLCalculator

---

## СВОДНАЯ ТАБЛИЦА Layer 1

| ID | Проблема | Severity | Влияние на PnL | Действие |
|----|----------|----------|----------------|----------|
| L1-1 | PnL от цены, не от маржи | 🟡 | Несоответствие бирже | Исправить |
| L1-2 | PositionSizer DEPRECATED | 🔴 | Неправильный размер | Удалить |
| L1-3 | Leverage без проверки | 🟡 | Ошибка API | Добавить проверку |
| L1-4 | Liquidation threshold 50% | 🔴 | Преждевременное закрытие | Уменьшить до 20-30% |
| L1-5 | Нет учета funding | 🟡 | Скрытые убытки | Добавить |
| L1-6 | Жесткие лимиты | 🟢 | Ограничение прибыльности | Сделать адаптивными |
| L1-7 | Кэш маржи 10с | 🟡 | Stale данные | Уменьшить TTL |
| L1-8 | daily_pnl не сбрасывается | 🟡 | Ложная остановка | Добавить проверку |
| L1-9 | Нет funding rate | 🟡 | Скрытые убытки | Добавить |

---

## РЕКОМЕНДАЦИИ ПО ПРИОРИТЕТАМ

### P0 (немедленно):
1. **L1-4** — Уменьшить liquidation safety_threshold до 20-30%
2. **L1-2** — Удалить или заблокировать PositionSizer

### P1 (в ближайшем спринте):
3. **L1-1** — Добавить расчет PnL от маржи
4. **L1-8** — Исправить сброс daily_pnl
5. **L1-3** — Проверять max leverage для символа

### P2 (техдолг):
6. **L1-5, L1-9** — Добавить учет funding rate
7. **L1-6** — Адаптивные лимиты
8. **L1-7** — Уменьшить TTL кэша маржи
