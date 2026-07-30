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

    prompt = f"""Распознанный текст с гидравлической схемы:
{recognized_text[:3000]}

Извлеки ВСЕ технические параметры в формате JSON-массива. Каждый объект должен иметь поля:
- type: тип параметра (valve_setting, pump_pressure, motor_power, motor_voltage, motor_rpm, coil_voltage, max_temp, fluid)
- name: название параметра
- value: значение
- unit: единица измерения
- tolerance: допуск (если есть)

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
            "maxTokens": 1000,
        },
        "messages": [
            {"role": "system", "text": "Ты — инженер. Извлекай параметры из текста схемы в формате JSON."},
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
            print(f"GPT извлёк {len(params)} параметров")
            return params
        except json.JSONDecodeError:
            pass

    return []
