# ========== routes.py ==========

import os
import shutil

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import authenticate, get_current_user, require_auth
from app.database import get_db
from app.ocr_engine import scan_document

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Папка для хранения файлов
UPLOAD_ROOT = "app/static/uploads"


def save_uploaded_file(order_id: int, doc_type: str, file: UploadFile) -> str:
    """Сохраняет файл и возвращает URL-путь."""
    order_dir = os.path.join(UPLOAD_ROOT, f"order_{order_id}")
    os.makedirs(order_dir, exist_ok=True)

    ext = os.path.splitext(file.filename)[1] or ".jpg"
    saved_name = f"{doc_type}{ext}"
    file_path = os.path.join(order_dir, saved_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return f"/static/uploads/order_{order_id}/{saved_name}"


def get_saved_file_path(order_id: int, doc_type: str) -> str | None:
    """Возвращает URL-путь к сохранённому файлу."""
    order_dir = os.path.join(UPLOAD_ROOT, f"order_{order_id}")
    if not os.path.exists(order_dir):
        return None

    for ext in [".jpg", ".jpeg", ".png"]:
        file_name = f"{doc_type}{ext}"
        file_path = os.path.join(order_dir, file_name)
        if os.path.exists(file_path):
            # Возвращаем URL-путь (без app/)
            return f"/uploads/order_{order_id}/{file_name}"
    return None


def check_visual_completed(order_id: str, completed_steps: list) -> list:
    """Добавляет visual и measurements в completed_steps если визуальный контроль заполнен."""
    if not order_id:
        return completed_steps
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT data FROM visual_results WHERE order_id = ?", (int(order_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        import json
        data = json.loads(row["data"])
        if data.get("gch_match") or any(s for s in (data.get("sizes") or []) if s) or data.get("ral") or data.get("mass"):
            if "visual" not in completed_steps:
                completed_steps.append("visual")
            if "measurements" not in completed_steps:
                completed_steps.append("measurements")
    return completed_steps

# ── Личный кабинет ───────────────────────────────


@router.get("/dashboard")
def dashboard_page(request: Request):
    from app.auth import get_current_user
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    from app.database import get_all_orders, get_order_photos, is_order_completed
    is_admin = user["role"] == "admin"
    orders = get_all_orders(user["id"], is_admin)

    for order in orders:
        order["is_completed"] = is_order_completed(order["id"])
        order["photos"] = get_order_photos(order["id"])

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "orders": orders,
    })

# ── Главная страница = сразу сканирование ──────────


@router.get("/")
def scan_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    order_id = request.query_params.get("order_id", "")
    order_data = None
    saved_photo = None
    completed_steps = []

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None
        if order_data:
            completed_steps.append("order")
            saved_photo = get_saved_file_path(int(order_id), "order")
        cursor.execute(
            "SELECT id FROM gch_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("gch")
        cursor.execute(
            "SELECT id FROM g3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("g3")
        cursor.execute(
            "SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("pg3")
        conn.close()
        completed_steps = check_visual_completed(order_id, completed_steps)

    return templates.TemplateResponse("scan.html", {
        "request": request,
        "current_step": "order",
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order_data": order_data,
        "saved_photo": saved_photo,
        "user": user,  # ← добавить
    })


# ── Эндпоинт приёма фото заказа ────────────────────
@router.post("/api/scan")
async def api_scan(file: UploadFile = File(...)):
    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    result = scan_document(file_path)

    from app.database import get_or_create_order
    from app.auth import get_current_user
    user = get_current_user(request)
    user_id = user["id"] if user else None

    order_id = get_or_create_order(
        result.get("order_number", ""),
        result.get("product_name", ""),
        result.get("department", ""),
        user_id,
    )

    # Сохраняем файл в папку заказа
    # Переоткрываем файл для сохранения
    with open(file_path, "rb") as f:
        file.file = f
        saved_path = save_uploaded_file(order_id, "order", file)

    return JSONResponse(content={
        "status": "ok",
        "order_id": order_id,
        "order_number": result.get("order_number", "НЕ РАСПОЗНАНО"),
        "product_name": result.get("product_name", "НЕ РАСПОЗНАНО"),
        "department": result.get("department", "НЕ РАСПОЗНАНО"),
        "saved_photo": saved_path,
        "confidence": result.get("confidence", 0.0)
    })


# ── Эндпоинт ручного сохранения заказа ─────────────
@router.post("/api/save-order")
async def api_save_order(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    order_number = data.get("order_number", "")
    product_name = data.get("product_name", "")
    department = data.get("department", "")

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET order_number=?, product_name=?, department=? WHERE id=?",
            (order_number, product_name, department, order_id),
        )
        conn.commit()
        conn.close()
        return JSONResponse(content={"status": "ok"})

    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Вспомогательная функция проверки изделия ────────
def check_product_match(order_id: str, found_product: str) -> str | None:
    if not order_id or not found_product:
        return None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_name, order_number FROM orders WHERE id = ?", (int(order_id),))
    order_row = cursor.fetchone()
    conn.close()

    if not order_row:
        return None

    order_product = order_row["product_name"]
    order_number = order_row["order_number"]
    order_clean = order_product.upper().replace("-", "").replace(" ", "")
    found_clean = found_product.upper().replace("-", "").replace(" ", "")

    if found_clean not in order_clean and order_clean not in found_clean:
        return f"❌ Этот документ от изделия «{found_product}», а заказ №{order_number} на изделие «{order_product}»!"

    return None


# ── Страница сканирования ГЧ ──────────────────────
@router.get("/check-gch")
def check_gch_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    order_id = request.query_params.get("order_id", "")

    gch_data = None
    order_data = None
    saved_photo = None
    completed_steps = ["order"]

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        cursor.execute(
            "SELECT * FROM gch_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        gch_data = dict(row) if row else None

        if gch_data:
            completed_steps.append("gch")
            saved_photo = get_saved_file_path(int(order_id), "gch")

        cursor.execute(
            "SELECT id FROM g3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("g3")

        cursor.execute(
            "SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("pg3")

        cursor.execute(
            "SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("visual")
            completed_steps.append("measurements")
        conn.close()

    import json

    return templates.TemplateResponse("check_gch.html", {
        "request": request,
        "current_step": "gch",
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order_data": order_data,
        "gch_data": gch_data,
        "saved_photo": saved_photo,
        "gch_number": gch_data.get("gch_number", "") if gch_data else "",
        "gch_product": order_data.get("product_name", "") if order_data else "",
        "gch_ral": gch_data.get("ral", "") if gch_data else "",
        "gch_sizes": json.loads(gch_data.get("sizes", "[]")) if gch_data else [],
        "user": user,
    })


# ── Эндпоинт приёма фото ГЧ ───────────────────────
@router.post("/api/scan-gch")
async def api_scan_gch(request: Request, file: UploadFile = File(...)):
    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    import uuid
    safe_name = f"gch_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    from app.ocr_engine import perspective_correction
    perspective_correction(file_path)

    import re

    result = scan_document(file_path)
    full_text = result.get("full_text", "")

    if "ГЧ" not in full_text and "Габаритный" not in full_text:
        return JSONResponse(content={"status": "error", "message": "❌ Это не ГЧ! Сфотографируйте габаритный чертёж."})

    gch_match = re.search(
        r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*ГЧ)",
        full_text, re.IGNORECASE,
    )
    gch_number = gch_match.group(1).strip() if gch_match else "НЕ НАЙДЕНО"

    product_match = re.search(
        r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}", full_text, re.IGNORECASE)
    found_product = product_match.group(
        0).strip() if product_match else "НЕ НАЙДЕНО"

    order_id_str = request.query_params.get("order_id", None)
    product_error = check_product_match(order_id_str, found_product)
    if product_error:
        return JSONResponse(content={"status": "error", "message": product_error})

    ral_match = re.search(r"RAL\s*(\d{4})", full_text, re.IGNORECASE)
    ral = ral_match.group(1).strip() if ral_match else ""

    from app.green_extractor import extract_all_colored_numbers
    numbers = extract_all_colored_numbers(file_path)

    if order_id_str:
        from app.database import save_gch
        save_gch(int(order_id_str), gch_number, ral, numbers)
        # Сохраняем файл (переоткрываем для чтения)
        with open(file_path, "rb") as f:
            # Копируем в папку заказа
            order_dir = os.path.join(
                "app/static/uploads", f"order_{int(order_id_str)}")
            os.makedirs(order_dir, exist_ok=True)
            dest_path = os.path.join(order_dir, "gch.jpeg")
            with open(dest_path, "wb") as dest:
                shutil.copyfileobj(f, dest)

    return JSONResponse(content={
        "status": "ok", "gch_number": gch_number, "found_product": found_product,
        "ral": ral, "numbers": numbers, "count": len(numbers),
    })


# ── Эндпоинт ручного сохранения ГЧ ─────────────────
@router.post("/api/save-gch")
async def api_save_gch(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import save_gch
        save_gch(int(order_id), data.get("gch_number", ""),
                 data.get("ral", ""), data.get("sizes", []))
        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Страница сканирования Г3 ──────────────────────
@router.get("/check-g3")
def check_g3_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    order_id = request.query_params.get("order_id", "")

    g3_data = None
    order_data = None
    saved_photo = None
    completed_steps = ["order", "gch"]

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        # Проверяем ГЧ (должен быть пройден)
        cursor.execute(
            "SELECT id FROM gch_data WHERE order_id = ?", (int(order_id),))
        if not cursor.fetchone():
            completed_steps.remove("gch")

        cursor.execute(
            "SELECT * FROM g3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        g3_data = dict(row) if row else None

        if g3_data:
            completed_steps.append("g3")
            saved_photo = get_saved_file_path(int(order_id), "g3")

        cursor.execute(
            "SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("pg3")
        cursor.execute(
            "SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("visual")
            completed_steps.append("measurements")
        conn.close()

    import json

    return templates.TemplateResponse("check_g3.html", {
        "request": request,
        "current_step": "g3",
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order_data": order_data,
        "g3_data": g3_data,
        "saved_photo": saved_photo,
        "g3_number": g3_data.get("g3_number", "") if g3_data else "",
        "g3_product": order_data.get("product_name", "") if order_data else "",
        "g3_params": json.loads(g3_data.get("params", "[]")) if g3_data else [],
        "user": user,
    })


# ── Эндпоинт приёма фото Г3 ───────────────────────
@router.post("/api/scan-g3")
async def api_scan_g3(request: Request, file: UploadFile = File(...)):
    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    import uuid
    safe_name = f"g3_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    from app.ocr_engine import perspective_correction
    perspective_correction(file_path)

    import re

    result = scan_document(file_path)
    full_text = result.get("full_text", "")

    if "Г3" not in full_text and "ГЗ" not in full_text and "Схема гидравлическая" not in full_text:
        return JSONResponse(content={"status": "error", "message": "❌ Это не Г3! Сфотографируйте гидравлическую схему."})

    g3_match = re.search(
        r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*Г[3З])", full_text, re.IGNORECASE)
    g3_number = g3_match.group(1).strip().replace(
        'ГЗ', 'Г3') if g3_match else "НЕ НАЙДЕНО"

    product_match = re.search(
        r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}", full_text, re.IGNORECASE)
    found_product = product_match.group(
        0).strip() if product_match else "НЕ НАЙДЕНО"

    order_id_str = request.query_params.get("order_id", None)
    product_error = check_product_match(order_id_str, found_product)
    if product_error:
        return JSONResponse(content={"status": "error", "message": product_error})

    from app.param_extractor import extract_params_via_gpt
    params = extract_params_via_gpt(full_text, found_product)

    if order_id_str:
        from app.database import save_g3
        save_g3(int(order_id_str), g3_number, params)
        # Сохраняем файл (переоткрываем для чтения)
        with open(file_path, "rb") as f:
            order_dir = os.path.join(
                "app/static/uploads", f"order_{int(order_id_str)}")
            os.makedirs(order_dir, exist_ok=True)
            dest_path = os.path.join(order_dir, "g3.jpeg")
            with open(dest_path, "wb") as dest:
                shutil.copyfileobj(f, dest)

    return JSONResponse(content={
        "status": "ok", "g3_number": g3_number, "found_product": found_product,
        "params": params, "count": len(params),
    })


# ── Эндпоинт ручного сохранения Г3 ─────────────────
@router.post("/api/save-g3")
async def api_save_g3(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import save_g3
        save_g3(int(order_id), data.get(
            "g3_number", ""), data.get("params", []))
        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Страница сканирования ПГ3 ─────────────────────
@router.get("/check-pg3")
def check_pg3_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    order_id = request.query_params.get("order_id", "")

    pg3_data = None
    order_data = None
    saved_photo = None
    completed_steps = ["order", "gch", "g3"]

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        # Проверяем что предыдущие шаги пройдены
        cursor.execute(
            "SELECT id FROM gch_data WHERE order_id = ?", (int(order_id),))
        if not cursor.fetchone():
            completed_steps = [s for s in completed_steps if s != "gch"]
        cursor.execute(
            "SELECT id FROM g3_data WHERE order_id = ?", (int(order_id),))
        if not cursor.fetchone():
            completed_steps = [s for s in completed_steps if s != "g3"]

        cursor.execute(
            "SELECT * FROM pg3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        pg3_data = dict(row) if row else None
        cursor.execute(
            "SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("visual")
            completed_steps.append("measurements")
        if pg3_data:
            completed_steps.append("pg3")
            saved_photo = get_saved_file_path(int(order_id), "pg3")

        conn.close()

    import json

    return templates.TemplateResponse("check_pg3.html", {
        "request": request,
        "current_step": "pg3",
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order_data": order_data,
        "pg3_data": pg3_data,
        "saved_photo": saved_photo,
        "pg3_number": pg3_data.get("pg3_number", "") if pg3_data else "",
        "pg3_product": order_data.get("product_name", "") if order_data else "",
        "pg3_items": json.loads(pg3_data.get("items", "[]")) if pg3_data else [],
        "user": user,
    })


# ── Эндпоинт приёма фото ПГ3 ──────────────────────
@router.post("/api/scan-pg3")
async def api_scan_pg3(request: Request, file: UploadFile = File(...)):
    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    import uuid
    safe_name = f"pg3_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    from app.ocr_engine import perspective_correction
    perspective_correction(file_path)

    import re

    result = scan_document(file_path)
    full_text = result.get("full_text", "")

    if "ПГ3" not in full_text and "ПГЗ" not in full_text and "Перечень элементов" not in full_text:
        return JSONResponse(content={"status": "error", "message": "❌ Это не ПГ3! Сфотографируйте перечень элементов."})

    pg3_match = re.search(
        r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*ПГ[3З])", full_text, re.IGNORECASE)
    pg3_number = pg3_match.group(1).strip().replace(
        'ПГЗ', 'ПГ3') if pg3_match else "НЕ НАЙДЕНО"

    product_match = re.search(
        r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}", full_text, re.IGNORECASE)
    found_product = product_match.group(
        0).strip() if product_match else "НЕ НАЙДЕНО"

    order_id_str = request.query_params.get("order_id", None)
    product_error = check_product_match(order_id_str, found_product)
    if product_error:
        return JSONResponse(content={"status": "error", "message": product_error})

    from app.param_extractor import extract_pg3_via_gpt
    items = extract_pg3_via_gpt(full_text, found_product)

    if order_id_str:
        from app.database import save_pg3
        save_pg3(int(order_id_str), pg3_number, items)
        with open(file_path, "rb") as f:
            order_dir = os.path.join(
                "app/static/uploads", f"order_{int(order_id_str)}")
            os.makedirs(order_dir, exist_ok=True)
            dest_path = os.path.join(order_dir, "pg3.jpeg")
            with open(dest_path, "wb") as dest:
                shutil.copyfileobj(f, dest)

    return JSONResponse(content={
        "status": "ok", "pg3_number": pg3_number, "found_product": found_product,
        "items": items, "count": len(items),
    })


# ── Эндпоинт ручного сохранения ПГ3 ────────────────
@router.post("/api/save-pg3")
async def api_save_pg3(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import save_pg3
        save_pg3(int(order_id), data.get(
            "pg3_number", ""), data.get("items", []))
        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Сохранение визуального контроля ──────────────────
@router.post("/api/save-visual")
async def api_save_visual(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import save_visual_results
        save_visual_results(int(order_id), data)
        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Сохранение измерений ────────────────────────────
@router.post("/api/save-measurements")
async def api_save_measurements(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import save_measurement_results
        save_measurement_results(int(order_id), data)
        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)

# ── Страница визуального контроля ──────────────────


@router.get("/visual-check")
def visual_check_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    order_id = request.query_params.get("order_id", None)

    gch_data = None
    g3_data = None
    pg3_data = None
    order_data = None
    completed_steps = ["order", "gch", "g3", "pg3"]

    if order_id:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        cursor.execute(
            "SELECT * FROM gch_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        gch_data = dict(row) if row else None

        cursor.execute(
            "SELECT * FROM g3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        g3_data = dict(row) if row else None

        cursor.execute(
            "SELECT * FROM pg3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        pg3_data = dict(row) if row else None

        # Проверяем реально пройденные шаги
        if not gch_data:
            completed_steps = [s for s in completed_steps if s != "gch"]
        if not g3_data:
            completed_steps = [s for s in completed_steps if s != "g3"]
        if not pg3_data:
            completed_steps = [s for s in completed_steps if s != "pg3"]

        # Визуальный контроль доступен если есть ПГ3
        if pg3_data:
            completed_steps.append("visual")
            completed_steps.append("measurements")

        conn.close()

    import json

    return templates.TemplateResponse("visual_check.html", {
        "request": request,
        "current_step": "visual",
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order": order_data,
        "gch": gch_data,
        "gch_sizes": json.loads(gch_data.get("sizes", "[]")) if gch_data else [],
        "gch_ral": gch_data.get("ral", "") if gch_data else "",
        "g3_params": json.loads(g3_data.get("params", "[]")) if g3_data else [],
        "pg3_items": json.loads(pg3_data.get("items", "[]")) if pg3_data else [],
        "user": user,
    })

# ── Страница испытаний ────────────────────────────


@router.get("/measurements")
def measurements_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    order_id = request.query_params.get("order_id", None)

    order_data = None
    g3_data = None
    completed_steps = ["order", "gch", "g3", "pg3", "visual"]

    if order_id:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        cursor.execute(
            "SELECT * FROM g3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        g3_data = dict(row) if row else None

        # Проверяем реально пройденные шаги
        if not g3_data:
            completed_steps = [s for s in completed_steps if s != "g3"]

        if g3_data:
            completed_steps.append("measurements")

        conn.close()

    import json

    return templates.TemplateResponse("measurements.html", {
        "request": request,
        "current_step": "measurements",
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order": order_data,
        "g3_params": json.loads(g3_data.get("params", "[]")) if g3_data else [],
        "user": user,
    })


# ── Загрузка визуального контроля ──────────────────
@router.get("/api/get-visual")
def api_get_visual(request: Request):
    order_id = request.query_params.get("order_id", None)
    if order_id:
        from app.database import get_visual_results
        data = get_visual_results(int(order_id))
        return JSONResponse(content={"status": "ok", "data": data})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)

# ── Загрузка измерений ──────────────────────────────


@router.get("/api/get-measurements")
def api_get_measurements(request: Request):
    order_id = request.query_params.get("order_id", None)
    if order_id:
        from app.database import get_measurement_results
        data = get_measurement_results(int(order_id))
        return JSONResponse(content={"status": "ok", "data": data})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)

# ── Страница фотографирования ─────────────────────


@router.get("/photo")
def photo_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    order_id = request.query_params.get("order_id", None)
    order_data = None
    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None
        conn.close()

    return templates.TemplateResponse("photo.html", {
        "request": request,
        "current_step": "photo",
        "completed_steps": ["order", "gch", "g3", "pg3", "visual", "measurements", "protocol", "photo"],
        "order_id": order_id,
        "order": order_data,
        "user": user,
    })


# ── Эндпоинт сохранения фото изделия ─────────────
@router.post("/api/save-photo")
async def api_save_photo(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    photo_index = data.get("photo_index")  # 1, 2, 3, 4

    if not order_id or not photo_index:
        return JSONResponse(content={"status": "error"}, status_code=400)

    # Здесь будет сохранение файла, если мы передаём base64
    # Пока просто возвращаем OK

    return JSONResponse(content={"status": "ok", "photo_index": photo_index})


# ── Эндпоинт загрузки фото изделия ───────────────
@router.post("/api/upload-photo")
async def api_upload_photo(request: Request, file: UploadFile = File(...)):
    order_id = request.query_params.get("order_id", None)
    photo_index = request.query_params.get("photo_index", "1")

    if not order_id:
        return JSONResponse(content={"status": "error"}, status_code=400)

    upload_dir = os.path.join("app/static/uploads", f"order_{int(order_id)}")
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, f"photo_{photo_index}.jpg")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return JSONResponse(content={
        "status": "ok",
        "photo_index": photo_index,
        "url": f"/uploads/order_{int(order_id)}/photo_{photo_index}.jpg"
    })


# ── Протокол испытаний ────────────────────────────
@router.get("/protocol")
def protocol_page(request: Request):
    import json
    import re
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    order_id = request.query_params.get("order_id", None)

    order_data = None
    visual_data = None
    measurement_data = None
    gch_data = None
    gch_sizes = []
    g3_params = []
    test_date = ""
    serial_number = ""

    if order_id:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        if order_data:
            from datetime import datetime
            test_date = datetime.now().strftime("%d.%m.%Y")

            order_num = order_data.get("order_number", "")
            match = re.search(r"ПС\d{2}[.\-](\d+)", order_num)
            if match:
                first_digits = match.group(1)[:4].zfill(4)
            else:
                first_digits = "0000"

            date_part = datetime.now().strftime("%d%m%y")
            serial_number = f"{first_digits}{date_part}01"

        from app.database import get_measurement_results, get_visual_results
        visual_data = get_visual_results(int(order_id))
        measurement_data = get_measurement_results(int(order_id))

        cursor.execute(
            "SELECT * FROM gch_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        gch_data = dict(row) if row else None
        gch_sizes = json.loads(gch_data.get("sizes", "[]")) if gch_data else []

        cursor.execute(
            "SELECT * FROM g3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        g3_data = dict(row) if row else None
        g3_params = json.loads(g3_data.get("params", "[]")) if g3_data else []

        conn.close()

    return templates.TemplateResponse("protocol.html", {
        "request": request,
        "current_step": "protocol",
        "completed_steps": ["order", "gch", "g3", "pg3", "visual", "measurements", "protocol"],
        "order_id": order_id,
        "order": order_data,
        "visual": visual_data,
        "measurements": measurement_data,
        "gch": gch_data,
        "gch_sizes": gch_sizes,
        "g3_params": g3_params,
        "test_date": test_date,
        "serial_number": serial_number,
        "user": user,
    })

# ── Логин ────────────────────────────────────────


@router.get("/login")
def login_page(request: Request, error: str = ""):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    login = form.get("login", "").strip()
    password = form.get("password", "").strip()

    user = authenticate(login, password)
    if user:
        request.session["user_id"] = user["id"]
        return RedirectResponse("/", status_code=303)

    return RedirectResponse("/login?error=1", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
