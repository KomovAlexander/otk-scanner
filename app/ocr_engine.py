# ========== ocr_engine.py ==========

import re
import os
import base64
import json
import requests
import cv2
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YANDEX_API_KEY")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")


def perspective_correction(image_path):
    """
    Выравнивает изображение: находит границы листа и поворачивает его.
    Не обрезает — расширяет холст перед поворотом.
    """
    img = cv2.imread(image_path)
    if img is None:
        print("⚠️ Не удалось загрузить изображение для выравнивания")
        return image_path

    # Создаём папку для отладки
    debug_dir = os.path.join(os.path.dirname(image_path), "debug")
    os.makedirs(debug_dir, exist_ok=True)

    # Сохраняем оригинал
    timestamp = datetime.now().strftime("%H%M%S")
    original_path = os.path.join(debug_dir, f"original_{timestamp}.jpg")
    cv2.imwrite(original_path, img)
    print(f"📷 Оригинал сохранён: {original_path}")

    h, w = img.shape[:2]

    # Переводим в серый
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    # Ищем края
    edges = cv2.Canny(blur, 50, 150)

    # Ищем контуры
    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        print("⚠️ Контуры не найдены")
        return image_path

    # Ищем самый большой контур (весь лист)
    largest = max(contours, key=cv2.contourArea)

    # Находим минимальный прямоугольник, охватывающий контур
    rect = cv2.minAreaRect(largest)
    angle = rect[2]

    # Корректируем угол
    if angle < -45:
        angle += 90

    # Расширяем холст чтобы при повороте не обрезалось
    diagonal = int(np.sqrt(h**2 + w**2))
    expanded = np.ones((diagonal, diagonal, 3), dtype=np.uint8) * 255

    # Вставляем оригинал в центр расширенного холста
    y_offset = (diagonal - h) // 2
    x_offset = (diagonal - w) // 2
    expanded[y_offset:y_offset+h, x_offset:x_offset+w] = img

    # Поворачиваем расширенное изображение
    center = (diagonal // 2, diagonal // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(expanded, M, (diagonal, diagonal),
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))

    # Обрезаем белые края после поворота
    gray_rotated = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray_rotated, 250, 255, cv2.THRESH_BINARY_INV)
    coords = cv2.findNonZero(thresh)
    if coords is not None:
        x, y, cw, ch = cv2.boundingRect(coords)
        # Добавляем небольшой отступ
        pad = 20
        x = max(0, x - pad)
        y = max(0, y - pad)
        cw = min(rotated.shape[1] - x, cw + pad*2)
        ch = min(rotated.shape[0] - y, ch + pad*2)
        rotated = rotated[y:y+ch, x:x+cw]

    # Сохраняем результат
    corrected_path = os.path.join(debug_dir, f"corrected_{timestamp}.jpg")
    cv2.imwrite(corrected_path, rotated)
    print(f"📐 Исправлено сохранено: {corrected_path}")
    print(f"📐 Поворот на {angle:.1f}°")

    # Сохраняем поверх исходного
    cv2.imwrite(image_path, rotated)

    return image_path


def scan_document(image_path: str) -> dict:
    """
    Распознавание производственного бланка через Yandex Vision API.
    """
    # Автовыравнивание перспективы перед распознаванием
    perspective_correction(image_path)

    print(f"Файл: {image_path}")
    print(f"Размер: {os.path.getsize(image_path)} байт")

    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    print(f"Base64 длина: {len(image_base64)} символов")

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

    # ── 1. Номер заказа ──────────────────────────
    order_match = re.search(
        r"ПС\d{2}[.\-]\d{2,4}[.\-]\d{1,2}(?:[.\-]\d{1,3})?",
        recognized_text, re.IGNORECASE,
    )
    if order_match:
        order_number = order_match.group(0)
    else:
        order_match = re.search(
            r"(?:Задание\s+)?(?:на|Hа)\s+производство\s*[№N]?\s*([A-Za-zА-Яа-я0-9.\-]+)",
            recognized_text, re.IGNORECASE,
        )
        order_number = order_match.group(
            1).strip() if order_match else "НЕ НАЙДЕНО"

    # ── 2. Подразделение ─────────────────────────
    dept_match = re.search(
        r"Подразделение\s*:?\s*(.+)",
        recognized_text, re.IGNORECASE,
    )
    department = dept_match.group(1).strip() if dept_match else "НЕ НАЙДЕНО"

    # ── 3. Изделие ───────────────────────────────
    # Ищем "Изделие:" и ближайший CTR-KV после него
    product_match = re.search(
        r"Изделие\s*:?\s*\n\s*(.+)",
        recognized_text, re.IGNORECASE,
    )
    if product_match:
        product_name = product_match.group(1).strip()
        # Если не похоже на изделие — ищем CTR-KV дальше
        if "CTR" not in product_name.upper():
            product_match = re.search(
                r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}",
                recognized_text, re.IGNORECASE,
            )
            product_name = product_match.group(
                0).strip() if product_match else "НЕ НАЙДЕНО"
    else:
        # Запасной: ищем CTR-KV в любом месте
        product_match = re.search(
            r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}",
            recognized_text, re.IGNORECASE,
        )
        product_name = product_match.group(
            0).strip() if product_match else "НЕ НАЙДЕНО"

    print(f"\n>>> РЕЗУЛЬТАТ: заказ={order_number}, отдел={department}, изделие={product_name}")

    return {
        "order_number": order_number,
        "product_name": product_name,
        "department": department,
        "confidence": 0.99,
        "full_text": recognized_text,
    }