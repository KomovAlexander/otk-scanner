# ========== test_orders_scanner.py ==========
"""
Скрипт для тестирования распознавания документов из папок заказов.
Запуск: python test_orders_scanner.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ocr_engine import scan_document
from app.param_extractor import extract_params_via_gpt, extract_pg3_via_gpt
from app.green_extractor import extract_all_colored_numbers

UPLOAD_ROOT = "app/static/uploads"


def test_order_documents():
    """Тестирует распознавание всех документов в папках заказов."""
    
    if not os.path.exists(UPLOAD_ROOT):
        print(f"❌ Папка {UPLOAD_ROOT} не найдена")
        return
    
    # Находим все папки заказов
    order_dirs = []
    for entry in os.listdir(UPLOAD_ROOT):
        if entry.startswith("order_"):
            order_dirs.append(entry)
    
    if not order_dirs:
        print("❌ Папки заказов не найдены")
        return
    
    print(f"Найдено заказов: {len(order_dirs)}")
    
    results = []
    
    for order_dir in sorted(order_dirs):
        order_id = order_dir.replace("order_", "")
        order_path = os.path.join(UPLOAD_ROOT, order_dir)
        
        print(f"\n{'='*60}")
        print(f"📦 Заказ {order_id}")
        print(f"{'='*60}")
        
        # Проверяем файлы в папке заказа
        files = os.listdir(order_path)
        print(f"Файлы: {files}")
        
        # Тестируем каждый тип документа
        doc_types = {
            "order.jpg": "Заказ",
            "gch.jpeg": "ГЧ",
            "g3.jpeg": "Г3",
            "pg3.jpeg": "ПГ3",
            "gch.jpg": "ГЧ",
            "g3.jpg": "Г3",
            "pg3.jpg": "ПГ3",
        }
        
        order_result = {
            "order_id": order_id,
            "documents": {}
        }
        
        for file_name, doc_type in doc_types.items():
            file_path = os.path.join(order_path, file_name)
            if os.path.exists(file_path):
                print(f"\n--- Тестирую: {file_name} ({doc_type}) ---")
                
                # Распознавание
                result = scan_document(file_path)
                full_text = result.get("full_text", "")
                
                print(f"Распознанный текст ({len(full_text)} символов):")
                print(full_text[:500])
                
                # Извлечение номера документа
                import re
                
                if doc_type == "ГЧ":
                    doc_match = re.search(
                        r"([A-ZА-Я0-9]{1,3}[.\-]\d{1,4}[.\-]\d{3,4}[.\-]\d{3,4}(?:[.\-]\d{1,3})?\s*(?:ГЧ|СБ))",
                        full_text, re.IGNORECASE
                    )
                    doc_number = doc_match.group(1).strip() if doc_match else "НЕ НАЙДЕНО"
                    
                    # Дополнительно: RAL и размеры
                    ral_match = re.search(r"RAL\s*(\d{4})", full_text, re.IGNORECASE)
                    ral = ral_match.group(1) if ral_match else ""
                    
                    # Размеры
                    numbers = extract_all_colored_numbers(file_path)
                    
                    print(f"📐 Номер ГЧ: {doc_number}")
                    print(f"🎨 RAL: {ral}")
                    print(f"📏 Размеры: {numbers}")
                    
                    order_result["documents"]["gch"] = {
                        "number": doc_number,
                        "ral": ral,
                        "sizes": numbers,
                        "recognized_text": full_text[:1000]
                    }
                
                elif doc_type == "Г3":
                    doc_match = re.search(
                        r"([A-ZА-Я0-9]{1,3}[.\-]\d{1,4}[.\-]\d{3,4}[.\-]\d{3,4}(?:[.\-]\d{1,3})?\s*Г[3З])",
                        full_text, re.IGNORECASE
                    )
                    doc_number = doc_match.group(1).strip().replace('ГЗ', 'Г3') if doc_match else "НЕ НАЙДЕНО"
                    
                    # Параметры
                    params = extract_params_via_gpt(full_text, "")
                    
                    print(f"🔧 Номер Г3: {doc_number}")
                    print(f"📊 Параметры: {len(params)} шт.")
                    
                    order_result["documents"]["g3"] = {
                        "number": doc_number,
                        "params": params,
                        "recognized_text": full_text[:1000]
                    }
                
                elif doc_type == "ПГ3":
                    doc_match = re.search(
                        r"([A-ZА-Я0-9]{1,3}[.\-]\d{1,4}[.\-]\d{3,4}[.\-]\d{3,4}(?:[.\-]\d{1,3})?\s*ПГ[3З])",
                        full_text, re.IGNORECASE
                    )
                    doc_number = doc_match.group(1).strip().replace('ПГЗ', 'ПГ3') if doc_match else "НЕ НАЙДЕНО"
                    
                    # Позиции
                    items = extract_pg3_via_gpt(full_text, "")
                    
                    print(f"📋 Номер ПГ3: {doc_number}")
                    print(f"📦 Позиции: {len(items)} шт.")
                    
                    order_result["documents"]["pg3"] = {
                        "number": doc_number,
                        "items": items,
                        "recognized_text": full_text[:1000]
                    }
                
                elif doc_type == "Заказ":
                    order_match = re.search(
                        r"ПС\d{2}[.\-]\d{2,4}[.\-]\d{1,2}(?:[.\-]\d{1,3})?",
                        full_text, re.IGNORECASE
                    )
                    order_number = order_match.group(0) if order_match else "НЕ НАЙДЕНО"
                    
                    print(f"📄 Номер заказа: {order_number}")
                    
                    order_result["documents"]["order"] = {
                        "number": order_number,
                        "recognized_text": full_text[:1000]
                    }
        
        results.append(order_result)
    
    # Сохраняем результаты
    output_file = "test_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Результаты сохранены в {output_file}")


if __name__ == "__main__":
    test_order_documents()