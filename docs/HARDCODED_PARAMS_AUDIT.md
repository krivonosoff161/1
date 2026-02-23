# Аудит захардкоженных параметров

**Дата:** 2026-02-23  
**Цель:** Выявить параметры, которые должны быть адаптивными (per-symbol/per-regime/calculated), но сейчас захардкожены.

---

## Сводка по приоритетам

| Приоритет | Количество | Влияние на P&L | Критичность |
|-----------|------------|----------------|-------------|
| **P0** | 12 | Прямое | Риск ликвидации, неверный размер позиции |
| **P1** | 28 | Косвенное | Потеря прибыли, ложные входы/выходы |
| **P2** | 45+ | Техдолг | Сложность поддержки, негибкость |

---

## P0: Критические (влияют на P&L напрямую)

### 1. Расчёт маржи — HARDCODED вместо config ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-1 | `risk_manager.py` | 336-344 | `base_percent` (margin allocation) | small: 15%, medium: 20%, large: 25% | **Config-only** |

**Почему критично:** `calculate_max_margin_per_position()` использует ХАРДКОДИРОВАННЫЕ проценты вместо значений из конфига. Config игнорируется!

**Текущий эффект:** При балансе $1000 выделяется $150 маржи независимо от конфига.

---

### 2. Leverage map — полностью hardcoded ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-2 | `adaptive_leverage.py` | 33-39 | `leverage_map` | very_weak: 3x, weak: 5x, medium: 10x, strong: 20x, very_strong: 30x | **Config-driven** |

**Почему критично:** 30x плечо при very_strong сигнале — риск ликвидации. Нет возможности ограничить через конфиг.

---

### 3. Daily loss limit — fallback hardcoded ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-3 | `risk_manager.py` | 92-94 | `max_daily_loss_percent` | 5.0% (fallback) | **Config-only** |

**Почему критично:** Если конфиг не загрузится, риск-менеджер позволит потерять 5% в день вместо остановки.

---

### 4. Liquidation buffer — hardcoded ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-4 | `liquidation_protector.py` | 44 | `safety_threshold` | 0.5 (50%) | **Config-driven** |

**Почему критично:** 50% буфер до ликвидации — последняя линия защиты. Должен быть настраиваемым.

---

### 5. TSL class defaults — mismatch с config ⚠️
| ID | Файл | Строка | Параметр | Класс default | Config value |
|----|------|--------|----------|---------------|--------------|
| P0-5 | `trailing_stop_loss.py` | 36-38 | `initial_trail` / `max_trail` / `min_trail` | 5% / 20% / 2% | 2.5% / 5% / 1% |

**Почему критично:** Если config не загрузится, TSL использует 20% max_trail вместо 5% — катастрофический риск.

---

### 6. Breakeven trigger — global для всех пар ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-6 | `config_futures.yaml` | 1752 | `breakeven_trigger` | 0.008 (0.8%) | **Per-symbol** |
| P0-7 | `trailing_sl_coordinator.py` | 945, 949 | `min_profit_to_activate` | 0.008 (0.8%) | **Per-symbol** |

**Почему критично:** BTC и DOGE имеют разную волатильность, но одинаковый порог безубытка.

---

### 7. Min holding bypass multiplier — hardcoded ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-8 | `exit_analyzer.py` | 1243, 1251 | `bypass_mult` | 1.2 (120%) | **Config-driven** |

**Почему критично:** Множитель для обхода min_holding при большом убытке. Влияет на защиту от проскальзывания.

---

### 8. TP extension 120% — hardcoded ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-9 | `exit_analyzer.py` | 3419 | `new_tp` extension | `tp_percent * 1.2` | **Configurable multiplier** |

**Почему критично:** Расширение TP на 20% при сильном тренде — должно быть настраиваемым.

---

### 9. Loss cut hold delay — hardcoded ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-10 | `trailing_stop_loss.py` | 879 | `min_loss_cut_hold_seconds` | 90.0 seconds | **Config-driven** |

**Почему критично:** 90-секундная задержка перед loss_cut — позиция может накопить большие потери.

---

### 10. Magic price fallbacks — MUST REMOVE ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-11 | `order_executor.py` | 2860-2865 | Fallback prices | BTC: $110000, ETH: $3900 | **REMOVE** — fetch real data or fail |

**Почему критично:** Хардкод цен — если API недоступен, используются устаревшие цены.

---

### 11. DCA trending profit threshold — hardcoded (L3-4) ⚠️
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P0-12 | `position_scaling_manager.py` | 305-306 | `TRENDING_MIN_PROFIT_FOR_ADDITION` | 1.5% | **Config per regime** |

**Почему критично:** Фиксированный порог прибыли для DCA в trending — должен зависеть от символа.

---

## P1: Важные (влияют на эффективность)

### Режим рынка (Regime Detection)
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P1-1 | `regime_manager.py` | 116-117 | `trending_adx_threshold` | 25.0 | Config per symbol |
| P1-2 | `regime_manager.py` | 119-120 | `ranging_adx_threshold` | 20.0 | Config per symbol |
| P1-3 | `regime_manager.py` | 122 | `high_volatility_threshold` | 0.05 (5%) | Config per symbol |
| P1-4 | `regime_manager.py` | 123 | `low_volatility_threshold` | 0.02 (2%) | Config per symbol |
| P1-5 | `regime_manager.py` | 124 | `trend_strength_percent` | 2.0% | Config per regime |
| P1-6 | `regime_manager.py` | 126 | `min_regime_duration_minutes` | 15 | Config per symbol |
| P1-7 | `regime_manager.py` | 127 | `required_confirmations` | 3 | Config per symbol |

### ADX Blocking Thresholds
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P1-8 | `signal_generator.py` | 3705 | ADX blocking (trending) | 20.0 | Config per symbol |
| P1-9 | `signal_generator.py` | 3707 | ADX blocking (ranging) | 25.0 | Config per symbol |
| P1-10 | `signal_generator.py` | 3710 | ADX blocking (choppy) | 35.0 | Config per symbol |

### Cooldown Periods
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P1-11 | `signal_coordinator.py` | 158 | Same-side cooldown | 12.0 sec | Config per symbol |
| P1-12 | `signal_coordinator.py` | 162 | Loss cooldown | 45.0 sec | Config per symbol |
| P1-13 | `signal_coordinator.py` | 185 | Opposite-side cooldown | 0.0 sec | Config per symbol |
| P1-14 | `regime_manager.py` | 143/158/173 | Cooldown by regime | 3/5/8 min | Config per regime |

### Conflict Penalties
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P1-15 | `signal_generator.py` | 2093 | Conflict penalty | 0.8 (-20%) | Config per regime |
| P1-16 | `rsi_signal_generator.py` | 217 | RSI conflict multiplier | 0.5 | Config per regime |
| P1-17 | `macd_signal_generator.py` | 243 | MACD conflict multiplier | 0.5 | Config per regime |

### Min Signal Strength
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P1-18 | `signal_generator.py` | 2030 | Choppy min strength | 0.15 | Config per regime |
| P1-19 | `signal_generator.py` | 4573 | RSI divergence (trending) | 0.12 | Config per regime |
| P1-20 | `signal_generator.py` | 4630 | RSI divergence (others) | 0.15 | Config per regime |

### Indicator Periods
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P1-21 | `signal_generator.py` | 133-134 | EMA periods | 12 / 26 | Config per symbol |
| P1-22 | `signal_generator.py` | 993-994 | MTF EMA periods | 8 / 21 | Config per symbol |
| P1-23 | `signal_generator.py` | 123 | RSI period | 14 | Config per symbol |
| P1-24 | `signal_generator.py` | 128-130 | MACD periods | 12 / 26 / 9 | Config per symbol |
| P1-25 | `signal_generator.py` | 126 | ATR period | 14 | Config per symbol |

### Score Thresholds
| ID | Файл | Строка | Параметр | Текущее значение | Должно быть |
|----|------|--------|----------|------------------|-------------|
| P1-26 | `regime_manager.py` | 137 | Trending min score | 3.0 | Config per regime |
| P1-27 | `regime_manager.py` | 152 | Ranging min score | 2.2 | Config per regime |
| P1-28 | `regime_manager.py` | 167 | Choppy min score | 5.0 | Config per regime |

---

## P2: Техдолг (рекомендуется сделать configurable)

### Order Executor — многочисленные thresholds
| ID | Файл | Строка | Параметр | Текущее значение |
|----|------|--------|----------|------------------|
| P2-1 | `order_executor.py` | 299 | Price delta for market order | 1.0% |
| P2-2 | `order_executor.py` | 307 | Price delta for reduced offset | 0.5% |
| P2-3 | `order_executor.py` | 344 | Signal age threshold | 10.0 sec |
| P2-4 | `order_executor.py` | 942-969 | Volatility buckets | <0.1%, <0.3%, >0.7% |
| P2-5 | `order_executor.py` | 1688 | Price divergence protection | 1.5% |

### Trailing Stop — timing parameters
| ID | Файл | Строка | Параметр | Текущее значение |
|----|------|--------|----------|------------------|
| P2-6 | `trailing_stop_loss.py` | 63-64 | Loss cut confirmation | 2 confirmations, 5 sec window |
| P2-7 | `trailing_stop_loss.py` | 626, 672 | Commission ignore period | 10.0 seconds |
| P2-8 | `trailing_stop_loss.py` | 815 | Min critical hold | 60.0 seconds |
| P2-9 | `trailing_stop_loss.py` | 963 | Min profit for timeout | 0.5% |

### Filters — various thresholds
| ID | Файл | Строка | Параметр | Текущее значение |
|----|------|--------|----------|------------------|
| P2-10 | `momentum_filter.py` | 34 | Max spike percent | 1.0% |
| P2-11 | `momentum_filter.py` | 39 | Max price velocity | 0.5% |
| P2-12 | `momentum_filter.py` | 170 | Coefficient of variation | 0.5 |
| P2-13 | `correlation_filter.py` | 1133 | Correlation threshold | 0.7 |
| P2-14 | `correlation_filter.py` | 1138 | Max correlated positions | 2 |

### Cache TTLs
| ID | Файл | Строка | Параметр | Текущее значение |
|----|------|--------|----------|------------------|
| P2-15 | `signal_generator.py` | 297 | Signal cache cooldown | 60 sec |
| P2-16 | `signal_generator.py` | 313 | REST update cooldown | 1.0 sec |
| P2-17 | `regime_manager.py` | 218 | Regime cache TTL | 5 sec |
| P2-18 | `parameter_provider.py` | 55 | Parameter cache TTL | 300 sec |

---

## Уже адаптивно (не включать в отчёт)

| Компонент | Статус | Примечание |
|-----------|--------|------------|
| `exit_params` (TP/SL) | ✅ | Через ParameterProvider, per-symbol |
| `symbol_profiles` | ✅ | Полностью конфигурируемые |
| `balance_profiles` | ✅ | Читаются из config (но есть hardcoded fallback) |
| `regime_params` | ✅ | Через ParameterProvider |
| `trailing_sl` (основные) | ✅ | В config, но class defaults опасны |

---

## Рекомендации по исправлению

### Немедленно (P0)
1. **P0-1** — Исправить `calculate_max_margin_per_position()` для чтения из конфига
2. **P0-2** — Перенести leverage_map в config
3. **P0-5** — Убрать class defaults в TrailingStopLoss или сделать их равными config
4. **P0-11** — Удалить magic price fallbacks

### Краткосрочно (P1)
1. Добавить per-symbol ADX thresholds в config (L5-1 уже частично реализован)
2. Сделать cooldown periods конфигурируемыми
3. Перенести conflict penalties в config

### Долгосрочно (P2)
1. Централизовать все indicator periods в config
2. Сделать все cache TTLs конфигурируемыми
3. Добавить валидацию: warning при использовании fallback значений

---

## Статистика

| Категория | Найдено | Уже адаптивно | Требует фикса |
|-----------|---------|---------------|---------------|
| P0 (Критические) | 12 | 0 | 12 |
| P1 (Важные) | 28 | 5 | 23 |
| P2 (Техдолг) | 45+ | 15+ | 30+ |
| **Итого** | **85+** | **20+** | **65+** |
