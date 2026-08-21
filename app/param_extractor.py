# ========== param_extractor.py ==========

import requests
import os
import re
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YANDEX_API_KEY")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")


def call_gpt_with_error_handling(prompt: str, max_tokens: int = 2000, system_text: str = "Ты — инженер.") -> str:
    """
    Вызывает YandexGPT и возвращает текст ответа.
    При ошибке API бросает исключение с понятным сообщением.
    """
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
            "maxTokens": max_tokens,
        },
        "messages": [
            {"role": "system", "text": system_text},
            {"role": "user", "text": prompt}
        ]
    }

    response = requests.post(url, json=body, headers=headers)
    
    if response.status_code != 200:
        print(f"Ошибка YandexGPT: {response.status_code}")
        print(f"Ответ: {response.text[:500]}")
        raise Exception(f"YandexGPT API error: {response.status_code}")
    
    data = response.json()
    try:
        return data["result"]["alternatives"][0]["message"]["text"]
    except (KeyError, IndexError) as e:
        print(f"Ошибка парсинга ответа GPT: {e}")
        raise Exception("YandexGPT API error: invalid response format")


def extract_params_via_gpt(recognized_text: str, product_name: str) -> list:
    """Отправляет текст в YandexGPT для извлечения параметров."""

    # Если текст пустой — не отправляем в GPT
    if not recognized_text or not recognized_text.strip():
        print("⚠️ Пустой текст, GPT не вызывается")
        return []

    prompt = f"""Распознанный текст с гидравлической схемы:
{recognized_text[:8000]}

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

    text = call_gpt_with_error_handling(
        prompt, 
        max_tokens=5000,
        system_text="Ты — инженер. Извлекай параметры из текста схемы строго по стандартной структуре."
    )

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

    # Если текст пустой — не отправляем в GPT
    if not recognized_text or not recognized_text.strip():
        print("⚠️ Пустой текст, GPT не вызывается")
        return []

    # Очищаем текст от мусора
    lines = recognized_text.split("\n")
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Оставляем только содержательные строки
        if re.match(r'^\d+$', line) or len(line) > 3:
            clean_lines.append(line)

    clean_text = "\n".join(clean_lines)
    print(f"Исходный текст: {len(recognized_text)} символов")
    print(f"Очищенный текст: {len(clean_text)} символов")

    # Разбиваем текст на части по ~500 символов
    chunk_size = 500
    chunks = []
    for i in range(0, len(clean_text), chunk_size):
        chunk = clean_text[i:i + chunk_size]
        if chunk.strip():
            chunks.append(chunk)

    print(f"Текст разбит на {len(chunks)} частей")

    all_items = []

    for chunk_index, chunk in enumerate(chunks):
        print(f"\n--- Часть {chunk_index + 1} из {len(chunks)} ---")

        prompt = f"""Извлеки позиции из этого фрагмента перечня элементов (ПГ3):
{chunk}

ВАЖНО: Верни ТОЛЬКО JSON-массив с полями position, name, quantity.
Если количество не указано — quantity = "1".
Если строка не является позицией — пропусти её.

Верни ТОЛЬКО JSON-массив, без лишнего текста."""

        text = call_gpt_with_error_handling(
            prompt,
            max_tokens=3000,
            system_text="Ты — инженер. Извлекай перечень элементов в формате JSON."
        )

        print(f"Длина ответа: {len(text)} символов")

        text = text.replace("```json", "").replace("```", "").strip()

        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            try:
                items = json.loads(json_match.group(0))
                for item in items:
                    if isinstance(item, dict) and "name" in item:
                        quantity = str(item.get("quantity", "")).strip()
                        if not quantity:
                            quantity = "1"
                        all_items.append({
                            "position": str(item.get("position", "")).strip(),
                            "name": item.get("name", ""),
                            "quantity": quantity
                        })
                print(f"Извлечено {len(items)} позиций из части {chunk_index + 1}")
            except json.JSONDecodeError as e:
                print(f"Ошибка парсинга JSON: {e}")
                print(f"Текст ответа: {text[:300]}...")

    # Убираем дубликаты по position
    seen_positions = set()
    unique_items = []
    for item in all_items:
        if item["position"] and item["position"] not in seen_positions:
            seen_positions.add(item["position"])
            unique_items.append(item)
        elif not item["position"]:
            unique_items.append(item)

    print(f"\nВсего извлечено {len(unique_items)} позиций")
    return unique_items