# ========== param_extractor.py ==========

import requests
import os
import re
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YANDEX_API_KEY")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")


def extract_params_via_gpt(recognized_text: str, product_name: str) -> list:
    """Отправляет текст в YandexGPT для извлечения параметров."""

    # Если текст пустой — не отправляем в GPT
    if not recognized_text or not recognized_text.strip():
        print("⚠️ Пустой текст, GPT не вызывается")
        return []

    prompt = f"""Распознанный текст с гидравлической схемы:
{recognized_text[:3000]}

Извлеки ВСЕ технические параметры в формате JSON-массива.

Используй СТРОГО следующие типы параметров:

1. valve_setting — "Давление открытия предохранительного клапана" (бар)
2. pump_flow — "Расход номинальный насоса" (л/мин)
3. pump_pressure — "Давление максимальное насоса" (бар)
4. motor_power — "Мощность электродвигателя" (кВт)
5. motor_voltage — "Номинальное напряжение электродвигателя" (В)
6. motor_rpm — "Частота вращения электродвигателя" (об/мин)
7. coil_voltage — "Напряжение катушек" (В) — БЕЗ position, всегда пустая строка
8. accumulator_charge — "Зарядка аккумулятора" (бар)
9. fluid — "Рабочая жидкость" — БЕЗ position, всегда пустая строка

НЕ включай: климатическое исполнение, температуру РЖ, номинальную частоту (Гц), направление вращения, объём бака.

ВАЖНЫЕ ПРАВИЛА:
- position: ТОЛЬКО цифры и точки (например "07.1", "08.1", "11.1"), БЕЗ скобок и лишних символов
- Для coil_voltage и fluid — position ВСЕГДА пустая строка ""
- value: ТОЛЬКО число (для числовых параметров) или строка (для fluid)
- tolerance: полное значение с единицей (например "+5 бар", "±10%", "±5%")
- Если tolerance нет — пустая строка
- Если параметров одного типа несколько (например, два насоса) — создай отдельный объект для каждого
- НЕ пропускай ни один параметр из списка

Каждый объект должен иметь поля:
- type: тип (из списка выше)
- name: СТРОГО стандартное название (из списка выше)
- position: позиция на схеме (ТОЛЬКО цифры и точки, для coil_voltage и fluid — пустая строка)
- value: значение (число или строка)
- unit: единица измерения (из списка выше)
- tolerance: допуск с единицей (если указан, иначе пустая строка)

Верни ТОЛЬКО JSON-массив, без лишнего текста."""

    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "modelUri": f"gpt://{FOLDER_ID}/yandexgpt",
        "completionOptions": {
            "stream": False,
            "temperature": 0.0,
            "maxTokens": 2000,
        },
        "messages": [
            {"role": "system", "text": "Ты — инженер. Извлекай параметры из текста схемы строго по стандартной структуре."},
            {"role": "user", "text": prompt}
        ]
    }

    response = requests.post(url, json=body, headers=headers)
    if response.status_code != 200:
        print(f"Ошибка YandexGPT: {response.status_code}")
        return []

    data = response.json()
    try:
        text = data["result"]["alternatives"][0]["message"]["text"]
    except (KeyError, IndexError):
        return []

    print(f"GPT ответ: {text[:500]}")

    # Убираем Markdown-обёртку ```
    text = text.replace("```json", "").replace("```", "").strip()

    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if json_match:
        try:
            params = json.loads(json_match.group(0))
            # Нормализуем: проверяем, что все обязательные поля есть
            normalized = []
            for p in params:
                if isinstance(p, dict) and "name" in p and "value" in p:
                    # Очищаем position от скобок
                    position = str(p.get("position", "")).strip()
                    position = re.sub(r'[\[\]\(\)]', '', position)

                    # Пропускаем параметры с пустым value
                    value = p.get("value", "")
                    if value == "" or value is None:
                        continue

                    normalized.append({
                        "type": p.get("type", "other"),
                        "name": p.get("name", ""),
                        "position": position,
                        "value": value,
                        "unit": p.get("unit", ""),
                        "tolerance": p.get("tolerance", "")
                    })
            print(f"GPT извлёк {len(normalized)} параметров")
            return normalized
        except json.JSONDecodeError:
            pass

    return []


def extract_pg3_via_gpt(recognized_text: str, product_name: str) -> list:
    """Извлекает перечень элементов из ПГ3 через YandexGPT."""

    if not recognized_text or not recognized_text.strip():
        print("⚠️ Пустой текст, GPT не вызывается")
        return []

    prompt = f"""Извлеки ВСЕ позиции из перечня элементов (ПГ3):
{recognized_text[:8000]}

Верни ТОЛЬКО JSON-массив. Каждый объект:
{{"position": "номер", "name": "наименование", "quantity": "количество"}}

Если количество не указано — "1".
Верни JSON одной строкой, без переносов, без Markdown."""

    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "modelUri": f"gpt://{FOLDER_ID}/yandexgpt",
        "completionOptions": {
            "stream": False,
            "temperature": 0.0,
            "maxTokens": 8000,
        },
        "messages": [
            {"role": "system", "text": "Ты — инженер. Извлекай позиции из перечня элементов."},
            {"role": "user", "text": prompt}
        ]
    }

    response = requests.post(url, json=body, headers=headers)
    if response.status_code != 200:
        print(f"Ошибка YandexGPT: {response.status_code}")
        return []

    data = response.json()
    try:
        text = data["result"]["alternatives"][0]["message"]["text"]
    except (KeyError, IndexError):
        return []

    print(f"GPT ответ (ПГ3): {text[:500]}")
    print(f"Длина ответа: {len(text)} символов")

    text = text.replace("```json", "").replace("```", "").strip()

    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if json_match:
        try:
            items = json.loads(json_match.group(0))
            normalized = []
            for item in items:
                if isinstance(item, dict) and "name" in item:
                    quantity = str(item.get("quantity", "")).strip()
                    if not quantity:
                        quantity = "1"
                    normalized.append({
                        "position": str(item.get("position", "")).strip(),
                        "name": item.get("name", ""),
                        "quantity": quantity
                    })
            print(f"GPT извлёк {len(normalized)} позиций")
            return normalized
        except json.JSONDecodeError as e:
            print(f"Ошибка JSON: {e}")
            print(f"Полный ответ: {text}")

    return []