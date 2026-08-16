# ========== debug_scanner.py ==========
"""
Скрипт для отладки распознавания Г3.
Запуск: python debug_scanner.py
"""

import os
import json
import sys

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr_engine import scan_document
from param_extractor import extract_params_via_gpt

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
    
    print(f"\n📝 Распознанный текст:")
    print(f"{'-'*40}")
    print(full_text[:2000] if full_text else "ПУСТО")
    print(f"{'-'*40}")

    # 2. GPT
    print("\n🤖 Шаг 2: Извлечение параметров (GPT)...")
    params = extract_params_via_gpt(full_text, "")

    print(f"\n📊 Извлечённые параметры:")
    print(json.dumps(params, ensure_ascii=False, indent=2))

    return {
        "file": file_path,
        "recognized_text": full_text,
        "params": params
    }


def main():
    # Создаём папку для результатов
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Ищем файлы в debug_samples
    if not os.path.exists(SAMPLES_DIR):
        print(f"❌ Папка '{SAMPLES_DIR}' не найдена!")
        print(f"Создай папку '{SAMPLES_DIR}' и положи туда фото/сканы Г3")
        return

    files = [f for f in os.listdir(SAMPLES_DIR) if f.endswith((".jpg", ".jpeg", ".png", ".pdf"))]

    if not files:
        print(f"❌ В папке '{SAMPLES_DIR}' нет файлов!")
        print("Положи туда фото или сканы Г3")
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