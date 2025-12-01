"""
Скрипт для полной распаковки архива логов.
Распаковывает главный ZIP и все вложенные ZIP файлы.
"""

import zipfile
import os
import sys
from pathlib import Path

def extract_all_nested_zips(archive_path: str, output_dir: str = None):
    """
    Распаковывает архив и все вложенные ZIP файлы рекурсивно.
    
    Args:
        archive_path: Путь к главному ZIP архиву
        output_dir: Папка для распаковки (по умолчанию рядом с архивом)
    """
    archive_path = Path(archive_path)
    
    if not archive_path.exists():
        print(f"❌ Файл не найден: {archive_path}")
        return
    
    # Определяем папку для распаковки
    if output_dir:
        output_path = Path(output_dir)
    else:
        # Создаём папку рядом с архивом с именем архива без расширения
        output_path = archive_path.parent / archive_path.stem
    
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"📂 Распаковка в: {output_path}")
    print("")
    
    # Шаг 1: Распаковываем главный архив
    print(f"📦 Распаковка главного архива: {archive_path.name}")
    try:
        with zipfile.ZipFile(archive_path, 'r') as zf:
            zf.extractall(output_path)
            main_files = zf.namelist()
            print(f"   ✅ Извлечено файлов: {len(main_files)}")
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return
    
    print("")
    
    # Шаг 2: Находим и распаковываем все вложенные ZIP файлы
    nested_zips = list(output_path.rglob("*.zip"))
    if nested_zips:
        print(f"📦 Найдено вложенных ZIP архивов: {len(nested_zips)}")
        print("")
        
        extracted_count = 0
        for i, nested_zip in enumerate(nested_zips, 1):
            try:
                # Создаём папку для распаковки вложенного архива
                # Имя папки = имя архива без .zip
                extract_to = nested_zip.parent / nested_zip.stem
                extract_to.mkdir(exist_ok=True)
                
                with zipfile.ZipFile(nested_zip, 'r') as zf:
                    zf.extractall(extract_to)
                    files_count = len(zf.namelist())
                
                # Удаляем вложенный ZIP после распаковки (опционально)
                # nested_zip.unlink()
                
                extracted_count += 1
                
                # Прогресс каждые 50 файлов
                if i % 50 == 0 or i == len(nested_zips):
                    print(f"   📊 Прогресс: {i}/{len(nested_zips)} архивов распаковано...")
                    
            except Exception as e:
                print(f"   ⚠️ Ошибка распаковки {nested_zip.name}: {e}")
        
        print(f"   ✅ Распаковано вложенных архивов: {extracted_count}")
    else:
        print("📦 Вложенных ZIP архивов не найдено")
    
    print("")
    
    # Шаг 3: Статистика
    all_files = list(output_path.rglob("*"))
    all_logs = list(output_path.rglob("*.log"))
    all_csv = list(output_path.rglob("*.csv"))
    all_json = list(output_path.rglob("*.json"))
    
    print("📊 СТАТИСТИКА РАСПАКОВКИ:")
    print(f"   Всего файлов: {len([f for f in all_files if f.is_file()])}")
    print(f"   LOG файлов: {len(all_logs)}")
    print(f"   CSV файлов: {len(all_csv)}")
    print(f"   JSON файлов: {len(all_json)}")
    print("")
    print(f"✅ Готово! Файлы распакованы в: {output_path}")
    
    return output_path


def main():
    # По умолчанию - архив из задачи
    default_archive = r"C:\Users\krivo\simple trading bot okx\logs\futures\archived\logs_2025-12-01_21-39-44.zip"
    
    # Можно передать путь как аргумент
    if len(sys.argv) > 1:
        archive_path = sys.argv[1]
    else:
        archive_path = default_archive
    
    print("=" * 60)
    print("🗜️ ПОЛНАЯ РАСПАКОВКА АРХИВА ЛОГОВ")
    print("=" * 60)
    print("")
    
    extract_all_nested_zips(archive_path)


if __name__ == "__main__":
    main()

