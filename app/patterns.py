# ========== patterns.py ==========
import re

# Номер заказа на производство
ORDER_NUMBER_PATTERN = r"ПС\d{2}[.\-]\d{2,4}[.\-]\d{1,2}(?:[.\-]\d{1,3})?"

# Любой номер документа
ANY_DOC_PATTERN = r"([A-ZА-Я]+(?:[.\-]?[A-ZА-Я0-9]+)*[.\-\s]?\d{3,4}[.\-\s]\d{3,4}(?:[.\-\s]\d{1,3})?\s*(?:ГЧ|СБ|Г[3З]|ПГ[3З]))"

# ГЧ
GCH_NUMBER_PATTERN = r"([A-ZА-Я]+(?:[.\-]?[A-ZА-Я0-9]+)*[.\-\s]?\d{3,4}[.\-\s]\d{3,4}(?:[.\-\s]\d{1,3})?\s*(?:ГЧ|СБ))"

# Г3
G3_NUMBER_PATTERN = r"([A-ZА-Я]+(?:[.\-]?[A-ZА-Я0-9]+)*[.\-\s]?\d{3,4}[.\-\s]\d{3,4}(?:[.\-\s]\d{1,3})?\s*Г[3З])"

# ПГ3
PG3_NUMBER_PATTERN = r"([A-ZА-Я]+(?:[.\-]?[A-ZА-Я0-9]+)*[.\-\s]?\d{3,4}[.\-\s]\d{3,4}(?:[.\-\s]\d{1,3})?\s*ПГ[3З])"

# Изделие (разные префиксы)
PRODUCT_PATTERNS = [
    r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9]+(?:[.\-][A-ZА-Я0-9]+)*",
    r"BLKV[.\-\s]?[A-ZА-Я0-9]+(?:[.\-][A-ZА-Я0-9]+)*",
    r"PNKV[.\-\s]?[A-ZА-Я0-9]+(?:[.\-][A-ZА-Я0-9]+)*",
    r"PPC[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9]+(?:[.\-][A-ZА-Я0-9]+)*",
    r"PM(?!MD)[.\-\s]?[A-ZА-Я0-9]+(?:[.\-][A-ZА-Я0-9]+)*",
]


def extract_order_number(text: str) -> str:
    """Извлекает номер заказа из текста."""
    match = re.search(ORDER_NUMBER_PATTERN, text, re.IGNORECASE)
    return match.group(0).strip() if match else "НЕ НАЙДЕНО"


def extract_gch_number(text: str) -> str:
    """Извлекает номер ГЧ из текста."""
    match = re.search(GCH_NUMBER_PATTERN, text, re.IGNORECASE)
    return match.group(1).strip() if match else "НЕ НАЙДЕНО"


def extract_g3_number(text: str) -> str:
    """Извлекает номер Г3 из текста."""
    match = re.search(G3_NUMBER_PATTERN, text, re.IGNORECASE)
    return match.group(1).strip().replace('ГЗ', 'Г3') if match else "НЕ НАЙДЕНО"


def extract_pg3_number(text: str) -> str:
    """Извлекает номер ПГ3 из текста."""
    match = re.search(PG3_NUMBER_PATTERN, text, re.IGNORECASE)
    return match.group(1).strip().replace('ПГЗ', 'ПГ3') if match else "НЕ НАЙДЕНО"


def extract_product_name(text: str) -> str:
    """Извлекает название изделия из текста."""
    # Сначала ищем в строке "Изделие:"
    product_match = re.search(
        r"Изделие\s*:?\s*\n?\s*([A-ZА-Я0-9][A-ZА-Я0-9.\-]*)",
        text, re.IGNORECASE
    )
    if product_match:
        candidate = product_match.group(1).strip()
        # Отрезаем часть с ".000.000" если это номер документа
        candidate = re.sub(r'\.\d{3,4}\.\d{3,4}.*$', '', candidate)
        if candidate:
            return candidate.strip()
    
    # Запасной: ищем по паттернам изделий
    for pattern in PRODUCT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result = match.group(0).strip()
            # Отрезаем ".000.000" если есть
            result = re.sub(r'\.\d{3,4}\.\d{3,4}.*$', '', result)
            return result
    
    return "НЕ НАЙДЕНО"


def detect_document_type(text: str) -> dict:
    """Определяет тип документа по распознанному тексту."""
    
    # 1. Ищем тип по словам
    if re.search(r'Сборочный\s+чертёж', text, re.IGNORECASE):
        doc_type = "ГЧ"
    elif re.search(r'Габаритный\s+чертёж', text, re.IGNORECASE):
        doc_type = "ГЧ"
    elif re.search(r'Перечень\s+элементов', text, re.IGNORECASE):
        doc_type = "ПГ3"
    elif re.search(r'Схема\s+гидравлическая', text, re.IGNORECASE):
        doc_type = "Г3"
    else:
        doc_type = None  # ← None вместо "неизвестный"
    
    # 2. Ищем номер документа с суффиксом
    any_doc_match = re.search(ANY_DOC_PATTERN, text, re.IGNORECASE)
    
    if any_doc_match:
        doc_full = any_doc_match.group(0).strip()
        doc_number = any_doc_match.group(1).strip()
        
        # Определяем тип по суффиксу
        if re.search(r'ПГ[3З]', doc_full, re.IGNORECASE):
            suffix_type = "ПГ3"
        elif re.search(r'ГЧ|СБ', doc_full, re.IGNORECASE):
            suffix_type = "ГЧ"
        elif re.search(r'Г[3З]', doc_full, re.IGNORECASE):
            suffix_type = "Г3"
        else:
            suffix_type = None
        
        # Если тип по словам не найден, но суффикс есть
        if doc_type is None and suffix_type:
            doc_type = suffix_type
        
        return {"type": doc_type, "number": doc_number}
    
    # 3. Ищем номер без суффикса
    doc_match = re.search(
        r'([A-ZА-Я]+(?:[.\-]?[A-ZА-Я0-9]+)*[.\-\s]?\d{3,4}[.\-\s]\d{3,4}(?:[.\-\s]\d{1,3})?)',
        text, re.IGNORECASE
    )
    
    if doc_match:
        doc_number = doc_match.group(1).strip()
        return {"type": doc_type, "number": doc_number}
    
    return {"type": doc_type, "number": "НЕ НАЙДЕНО"}