# ========== patterns.py ==========
import re

# Номер заказа на производство
ORDER_NUMBER_PATTERN = r"ПС\d{2}[.\-]\d{2,4}[.\-]\d{1,2}(?:[.\-]\d{1,3})?"

# Номер документа ГЧ (или СБ)
GCH_NUMBER_PATTERN = r"([A-ZА-Я0-9]{1,3}[.\-]\d{1,4}[.\-]\d{3,4}[.\-]\d{3,4}(?:[.\-]\d{1,3})?\s*(?:ГЧ|СБ))"

# Номер документа Г3
G3_NUMBER_PATTERN = r"([A-ZА-Я0-9]{1,3}[.\-]\d{1,4}[.\-]\d{3,4}[.\-]\d{3,4}(?:[.\-]\d{1,3})?\s*Г[3З])"

# Номер документа ПГ3
PG3_NUMBER_PATTERN = r"([A-ZА-Я0-9]{1,3}[.\-]\d{1,4}[.\-]\d{3,4}[.\-]\d{3,4}(?:[.\-]\d{1,3})?\s*ПГ[3З])"

# Любой номер документа (для определения типа)
ANY_DOC_PATTERN = r"([A-ZА-Я0-9]{1,3}[.\-]\d{1,4}[.\-]\d{3,4}[.\-]\d{3,4}(?:[.\-]\d{1,3})?\s*(?:ГЧ|СБ|Г[3З]|ПГ[3З]))"

# Изделие (разные префиксы)
PRODUCT_PATTERNS = [
    r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]+",
    r"PM[.\-\s]?[A-ZА-Я0-9.\-]+",
    r"BLKV[.\-\s]?[A-ZА-Я0-9.\-]+",
    r"PNKV[.\-\s]?[A-ZА-Я0-9.\-]+",
    r"PPC[.\-\s]?[A-ZА-Я0-9.\-]+",
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
    for pattern in PRODUCT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return "НЕ НАЙДЕНО"


def detect_document_type(text: str) -> dict:
    """
    Определяет тип документа по распознанному тексту.
    Возвращает: {"type": "ГЧ"|"Г3"|"ПГ3"|"неизвестный", "number": "номер документа"}
    """
    # Ищем любой номер документа
    any_doc_match = re.search(ANY_DOC_PATTERN, text, re.IGNORECASE)
    
    if not any_doc_match:
        return {"type": "неизвестный", "number": "НЕ НАЙДЕНО"}
    
    doc_full = any_doc_match.group(0).strip()
    doc_number = any_doc_match.group(1).strip()
    
    # Определяем тип по суффиксу
    if re.search(r'ПГ[3З]', doc_full, re.IGNORECASE):
        doc_type = "ПГ3"
        doc_number = doc_number.replace('ПГЗ', 'ПГ3')
    elif re.search(r'ГЧ|СБ', doc_full, re.IGNORECASE):
        doc_type = "ГЧ"
    elif re.search(r'Г[3З]', doc_full, re.IGNORECASE):
        doc_type = "Г3"
        doc_number = doc_number.replace('ГЗ', 'Г3')
    else:
        doc_type = "неизвестный"
    
    return {"type": doc_type, "number": doc_number}