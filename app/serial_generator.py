from datetime import datetime
import random
import string


# Словарь сокращений для популярных типов изделий
ABBREVIATIONS = {
    "вал": "ВЛ",
    "вал-шестерня": "ВШ",
    "корпус": "КР",
    "редуктор": "РД",
    "фланец": "ФЛ",
    "муфта": "МФ",
    "шестерня": "ШС",
    "плита": "ПЛ",
    "кронштейн": "КРШ",
    "крышка": "КРШК",
}


def generate_serial(product_name: str) -> str:
    """
    Генерирует читаемый серийный номер.
    Формат: [ТИП]-[ГГММДД]-[XXXX]
    Пример: ВШ-250719-A3F8
    """
    # Определяем тип изделия
    product_lower = product_name.lower()
    type_code = "ИЗД"  # По умолчанию

    for key, code in ABBREVIATIONS.items():
        if key in product_lower:
            type_code = code
            break

    # Дата (сегодня)
    date_part = datetime.now().strftime("%y%m%d")

    # Случайный 4-значный хвост (буквы + цифры)
    tail = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

    return f"{type_code}-{date_part}-{tail}"