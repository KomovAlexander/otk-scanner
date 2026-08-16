# ========== admin_routes.py ==========

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.auth import require_admin, get_current_user
from app.database import get_all_users, create_user, delete_user, update_user, update_user_password

admin_router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")


def admin_required(request: Request):
    user = get_current_user(request)
    if not user or user["role"] != "admin":
        return None
    return user


# ── Главная админки ──────────────────────────────
@admin_router.get("")
def admin_dashboard(request: Request):
    user = admin_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    users = get_all_users()
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "users": users,
    })


# ── Создание пользователя ────────────────────────
@admin_router.post("/users/create")
async def create_user_route(request: Request):
    user = admin_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    form = await request.form()
    login = form.get("login", "").strip()
    password = form.get("password", "").strip()
    first_name = form.get("first_name", "").strip()
    last_name = form.get("last_name", "").strip()
    role = form.get("role", "tester")
    
    if login and password:
        create_user(login, password, first_name, last_name, role)
    
    return RedirectResponse("/admin", status_code=303)


# ── Удаление пользователя ────────────────────────
@admin_router.get("/users/delete/{user_id}")
def delete_user_route(request: Request, user_id: int):
    user = admin_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    delete_user(user_id)
    return RedirectResponse("/admin", status_code=303)


# ── Смена пароля ─────────────────────────────────
@admin_router.post("/users/password/{user_id}")
async def change_password_route(request: Request, user_id: int):
    user = admin_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    form = await request.form()
    new_password = form.get("new_password", "").strip()
    
    if new_password:
        update_user_password(user_id, new_password)
    
    return RedirectResponse("/admin", status_code=303)