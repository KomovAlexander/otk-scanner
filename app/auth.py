import hashlib
from fastapi import Request, HTTPException
from app.database import get_user_by_login


def hash_password(password: str) -> str:
    """Хеширует пароль."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль."""
    return hash_password(password) == password_hash


def authenticate(login: str, password: str) -> dict | None:
    """Проверяет логин и пароль."""
    user = get_user_by_login(login)
    if user and verify_password(password, user["password_hash"]):
        return user
    return None


def get_current_user(request: Request) -> dict | None:
    """Достаёт пользователя из сессии."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    from app.database import get_db
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def require_auth(request: Request) -> dict:
    """Проверяет что пользователь авторизован."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return user


def require_admin(request: Request) -> dict:
    """Проверяет что пользователь — админ."""
    user = require_auth(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    return user