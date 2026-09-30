# ========== database.py ==========

import sqlite3
import os
import json

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
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
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

    # Страницы ПГ3 (несколько листов)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pg3_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            page_number INTEGER NOT NULL,
            pg3_number TEXT DEFAULT '',
            items TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            UNIQUE(order_id, page_number)
        )
    """)

    # Старая таблица pg3_data (оставляем для совместимости, но не используем)
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

    # Пользователи
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            middle_name TEXT DEFAULT '',
            position TEXT DEFAULT '',
            role TEXT DEFAULT 'tester',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Прогресс заказа
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            current_step TEXT NOT NULL DEFAULT 'order',
            completed_steps TEXT DEFAULT '[]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    # Запросы разрешений (например, работать без ГЧ)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS permission_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            admin_id INTEGER,
            admin_comment TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Добавляем колонку user_id если её нет
    cursor.execute("PRAGMA table_info(orders)")
    columns = [row["name"] for row in cursor.fetchall()]
    if "user_id" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")

    conn.commit()
    conn.close()


# ─── Функции для работы с прогрессом заказа ───
def init_order_progress(order_id: int):
    """Создаёт запись о прогрессе для заказа, если её ещё нет."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO order_progress (order_id, current_step, completed_steps) VALUES (?, 'gch', '[\"order\"]')",
        (order_id,)
    )
    conn.commit()
    conn.close()


def update_order_step(order_id: int, current_step: str, completed_steps: list = None):
    """Обновляет текущий шаг заказа. Если completed_steps не передан — только current_step."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT OR IGNORE INTO order_progress (order_id, current_step, completed_steps) VALUES (?, 'order', '[]')",
        (order_id,)
    )

    if completed_steps is not None:
        cursor.execute(
            "UPDATE order_progress SET current_step=?, completed_steps=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
            (current_step, json.dumps(completed_steps, ensure_ascii=False), order_id)
        )
    else:
        cursor.execute(
            "UPDATE order_progress SET current_step=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
            (current_step, order_id)
        )

    conn.commit()
    conn.close()


def get_order_progress(order_id: int) -> dict:
    """Возвращает прогресс заказа: {current_step, completed_steps}."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT current_step, completed_steps FROM order_progress WHERE order_id = ?",
        (order_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "current_step": row["current_step"],
            "completed_steps": json.loads(row["completed_steps"]) if row["completed_steps"] else []
        }
    return {"current_step": "order", "completed_steps": []}


def mark_step_completed(order_id: int, step: str, next_step: str):
    """Отмечает шаг как пройденный и переводит на следующий."""
    progress = get_order_progress(order_id)
    completed = progress["completed_steps"]

    if step not in completed:
        completed.append(step)

    update_order_step(order_id, next_step, completed)


# ─── Функции для работы со страницами ПГ3 ───
def get_pg3_pages(order_id: int) -> list:
    """Возвращает список страниц ПГ3."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM pg3_pages WHERE order_id = ? ORDER BY page_number",
        (order_id,)
    )
    pages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return pages


def save_pg3_page(order_id: int, page_number: int, pg3_number: str, items: list):
    """Сохраняет одну страницу ПГ3."""
    normalized_items = []
    for item in items:
        item = dict(item) if isinstance(item, dict) else {}
        if not item.get("quantity"):
            item["quantity"] = "1"
        normalized_items.append(item)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO pg3_pages (order_id, page_number, pg3_number, items) VALUES (?, ?, ?, ?)",
        (order_id, page_number, pg3_number, json.dumps(normalized_items, ensure_ascii=False))
    )
    conn.commit()
    conn.close()


def get_all_pg3_items(order_id: int) -> list:
    """Объединяет позиции со всех страниц ПГ3."""
    pages = get_pg3_pages(order_id)
    all_items = []
    for page in pages:
        items = json.loads(page.get("items", "[]"))
        all_items.extend(items)
    return all_items


def delete_pg3_page(page_id: int):
    """Удаляет страницу ПГ3."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pg3_pages WHERE id = ?", (page_id,))
    conn.commit()
    conn.close()


def clear_visual_pg3_for_order(order_id: int):
    """Очищает только ПГ3-часть визуального контроля."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM visual_results WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()

    if row:
        data = json.loads(row["data"])
        data["pg3_confirmed"] = []
        data["pg3_changes"] = []
        cursor.execute(
            "UPDATE visual_results SET data=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
            (json.dumps(data, ensure_ascii=False), order_id)
        )
        print(f"✅ ПГ3-часть визуального контроля очищена для order_id={order_id}")
    else:
        print(f"⚠️ Визуальный контроль не найден для order_id={order_id}")

    conn.commit()
    conn.close()


# ─── Функции для работы с заказами ───
def get_or_create_order(order_number: str, product_name: str, department: str, user_id: int = None) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM orders WHERE order_number = ?", (order_number,))
    existing = cursor.fetchone()
    if existing:
        if user_id:
            cursor.execute("UPDATE orders SET user_id=? WHERE id=?", (user_id, existing["id"]))
        conn.commit()
        conn.close()
        init_order_progress(existing["id"])
        return existing["id"]
    else:
        cursor.execute(
            "INSERT INTO orders (order_number, product_name, department, user_id) VALUES (?, ?, ?, ?)",
            (order_number, product_name, department, user_id),
        )
        conn.commit()
        order_id = cursor.lastrowid
        conn.close()
        init_order_progress(order_id)
        return order_id


def save_gch(order_id: int, gch_number: str, ral: str, sizes: list):
    """Сохраняет данные ГЧ."""
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
    """Сохраняет данные Г3."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM g3_data WHERE order_id = ?", (order_id,))
    cursor.execute(
        "INSERT INTO g3_data (order_id, g3_number, params) VALUES (?, ?, ?)",
        (order_id, g3_number, json.dumps(params, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def save_visual_results(order_id: int, data: dict):
    """Сохраняет результаты визуального контроля."""
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
        return json.loads(row["data"])
    return {}


def save_measurement_results(order_id: int, data: dict):
    """Сохраняет результаты измерений."""
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
        return json.loads(row["data"])
    return {}


def create_default_admin():
    """Создаёт админа по умолчанию."""
    import hashlib
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        password_hash = hashlib.sha256("admin".encode()).hexdigest()
        cursor.execute(
            "INSERT INTO users (login, password_hash, first_name, last_name, role) VALUES (?, ?, ?, ?, ?)",
            ("admin", password_hash, "Админ", "Системы", "admin"),
        )
        conn.commit()
    conn.close()


def get_user_by_login(login: str) -> dict | None:
    """Находит пользователя по логину."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE login = ?", (login,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users() -> list:
    """Возвращает всех пользователей."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY id")
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return users


def create_user(login: str, password: str, first_name: str, last_name: str, middle_name: str = "", position: str = "", role: str = "tester") -> int:
    """Создаёт пользователя."""
    import hashlib
    conn = get_db()
    cursor = conn.cursor()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    cursor.execute(
        "INSERT INTO users (login, password_hash, first_name, last_name, middle_name, position, role) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (login, password_hash, first_name, last_name, middle_name, position, role),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def delete_user(user_id: int):
    """Удаляет пользователя."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ? AND login != 'admin'", (user_id,))
    conn.commit()
    conn.close()


def update_user(user_id: int, first_name: str, last_name: str, middle_name: str = "", position: str = "", role: str = "tester"):
    """Обновляет данные пользователя."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET first_name=?, last_name=?, middle_name=?, position=?, role=? WHERE id=?",
        (first_name, last_name, middle_name, position, role, user_id),
    )
    conn.commit()
    conn.close()


def update_user_password(user_id: int, new_password: str):
    """Обновляет пароль пользователя."""
    import hashlib
    conn = get_db()
    cursor = conn.cursor()
    password_hash = hashlib.sha256(new_password.encode()).hexdigest()
    cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))
    conn.commit()
    conn.close()


def get_all_orders(user_id: int = None, is_admin: bool = False) -> list:
    conn = get_db()
    cursor = conn.cursor()

    if is_admin:
        cursor.execute("""
            SELECT o.*, 
                   (SELECT COUNT(*) FROM pg3_pages WHERE order_id = o.id) as has_pg3
            FROM orders o
            ORDER BY o.id DESC
        """)
    else:
        cursor.execute("""
            SELECT o.*, 
                   (SELECT COUNT(*) FROM pg3_pages WHERE order_id = o.id) as has_pg3
            FROM orders o
            WHERE o.user_id = ?
            ORDER BY o.id DESC
        """, (user_id,))

    orders = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return orders


def get_order_photos(order_id: int) -> list:
    """Возвращает список фото для заказа."""
    order_dir = os.path.join("app/static/uploads", f"order_{order_id}")
    if not os.path.exists(order_dir):
        return []

    photos = []
    for f in sorted(os.listdir(order_dir)):
        if f.startswith("photo_") and f.endswith((".jpg", ".jpeg", ".png")):
            photos.append(f"/uploads/order_{order_id}/{f}")
    return photos


def is_order_completed(order_id: int) -> bool:
    """Проверяет завершён ли заказ (есть ли фото)."""
    order_dir = os.path.join("app/static/uploads", f"order_{order_id}")
    if not os.path.exists(order_dir):
        return False

    for f in os.listdir(order_dir):
        if f.startswith("photo_") and f.endswith((".jpg", ".jpeg", ".png")):
            return True
    return False


def delete_order(order_id: int):
    """Удаляет заказ и все связанные данные."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM gch_data WHERE order_id = ?", (order_id,))
    cursor.execute("DELETE FROM g3_data WHERE order_id = ?", (order_id,))
    cursor.execute("DELETE FROM pg3_data WHERE order_id = ?", (order_id,))
    cursor.execute("DELETE FROM pg3_pages WHERE order_id = ?", (order_id,))
    cursor.execute("DELETE FROM visual_results WHERE order_id = ?", (order_id,))
    cursor.execute("DELETE FROM measurement_results WHERE order_id = ?", (order_id,))
    cursor.execute("DELETE FROM order_progress WHERE order_id = ?", (order_id,))
    cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    conn.commit()
    conn.close()

    import shutil
    order_dir = os.path.join("app/static/uploads", f"order_{order_id}")
    if os.path.exists(order_dir):
        shutil.rmtree(order_dir)



# ─── Функции для работы с запросами разрешений ───
def create_permission_request(order_id: int, user_id: int, type_: str, reason: str) -> int:
    """Создаёт запрос разрешения. Старые pending-запросы этого типа отменяет."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE permission_requests SET status='cancelled' "
        "WHERE order_id=? AND type=? AND status='pending'",
        (order_id, type_)
    )
    cursor.execute(
        "INSERT INTO permission_requests (order_id, user_id, type, reason) VALUES (?,?,?,?)",
        (order_id, user_id, type_, reason)
    )
    conn.commit()
    rid = cursor.lastrowid
    conn.close()
    return rid


def get_active_permission(order_id: int, type_: str) -> dict | None:
    """Возвращает последний запрос по заказу и типу (любого статуса)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM permission_requests WHERE order_id=? AND type=? "
        "ORDER BY id DESC LIMIT 1",
        (order_id, type_)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_requests() -> list:
    """Все активные запросы (для страницы админа)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pr.*, o.order_number, o.product_name,
               u.last_name, u.first_name, u.login
        FROM permission_requests pr
        JOIN orders o ON o.id = pr.order_id
        JOIN users u ON u.id = pr.user_id
        WHERE pr.status = 'pending'
        ORDER BY pr.id DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_all_requests(limit: int = 100) -> list:
    """Все запросы включая закрытые (для истории в админке)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pr.*, o.order_number, o.product_name,
               u.last_name, u.first_name, u.login
        FROM permission_requests pr
        JOIN orders o ON o.id = pr.order_id
        JOIN users u ON u.id = pr.user_id
        ORDER BY pr.id DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def resolve_permission(request_id: int, admin_id: int, status_: str, comment: str):
    """Админ разрешает или отклоняет запрос."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE permission_requests SET status=?, admin_id=?, admin_comment=?, "
        "resolved_at=CURRENT_TIMESTAMP WHERE id=?",
        (status_, admin_id, comment, request_id)
    )
    conn.commit()
    conn.close()


def count_pending_requests() -> int:
    """Сколько запросов ждут ответа админа."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM permission_requests WHERE status='pending'")
    n = cursor.fetchone()[0]
    conn.close()
    return n        