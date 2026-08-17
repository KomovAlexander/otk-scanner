# ========== debug_scanner.py ==========
"""
Скрипт для отладки распознавания Г3 и ПГ3.
Запуск: python debug_scanner.py
"""

import os
import json
import sys

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr_engine import scan_document
from param_extractor import extract_params_via_gpt, extract_pg3_via_gpt

SAMPLES_DIR = "debug_samples"
OUTPUT_DIR = "debug_output"


def debug_scan(file_path: str):
    """Прогоняет файл через OCR и GPT, сохраняет результат."""
    print(f"\n{'='*60}")
    print(f"📄 Обрабатываю: {file_path}")
    print(f"{'='*60}")

    # 1. OCR
    print("\n🔍 Шаг 1: Распознавание текста (OCR)...")
    result = scan_document(file_path)
    full_text = result.get("full_text", "")
    
    print(f"\n📝 Распознанный текст ({len(full_text)} символов):")
    print(f"{'-'*40}")
    print(full_text[:2000] if full_text else "ПУСТО")
    print(f"{'-'*40}")

    # Определяем тип документа
    is_pg3 = "ПГ3" in full_text or "ПГЗ" in full_text or "Перечень элементов" in full_text
    is_g3 = "Г3" in full_text or "ГЗ" in full_text or "Схема гидравлическая" in full_text

    if is_pg3:
        # 2. GPT для ПГ3
        print("\n🤖 Шаг 2: Извлечение позиций ПГ3 (GPT)...")
        items = extract_pg3_via_gpt(full_text, "")
        print(f"\n📊 Извлечённые позиции:")
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return {
            "file": file_path,
            "type": "pg3",
            "recognized_text": full_text,
            "items": items
        }
    elif is_g3:
        # 2. GPT для Г3
        print("\n🤖 Шаг 2: Извлечение параметров Г3 (GPT)...")
        params = extract_params_via_gpt(full_text, "")
        print(f"\n📊 Извлечённые параметры:")
        print(json.dumps(params, ensure_ascii=False, indent=2))
        return {
            "file": file_path,
            "type": "g3",
            "recognized_text": full_text,
            "params": params
        }
    else:
        print("⚠️ Не удалось определить тип документа (Г3 или ПГ3)")
        return {
            "file": file_path,
            "type": "unknown",
            "recognized_text": full_text,
        }


def main():
    # Создаём папку для результатов
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Ищем файлы в debug_samples
    if not os.path.exists(SAMPLES_DIR):
        print(f"❌ Папка '{SAMPLES_DIR}' не найдена!")
        print(f"Создай папку '{SAMPLES_DIR}' и положи туда фото/сканы Г3 и ПГ3")
        return

    files = [f for f in os.listdir(SAMPLES_DIR) if f.endswith((".jpg", ".jpeg", ".png", ".pdf"))]

    if not files:
        print(f"❌ В папке '{SAMPLES_DIR}' нет файлов!")
        print("Положи туда фото или сканы Г3 и ПГ3")
        return

    print(f"🔎 Найдено файлов: {len(files)}")

    all_results = []

    for file_name in files:
        file_path = os.path.join(SAMPLES_DIR, file_name)
        try:
            result = debug_scan(file_path)
            all_results.append(result)
        except Exception as e:
            print(f"❌ Ошибка при обработке {file_name}: {e}")

    # Сохраняем всё в JSON
    output_file = os.path.join(OUTPUT_DIR, "debug_results.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Результаты сохранены в {output_file}")


if __name__ == "__main__":
    main()