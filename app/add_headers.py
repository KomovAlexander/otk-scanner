# ========== add_headers.py ==========
"""
Скрипт добавляет в начало каждого файла закомментированное название файла.
Поддерживает: .py, .html, .css, .js
Запуск: python add_headers.py
"""
import os
from pathlib import Path

# Корневая директория проекта
ROOT_DIR = Path(__file__).parent

# Директории, которые нужно обработать
TARGET_DIRS = ["app", "templates", "static"]  # можно добавить свои

# Расширения файлов и соответствующие стили комментариев
COMMENT_STYLES = {
    ".py": ("# ========== {filename} ==========\n", "# "),
    ".html": ("<!-- ========== {filename} ========== -->\n", "<!-- "),
    ".css": ("/* ========== {filename} ========== */\n", "/* "),
    ".js": ("// ========== {filename} ==========\n", "// "),
}

# Файлы, которые нужно пропустить
SKIP_FILES = {"__pycache__", ".git", ".venv", "venv", "env"}


def has_header(file_path: Path, filename: str, comment_start: str) -> bool:
    """Проверяет, есть ли уже заголовок с названием файла."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            first_lines = f.read(500)  # читаем первые 500 символов
        return f"========== {filename} ==========" in first_lines
    except (UnicodeDecodeError, PermissionError):
        return True  # пропускаем бинарные или недоступные файлы


def add_header_to_file(file_path: Path, ext: str) -> bool:
    """Добавляет заголовок в файл. Возвращает True если файл изменён."""
    filename = file_path.name
    comment_template = COMMENT_STYLES.get(ext.lower())
    
    if not comment_template:
        return False
    
    # Проверяем есть ли уже заголовок
    if has_header(file_path, filename, comment_template[1]):
        return False
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, PermissionError):
        return False
    
    # Формируем заголовок
    header = comment_template[0].format(filename=filename)
    
    # Добавляем заголовок в начало
    new_content = header + "\n" + content
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    return True


def process_directory(directory: Path) -> int:
    """Обрабатывает директорию рекурсивно. Возвращает количество изменённых файлов."""
    changed = 0
    
    if not directory.exists():
        print(f"⚠️ Директория не найдена: {directory}")
        return 0
    
    for root, dirs, files in os.walk(directory):
        # Пропускаем служебные директории
        dirs[:] = [d for d in dirs if d not in SKIP_FILES]
        
        for file in files:
            ext = Path(file).suffix.lower()
            if ext not in COMMENT_STYLES:
                continue
            
            file_path = Path(root) / file
            
            if add_header_to_file(file_path, ext):
                print(f"✅ Добавлен заголовок: {file_path.relative_to(ROOT_DIR)}")
                changed += 1
            else:
                print(f"⏭️ Пропущен (уже есть или недоступен): {file_path.relative_to(ROOT_DIR)}")
    
    return changed


def main():
    print("=" * 60)
    print("Добавление заголовков в файлы проекта")
    print("=" * 60)
    
    total_changed = 0
    
    # Обрабатываем корневые .py файлы
    for py_file in ROOT_DIR.glob("*.py"):
        if py_file.name == "add_headers.py":
            continue
        if add_header_to_file(py_file, ".py"):
            print(f"✅ Добавлен заголовок: {py_file.name}")
            total_changed += 1
    
    # Обрабатываем целевые директории
    for target_dir in TARGET_DIRS:
        dir_path = ROOT_DIR / target_dir
        if dir_path.exists():
            print(f"\n📁 Обработка директории: {target_dir}/")
            total_changed += process_directory(dir_path)
    
    print("\n" + "=" * 60)
    print(f"Готово! Изменено файлов: {total_changed}")
    print("=" * 60)


if __name__ == "__main__":
    main()