import cv2
import numpy as np
import base64
import requests
import os
import re
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YANDEX_API_KEY")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")


def boost_colors(image_path):
    """Усиливает насыщенность цветов на фото в 1.5 раза."""
    img = cv2.imread(image_path)
    if img is None:
        return image_path
    
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.2, 0, 255).astype(np.uint8)
    img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    cv2.imwrite(image_path, img)
    print("🎨 Насыщенность цветов усилена!")
    return image_path


def is_green_pixel(r, g, b, threshold=40):
    max_rgb = max(int(r), int(g), int(b))
    min_rgb = min(int(r), int(g), int(b))
    saturation = max_rgb - min_rgb
    brightness = (int(r) + int(g) + int(b)) / 3
    return saturation > threshold and 30 < brightness < 240


def get_background_color(img, vertices, offset=3):
    h, w = img.shape[:2]
    xs, ys = [], []
    for v in vertices:
        if isinstance(v, dict):
            xs.append(int(v.get("x", 0)))
            ys.append(int(v.get("y", 0)))
        else:
            xs.append(int(v[0]))
            ys.append(int(v[1]))

    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)

    bg_pixels = []
    for y in range(max(0, y1 - offset), min(h, y1)):
        for x in range(max(0, x1), min(w, x2)):
            bg_pixels.append(img[y, x])
    for y in range(max(0, y2), min(h, y2 + offset)):
        for x in range(max(0, x1), min(w, x2)):
            bg_pixels.append(img[y, x])
    for y in range(max(0, y1), min(h, y2)):
        for x in range(max(0, x1 - offset), min(w, x1)):
            bg_pixels.append(img[y, x])
    for y in range(max(0, y1), min(h, y2)):
        for x in range(max(0, x2), min(w, x2 + offset)):
            bg_pixels.append(img[y, x])

    if not bg_pixels:
        return (0, 0, 0)

    avg = np.mean(bg_pixels, axis=0)
    return (int(avg[2]), int(avg[1]), int(avg[0]))


def extract_all_colored_numbers(image_path: str) -> list:
    # Усиливаем цвета перед распознаванием
    # Усиливаем цвета
    boost_colors(image_path)
    
    # Загружаем усиленное изображение
    img = cv2.imread(image_path)
    # Сохраняем обработанное изображение для отладки
    debug_dir = os.path.join(os.path.dirname(image_path), "debug_gch")
    os.makedirs(debug_dir, exist_ok=True)
    from datetime import datetime
    timestamp = datetime.now().strftime("%H%M%S")
    debug_path = os.path.join(debug_dir, f"boosted_{timestamp}.jpg")
    cv2.imwrite(debug_path, img)
    print(f"📷 Обработанное фото сохранено: {debug_path}")
    img = cv2.imread(image_path)
    if img is None:
        print("Ошибка загрузки изображения")
        return []

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
        return []

    data = response.json()
    colored_texts = []

    try:
        for page in data["results"][0]["results"][0]["textDetection"]["pages"]:
            for block in page.get("blocks", []):
                for line in block.get("lines", []):
                    for word in line.get("words", []):
                        text = word["text"]
                        bbox = word["boundingBox"]["vertices"]
                        bg_r, bg_g, bg_b = get_background_color(img, bbox, offset=5)

                        if is_green_pixel(bg_r, bg_g, bg_b, threshold=30):
                            colored_texts.append(text)
                            print(f"  🟢 '{text}' — R={bg_r}, G={bg_g}, B={bg_b}")
    except (KeyError, IndexError, TypeError) as e:
        print(f"Ошибка: {e}")
        return []

    if not colored_texts:
        print("Цветной текст не найден")
        return []

    combined = " ".join(colored_texts)
    print(f"Цветной текст: {combined}")

    numbers = re.findall(r'\d+[.,]?\d*', combined)
    numbers = [n.replace(',', '.') for n in numbers]

    print(f"Найдено размеров: {numbers}")
    # Фильтруем: целые числа >= 10, не начинаются с 0
    filtered = []
    for n in numbers:
        try:
            val = float(n)
            if val > 1 and '.' not in n and not n.startswith('0') and n not in filtered:
                filtered.append(n)
        except ValueError:
            pass
    
    print(f"Найдено размеров (>=10): {filtered}")
    return filtered