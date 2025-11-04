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
    Архивация старых логов

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

    # Обрабатываем .log файлы
    for log_file in logs_path.glob("*.log"):
        if log_file.name.endswith(".zip"):
            continue

        # Получаем время модификации
        mod_time = datetime.fromtimestamp(log_file.stat().st_mtime)
        age_days = (now - mod_time).days

        # Если файл старше auto_archive_days и еще не заархивирован
        if age_days >= auto_archive_days:
            # Создаем архив
            zip_name = f"{log_file.stem}.zip"
            zip_path = archive_dir / zip_name

            if not zip_path.exists():
                try:
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                        zipf.write(log_file, log_file.name)

                    # Удаляем оригинальный файл
                    log_file.unlink()
                    archived_count += 1
                    print(f"✅ Заархивирован: {log_file.name} → {zip_name}")
                except Exception as e:
                    print(f"⚠️ Ошибка архивации {log_file.name}: {e}")

        # Если файл старше keep_days - удаляем
        elif age_days >= keep_days:
            try:
                log_file.unlink()
                deleted_count += 1
                print(f"🗑️  Удален (старше {keep_days} дней): {log_file.name}")
            except Exception as e:
                print(f"⚠️ Ошибка удаления {log_file.name}: {e}")

    # Обрабатываем существующие архивы
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
