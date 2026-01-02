#!/usr/bin/env python3
"""
Скрипт для анализа движения цены после закрытия позиций.

Цель: Проверить гипотезу о преждевременном закрытии позиций - пошла ли цена 
дальше в сторону позиции после закрытия.

Использование:
    python scripts/analyze_price_after_close.py
"""

import asyncio
import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import aiohttp
from loguru import logger


class PriceMovementAnalyzer:
    """Анализатор движения цены после закрытия позиций"""

    def __init__(self, output_dir: Path = Path("docs/analysis/reports/2025-12")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = "https://www.okx.com/api/v5/market/candles"
        
    def parse_position_time(self, time_str: str) -> datetime:
        """
        Парсит время позиции из формата "HH:MM:SS" в datetime.
        
        Предполагает дату 30.12.2025 (из контекста анализа)
        """
        try:
            # Формат: "11:42:28" или "30.12.2025, 11:42:28"
            if "," in time_str:
                # Формат с датой
                date_part, time_part = time_str.split(",")
                time_str = time_part.strip()
            
            hour, minute, second = map(int, time_str.split(":"))
            # Дата из контекста анализа - 30.12.2025
            dt = datetime(2025, 12, 30, hour, minute, second, tzinfo=timezone.utc)
            return dt
        except Exception as e:
            logger.error(f"Ошибка парсинга времени '{time_str}': {e}")
            raise
    
    async def get_historical_candles(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str = "1m",
    ) -> List[Dict]:
        """
        Получает исторические свечи от OKX API.
        
        Args:
            symbol: Торговая пара (например "BTC-USDT")
            start_time: Время начала (UTC)
            end_time: Время окончания (UTC)
            timeframe: Таймфрейм свечей ("1m", "5m", etc.)
        
        Returns:
            Список свечей в формате [timestamp, open, high, low, close, volume]
        """
        try:
            # OKX требует instId в формате "BTC-USDT-SWAP" для futures
            inst_id = f"{symbol}-SWAP"
            
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ по документации OKX API:
            # - `after`: получить свечи, предшествующие указанному timestamp (более старые)
            # - `before`: получить свечи, следующие за указанным timestamp (более новые)
            # - Для исторических данных используем `after` с end_time
            # 
            # ВАЖНО: `before` для давних данных не работает - API возвращает последние свечи
            # Поэтому используем `after` с end_time для получения свечей ДО этого времени
            
            time_diff = end_time - start_time
            minutes_diff = int(time_diff.total_seconds() / 60)
            
            # Рассчитываем limit: нужное количество минут + запас
            # OKX максимум 300 свечей за запрос
            limit = min(300, minutes_diff + 30)
            
            # ✅ ИСПРАВЛЕНО: Используем `after` с end_time для исторических данных
            # `after` возвращает свечи, предшествующие указанному timestamp (более старые)
            after_timestamp_ms = int(end_time.timestamp() * 1000)
            
            url = self.base_url
            params = {
                "instId": inst_id,
                "bar": timeframe,
                "after": str(after_timestamp_ms),  # ✅ Получаем свечи ДО end_time (исторические)
                "limit": str(limit),
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # ✅ ДОБАВЛЕНО: Логируем ответ API для отладки
                        logger.debug(f"🔍 API ответ для {symbol}: code={data.get('code')}, msg={data.get('msg')}, data_len={len(data.get('data', []))}")
                        
                        if data.get("code") == "0":
                            if not data.get("data"):
                                logger.warning(
                                    f"⚠️ API вернул пустой массив для {symbol}. "
                                    f"Параметры: after={params.get('after')} ({datetime.fromtimestamp(int(params.get('after', 0))/1000, tz=timezone.utc)}), "
                                    f"limit={params.get('limit')}, запрошенный период: {start_time} - {end_time}"
                                )
                                return []
                            candles = data["data"]
                            
                            # ✅ ДОБАВЛЕНО: Логируем первые свечи для отладки
                            # ✅ ВАЖНО: OKX возвращает свечи в обратном порядке (от новых к старым)
                            # Поэтому первая свеча в массиве - самая новая, последняя - самая старая
                            if candles:
                                first_candle_ts = int(candles[0][0]) if candles else None
                                last_candle_ts = int(candles[-1][0]) if candles else None
                                logger.debug(
                                    f"🔍 Получено {len(candles)} свечей от API для {symbol}: "
                                    f"первая (новая) свеча={datetime.fromtimestamp(first_candle_ts/1000, tz=timezone.utc) if first_candle_ts else None}, "
                                    f"последняя (старая) свеча={datetime.fromtimestamp(last_candle_ts/1000, tz=timezone.utc) if last_candle_ts else None}, "
                                    f"запрошенный диапазон: {start_time} - {end_time}"
                                )
                            
                            # ✅ ИСПРАВЛЕНО: OKX возвращает свечи с timestamp начала минуты
                            # Например, свеча за 11:42:00 покрывает весь период 11:42:00-11:42:59
                            # Поэтому используем округление времени до начала минуты для фильтрации
                            filtered_candles = []
                            start_ts = int(start_time.timestamp() * 1000)
                            end_ts = int(end_time.timestamp() * 1000)
                            
                            # ✅ Округляем до начала минуты (для сравнения со свечами OKX)
                            start_minute_ts = (start_ts // 60000) * 60000  # Округляем до начала минуты
                            end_minute_ts = ((end_ts // 60000) + 1) * 60000  # Добавляем 1 минуту для включения последней
                            
                            logger.debug(
                                f"🔍 Фильтрация для {symbol}: start_ts={start_ts} ({start_time}), "
                                f"end_ts={end_ts} ({end_time}), start_minute={start_minute_ts}, "
                                f"end_minute={end_minute_ts}, всего свечей от API={len(candles)}"
                            )
                            
                            for candle in candles:
                                candle_ts = int(candle[0])
                                # ✅ Используем округленное время для сравнения (свечи имеют timestamp начала минуты)
                                if start_minute_ts <= candle_ts <= end_minute_ts:
                                    filtered_candles.append({
                                        "timestamp": candle_ts / 1000,  # Конвертируем в секунды
                                        "datetime": datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc),
                                        "open": float(candle[1]),
                                        "high": float(candle[2]),
                                        "low": float(candle[3]),
                                        "close": float(candle[4]),
                                        "volume": float(candle[5]),
                                    })
                            
                            # ✅ ИСПРАВЛЕНО: OKX возвращает свечи в обратном порядке (от новых к старым)
                            # Переворачиваем список, чтобы получить хронологический порядок (старые -> новые)
                            filtered_candles.reverse()
                            # Дополнительная сортировка для надежности
                            filtered_candles.sort(key=lambda x: x["timestamp"])
                            
                            if filtered_candles:
                                logger.info(
                                    f"✅ Получено {len(filtered_candles)} свечей для {symbol} "
                                    f"с {start_time} по {end_time}"
                                )
                            else:
                                # ✅ УЛУЧШЕНО: Показываем примеры timestamp свечей для отладки
                                if candles:
                                    sample_timestamps = [int(c[0]) for c in candles[:3]]
                                    sample_dates = [datetime.fromtimestamp(ts/1000, tz=timezone.utc) for ts in sample_timestamps]
                                    logger.warning(
                                        f"⚠️ Получено 0 свечей после фильтрации для {symbol}. "
                                        f"API вернул {len(candles)} свечей, но они не попадают в диапазон "
                                        f"[{start_time} ({start_ts}, округлено до {start_minute_ts}) - "
                                        f"{end_time} ({end_ts}, округлено до {end_minute_ts})]. "
                                        f"Примеры timestamp свечей от API: {sample_timestamps} "
                                        f"({sample_dates})"
                                    )
                                else:
                                    logger.warning(
                                        f"⚠️ API вернул 0 свечей для {symbol} "
                                        f"(параметры: after={after_timestamp_ms}, limit={limit})"
                                    )
                            return filtered_candles
                        else:
                            logger.warning(
                                f"⚠️ API вернул ошибку для {symbol}: code={data.get('code')}, "
                                f"msg={data.get('msg', 'Unknown')}"
                            )
                            return []
                    else:
                        response_text = await resp.text()
                        logger.warning(
                            f"⚠️ HTTP {resp.status} при получении свечей для {symbol}: {response_text[:200]}"
                        )
                        return []
        except Exception as e:
            logger.error(f"❌ Ошибка получения свечей для {symbol}: {e}", exc_info=True)
            return []
    
    def analyze_price_movement(
        self,
        position_side: str,
        entry_price: float,
        exit_price: float,
        candles_after: List[Dict],
        minutes_after: int = 15,
    ) -> Dict:
        """
        Анализирует движение цены после закрытия позиции.
        
        Args:
            position_side: Направление позиции ("LONG" или "SHORT")
            entry_price: Цена входа
            exit_price: Цена выхода
            candles_after: Свечи после закрытия позиции
            minutes_after: Количество минут для анализа (по умолчанию 15)
        
        Returns:
            Словарь с результатами анализа:
            {
                "price_continued_direction": bool,  # Продолжила ли цена идти в сторону позиции
                "price_reversed": bool,  # Развернулась ли цена в сторону позиции
                "max_profit_if_held": float,  # Максимальная прибыль, если бы держали
                "max_loss_if_held": float,  # Максимальный убыток, если бы держали
                "price_after_5min": float,  # Цена через 5 минут
                "price_after_10min": float,  # Цена через 10 минут
                "price_after_15min": float,  # Цена через 15 минут
                "premature_close": bool,  # Преждевременное закрытие (цена развернулась в нашу сторону)
                "wrong_direction": bool,  # Неправильное направление (цена продолжила против нас)
            }
        """
        if not candles_after:
            return {
                "price_continued_direction": None,
                "price_reversed": None,
                "max_profit_if_held": None,
                "max_loss_if_held": None,
                "price_after_5min": None,
                "price_after_10min": None,
                "price_after_15min": None,
                "premature_close": None,
                "wrong_direction": None,
                "error": "Нет данных о свечах",
            }
        
        # Берем первую свечу как базовую (время закрытия)
        first_candle = candles_after[0] if candles_after else None
        if not first_candle:
            return {"error": "Нет первой свечи"}
        
        close_price = exit_price  # Цена закрытия позиции
        
        # Рассчитываем PnL для каждой свечи (что было бы, если бы держали позицию)
        pnl_percentages = []
        prices = []
        
        for candle in candles_after:
            price = candle["close"]
            prices.append(price)
            
            if position_side.upper() == "LONG":
                pnl_pct = ((price - entry_price) / entry_price) * 100
            else:  # SHORT
                pnl_pct = ((entry_price - price) / entry_price) * 100
            
            pnl_percentages.append(pnl_pct)
        
        # Находим максимальную прибыль и убыток
        max_profit = max(pnl_percentages) if pnl_percentages else 0
        max_loss = min(pnl_percentages) if pnl_percentages else 0
        
        # Цены через определенное время
        price_after_5min = None
        price_after_10min = None
        price_after_15min = None
        
        first_candle_time = first_candle["datetime"]
        
        for candle in candles_after:
            candle_time = candle["datetime"]
            time_diff = (candle_time - first_candle_time).total_seconds() / 60
            
            if price_after_5min is None and time_diff >= 5:
                price_after_5min = candle["close"]
            if price_after_10min is None and time_diff >= 10:
                price_after_10min = candle["close"]
            if price_after_15min is None and time_diff >= 15:
                price_after_15min = candle["close"]
        
        # Анализ: продолжала ли цена идти в сторону позиции или развернулась
        # Для LONG: цена должна расти после закрытия (плохо - закрыли рано)
        # Для LONG: цена должна падать после закрытия (хорошо - правильно закрыли)
        
        if position_side.upper() == "LONG":
            # Цена продолжила идти в сторону позиции = цена выросла (плохо - преждевременное закрытие)
            price_continued_direction = prices[-1] > close_price if prices else False
            
            # Цена развернулась в нашу сторону = цена выросла после падения (плохо - преждевременное закрытие)
            # Проверяем: была ли цена ниже exit_price, а затем выросла выше
            min_price_after = min([c["low"] for c in candles_after]) if candles_after else close_price
            max_price_after = max([c["high"] for c in candles_after]) if candles_after else close_price
            
            # Если минимальная цена была ниже exit, а максимальная выше exit - был разворот
            price_reversed = min_price_after < close_price and max_price_after > close_price
            
            # Преждевременное закрытие: цена развернулась вверх после закрытия
            premature_close = max_price_after > close_price
            
            # Неправильное направление: цена продолжила падать после закрытия
            wrong_direction = prices[-1] < close_price if prices else False
            
        else:  # SHORT
            # Цена продолжила идти в сторону позиции = цена упала (плохо - преждевременное закрытие)
            price_continued_direction = prices[-1] < close_price if prices else False
            
            # Цена развернулась в нашу сторону = цена упала после роста (плохо - преждевременное закрытие)
            min_price_after = min([c["low"] for c in candles_after]) if candles_after else close_price
            max_price_after = max([c["high"] for c in candles_after]) if candles_after else close_price
            
            # Если максимальная цена была выше exit, а минимальная ниже exit - был разворот
            price_reversed = max_price_after > close_price and min_price_after < close_price
            
            # Преждевременное закрытие: цена развернулась вниз после закрытия
            premature_close = min_price_after < close_price
            
            # Неправильное направление: цена продолжила расти после закрытия
            wrong_direction = prices[-1] > close_price if prices else False
        
        return {
            "price_continued_direction": price_continued_direction,
            "price_reversed": price_reversed,
            "max_profit_if_held": max_profit,
            "max_loss_if_held": max_loss,
            "price_after_5min": price_after_5min,
            "price_after_10min": price_after_10min,
            "price_after_15min": price_after_15min,
            "premature_close": premature_close,
            "wrong_direction": wrong_direction,
            "prices": prices,
            "pnl_percentages": pnl_percentages,
        }
    
    def load_positions_from_report(self, report_file: Path) -> List[Dict]:
        """
        Загружает позиции из отчета в формате Markdown таблицы.
        
        Ожидаемый формат таблицы:
        | Пара | Время открытия | Направление | Entry | Exit | ... | Причина |
        """
        positions = []
        
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Ищем таблицу с позициями
            lines = content.split("\n")
            in_table = False
            header_found = False
            
            for line in lines:
                # Ищем начало таблицы
                if "| Пара |" in line or "| Пара | Время" in line:
                    in_table = True
                    header_found = True
                    continue
                
                # Пропускаем разделитель строки таблицы
                if in_table and line.strip().startswith("|---"):
                    continue
                
                # Обрабатываем строки таблицы
                if in_table and "|" in line and header_found:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    
                    if len(parts) >= 6:
                        try:
                            symbol = parts[0].replace("USDT", "-USDT")
                            time_str = parts[1]
                            side = parts[2]
                            entry = float(parts[3])
                            exit_price = float(parts[4])
                            
                            # Причина закрытия (может быть в разных колонках)
                            reason = parts[-1] if len(parts) > 6 else "unknown"
                            
                            positions.append({
                                "symbol": symbol,
                                "time": time_str,
                                "side": side,
                                "entry": entry,
                                "exit": exit_price,
                                "reason": reason,
                            })
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Ошибка парсинга строки таблицы: {line[:100]}... - {e}")
                            continue
                
                # Если встречаем следующий заголовок, выходим из таблицы
                if in_table and line.startswith("#") and header_found:
                    break
            
            logger.info(f"✅ Загружено {len(positions)} позиций из отчета")
            return positions
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки позиций из отчета: {e}", exc_info=True)
            return []
    
    async def analyze_all_positions(
        self,
        positions: List[Dict],
        minutes_after: int = 15,
    ) -> List[Dict]:
        """
        Анализирует все позиции.
        
        Args:
            positions: Список позиций для анализа
            minutes_after: Количество минут после закрытия для анализа
        
        Returns:
            Список результатов анализа для каждой позиции
        """
        results = []
        
        for i, pos in enumerate(positions, 1):
            logger.info(
                f"📊 Анализ позиции {i}/{len(positions)}: {pos['symbol']} {pos['side']} "
                f"в {pos['time']}"
            )
            
            try:
                # Парсим время закрытия
                close_time = self.parse_position_time(pos["time"])
                
                # ✅ ДОБАВЛЕНО: Логируем распарсенное время для отладки
                logger.debug(
                    f"🔍 Позиция {i}/{len(positions)}: {pos['symbol']} {pos['side']} - "
                    f"время из отчета: '{pos['time']}', распарсено: {close_time} "
                    f"(timestamp={int(close_time.timestamp() * 1000)})"
                )
                
                # Добавляем длительность позиции (если есть в данных)
                # Для начала используем время закрытия + небольшая задержка
                start_analysis_time = close_time
                end_analysis_time = close_time + timedelta(minutes=minutes_after)
                
                # Получаем исторические свечи
                candles = await self.get_historical_candles(
                    symbol=pos["symbol"],
                    start_time=start_analysis_time,
                    end_time=end_analysis_time,
                    timeframe="1m",
                )
                
                # Анализируем движение цены
                analysis = self.analyze_price_movement(
                    position_side=pos["side"],
                    entry_price=pos["entry"],
                    exit_price=pos["exit"],
                    candles_after=candles,
                    minutes_after=minutes_after,
                )
                
                # Добавляем исходные данные позиции
                result = {
                    **pos,
                    "close_time": close_time.isoformat(),
                    "analysis": analysis,
                }
                
                results.append(result)
                
                # Небольшая задержка между запросами, чтобы не перегружать API
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(
                    f"❌ Ошибка анализа позиции {pos.get('symbol', 'unknown')}: {e}",
                    exc_info=True,
                )
                results.append({
                    **pos,
                    "error": str(e),
                    "analysis": None,
                })
        
        return results
    
    def generate_report(self, results: List[Dict], output_file: Path):
        """Генерирует детальный отчет в формате Markdown"""
        
        premature_closes = [r for r in results if r.get("analysis", {}).get("premature_close")]
        wrong_directions = [r for r in results if r.get("analysis", {}).get("wrong_direction")]
        
        report = f"""# 🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ДВИЖЕНИЯ ЦЕНЫ ПОСЛЕ ЗАКРЫТИЯ ПОЗИЦИЙ

**Дата анализа:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  
**Всего позиций проанализировано:** {len(results)}  
**Преждевременных закрытий:** {len(premature_closes)} ({len(premature_closes)/len(results)*100:.1f}%)  
**Неправильных направлений:** {len(wrong_directions)} ({len(wrong_directions)/len(results)*100:.1f}%)

---

## 📊 СВОДНАЯ СТАТИСТИКА

| Категория | Количество | Процент |
|-----------|------------|---------|
| Всего позиций | {len(results)} | 100% |
| Преждевременное закрытие | {len(premature_closes)} | {len(premature_closes)/len(results)*100:.1f}% |
| Неправильное направление | {len(wrong_directions)} | {len(wrong_directions)/len(results)*100:.1f}% |
| Нет данных | {len([r for r in results if r.get('analysis', {}).get('error')])} | {len([r for r in results if r.get('analysis', {}).get('error')])/len(results)*100:.1f}% |

---

## 🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ПО ПОЗИЦИЯМ

"""
        
        for i, result in enumerate(results, 1):
            symbol = result.get("symbol", "unknown")
            side = result.get("side", "unknown")
            time = result.get("time", "unknown")
            entry = result.get("entry", 0)
            exit_price = result.get("exit", 0)
            reason = result.get("reason", "unknown")
            analysis = result.get("analysis", {})
            
            report += f"""### Позиция #{i}: {symbol} {side} | {time}

**Базовые данные:**
- Entry: {entry}
- Exit: {exit_price}
- Причина закрытия: {reason}

"""
            
            if analysis.get("error"):
                report += f"**⚠️ Ошибка анализа:** {analysis['error']}\n\n"
            else:
                premature = analysis.get("premature_close", False)
                wrong_dir = analysis.get("wrong_direction", False)
                max_profit = analysis.get("max_profit_if_held", 0)
                max_loss = analysis.get("max_loss_if_held", 0)
                
                price_5m = analysis.get("price_after_5min")
                price_10m = analysis.get("price_after_10min")
                price_15m = analysis.get("price_after_15min")
                
                report += f"""**Анализ движения цены после закрытия:**

- **Преждевременное закрытие:** {'🔴 ДА' if premature else '✅ НЕТ'}
- **Неправильное направление:** {'🔴 ДА' if wrong_dir else '✅ НЕТ'}
- **Максимальная прибыль, если бы держали:** {max_profit:.2f}%
- **Максимальный убыток, если бы держали:** {max_loss:.2f}%
- **Цена через 5 минут:** {price_5m if price_5m else 'N/A'}
- **Цена через 10 минут:** {price_10m if price_10m else 'N/A'}
- **Цена через 15 минут:** {price_15m if price_15m else 'N/A'}

"""
        
        # Сохраняем отчет
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report)
        
        logger.info(f"✅ Отчет сохранен в {output_file}")
        
        # Также сохраняем результаты в JSON для дальнейшего анализа
        json_file = output_file.with_suffix(".json")
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"✅ JSON данные сохранены в {json_file}")


async def main():
    """Основная функция"""
    logger.info("🚀 Запуск анализа движения цены после закрытия позиций")
    
    analyzer = PriceMovementAnalyzer()
    
    # Загружаем позиции из отчета
    report_file = Path("docs/analysis/reports/2025-12/ПОЛНЫЙ_АНАЛИЗ_ПОЗИЦИЙ_30_12_2025_ВЕЧЕР.md")
    
    if not report_file.exists():
        logger.error(f"❌ Файл отчета не найден: {report_file}")
        return
    
    positions = analyzer.load_positions_from_report(report_file)
    
    if not positions:
        logger.error("❌ Не удалось загрузить позиции из отчета")
        return
    
    logger.info(f"✅ Загружено {len(positions)} позиций для анализа")
    
    # Анализируем все позиции
    results = await analyzer.analyze_all_positions(positions, minutes_after=15)
    
    # Генерируем отчет
    output_file = analyzer.output_dir / "АНАЛИЗ_ДВИЖЕНИЯ_ЦЕНЫ_ПОСЛЕ_ЗАКРЫТИЯ_ДЕТАЛЬНЫЙ.md"
    analyzer.generate_report(results, output_file)
    
    logger.info("✅ Анализ завершен!")


if __name__ == "__main__":
    asyncio.run(main())

