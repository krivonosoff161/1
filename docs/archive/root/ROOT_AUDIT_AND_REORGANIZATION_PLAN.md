# 📋 АУДИТ И ПЛАН РЕОРГАНИЗАЦИИ КОРНЯ ПРОЕКТА

**Дата:** 2025-12-20  
**Цель:** Организовать файлы в корне проекта, переместить MD файлы в архив

---

## 📊 ТЕКУЩАЯ СИТУАЦИЯ

В корне проекта находится **~60 MD файлов**, которые нужно организовать.

---

## ✅ ФАЙЛЫ, КОТОРЫЕ ДОЛЖНЫ ОСТАТЬСЯ В КОРНЕ

### 📖 Инструкции и документация (3 файла)
- ✅ `README.md` - основная инструкция проекта
- ✅ `TECHNICAL_SPECIFICATION.md` - техническая спецификация (если актуальна)
- ✅ `ПОЛНОЕ_ОПИСАНИЕ_ТОРГОВОГО_БОТА.md` - полное описание бота на русском

### 🚀 Скрипты запуска (.bat файлы)
- ✅ `start.bat` - запуск бота
- ✅ `stop_bot.bat` - остановка бота
- ✅ `stop_all.bat` - остановка всех процессов
- ✅ `view_logs.bat` - просмотр логов
- ✅ `debug_console.bat` - отладочная консоль
- ✅ `analyze_logs.bat` - анализ логов
- ✅ `analyze_exit_decisions.bat` - анализ решений о выходе
- ✅ `clean_logs.bat` - очистка логов
- ✅ `clear_cache.bat` - очистка кэша
- ✅ `validate_configs.bat` - проверка конфигов
- ✅ `cleanup_md_files.bat` - очистка MD файлов (можно удалить после реорганизации)
- ✅ `restructure_project.bat` - реструктуризация проекта (можно удалить после реорганизации)

### ⚙️ Конфигурация
- ✅ `config.yaml` - основной конфиг
- ✅ `env.example` - пример переменных окружения
- ✅ `env.hybrid.example` - пример гибридных переменных окружения

### 🐍 Python файлы
- ✅ `run.py` - главный файл запуска бота
- ✅ `requirements.txt` - зависимости Python

### 📁 Папки (остаются как есть)
- ✅ `src/` - исходный код
- ✅ `config/` - конфигурации
- ✅ `scripts/` - скрипты
- ✅ `scripts_bat/` - bat скрипты
- ✅ `docs/` - документация
- ✅ `tests/` - тесты
- ✅ `data/` - данные
- ✅ `logs/` - логи
- ✅ `temp/` - временные файлы
- ✅ `backups/` - резервные копии
- ✅ `reports/` - отчеты
- ✅ `venv/` - виртуальное окружение

---

## 📦 ФАЙЛЫ, КОТОРЫЕ НУЖНО ПЕРЕМЕСТИТЬ

### 📂 Структура архива в `docs/archive/root/`

```
docs/archive/root/
├── analysis/           # Анализы и исследования
├── fixes/              # Отчеты об исправлениях
├── audits/             # Аудиты системы
├── reports/            # Отчеты о работе
├── plans/              # Планы развития
├── summaries/          # Сводки и итоги
└── misc/               # Прочее
```

---

## 📝 ДЕТАЛЬНЫЙ ПЛАН ПЕРЕМЕЩЕНИЯ

### 📊 ANALYSIS (Анализы) → `docs/archive/root/analysis/`

**Все файлы с префиксом `ANALYSIS_*` и `*_ANALYSIS`:**
1. `ANALYSIS_CLOSING_PRICE.md`
2. `ANALYSIS_DATA_FOR_KIMI.md`
3. `ANALYSIS_EXITANALYZER_PARAMETERS.md`
4. `ANALYSIS_LIMIT_ORDER_PRICE_PROBLEM.md`
5. `ANALYSIS_NEGATIVE_CLOSES_END_SESSION.md`
6. `ANALYSIS_REPORT_2025-12-08.md`
7. `ANALYSIS_SIGNATURES_INTERPRETATIONS.md`
8. `ANALYSIS_SMALL_PROFIT_EARLY_EXIT.md`
9. `ANALYSIS_STAGE2_FOR_KIMI.md`
10. `ANALYSIS_STRATEGY_PLACEMENT_CLOSING.md`
11. `ANALYSIS_TIMEOUT_VS_EXITANALYZER.md`
12. `COMPREHENSIVE_ANALYSIS_BROKER_MATH.md`
13. `COMPREHENSIVE_ARCHIVE_ANALYSIS.md`
14. `COMPREHENSIVE_BOT_ANALYSIS.md`
15. `FINAL_COMPREHENSIVE_ANALYSIS.md`
16. `PEAK_PROFIT_USD_ANALYSIS.md`
17. `SCALPING_STRATEGIES_ANALYSIS.md`
18. `TRADING_EXPERT_ANALYSIS.md`
19. `TRENDS_METRICS_ECONOMY_2025-12-08.md`

**Итого: 19 файлов**

---

### 🔧 FIXES (Исправления) → `docs/archive/root/fixes/`

**Все файлы с префиксом `FIXES_*`, `*_FIXES`, `SUMMARY_*_FIX`:**
1. `ALL_FIXES_COMPLETED_REPORT.md`
2. `FIXES_2025-12-18.md`
3. `FIXES_SMALL_PROFIT_EARLY_EXIT.md`
4. `FIXES_STRATEGY_OPTIMIZATION.md`
5. `SUMMARY_CLOSING_FIXES_APPLIED.md`
6. `SUMMARY_EXITANALYZER_FIXES.md`
7. `SUMMARY_FIXES_APPLIED.md`
8. `SUMMARY_FIXES_INDENTATION.md`
9. `SUMMARY_NEGATIVE_CLOSES_FIX.md`
10. `SUMMARY_SIGNAL_PRICE_FIX.md`
11. `SUMMARY_SYNTAX_FIXES.md`
12. `SUMMARY_TRAILING_STOP_LOSS_FIX.md`
13. `CORRECTION_SELL_LOGIC.md`
14. `SOLUTION_SIGNAL_PRICE_FROM_ORDERBOOK.md`

**Итого: 14 файлов**

---

### 🔍 AUDITS (Аудиты) → `docs/archive/root/audits/`

**Все файлы с префиксом `AUDIT_*`, `*_AUDIT`:**
1. `AUDIT_BUNDLE_TASK_v1.3.md`
2. `AUDIT_SUMMARY_2025-12-08.md`
3. `FULL_AUDIT_REPORT_2025-12-08.md`
4. `PROJECT_ROOT_AUDIT_REPORT.md`
5. `DETAILED_MARKPX_ANALYSIS_2025-12-08.md`
6. `UNINITIALIZED_MODULES_REPORT.md`
7. `VERIFICATION_REPORT.md` (можно в reports, но это проверка после аудита)

**Итого: 7 файлов**

---

### 📄 REPORTS (Отчеты) → `docs/archive/root/reports/`

**Все файлы с префиксом `*_REPORT`, `*_SUMMARY`, итоговые отчеты:**
1. `ALL_ERRORS_SUMMARY.md`
2. `FINAL_AUDIT_DATA_FOR_KIMI.md`
3. `FINAL_EXITANALYZER_ANALYSIS.md`
4. `FINAL_INTEGRATION_REPORT.md`
5. `FINAL_MASTER_PLAN.md`
6. `FINAL_SOLUTIONS_PLAN.md`
7. `FINAL_SUMMARY_ALL_FIXES.md`
8. `LOG_CHECK_2025-12-18_23-00.md`
9. `REFACTORING_COMPLETE_REPORT.md`
10. `REORGANIZATION_COMPLETED.md`
11. `SUMMARY_CLOSING_PRICE_ANALYSIS.md`
12. `SUMMARY_EXITANALYZER_CHECK.md`
13. `PARAMETERS_UPDATE_SUMMARY.md`

**Итого: 13 файлов**

---

### 📋 PLANS (Планы) → `docs/archive/root/plans/`

**Все файлы с префиксом `*_PLAN`, `TODO_*`, `MASTER_*`:**
1. `MASTER_PLAN_FIXES.md`
2. `MASTER_TODO_ALL_PROBLEMS.md`
3. `TODO_MASTER_PLAN.md`
4. `QUESTIONS_AND_PLAN.md`
5. `RECOMMENDATION_TIMEOUT_REMOVAL.md`

**Итого: 5 файлов**

---

### 📌 MISC (Прочее) → `docs/archive/root/misc/`

**Остальные файлы:**
1. `SIGNAL_EXECUTION_BLOCKING_ANALYSIS.md` (можно в analysis, но специфичный)
2. `archive_analysis_output.txt` (текстовый файл)
3. `backtest_data_2025-12-17.json` (данные бэктеста)
4. `backtest_vs_reality_comparison.json` (сравнение)
5. `improved_backtest_results.json` (результаты)
6. `FINAL_CORRECTIONS_2025-12-08.json` (корректировки)
7. `signals_sample_50.csv` (примеры сигналов)
8. `tatus` (неизвестный файл, вероятно временный - можно удалить или в misc)
9. `tatus --short` (неизвестный файл, вероятно временный - можно удалить или в misc)

**Итого: 9 файлов**

**⚠️ Внимание:** Файлы `tatus` и `tatus --short` выглядят как временные или ошибочные. Рекомендуется проверить их содержимое и при необходимости удалить.

---

### 🐍 PYTHON СКРИПТЫ АНАЛИЗА → `scripts/analysis/root_scripts/`

**Python файлы анализа, которые лежат в корне:**
1. `analyze_archived_logs.py` → `scripts/analysis/root_scripts/`
2. `analyze_backtest_vs_reality.py` → `scripts/analysis/root_scripts/`
3. `analyze_position_closing_logic.py` → `scripts/analysis/root_scripts/`
4. `manual_log_analysis.py` → `scripts/analysis/root_scripts/`
5. `quick_analyze.py` → `scripts/analysis/root_scripts/`
6. `temp_analyze_today.py` → `scripts/analysis/root_scripts/` или `temp/`
7. `improved_backtest.py` → `scripts/analysis/root_scripts/`
8. `export_backtest_data.py` → `scripts/analysis/root_scripts/`

**Итого: 8 файлов**

---

## 📊 ИТОГОВАЯ СТАТИСТИКА

### В корне останется:
- **MD файлы:** 3 (README.md, TECHNICAL_SPECIFICATION.md, ПОЛНОЕ_ОПИСАНИЕ_ТОРГОВОГО_БОТА.md)
- **BAT файлы:** 12 (все скрипты запуска и утилиты)
- **Конфиги:** 3 (config.yaml, env.example, env.hybrid.example)
- **Python файлы:** 2 (run.py, requirements.txt)
- **Папки:** 13 (как есть)

### Будет перемещено:
- **MD файлы:** ~58 файлов
- **Python скрипты анализа:** 8 файлов
- **Данные JSON/CSV/TXT:** 9 файлов

**Всего перемещается:** ~75 файлов

---

## 🔨 ПЛАН ДЕЙСТВИЙ

### Шаг 1: Создать структуру папок
```bash
mkdir -p docs/archive/root/analysis
mkdir -p docs/archive/root/fixes
mkdir -p docs/archive/root/audits
mkdir -p docs/archive/root/reports
mkdir -p docs/archive/root/plans
mkdir -p docs/archive/root/misc
mkdir -p scripts/analysis/root_scripts
```

### Шаг 2: Переместить файлы по категориям
- Использовать PowerShell скрипт или батник для перемещения

### Шаг 3: Проверить результат
- Убедиться, что все файлы перемещены
- Проверить, что бот запускается
- Обновить ссылки в документации (если есть)

---

## ⚠️ ВАЖНЫЕ ЗАМЕЧАНИЯ

1. **Не перемещать активные файлы** - если файл используется в работе, оставить в корне
2. **Проверить зависимости** - некоторые Python скрипты могут ссылаться на файлы в корне
3. **Сохранить историю** - все файлы перемещаются, не удаляются
4. **Создать README в архиве** - описать структуру архива

---

## 📝 ПРИМЕЧАНИЯ ПО СПЕЦИФИЧЕСКИМ ФАЙЛАМ

- `VERIFICATION_REPORT.md` - недавний отчет проверки, можно оставить в корне или переместить в `docs/reports/`
- `TECHNICAL_SPECIFICATION.md` - если актуален, оставить, если устарел - в архив
- `tatus` и `tatus --short` - проверить что это за файлы, возможно удалить

---

**Следующий шаг:** Создать скрипт для автоматического перемещения файлов

