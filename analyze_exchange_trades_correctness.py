#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ правильности выполнения сделок на основе данных с биржи
Группирует fills в позиции и проверяет корректность
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict


class ExchangeTradesAnalyzer:
    """Анализирует сделки с биржи и проверяет их корректность"""
    
    def __init__(self):
        self.trades = []
        self.positions = []  # Группированные позиции (открытие + закрытие)
        self.issues = []
    
    def load_trades(self, filepath: Path):
        """Загружает сделки с биржи"""
        print(f"📂 Загружаю сделки из {filepath.name}...")
        with open(filepath, 'r', encoding='utf-8') as f:
            self.trades = json.load(f)
        print(f"✅ Загружено {len(self.trades)} сделок")
    
    def group_into_positions(self):
        """Группирует fills в позиции (открытие + закрытие)"""
        print(f"\n🔄 Группирую fills в позиции...")
        
        # Группируем по символу и направлению (pos_side)
        by_symbol_side = defaultdict(list)
        
        for trade in self.trades:
            symbol = trade.get("symbol", "")
            pos_side = trade.get("pos_side", "").lower()
            side = trade.get("side", "").lower()
            
            key = f"{symbol}_{pos_side}"
            by_symbol_side[key].append(trade)
        
        # Для каждого символа/направления группируем в позиции
        for key, trades in by_symbol_side.items():
            symbol, pos_side = key.split("_", 1)
            
            # Сортируем по времени
            trades.sort(key=lambda x: x.get("timestamp", ""))
            
            # Группируем: buy -> sell (для long) или sell -> buy (для short)
            if pos_side == "long":
                # Long: buy открывает, sell закрывает
                self._group_long_positions(symbol, trades)
            elif pos_side == "short":
                # Short: sell открывает, buy закрывает
                self._group_short_positions(symbol, trades)
        
        print(f"✅ Сформировано {len(self.positions)} позиций")
    
    def _group_long_positions(self, symbol: str, trades: List[Dict]):
        """Группирует long позиции (buy открывает, sell закрывает) с учетом частичных закрытий"""
        # Используем FIFO для отслеживания открытых позиций
        open_positions = []  # Список: {entry_price, remaining_size, entry_time, entry_order_id, entry_fee, closing_fills}
        
        for trade in trades:
            side = trade.get("side", "").lower()
            price = trade.get("price", 0)
            size = trade.get("size", 0)
            timestamp = trade.get("timestamp", "")
            order_id = trade.get("order_id", "")
            fill_pnl = trade.get("pnl")  # fillPnl от биржи (только для этого fill)
            fee = abs(trade.get("fee", 0) or 0)
            
            if side == "buy":
                # Открытие позиции
                open_positions.append({
                    "entry_price": price,
                    "remaining_size": size,
                    "entry_time": timestamp,
                    "entry_order_id": order_id,
                    "entry_fee": fee,
                    "closing_fills": []  # Список fills закрытия для суммирования fillPnl
                })
            
            elif side == "sell" and open_positions:
                # Закрытие позиции (может быть частичным)
                remaining_to_close = size
                
                while remaining_to_close > 0.000001 and open_positions:
                    entry = open_positions[0]
                    
                    # Сколько закрываем из этой позиции
                    close_size = min(remaining_to_close, entry["remaining_size"])
                    
                    # Рассчитываем PnL для этой части
                    calculated_pnl = (price - entry["entry_price"]) * close_size
                    
                    # Пропорциональная комиссия входа
                    if entry["remaining_size"] > 0:
                        entry_fee_part = entry["entry_fee"] * (close_size / (entry["remaining_size"] + close_size))
                    else:
                        entry_fee_part = 0
                    
                    # Добавляем fill в список закрытий
                    if fill_pnl is not None:
                        entry["closing_fills"].append({
                            "size": close_size,
                            "price": price,
                            "fill_pnl": fill_pnl,
                            "fee": fee
                        })
                    
                    # Если это полное закрытие позиции
                    if abs(close_size - entry["remaining_size"]) < 0.000001:
                        # Полное закрытие - суммируем fillPnl всех fills
                        total_exchange_pnl = sum(f["fill_pnl"] for f in entry["closing_fills"]) if entry["closing_fills"] else None
                        total_exit_fee = sum(f["fee"] for f in entry["closing_fills"]) if entry["closing_fills"] else fee
                        
                        position = {
                            "symbol": symbol,
                            "side": "long",
                            "entry_price": entry["entry_price"],
                            "exit_price": price,  # Последняя цена закрытия
                            "size": entry["remaining_size"],
                            "entry_time": entry["entry_time"],
                            "exit_time": timestamp,
                            "entry_order_id": entry["entry_order_id"],
                            "exit_order_id": order_id,
                            "entry_fee": entry["entry_fee"],
                            "exit_fee": total_exit_fee,
                            "total_fee": entry["entry_fee"] + total_exit_fee,
                            "exchange_pnl": total_exchange_pnl,
                            "calculated_pnl": calculated_pnl,
                            "net_pnl": (total_exchange_pnl - (entry["entry_fee"] + total_exit_fee)) if total_exchange_pnl is not None else (calculated_pnl - (entry["entry_fee"] + total_exit_fee)),
                            "fills_count": len(entry["closing_fills"])
                        }
                        
                        self._check_position_correctness(position)
                        self.positions.append(position)
                        open_positions.pop(0)
                    else:
                        # Частичное закрытие - создаем позицию для закрытой части
                        # Для частичного закрытия fillPnl относится только к этой части
                        position = {
                            "symbol": symbol,
                            "side": "long",
                            "entry_price": entry["entry_price"],
                            "exit_price": price,
                            "size": close_size,
                            "entry_time": entry["entry_time"],
                            "exit_time": timestamp,
                            "entry_order_id": entry["entry_order_id"],
                            "exit_order_id": order_id,
                            "entry_fee": entry_fee_part,
                            "exit_fee": fee,
                            "total_fee": entry_fee_part + fee,
                            "exchange_pnl": fill_pnl if fill_pnl is not None else None,
                            "calculated_pnl": calculated_pnl,
                            "net_pnl": (fill_pnl - (entry_fee_part + fee)) if fill_pnl is not None else (calculated_pnl - (entry_fee_part + fee)),
                            "is_partial": True
                        }
                        
                        self._check_position_correctness(position)
                        self.positions.append(position)
                        
                        # Обновляем оставшийся размер
                        entry["remaining_size"] -= close_size
                        entry["entry_fee"] -= entry_fee_part
                    
                    remaining_to_close -= close_size
    
    def _group_short_positions(self, symbol: str, trades: List[Dict]):
        """Группирует short позиции (sell открывает, buy закрывает) с учетом частичных закрытий"""
        open_positions = []
        
        for trade in trades:
            side = trade.get("side", "").lower()
            price = trade.get("price", 0)
            size = trade.get("size", 0)
            timestamp = trade.get("timestamp", "")
            order_id = trade.get("order_id", "")
            fill_pnl = trade.get("pnl")
            fee = abs(trade.get("fee", 0) or 0)
            
            if side == "sell":
                # Открытие short позиции
                open_positions.append({
                    "entry_price": price,
                    "remaining_size": size,
                    "entry_time": timestamp,
                    "entry_order_id": order_id,
                    "entry_fee": fee,
                    "closing_fills": []
                })
            
            elif side == "buy" and open_positions:
                # Закрытие short позиции (может быть частичным)
                remaining_to_close = size
                
                while remaining_to_close > 0.000001 and open_positions:
                    entry = open_positions[0]
                    close_size = min(remaining_to_close, entry["remaining_size"])
                    
                    # Для short: PnL = (entry_price - exit_price) * size
                    calculated_pnl = (entry["entry_price"] - price) * close_size
                    
                    # Пропорциональная комиссия
                    if entry["remaining_size"] > 0:
                        entry_fee_part = entry["entry_fee"] * (close_size / (entry["remaining_size"] + close_size))
                    else:
                        entry_fee_part = 0
                    
                    # Добавляем fill в список закрытий
                    if fill_pnl is not None:
                        entry["closing_fills"].append({
                            "size": close_size,
                            "price": price,
                            "fill_pnl": fill_pnl,
                            "fee": fee
                        })
                    
                    if abs(close_size - entry["remaining_size"]) < 0.000001:
                        # Полное закрытие - суммируем fillPnl
                        total_exchange_pnl = sum(f["fill_pnl"] for f in entry["closing_fills"]) if entry["closing_fills"] else None
                        total_exit_fee = sum(f["fee"] for f in entry["closing_fills"]) if entry["closing_fills"] else fee
                        
                        position = {
                            "symbol": symbol,
                            "side": "short",
                            "entry_price": entry["entry_price"],
                            "exit_price": price,
                            "size": entry["remaining_size"],
                            "entry_time": entry["entry_time"],
                            "exit_time": timestamp,
                            "entry_order_id": entry["entry_order_id"],
                            "exit_order_id": order_id,
                            "entry_fee": entry["entry_fee"],
                            "exit_fee": total_exit_fee,
                            "total_fee": entry["entry_fee"] + total_exit_fee,
                            "exchange_pnl": total_exchange_pnl,
                            "calculated_pnl": calculated_pnl,
                            "net_pnl": (total_exchange_pnl - (entry["entry_fee"] + total_exit_fee)) if total_exchange_pnl is not None else (calculated_pnl - (entry["entry_fee"] + total_exit_fee)),
                            "fills_count": len(entry["closing_fills"])
                        }
                        
                        self._check_position_correctness(position)
                        self.positions.append(position)
                        open_positions.pop(0)
                    else:
                        # Частичное закрытие
                        position = {
                            "symbol": symbol,
                            "side": "short",
                            "entry_price": entry["entry_price"],
                            "exit_price": price,
                            "size": close_size,
                            "entry_time": entry["entry_time"],
                            "exit_time": timestamp,
                            "entry_order_id": entry["entry_order_id"],
                            "exit_order_id": order_id,
                            "entry_fee": entry_fee_part,
                            "exit_fee": fee,
                            "total_fee": entry_fee_part + fee,
                            "exchange_pnl": fill_pnl if fill_pnl is not None else None,
                            "calculated_pnl": calculated_pnl,
                            "net_pnl": (fill_pnl - (entry_fee_part + fee)) if fill_pnl is not None else (calculated_pnl - (entry_fee_part + fee)),
                            "is_partial": True
                        }
                        
                        self._check_position_correctness(position)
                        self.positions.append(position)
                        entry["remaining_size"] -= close_size
                        entry["entry_fee"] -= entry_fee_part
                    
                    remaining_to_close -= close_size
    
    def _check_position_correctness(self, position: Dict):
        """Проверяет корректность позиции"""
        issues = []
        
        # Проверка 1: PnL с биржи vs рассчитанный
        # ВАЖНО: fillPnl от биржи рассчитывается от средней цены входа позиции (avgPx), 
        # а не от цены конкретного fill. Поэтому расхождения нормальны для позиций,
        # открытых несколькими fills. Проверяем только явные аномалии.
        if position["exchange_pnl"] is not None:
            # Используем fillPnl от биржи как основной источник истины
            # Расчетный PnL используем только для логической проверки
            calculated_pnl = position["calculated_pnl"]
            exchange_pnl = position["exchange_pnl"]
            
            # Если разница очень большая (>$10 и >50%), это может быть ошибка
            diff = abs(exchange_pnl - calculated_pnl)
            pnl_abs = max(abs(exchange_pnl), abs(calculated_pnl))
            
            if pnl_abs > 0:
                diff_percent = (diff / pnl_abs * 100)
                # Флаг проблемы только если очень большая разница
                if diff > 10.0 and diff_percent > 50:
                    issues.append({
                        "type": "pnl_mismatch",
                        "message": f"Большое расхождение PnL: биржа={exchange_pnl:.2f}, расчет={calculated_pnl:.2f}, разница=${diff:.2f} ({diff_percent:.1f}%) - возможно позиция открывалась несколькими fills",
                        "position": position
                    })
        
        # Проверка 2: Отрицательный размер
        if position["size"] <= 0:
            issues.append({
                "type": "invalid_size",
                "message": f"Некорректный размер позиции: {position['size']}",
                "position": position
            })
        
        # Проверка 3: Нулевая или отрицательная цена
        if position["entry_price"] <= 0 or position["exit_price"] <= 0:
            issues.append({
                "type": "invalid_price",
                "message": f"Некорректная цена: entry={position['entry_price']}, exit={position['exit_price']}",
                "position": position
            })
        
        # Проверка 4: Очень большая комиссия (>10% от размера позиции - это уже критично)
        position_value = position["entry_price"] * position["size"]
        fee_percent = (position["total_fee"] / position_value * 100) if position_value > 0 else 0
        if fee_percent > 10:  # Увеличил порог до 10% - 5% может быть нормально для очень маленьких позиций
            issues.append({
                "type": "high_fee",
                "message": f"Критически высокая комиссия: ${position['total_fee']:.4f} ({fee_percent:.2f}% от размера позиции ${position_value:.2f})",
                "position": position
            })
        
        self.issues.extend(issues)
    
    def generate_report(self) -> str:
        """Генерирует отчет"""
        report = []
        report.append("=" * 80)
        report.append("📊 АНАЛИЗ ПРАВИЛЬНОСТИ ВЫПОЛНЕНИЯ СДЕЛОК")
        report.append("=" * 80)
        report.append("")
        
        # Общая статистика
        total_positions = len(self.positions)
        profitable = sum(1 for p in self.positions if p.get("net_pnl", 0) > 0)
        losing = total_positions - profitable
        
        # Используем fillPnl от биржи как основной источник (если есть), иначе расчетный
        total_pnl = 0
        total_fee = sum(p.get("total_fee", 0) for p in self.positions)
        
        for p in self.positions:
            if p.get("exchange_pnl") is not None:
                # Используем PnL от биржи минус комиссия
                total_pnl += p.get("exchange_pnl", 0) - p.get("total_fee", 0)
            else:
                # Используем расчетный PnL
                total_pnl += p.get("net_pnl", 0)
        
        report.append("📈 ОБЩАЯ СТАТИСТИКА:")
        report.append(f"   Всего позиций: {total_positions}")
        report.append(f"   Прибыльных: {profitable} ({profitable/total_positions*100:.1f}%)")
        report.append(f"   Убыточных: {losing} ({losing/total_positions*100:.1f}%)")
        report.append(f"   Общий PnL (от биржи): ${total_pnl:.2f}")
        report.append(f"   Общая комиссия: ${total_fee:.2f}")
        report.append(f"   Чистый PnL: ${total_pnl:.2f}")
        report.append("")
        
        # Статистика по символам
        by_symbol = defaultdict(list)
        for pos in self.positions:
            by_symbol[pos["symbol"]].append(pos)
        
        report.append("📊 ПО СИМВОЛАМ:")
        for symbol in sorted(by_symbol.keys()):
            positions = by_symbol[symbol]
            symbol_pnl = sum(p.get("net_pnl", 0) for p in positions)
            symbol_fee = sum(p.get("total_fee", 0) for p in positions)
            symbol_profitable = sum(1 for p in positions if p.get("net_pnl", 0) > 0)
            
            report.append(f"\n   {symbol}:")
            report.append(f"      Позиций: {len(positions)}")
            report.append(f"      Прибыльных: {symbol_profitable}")
            report.append(f"      PnL: ${symbol_pnl:.2f}")
            report.append(f"      Комиссия: ${symbol_fee:.2f}")
        
        report.append("")
        
        # Проблемы
        if self.issues:
            report.append("=" * 80)
            report.append("⚠️ ОБНАРУЖЕННЫЕ ПРОБЛЕМЫ")
            report.append("=" * 80)
            report.append("")
            
            by_type = defaultdict(list)
            for issue in self.issues:
                by_type[issue["type"]].append(issue)
            
            for issue_type, issues_list in by_type.items():
                report.append(f"\n{issue_type.upper()}: {len(issues_list)} случаев")
                for issue in issues_list[:5]:  # Первые 5
                    report.append(f"   - {issue['message']}")
                if len(issues_list) > 5:
                    report.append(f"   ... и еще {len(issues_list) - 5}")
        else:
            report.append("✅ Проблем не обнаружено")
        
        report.append("")
        
        # Примеры позиций
        report.append("=" * 80)
        report.append("📋 ПРИМЕРЫ ПОЗИЦИЙ (первые 10)")
        report.append("=" * 80)
        report.append("")
        
        for i, pos in enumerate(self.positions[:10], 1):
            report.append(f"{i}. {pos['symbol']} {pos['side'].upper()}")
            report.append(f"   Entry: ${pos['entry_price']:.2f} @ {pos['entry_time']}")
            report.append(f"   Exit:  ${pos['exit_price']:.2f} @ {pos['exit_time']}")
            report.append(f"   Size:  {pos['size']:.6f}")
            report.append(f"   Fee:   ${pos['total_fee']:.4f}")
            
            if pos['exchange_pnl'] is not None:
                report.append(f"   PnL (биржа): ${pos['exchange_pnl']:.2f}")
            report.append(f"   PnL (расчет): ${pos['calculated_pnl']:.2f}")
            report.append(f"   Net PnL: ${pos['net_pnl']:.2f}")
            report.append("")
        
        return "\n".join(report)


def main():
    """Главная функция"""
    print("=" * 80)
    print("📊 АНАЛИЗ ПРАВИЛЬНОСТИ ВЫПОЛНЕНИЯ СДЕЛОК")
    print("=" * 80)
    
    analyzer = ExchangeTradesAnalyzer()
    
    # Загружаем сделки
    trade_file = Path("trades_all_20251204_201255.json")
    if not trade_file.exists():
        files = list(Path(".").glob("trades_all_*.json"))
        if files:
            trade_file = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        else:
            print("❌ Не найден файл со сделками!")
            return
    
    analyzer.load_trades(trade_file)
    
    # Группируем в позиции
    analyzer.group_into_positions()
    
    # Генерируем отчет
    report = analyzer.generate_report()
    print("\n" + report)
    
    # Сохраняем отчет
    report_file = Path("exchange_trades_analysis_report.md")
    report_file.write_text(report, encoding='utf-8')
    print(f"\n💾 Отчет сохранен в {report_file}")
    
    # Сохраняем позиции
    positions_file = Path("exchange_positions.json")
    positions_file.write_text(
        json.dumps(analyzer.positions, indent=2, ensure_ascii=False, default=str),
        encoding='utf-8'
    )
    print(f"💾 Позиции сохранены в {positions_file}")


if __name__ == "__main__":
    main()

