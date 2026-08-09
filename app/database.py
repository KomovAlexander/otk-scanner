import sqlite3
import os

DB_PATH = "otk.db"


def get_db():
    """Создаёт подключение к SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт все таблицы, если их нет."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL,
            product_name TEXT DEFAULT '',
            department TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gch_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            gch_number TEXT DEFAULT '',
            ral TEXT DEFAULT '',
            sizes TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS g3_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            g3_number TEXT DEFAULT '',
            params TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pg3_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            pg3_number TEXT DEFAULT '',
            items TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)
    # Результаты визуального контроля
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visual_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            data TEXT DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    # Результаты измерений
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS measurement_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            data TEXT DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)
    conn.commit()
    conn.close()


def get_or_create_order(order_number: str, product_name: str, department: str) -> int:
    """Находит существующий заказ или создаёт новый."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM orders WHERE order_number = ?", (order_number,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            "UPDATE orders SET product_name = ?, department = ? WHERE id = ?",
            (product_name, department, existing["id"]),
        )
        conn.commit()
        conn.close()
        return existing["id"]
    else:
        cursor.execute(
            "INSERT INTO orders (order_number, product_name, department) VALUES (?, ?, ?)",
            (order_number, product_name, department),
        )
        conn.commit()
        order_id = cursor.lastrowid
        conn.close()
        return order_id


def save_gch(order_id: int, gch_number: str, ral: str, sizes: list):
    """Сохраняет данные ГЧ (удаляет старую запись для этого заказа)."""
    import json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM gch_data WHERE order_id = ?", (order_id,))
    cursor.execute(
        "INSERT INTO gch_data (order_id, gch_number, ral, sizes) VALUES (?, ?, ?, ?)",
        (order_id, gch_number, ral, json.dumps(sizes, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def save_g3(order_id: int, g3_number: str, params: list):
    """Сохраняет данные Г3 (удаляет старую запись для этого заказа)."""
    import json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM g3_data WHERE order_id = ?", (order_id,))
    cursor.execute(
        "INSERT INTO g3_data (order_id, g3_number, params) VALUES (?, ?, ?)",
        (order_id, g3_number, json.dumps(params, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def save_pg3(order_id: int, pg3_number: str, items: list):
    """Сохраняет данные ПГ3 (удаляет старую запись для этого заказа)."""
    import json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pg3_data WHERE order_id = ?", (order_id,))
    cursor.execute(
        "INSERT INTO pg3_data (order_id, pg3_number, items) VALUES (?, ?, ?)",
        (order_id, pg3_number, json.dumps(items, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

def save_visual_results(order_id: int, data: dict):
    """Сохраняет результаты визуального контроля."""
    import json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO visual_results (order_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (order_id, json.dumps(data, ensure_ascii=False))
    )
    conn.commit()
    conn.close()


def get_visual_results(order_id: int) -> dict:
    """Загружает результаты визуального контроля."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM visual_results WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        import json
        return json.loads(row["data"])
    return {}


def save_measurement_results(order_id: int, data: dict):
    """Сохраняет результаты измерений."""
    import json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO measurement_results (order_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (order_id, json.dumps(data, ensure_ascii=False))
    )
    conn.commit()
    conn.close()


def get_measurement_results(order_id: int) -> dict:
    """Загружает результаты измерений."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM measurement_results WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        import json
        return json.loads(row["data"])
    return {}    