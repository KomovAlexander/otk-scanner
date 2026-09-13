# ========== admin_routes.py ==========

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import get_current_user, require_admin
from app.database import (count_pending_requests, create_user, delete_user,
                          get_all_requests, get_all_users,
                          get_pending_requests, resolve_permission,
                          update_user, update_user_password)

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
    pending_count = count_pending_requests()
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "users": users,
        "pending_count": pending_count,
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
    middle_name = form.get("middle_name", "").strip()
    position = form.get("position", "").strip()
    role = form.get("role", "tester")
    
    if login and password:
        create_user(login, password, first_name, last_name, middle_name, position, role)
    
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



# ── Запросы разрешений ────────────────────────────

@admin_router.get("/requests")
def admin_requests_page(request: Request):
    user = admin_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    pending = get_pending_requests()
    history = get_all_requests(limit=50)

    return templates.TemplateResponse("admin_requests.html", {
        "request": request,
        "user": user,
        "pending": pending,
        "history": history,
    })


@admin_router.post("/requests/{request_id}/resolve")
async def admin_resolve_request(request: Request, request_id: int):
    user = admin_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    status_ = form.get("status", "rejected")
    comment = (form.get("comment") or "").strip()

    if status_ not in ("approved", "rejected"):
        status_ = "rejected"

    resolve_permission(request_id, user["id"], status_, comment)

    return RedirectResponse("/admin/requests", status_code=303)