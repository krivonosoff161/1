# ТЗ для Cursor: Сбор и структурирование данных для аудита кода и торговой стратегии  
**Версия:** 1.3  
**Дата:** 2025-12-08  
**Назначение:** Инструкция для Cursor по сбору данных для внешнего аналитика (Kimi)

---

## 1. Цель
Сформировать унифицированный «пакет данных» (далее – **Пакет**) для:
- аудита качества кода (data quality audit);
- аудита логики торговой стратегии (strategy logic audit);
- расчёта метрик до/после-ковки (pre/post-burn analysis);
- выявления потенциальных утечек/оверфиттинга.

---

## 2. Общие правила сбора
### 2.1. Запрашивать файлы строго в порядке, указанном в разделе 3
### 2.2. После получения каждого файла:
1. Проверять наличие обязательных колонок (см. раздел 4);
2. Фиксировать метаданные: shape, date_modified, md5_hash (после редактирования секретов), file_size_bytes;
3. Записывать краткий словарь: название, тип, единицы, частота, описание;
4. Проверка блокировки файла: при PermissionError просить сделать копию;
5. Обработка Parquet: если путь указывает на директорию – использовать pyarrow.dataset;
6. Если обязательная колонка отсутствует → записать в integrity_errors.json и спросить у пользователя.

---

## 3. Последовательность запроса файлов
| № | Файл | Что вытащить |
|---|------|--------------|
| 1 | config/config_futures.yaml | entry_exit_params, filters, limits, leverage, commission, slippage, rebalancing_mode |
| 2 | src/strategies/scalping/futures/*.py | data_structures, constants, random_sources, forward-looking patterns |
| 3 | logs/trades_YYYY-MM-DD.csv | trade_id, timestamp, symbol, side, entry/exit, size, gross/net PnL, commission, duration, reason |
| 4 | market_data_YYYY-MM-DD.csv | timestamp, symbol, open, high, low, close, volume, bid, ask, quote_currency |
| 5 | logs/positions_open_YYYY-MM-DD.csv | timestamp, symbol, side, entry_price, size, leverage, margin, regime, order_id, order_type |
| 6 | logs/orders_YYYY-MM-DD.csv | order_id, timestamp, symbol, side, order_type, size, price, status, fill_price, fill_size, execution_time_ms, slippage, slippage_units, time_in_force, trigger_price, maker_taker |
| 7 | Экзогенные данные (если есть) | funding.csv, borrow_rates.csv, options_chain.csv, economic_calendar.csv |
| 8 | burn_params.json | optimization_method, metric, iterations, seed, parameter_ranges, train/validation periods |
| 9 | burn_results.csv | iteration, params_json, train/val sharpe, max_dd, pnl, sortino, calmar, profit_factor |
|10 | performance_report.yaml | sharpe, sortino, calmar, cagr, max_dd, win_rate, profit_factor, total_trades, total_pnl, commission |

---

## 4. Проверки целостности (обязательные)
- Дубликаты: trade_id, (timestamp, symbol, side), (order_id, fill_id)
- Отсутствие NaN/None в обязательных полях
- Монотонность timestamp
- Корректность знаков qty (long &gt; 0, short &lt; 0)
- Корректность цен (high ≥ max(open, close), bid ≤ ask, exit_price логичен по side)
- Zero-byte файлы → status "missing", не ошибка
- DST переходы 02:00-03:00 UTC → warning, не ошибка
- Unclosed candles OKX → skipping, не ошибка

---

## 5. Дополнительные технические проверки (раздел 7.0)
| Подпункт | Что проверить |
|----------|---------------|
| 7.0.1 | Contract Multiplier (ctVal, ctMult, quoteCcy, lotSz, tickSz) из instruments.csv |
| 7.0.2 | Leverage в positions.csv (margin = size × ctVal × price / leverage) |
| 7.0.3 | Slippage Units (abs/pct) и знак ≥ 0 |
| 7.0.4 | Forward-looking regex-паттерны (df.shift(-1), iloc[i+1], loc[t+Timedelta]) |
| 7.0.5 | Secrets Redaction (api_key, secret, passphrase → "***REDACTED***" перед MD5) |
| 7.0.6 | DST Transition (дубликаты 02:00-03:00 UTC в марте/октябре → warning) |
| 7.0.7 | File Lock (PermissionError → просить копию файла) |
| 7.0.8 | Parquet с partition columns (использовать pyarrow.dataset) |
| 7.0.9 | Partial Fill → несколько строк с (order_id, fill_id), avg_fill_price ±1 тик |
| 7.0.10 | OKX "касание" последней свечи (разница 1 с → не дубль) |
| 7.0.11 | Funding Fee Sign (long + rate &gt; 0 → fee &gt; 0; spot → not applicable) |
| 7.0.12 | Time In Force (GTD → обязательно expire_time) |
| 7.0.13 | Commission OKX VIP (maker/taker по fee_level) |
| 7.0.14 | Lot Multiplier (size % lot_multiplier == 0) |
| 7.0.15 | Quote Currency (SOL-USDC, ETH-BTC → проверка соответствия) |
| 7.0.16 | Кодировка файлов (utf-8-sig → utf-8 → cp1251 → koi8-r) |
| 7.0.17 | Rollover контрактов (contract_id с датой экспирации) |
| 7.0.18 | Cross-margin (флаг cross_margin, margin может быть &gt; balance) |
| 7.0.19 | Position Mode (hedge vs netting → одновременные long/short) |
| 7.0.20 | Trigger Price (для stop_market/stop_limit обязателен) |

---

## 6. Финальная структура JSON
См. полную схему в исходном файле (раздел 6 остаётся без изменений).

---

## 7. Промт для Cursor (после перезапуска)
