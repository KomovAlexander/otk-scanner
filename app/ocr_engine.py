# ========== ocr_engine.py ==========

import re
import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YANDEX_API_KEY")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")


def scan_document(image_path: str) -> dict:
    """Распознавание производственного бланка через Yandex Vision API."""

    print(f"Файл: {image_path}")
    print(f"Размер: {os.path.getsize(image_path)} байт")

    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

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

    if response.status_code != 200:
        print("ERROR:", response.text)
        return {
            "order_number": "ОШИБКА API",
            "product_name": "ОШИБКА API",
            "department": "ОШИБКА API",
            "confidence": 0.0,
        }

    data = response.json()

    recognized_text = ""
    try:
        for page in data["results"][0]["results"][0]["textDetection"]["pages"]:
            for block in page.get("blocks", []):
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
            "order_number": "ОШИБКА API",
            "product_name": "ОШИБКА API",
            "department": "ОШИБКА API",
            "confidence": 0.0,
            "full_text": "",
        }

    from app.patterns import extract_order_number, extract_product_name

    # 1. Номер заказа
    order_number = extract_order_number(recognized_text)
    if order_number == "НЕ НАЙДЕНО":
        # Запасной: "Задание на производство № ..."
        order_match = re.search(
            r"(?:Задание\s+)?(?:на|Hа)\s+производство\s*[№N]?\s*([A-Za-zА-Яа-я0-9.\-]+)",
            recognized_text, re.IGNORECASE,
        )
        if order_match:
            order_number = order_match.group(1).strip()

    # 2. Подразделение
    dept_match = re.search(
        r"Подразделение\s*:?\s*(.+)",
        recognized_text, re.IGNORECASE,
    )
    department = dept_match.group(1).strip() if dept_match else "НЕ НАЙДЕНО"

    # 3. Изделие
    product_name = extract_product_name(recognized_text)

    print(
        f"\n>>> РЕЗУЛЬТАТ: заказ={order_number}, отдел={department}, изделие={product_name}")

    return {
        "order_number": order_number,
        "product_name": product_name,
        "department": department,
        "confidence": 0.99,
        "full_text": recognized_text,
    }
