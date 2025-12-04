#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сравнение сделок из логов бота с реальными сделками с биржи
Проверка правильности выполнения и выявление расхождений
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from logs.analyze_logs import LogAnalyzer


class TradeComparator:
    """Сравнивает сделки из логов бота с реальными сделками с биржи"""
    
    def __init__(self):
        self.bot_trades = []  # Сделки из логов бота
        self.exchange_trades = []  # Сделки с биржи
        self.matched_trades = []  # Совпадающие сделки
        self.bot_only = []  # Только в логах бота
        self.exchange_only = []  # Только на бирже
        self.discrepancies = []  # Расхождения
    
    def load_exchange_trades(self, filepath: Path):
        """Загружает сделки с биржи из JSON"""
        print(f"📂 Загружаю сделки с биржи из {filepath.name}...")
        with open(filepath, 'r', encoding='utf-8') as f:
            self.exchange_trades = json.load(f)
        print(f"✅ Загружено {len(self.exchange_trades)} сделок с биржи")
    
    def extract_trades_from_logs(self, log_files: List[Path], start_date: datetime, end_date: datetime):
        """Извлекает сделки из логов бота"""
        print(f"\n📂 Извлекаю сделки из логов бота...")
        
        analyzer = LogAnalyzer()
        parsed_logs = []
        
        # Читаем и парсим логи
        for log_file in log_files:
            lines = analyzer.read_log_file(log_file)
            for line in lines:
                parsed = analyzer.parse_log_line(line)
                if parsed:
                    # Фильтруем по дате
                    if parsed["timestamp"]:
                        if start_date <= parsed["timestamp"] <= end_date:
                            parsed_logs.append(parsed)
        
        print(f"✅ Парсировано {len(parsed_logs)} строк логов")
        
        # Извлекаем сделки (открытие + закрытие = сделка)
        open_positions = {}  # symbol -> {entry_price, size, side, timestamp, order_id}
        
        for log in parsed_logs:
            message = log["message"]
            timestamp = log["timestamp"]
            
            # Открытие позиции
            # Паттерны: "✅ ПОЗИЦИЯ ОТКРЫТА", "Позиция открыта", "POSITION OPENED"
            if any(x in message.upper() for x in ["ПОЗИЦИЯ ОТКРЫТА", "POSITION OPENED", "ПОЗИЦИЯ ОТКРЫТ"]):
                trade = self._parse_position_opened(message, timestamp)
                if trade:
                    key = f"{trade['symbol']}_{trade['side']}"
                    open_positions[key] = trade
            
            # Закрытие позиции
            # Паттерны: "💰 ПОЗИЦИЯ ЗАКРЫТА", "TRADE CLOSED", "Позиция закрыта"
            elif any(x in message.upper() for x in ["ПОЗИЦИЯ ЗАКРЫТА", "TRADE CLOSED", "EXIT_HIT"]):
                trade = self._parse_position_closed(message, timestamp)
                if trade:
                    # Ищем соответствующее открытие
                    key = f"{trade['symbol']}_{trade['side']}"
                    if key in open_positions:
                        entry = open_positions[key]
                        # Объединяем в полную сделку
                        full_trade = {
                            **entry,
                            "exit_price": trade.get("exit_price"),
                            "exit_time": timestamp,
                            "net_pnl": trade.get("net_pnl"),
                            "gross_pnl": trade.get("gross_pnl"),
                            "commission": trade.get("commission"),
                            "reason": trade.get("reason"),
                            "duration_sec": (timestamp - entry["timestamp"]).total_seconds() if entry["timestamp"] else None
                        }
                        self.bot_trades.append(full_trade)
                        del open_positions[key]
        
        print(f"✅ Извлечено {len(self.bot_trades)} сделок из логов бота")
        if open_positions:
            print(f"⚠️ Осталось {len(open_positions)} открытых позиций без закрытия")
    
    def _parse_position_opened(self, message: str, timestamp: datetime) -> Optional[Dict]:
        """Парсит сообщение об открытии позиции"""
        # Паттерны:
        # "✅ ПОЗИЦИЯ ОТКРЫТА: BTC-USDT LONG entry=86346.2 size=0.23"
        # "Позиция BTC-USDT LONG открыта по цене 86346.2 размер 0.23"
        
        # Ищем символ
        symbol_match = re.search(r'([A-Z]+-[A-Z]+)', message)
        if not symbol_match:
            return None
        
        symbol = symbol_match.group(1)
        
        # Ищем side (LONG/SHORT)
        side_match = re.search(r'\b(LONG|SHORT)\b', message, re.I)
        side = (side_match.group(1).lower() if side_match else "long")
        
        # Ищем entry price
        entry_match = re.search(r'entry[=:]?\s*([\d.]+)', message, re.I)
        if not entry_match:
            entry_match = re.search(r'цене\s+([\d.]+)', message, re.I)
        entry_price = float(entry_match.group(1)) if entry_match else None
        
        # Ищем size
        size_match = re.search(r'size[=:]?\s*([\d.]+)', message, re.I)
        if not size_match:
            size_match = re.search(r'размер\s+([\d.]+)', message, re.I)
        size = float(size_match.group(1)) if size_match else None
        
        # Ищем order_id
        order_id_match = re.search(r'order[_\s]?id[=:]?\s*(\d+)', message, re.I)
        order_id = order_id_match.group(1) if order_id_match else None
        
        return {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "size": size,
            "timestamp": timestamp,
            "order_id": order_id
        }
    
    def _parse_position_closed(self, message: str, timestamp: datetime) -> Optional[Dict]:
        """Парсит сообщение о закрытии позиции"""
        # Паттерны:
        # "💰 ПОЗИЦИЯ ЗАКРЫТА: BTC-USDT LONG exit=92807.0 net_pnl=14.85"
        # "TRADE CLOSED: BTC-USDT LONG Exit: $92807.0 Net PnL: $14.85"
        
        # Ищем символ
        symbol_match = re.search(r'([A-Z]+-[A-Z]+)', message)
        if not symbol_match:
            return None
        
        symbol = symbol_match.group(1)
        
        # Ищем side
        side_match = re.search(r'\b(LONG|SHORT)\b', message, re.I)
        side = (side_match.group(1).lower() if side_match else "long")
        
        # Ищем exit price
        exit_match = re.search(r'exit[=:]?\s*\$?([\d.]+)', message, re.I)
        if not exit_match:
            exit_match = re.search(r'Exit[=:]?\s*\$?([\d.]+)', message, re.I)
        exit_price = float(exit_match.group(1)) if exit_match else None
        
        # Ищем PnL
        pnl_match = re.search(r'net[_\s]?pnl[=:]?\s*\$?([\-\+]?[\d.]+)', message, re.I)
        if not pnl_match:
            pnl_match = re.search(r'Net PnL[=:]?\s*\$?([\-\+]?[\d.]+)', message, re.I)
        net_pnl = float(pnl_match.group(1)) if pnl_match else None
        
        # Ищем gross PnL
        gross_match = re.search(r'gross[_\s]?pnl[=:]?\s*\$?([\-\+]?[\d.]+)', message, re.I)
        gross_pnl = float(gross_match.group(1)) if gross_match else None
        
        # Ищем commission
        comm_match = re.search(r'commission[=:]?\s*\$?([\d.]+)', message, re.I)
        commission = float(comm_match.group(1)) if comm_match else None
        
        # Ищем reason
        reason_match = re.search(r'reason[=:]?\s*(\w+)', message, re.I)
        if not reason_match:
            reason_match = re.search(r'закрыт[а]?\s+(?:по|через)\s+(\w+)', message, re.I)
        reason = reason_match.group(1) if reason_match else None
        
        return {
            "symbol": symbol,
            "side": side,
            "exit_price": exit_price,
            "net_pnl": net_pnl,
            "gross_pnl": gross_pnl,
            "commission": commission,
            "reason": reason
        }
    
    def match_trades(self):
        """Сопоставляет сделки из логов с реальными сделками с биржи"""
        print(f"\n🔍 Сопоставляю сделки...")
        
        # Группируем сделки с биржи по символам и времени
        exchange_by_symbol = defaultdict(list)
        for trade in self.exchange_trades:
            symbol = trade.get("symbol", "")
            exchange_by_symbol[symbol].append(trade)
        
        # Для каждой сделки из логов ищем соответствующую на бирже
        for bot_trade in self.bot_trades:
            symbol = bot_trade.get("symbol", "")
            entry_time = bot_trade.get("timestamp")
            exit_time = bot_trade.get("exit_time")
            
            if not entry_time or not exit_time:
                self.bot_only.append(bot_trade)
                continue
            
            # Ищем сделки на бирже в этом временном окне
            candidates = []
            for ex_trade in exchange_by_symbol.get(symbol, []):
                ex_time = datetime.fromisoformat(ex_trade.get("timestamp", ""))
                
                # Проверяем, попадает ли сделка с биржи в окно открытия/закрытия
                time_diff_entry = abs((ex_time - entry_time).total_seconds())
                time_diff_exit = abs((ex_time - exit_time).total_seconds())
                
                # Если сделка близка по времени к открытию или закрытию
                if time_diff_entry < 60 or time_diff_exit < 60:  # В пределах 60 секунд
                    candidates.append((ex_trade, min(time_diff_entry, time_diff_exit)))
            
            if candidates:
                # Берем ближайшую по времени
                candidates.sort(key=lambda x: x[1])
                best_match = candidates[0][0]
                
                # Проверяем совпадение
                match_result = self._check_match(bot_trade, best_match)
                if match_result["matched"]:
                    self.matched_trades.append({
                        "bot": bot_trade,
                        "exchange": best_match,
                        "match_quality": match_result
                    })
                else:
                    self.discrepancies.append({
                        "bot": bot_trade,
                        "exchange": best_match,
                        "issues": match_result["issues"]
                    })
            else:
                self.bot_only.append(bot_trade)
        
        # Находим сделки, которые есть на бирже, но нет в логах
        matched_exchange_ids = {id(t["exchange"]) for t in self.matched_trades}
        matched_exchange_ids.update({id(t["exchange"]) for t in self.discrepancies})
        
        for trade in self.exchange_trades:
            if id(trade) not in matched_exchange_ids:
                self.exchange_only.append(trade)
        
        print(f"✅ Сопоставление завершено:")
        print(f"   Совпадающих: {len(self.matched_trades)}")
        print(f"   С расхождениями: {len(self.discrepancies)}")
        print(f"   Только в логах: {len(self.bot_only)}")
        print(f"   Только на бирже: {len(self.exchange_only)}")
    
    def _check_match(self, bot_trade: Dict, exchange_trade: Dict) -> Dict:
        """Проверяет совпадение сделки из логов с реальной сделкой"""
        issues = []
        matched = True
        
        # Проверка цены (для закрытия)
        bot_exit = bot_trade.get("exit_price")
        ex_price = exchange_trade.get("price")
        
        if bot_exit and ex_price:
            price_diff = abs(bot_exit - ex_price) / ex_price * 100
            if price_diff > 0.1:  # Более 0.1% разница
                issues.append(f"Цена закрытия: бот={bot_exit:.2f}, биржа={ex_price:.2f} (разница {price_diff:.2f}%)")
                matched = False
        
        # Проверка размера
        bot_size = bot_trade.get("size")
        ex_size = exchange_trade.get("size")
        
        if bot_size and ex_size:
            size_diff = abs(bot_size - ex_size) / max(bot_size, ex_size) * 100
            if size_diff > 1.0:  # Более 1% разница
                issues.append(f"Размер: бот={bot_size:.6f}, биржа={ex_size:.6f} (разница {size_diff:.2f}%)")
                matched = False
        
        # Проверка PnL (если есть)
        bot_pnl = bot_trade.get("net_pnl")
        ex_pnl = exchange_trade.get("pnl")
        
        if bot_pnl is not None and ex_pnl is not None:
            pnl_diff = abs(bot_pnl - ex_pnl)
            if pnl_diff > 0.1:  # Более $0.1 разница
                issues.append(f"PnL: бот={bot_pnl:.2f}, биржа={ex_pnl:.2f} (разница ${pnl_diff:.2f})")
                matched = False
        
        # Проверка комиссии
        bot_fee = bot_trade.get("commission")
        ex_fee = abs(exchange_trade.get("fee", 0) or 0)
        
        if bot_fee and ex_fee:
            fee_diff = abs(bot_fee - ex_fee)
            if fee_diff > 0.01:  # Более $0.01 разница
                issues.append(f"Комиссия: бот={bot_fee:.4f}, биржа={ex_fee:.4f} (разница ${fee_diff:.4f})")
        
        return {
            "matched": matched,
            "issues": issues
        }
    
    def generate_report(self) -> str:
        """Генерирует отчет о сравнении"""
        report = []
        report.append("=" * 80)
        report.append("📊 СРАВНЕНИЕ СДЕЛОК: БОТ vs БИРЖА")
        report.append("=" * 80)
        report.append("")
        
        # Общая статистика
        report.append("📈 ОБЩАЯ СТАТИСТИКА:")
        report.append(f"   Сделок в логах бота: {len(self.bot_trades)}")
        report.append(f"   Сделок на бирже: {len(self.exchange_trades)}")
        report.append(f"   Совпадающих: {len(self.matched_trades)}")
        report.append(f"   С расхождениями: {len(self.discrepancies)}")
        report.append(f"   Только в логах: {len(self.bot_only)}")
        report.append(f"   Только на бирже: {len(self.exchange_only)}")
        report.append("")
        
        # Совпадающие сделки
        if self.matched_trades:
            report.append("=" * 80)
            report.append("✅ СОВПАДАЮЩИЕ СДЕЛКИ")
            report.append("=" * 80)
            report.append("")
            
            for i, match in enumerate(self.matched_trades[:10], 1):  # Первые 10
                bot = match["bot"]
                ex = match["exchange"]
                report.append(f"{i}. {bot.get('symbol')} {bot.get('side').upper()}")
                report.append(f"   Время: {bot.get('timestamp')} -> {bot.get('exit_time')}")
                report.append(f"   Цена закрытия: бот=${bot.get('exit_price'):.2f}, биржа=${ex.get('price'):.2f}")
                report.append(f"   PnL: бот=${bot.get('net_pnl'):.2f}, биржа=${ex.get('pnl'):.2f}")
                report.append("")
            
            if len(self.matched_trades) > 10:
                report.append(f"   ... и еще {len(self.matched_trades) - 10} совпадающих сделок")
                report.append("")
        
        # Расхождения
        if self.discrepancies:
            report.append("=" * 80)
            report.append("⚠️ РАСХОЖДЕНИЯ")
            report.append("=" * 80)
            report.append("")
            
            for i, disc in enumerate(self.discrepancies[:10], 1):  # Первые 10
                bot = disc["bot"]
                ex = disc["exchange"]
                report.append(f"{i}. {bot.get('symbol')} {bot.get('side').upper()}")
                report.append(f"   Время: {bot.get('timestamp')} -> {bot.get('exit_time')}")
                for issue in disc["issues"]:
                    report.append(f"   ⚠️ {issue}")
                report.append("")
            
            if len(self.discrepancies) > 10:
                report.append(f"   ... и еще {len(self.discrepancies) - 10} расхождений")
                report.append("")
        
        # Только в логах
        if self.bot_only:
            report.append("=" * 80)
            report.append("🔴 СДЕЛКИ ТОЛЬКО В ЛОГАХ БОТА (НЕТ НА БИРЖЕ)")
            report.append("=" * 80)
            report.append("")
            
            for i, trade in enumerate(self.bot_only[:10], 1):
                report.append(f"{i}. {trade.get('symbol')} {trade.get('side').upper()}")
                report.append(f"   Время: {trade.get('timestamp')} -> {trade.get('exit_time')}")
                report.append(f"   Entry: ${trade.get('entry_price'):.2f}, Exit: ${trade.get('exit_price'):.2f}")
                report.append("")
            
            if len(self.bot_only) > 10:
                report.append(f"   ... и еще {len(self.bot_only) - 10} сделок")
                report.append("")
        
        # Только на бирже
        if self.exchange_only:
            report.append("=" * 80)
            report.append("🔵 СДЕЛКИ ТОЛЬКО НА БИРЖЕ (НЕТ В ЛОГАХ)")
            report.append("=" * 80)
            report.append("")
            
            for i, trade in enumerate(self.exchange_only[:10], 1):
                report.append(f"{i}. {trade.get('symbol')} {trade.get('side')}")
                report.append(f"   Время: {trade.get('timestamp')}")
                report.append(f"   Цена: ${trade.get('price'):.2f}, Размер: {trade.get('size'):.6f}")
                report.append("")
            
            if len(self.exchange_only) > 10:
                report.append(f"   ... и еще {len(self.exchange_only) - 10} сделок")
                report.append("")
        
        return "\n".join(report)


def main():
    """Главная функция"""
    print("=" * 80)
    print("🔍 СРАВНЕНИЕ СДЕЛОК: БОТ vs БИРЖА")
    print("=" * 80)
    
    comparator = TradeComparator()
    
    # Загружаем сделки с биржи
    exchange_file = Path("trades_all_20251204_201255.json")
    if not exchange_file.exists():
        # Ищем последний файл
        files = list(Path(".").glob("trades_all_*.json"))
        if files:
            exchange_file = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        else:
            print("❌ Не найден файл со сделками с биржи!")
            return
    
    comparator.load_exchange_trades(exchange_file)
    
    # Находим логи за период 2-3 декабря
    logs_dir = Path("logs/futures")
    log_files = []
    
    # Ищем логи за 2-3 декабря
    for log_file in logs_dir.rglob("*.log"):
        if "2025-12-02" in log_file.name or "2025-12-03" in log_file.name:
            log_files.append(log_file)
    
    if not log_files:
        print("❌ Не найдены логи за 2-3 декабря!")
        return
    
    print(f"\n📂 Найдено {len(log_files)} log файлов")
    
    # Извлекаем сделки из логов
    start_date = datetime(2025, 12, 2, 0, 0, 0)
    end_date = datetime(2025, 12, 3, 23, 59, 59)
    
    comparator.extract_trades_from_logs(log_files, start_date, end_date)
    
    # Сопоставляем
    comparator.match_trades()
    
    # Генерируем отчет
    report = comparator.generate_report()
    print("\n" + report)
    
    # Сохраняем отчет
    report_file = Path("trade_comparison_report.md")
    report_file.write_text(report, encoding='utf-8')
    print(f"\n💾 Отчет сохранен в {report_file}")
    
    # Сохраняем детальные данные
    details = {
        "matched": comparator.matched_trades,
        "discrepancies": comparator.discrepancies,
        "bot_only": comparator.bot_only,
        "exchange_only": comparator.exchange_only
    }
    
    details_file = Path("trade_comparison_details.json")
    details_file.write_text(
        json.dumps(details, indent=2, ensure_ascii=False, default=str),
        encoding='utf-8'
    )
    print(f"💾 Детальные данные сохранены в {details_file}")


if __name__ == "__main__":
    main()

