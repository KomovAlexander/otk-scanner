# ========== shildik_generator.py ==========
"""
Генератор шильдика на основе SVG-шаблона.
"""

import os
import re

TEMPLATE_PATH = "app/static/images/shildik_template.svg"


def generate_shildik_svg(product_name: str, serial_number: str, test_date: str, order_number: str = "") -> str:
    """Заменяет поля в SVG-шаблоне."""
    
    if not os.path.exists(TEMPLATE_PATH):
        return f"Ошибка: файл шаблона не найден: {TEMPLATE_PATH}"
    
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        svg = f.read()
    
    # Заменяем изделие
    svg = svg.replace("PPC-KV0252-2", product_name)
    
    # Дата
    svg = svg.replace("03.08.2026", test_date)
    
    # Серийный номер
    svg = svg.replace("094703082601", serial_number)
    
    return svg