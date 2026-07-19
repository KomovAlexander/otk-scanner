import re
import os
import base64
import json
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YANDEX_API_KEY")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")


def scan_document(image_path: str) -> dict:
    """
    Распознавание производственного бланка через Yandex Vision API.
    """
    # Проверяем что файл существует и не пустой
    print(f"Файл: {image_path}")
    print(f"Размер: {os.path.getsize(image_path)} байт")

    # ── Кодируем фото в base64 ────────────────────
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    print(f"Base64 длина: {len(image_base64)} символов")

    # ── Запрос к Yandex Vision ────────────────────
    url = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"
    headers = {
        "Authorization": f"Api-Key {API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "folderId": FOLDER_ID,
        "analyze_specs": [{
            "content": image_base64,
            "features": [{
                "type": "TEXT_DETECTION",
                "text_detection_config": {
                    "language_codes": ["ru", "en"]
                }
            }]
        }]
    }

    response = requests.post(url, json=body, headers=headers)
    print("STATUS:", response.status_code)
    
    if response.status_code != 200:
        print("ERROR:", response.text)
        return {
            "order_number": "ОШИБКА API",
            "product_name": "ОШИБКА API",
            "product_code": "",
            "department": "ОШИБКА API",
            "serial_number": "",
            "confidence": 0.0,
        }

    data = response.json()
    
    # Выведем полный ответ Яндекса
    print("ОТВЕТ Яндекс:")
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])

    # ── Собираем текст из ответа ──────────────────
    recognized_text = ""
    try:
        pages = data["results"][0]["results"][0]["textDetection"]["pages"]
        if not pages:
            print("ПУСТЫЕ СТРАНИЦЫ!")
        for page in pages:
            blocks = page.get("blocks", [])
            if not blocks:
                print("ПУСТЫЕ БЛОКИ!")
            for block in blocks:
                for line in block.get("lines", []):
                    words = line.get("words", [])
                    line_text = " ".join([w["text"] for w in words])
                    recognized_text += line_text + "\n"
    except (KeyError, IndexError) as e:
        print(f"ОШИБКА ПАРСИНГА: {e}")
        recognized_text = ""

    print("=" * 60)
    print("РАСПОЗНАНО:")
    print(recognized_text if recognized_text else "ПУСТО")
    print("=" * 60)

    if not recognized_text.strip():
        return {
            "order_number": "ТЕКСТ НЕ НАЙДЕН",
            "product_name": "ТЕКСТ НЕ НАЙДЕН",
            "product_code": "",
            "department": "ТЕКСТ НЕ НАЙДЕН",
            "serial_number": "",
            "confidence": 0.0,
        }

    # ── 1. Номер заказа ──────────────────────────
    order_match = re.search(
        r"Задание на производство\s*[№N]?\s*([A-Za-zА-Яа-я0-9.\-]+)",
        recognized_text,
        re.IGNORECASE,
    )
    order_number = order_match.group(1).strip() if order_match else "НЕ НАЙДЕНО"

    # ── 2. Подразделение ─────────────────────────
    dept_match = re.search(
        r"Подразделение\s*:?\s*(.+)",
        recognized_text,
        re.IGNORECASE,
    )
    department = dept_match.group(1).strip() if dept_match else "НЕ НАЙДЕНО"

    # ── 3. Изделие ───────────────────────────────
    product_match = re.search(
        r"Изделие\s*:?\s*\n\s*(.+)",
        recognized_text,
        re.IGNORECASE,
    )
    product_name = product_match.group(1).strip() if product_match else "НЕ НАЙДЕНО"

    # ── 5. Серийный номер ────────────────────────
    # Формат: 0***ДДММГГГГ01
    serial_number = ""
    if order_number != "НЕ НАЙДЕНО":
        ps_match = re.search(r"ПС\d{2}[.\-](\d{3,4})", order_number, re.IGNORECASE)
        if ps_match:
            ps_code = ps_match.group(1)  # "788"
            # Добиваем до 4 цифр нулями слева: 0788
            ps_code = ps_code.zfill(4)
        else:
            ps_code = "0000"

        from datetime import datetime
        date_part = datetime.now().strftime("%d%m%y")  # 19072026
        serial_number = f"{ps_code}{date_part}01"


    print(f"\n>>> РЕЗУЛЬТАТ: заказ={order_number}, отдел={department}, изделие={product_name}, серийный={serial_number}")

    return {
        "order_number": order_number,
        "product_name": product_name,
        "department": department,
        "serial_number": serial_number,
        "confidence": 0.99,
    }