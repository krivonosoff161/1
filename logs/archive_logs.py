#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автоматическая архивация логов
"""

import os
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path


def archive_old_logs(
    logs_dir: str = "logs/futures", keep_days: int = 30, auto_archive_days: int = 7
):
    """
    Архивация старых логов и сделок (JSON/CSV)

    ✅ ИСПРАВЛЕНО: Архивирует логи и сделки вместе, чтобы не было путаницы

    Args:
        logs_dir: Папка с логами
        keep_days: Сколько дней хранить
        auto_archive_days: Через сколько дней архивировать
    """
    logs_path = Path(logs_dir)
    if not logs_path.exists():
        return

    now = datetime.now()
    archived_count = 0
    deleted_count = 0

    # Создаем папку для архивов
    archive_dir = logs_path / "archived"
    archive_dir.mkdir(exist_ok=True)

    # ✅ НОВОЕ: Папка для сделок (JSON/CSV)
    trades_dir = logs_path.parent  # logs/ (родительская папка для logs/futures)

    # ✅ ИСПРАВЛЕНО: Правильная логика обработки файлов

    # 1. Обрабатываем .log файлы (еще не заархивированные)
    for log_file in logs_path.glob("*.log"):
        # Пропускаем файлы с расширением .zip (это уже архивы)
        if log_file.name.endswith(".zip"):
            continue

        # Получаем время модификации
        mod_time = datetime.fromtimestamp(log_file.stat().st_mtime)
        age_days = (now - mod_time).days

        # ✅ ИСПРАВЛЕНО: Правильная логика
        if age_days >= keep_days:
            # Файл старше keep_days - удаляем (сначала архивируем, если нужно)
            zip_name = f"{log_file.stem}.zip"
            zip_path = archive_dir / zip_name

            # Архивируем перед удалением (если еще не заархивирован)
            if not zip_path.exists() and age_days >= auto_archive_days:
                try:
                    # ✅ ИСПРАВЛЕНО: Архивируем лог + соответствующие сделки
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                        zipf.write(log_file, log_file.name)

                        # Ищем соответствующие файлы сделок
                        date_match = None
                        for part in log_file.stem.split("_"):
                            if len(part) == 10 and part.count("-") == 2:
                                date_match = part
                                break

                        if date_match:
                            trades_json = trades_dir / f"trades_{date_match}.json"
                            trades_csv = trades_dir / f"trades_{date_match}.csv"

                            if trades_json.exists():
                                zipf.write(trades_json, trades_json.name)

                            if trades_csv.exists():
                                zipf.write(trades_csv, trades_csv.name)

                    print(f"✅ Заархивирован перед удалением: {log_file.name}")
                except Exception as e:
                    print(f"⚠️ Ошибка архивации {log_file.name}: {e}")

            # Удаляем оригинал
            try:
                log_file.unlink()
                deleted_count += 1
                print(f"🗑️  Удален (старше {keep_days} дней): {log_file.name}")
            except Exception as e:
                print(f"⚠️ Ошибка удаления {log_file.name}: {e}")

        elif age_days >= auto_archive_days:
            # Файл старше auto_archive_days, но младше keep_days - архивируем
            zip_name = f"{log_file.stem}.zip"
            zip_path = archive_dir / zip_name

            if not zip_path.exists():
                try:
                    # ✅ ИСПРАВЛЕНО: Архивируем лог + соответствующие сделки (JSON/CSV)
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                        # Добавляем сам лог файл
                        zipf.write(log_file, log_file.name)

                        # Ищем соответствующие файлы сделок (по дате из имени файла)
                        # Формат имени: futures_main_YYYY-MM-DD.log
                        date_match = None
                        for part in log_file.stem.split("_"):
                            if len(part) == 10 and part.count("-") == 2:  # YYYY-MM-DD
                                date_match = part
                                break

                        if date_match:
                            # Ищем JSON и CSV файлы сделок с этой датой
                            trades_json = trades_dir / f"trades_{date_match}.json"
                            trades_csv = trades_dir / f"trades_{date_match}.csv"

                            if trades_json.exists():
                                zipf.write(trades_json, trades_json.name)
                                print(f"   📄 Добавлен в архив: {trades_json.name}")

                            if trades_csv.exists():
                                zipf.write(trades_csv, trades_csv.name)
                                print(f"   📄 Добавлен в архив: {trades_csv.name}")

                    # Удаляем оригинальный файл
                    log_file.unlink()
                    archived_count += 1
                    print(f"✅ Заархивирован: {log_file.name} → {zip_name}")
                except Exception as e:
                    print(f"⚠️ Ошибка архивации {log_file.name}: {e}")

    # ✅ ИСПРАВЛЕНО 2: Обрабатываем .log.zip файлы в корне (уже заархивированные)
    for zip_file in logs_path.glob("*.log.zip"):
        mod_time = datetime.fromtimestamp(zip_file.stat().st_mtime)
        age_days = (now - mod_time).days

        if age_days >= keep_days:
            # Перемещаем в archived (если еще не там)
            archive_zip_path = archive_dir / zip_file.name
            if not archive_zip_path.exists():
                try:
                    zip_file.rename(archive_zip_path)
                    print(f"✅ Перемещен в архив: {zip_file.name}")
                except Exception as e:
                    print(f"⚠️ Ошибка перемещения {zip_file.name}: {e}")
            else:
                # Удаляем дубликат
                try:
                    zip_file.unlink()
                    deleted_count += 1
                    print(f"🗑️  Удален дубликат: {zip_file.name}")
                except Exception as e:
                    print(f"⚠️ Ошибка удаления дубликата {zip_file.name}: {e}")
        elif age_days >= auto_archive_days:
            # Перемещаем в archived (если еще не там)
            archive_zip_path = archive_dir / zip_file.name
            if not archive_zip_path.exists():
                try:
                    zip_file.rename(archive_zip_path)
                    archived_count += 1
                    print(f"✅ Перемещен в архив: {zip_file.name}")
                except Exception as e:
                    print(f"⚠️ Ошибка перемещения {zip_file.name}: {e}")

    # ✅ ИСПРАВЛЕНО 3: Обрабатываем существующие архивы в папке archived
    for zip_file in archive_dir.glob("*.zip"):
        mod_time = datetime.fromtimestamp(zip_file.stat().st_mtime)
        age_days = (now - mod_time).days

        if age_days >= keep_days:
            try:
                zip_file.unlink()
                deleted_count += 1
                print(f"🗑️  Удален архив (старше {keep_days} дней): {zip_file.name}")
            except Exception as e:
                print(f"⚠️ Ошибка удаления архива {zip_file.name}: {e}")

    print(f"\n📊 Итого: заархивировано {archived_count}, удалено {deleted_count}")


if __name__ == "__main__":
    archive_old_logs()
