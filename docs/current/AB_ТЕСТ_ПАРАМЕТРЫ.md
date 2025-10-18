# 🧪 A/B ТЕСТ ПАРАМЕТРОВ TP/SL

> **Дата**: 18 октября 2025  
> **Цель**: Найти оптимальные TP/SL для максимальной прибыли  
> **Метод**: 3 варианта по 8 часов каждый

---

## 📊 ПЛАН ТЕСТИРОВАНИЯ

### График:

| День | Время | Вариант | TP mult | SL mult | Max Hold |
|------|-------|---------|---------|---------|----------|
| 10 | 00:00-08:00 | A (текущий) | 1.25 | 1.0 | 10 мин |
| 10 | 08:00-16:00 | B (ближе) | 0.8 | 0.9 | 8 мин |
| 10 | 16:00-24:00 | C (скальп) | 0.5 | 0.6 | 5 мин |
| 11 | Анализ | - | - | - | - |

---

## 🔧 ВАРИАНТ A: ТЕКУЩИЙ (BASELINE)

### Параметры:
```yaml
# config.yaml - adaptive_regime.ranging:
ranging:
  tp_atr_multiplier: 1.25    # ~$25 TP
  sl_atr_multiplier: 1.0     # ~$20 SL
  max_holding_minutes: 10    # 10 минут
```

### Ожидания:
- TP далеко → меньше срабатываний
- SL близко → больше стопов
- Win Rate: 40-50%
- Avg Duration: 8-10 минут

### Запуск:
```bash
# Убедись что эти параметры в config.yaml
# Запуск:
start_bot.bat

# Мониторинг:
view_logs.bat

# Через 8 часов:
stop_bot.bat
```

### Сохранение результатов:
```bash
# Переименуй CSV:
mv logs\trades_2025-10-18.csv logs\trades_variant_a.csv
```

---

## 🔧 ВАРИАНТ B: БЛИЖЕ TP/SL

### Параметры:
```yaml
# config.yaml - adaptive_regime.ranging:
ranging:
  tp_atr_multiplier: 0.8     # ~$16 TP
  sl_atr_multiplier: 0.9     # ~$18 SL
  max_holding_minutes: 8     # 8 минут
```

### Ожидания:
- TP ближе → больше срабатываний
- SL ближе → больше стопов, но меньше потери
- Win Rate: 45-55%
- Avg Duration: 5-8 минут

### Запуск:
```bash
# 1. Измени config.yaml (параметры выше)
# 2. Очисти кэш:
rm -rf data/cache/*

# 3. Запуск:
start_bot.bat

# Через 8 часов:
stop_bot.bat
```

### Сохранение результатов:
```bash
mv logs\trades_2025-10-18.csv logs\trades_variant_b.csv
```

---

## 🔧 ВАРИАНТ C: СКАЛЬПИНГ

### Параметры:
```yaml
# config.yaml - adaptive_regime.ranging:
ranging:
  tp_atr_multiplier: 0.5     # ~$10 TP
  sl_atr_multiplier: 0.6     # ~$12 SL
  max_holding_minutes: 5     # 5 минут
```

### Ожидания:
- TP очень близко → много срабатываний
- SL близко → много стопов
- Win Rate: 50-60% (нужен точный вход!)
- Avg Duration: 2-5 минут
- Больше сделок!

### Запуск:
```bash
# 1. Измени config.yaml
# 2. Очисти кэш:
rm -rf data/cache/*

# 3. Запуск:
start_bot.bat

# Через 8 часов:
stop_bot.bat
```

### Сохранение результатов:
```bash
mv logs\trades_2025-10-18.csv logs\trades_variant_c.csv
```

---

## 📊 АНАЛИЗ РЕЗУЛЬТАТОВ

### После всех 3 вариантов:

```bash
# Анализ каждого:
python scripts/analyze_trades.py logs/trades_variant_a.csv
python scripts/analyze_trades.py logs/trades_variant_b.csv
python scripts/analyze_trades.py logs/trades_variant_c.csv

# Сравнение:
python scripts/analyze_trades.py --compare ^
  logs/trades_variant_a.csv ^
  logs/trades_variant_b.csv ^
  logs/trades_variant_c.csv
```

### Таблица сравнения:

```
| Вариант | Trades | Win Rate | Total PnL | Avg Trade | Avg Time |
|---------|--------|----------|-----------|-----------|----------|
| A       | 45     | 44.4%    | $12.35    | $0.27     | 8.5 min  |
| B       | 67     | 52.2%    | $28.90    | $0.43     | 6.2 min  |
| C       | 112    | 58.9%    | $45.67    | $0.41     | 3.1 min  |

🏆 ПОБЕДИТЕЛЬ: Вариант C (больше сделок, выше WR!)
```

### Критерии выбора:

**Если Win Rate важнее:**
- Выбираем вариант с максимальным WR

**Если PnL важнее:**
- Выбираем вариант с максимальным Total PnL

**Если баланс:**
- Выбираем вариант с лучшим соотношением WR × PnL

---

## ⚙️ БЫСТРОЕ ПЕРЕКЛЮЧЕНИЕ ПАРАМЕТРОВ

### Создай 3 конфига:

```bash
# Сохраняем текущий:
cp config.yaml config_variant_a.yaml

# После изменений для B:
cp config.yaml config_variant_b.yaml

# После изменений для C:
cp config.yaml config_variant_c.yaml
```

### Переключение:

```bash
# Вариант A:
cp config_variant_a.yaml config.yaml
rm -rf data/cache/*
start_bot.bat

# Вариант B:
cp config_variant_b.yaml config.yaml
rm -rf data/cache/*
start_bot.bat

# Вариант C:
cp config_variant_c.yaml config.yaml
rm -rf data/cache/*
start_bot.bat
```

---

## 🎯 ДОПОЛНИТЕЛЬНЫЕ ВАРИАНТЫ

### Если Вариант C показал отличные результаты:

**Вариант D: Экстрим скальп**
```yaml
ranging:
  tp_atr_multiplier: 0.3     # ~$6 TP
  sl_atr_multiplier: 0.4     # ~$8 SL
  max_holding_minutes: 3     # 3 минуты
  
# Profit Harvesting:
quick_profit_threshold: 2.0  # $2 (ниже!)
quick_profit_time_limit: 20  # 20 сек
```

**Вариант E: Микро-скальп**
```yaml
ranging:
  tp_atr_multiplier: 0.2     # ~$4 TP
  sl_atr_multiplier: 0.3     # ~$6 SL
  max_holding_minutes: 2     # 2 минуты
  
quick_profit_threshold: 1.5  # $1.5
quick_profit_time_limit: 15  # 15 сек
```

---

## 📋 ЧЕКЛИСТ A/B ТЕСТА

### Перед каждым вариантом:

- [ ] Изменить параметры в config.yaml
- [ ] Очистить кэш: `rm -rf data/cache/*`
- [ ] Запустить бота: `start_bot.bat`
- [ ] Записать время старта
- [ ] Мониторить первые 10 минут

### Во время теста (каждый час):

- [ ] Проверить логи на ошибки
- [ ] Проверить количество сделок
- [ ] Проверить Win Rate (в логах)
- [ ] Проверить нет ли зависаний

### После 8 часов:

- [ ] Остановить бота: `stop_bot.bat`
- [ ] Переименовать CSV: `mv logs/trades... logs/trades_variant_X.csv`
- [ ] Быстрый анализ: `python scripts/analyze_trades.py logs/trades_variant_X.csv`
- [ ] Записать результаты

### После всех вариантов:

- [ ] Полный анализ каждого
- [ ] Сравнение вариантов
- [ ] Выбор победителя
- [ ] Обновление config.yaml с лучшими параметрами

---

## 🎯 КРИТЕРИИ УСПЕХА

### Минимальные требования (чтобы продолжать):

- ✅ Win Rate > 45%
- ✅ Daily PnL > $5
- ✅ Avg trade > $0.10
- ✅ Нет критичных ошибок

### Хорошие результаты (production ready):

- ✅ Win Rate > 55%
- ✅ Daily PnL > $15
- ✅ Avg trade > $0.25
- ✅ Profit Harvesting работает

### Отличные результаты (масштабирование):

- ✅ Win Rate > 60%
- ✅ Daily PnL > $30
- ✅ Avg trade > $0.40
- ✅ Готов к увеличению частоты

---

## 📝 ШАБЛОН РЕЗУЛЬТАТОВ

### Вариант X:

**Параметры:**
- TP multiplier: X.XX
- SL multiplier: X.XX
- Max holding: X мин

**Результаты:**
- Trades: XXX
- Win Rate: XX.X%
- Total PnL: $XX.XX
- Avg Win: $X.XX
- Avg Loss: -$X.XX
- Avg Duration: XX.X мин
- Profit Harvesting: XX trades (XX%)

**Вывод:**
- ✅/⚠️/❌ [Оценка]
- Рекомендация: [...]

---

📂 **Файл**: `docs/current/AB_ТЕСТ_ПАРАМЕТРЫ.md`  
📊 **Статус**: Готов к использованию  
🎯 **День**: 10-11

**ГОТОВ К ТЕСТИРОВАНИЮ! 🧪**

