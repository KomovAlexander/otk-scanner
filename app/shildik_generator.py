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
    
    # Подбираем размер шрифта для изделия
    def calc_font_size(text, base_size=9.80472, max_width=65):
        """Подбирает размер шрифта, чтобы текст влез в ширину."""
        est_width = len(text) * 0.55 * base_size
        if est_width <= max_width:
            return base_size
        return max(4, base_size * (max_width / est_width))
    
    product_font_size = calc_font_size(product_name)
    
    # Заменяем изделие
    svg = svg.replace("CTR-KV-B1-0073", product_name)
    
    # Заменяем размер шрифта изделия
    svg = svg.replace("font-size:9.80472px", f"font-size:{product_font_size:.4f}px")
    
    # Дата
    svg = svg.replace("11.08.2026", test_date)
    
    # Серийный номер
    svg = svg.replace("091011082610", serial_number)
    
    return svg