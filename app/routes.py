# ========== routes.py ==========

import os
import re
import shutil
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import authenticate, get_current_user, require_auth
from app.database import (get_all_orders, get_db, get_measurement_results,
                          get_order_photos, get_order_progress,
                          get_visual_results, is_order_completed,
                          mark_step_completed, update_order_step)
from app.ocr_engine import scan_document
from app.patterns import (detect_document_type, extract_g3_number,
                          extract_gch_number, extract_pg3_number,
                          extract_product_name)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Папка для хранения файлов
UPLOAD_ROOT = "app/static/uploads"

# Порядок шагов
STEP_ORDER = ["order", "gch", "g3", "pg3",
              "visual", "measurements", "protocol", "photo"]
STEP_URLS = {
    "order": "/",
    "gch": "/check-gch",
    "g3": "/check-g3",
    "pg3": "/check-pg3",
    "visual": "/visual-check",
    "measurements": "/measurements",
    "protocol": "/protocol",
    "photo": "/photo",
}


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
            return f"/uploads/order_{order_id}/{file_name}"
    return None


def check_document_match(order_id: str, found_product: str, doc_number: str) -> str | None:
    """Проверяет, что документ соответствует заказу по изделию и номеру."""
    if not order_id:
        return None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT product_name FROM orders WHERE id = ?", (int(order_id),))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    order_product = row["product_name"]

    def normalize(s: str) -> str:
        return s.upper().replace("-", "").replace(" ", "").replace(".", "")

    # Проверяем изделие
    product_found = False
    product_ok = False
    if found_product and found_product != "НЕ НАЙДЕНО":
        product_found = True
        op = normalize(order_product)
        fp = normalize(found_product)
        if fp == op or fp in op or op in fp:
            product_ok = True
        elif levenshtein_distance(op, fp) <= 2:
            product_ok = True

    # Проверяем номер документа
    doc_found = False
    doc_ok = False
    if doc_number and doc_number != "НЕ НАЙДЕНО":
        doc_found = True
        # Из номера документа обрезаем .000.000 и суффикс
        doc_base = re.sub(r'[.\-\s]\d{3,4}[.\-\s]\d{3,4}.*$', '', doc_number.strip())
        doc_base = re.sub(r'\s*(?:ГЧ|СБ|Г[3З]|ПГ[3З])$', '', doc_base)
        doc_code = normalize(doc_base)
        
        # Нормализуем изделие
        product_code = normalize(order_product)
        
        if doc_code == product_code:
            doc_ok = True
        elif doc_code in product_code or product_code in doc_code:
            doc_ok = True
        elif levenshtein_distance(doc_code, product_code) <= 2:
            doc_ok = True

    # Итог — упрощённая версия
    if product_ok and doc_ok:
        return None  # ✅ Всё совпало
    
    elif not doc_found:
        # Номер не найден — предупреждаем, но пропускаем
        return f"⚠️ Номер документа не распознан. Изделие: «{found_product}». Продолжить?"
    
    elif not product_found:
        # Изделие не найдено — предупреждаем
        return f"⚠️ Изделие не распознано. Номер документа: «{doc_number}». Продолжить?"
    
    elif not product_ok and not doc_ok:
        # Оба не совпали — ошибка
        return f"❌ Документ не соответствует заказу!"
    
    else:
        # Частичное совпадение — предупреждение
        return f"⚠️ Документ частично не совпадает. Перепроверьте!"
    
    return None


def process_document_scan(file_path: str, expected_type: str, order_id_str: str) -> dict:
    from app.patterns import detect_document_type, extract_product_name
    
    # 1. Распознаём текст
    result = scan_document(file_path)
    full_text = result.get("full_text", "")
    
    # 2. Определяем тип и номер документа
    doc_info = detect_document_type(full_text)
    doc_type = doc_info["type"]
    doc_number = doc_info["number"]
    
    # 3. Извлекаем изделие
    found_product = extract_product_name(full_text)
    
    # 4. Проверяем тип
    type_names = {
        "ГЧ": "габаритный чертёж",
        "Г3": "гидравлическую схему",
        "ПГ3": "перечень элементов",
    }
    
    # Если тип определён, но не тот — ошибка
    if doc_type is not None and doc_type != expected_type:
        return {
            "status": "error",
            "message": f"❌ Это {doc_type}, а ожидается {expected_type}! Сфотографируйте {type_names.get(expected_type, 'документ')}."
        }
    
    # Если тип не определён и номер не найден
    if doc_type is None and doc_number == "НЕ НАЙДЕНО":
        if found_product != "НЕ НАЙДЕНО":
            # Изделие найдено, но тип и номер не определены — спрашиваем
            return {
                "status": "warning",
                "message": f"⚠️ Найдено изделие «{found_product}», но номер документа не распознан. Похоже на {expected_type}?",
                "doc_number": "НЕ НАЙДЕНО",
                "found_product": found_product,
                "full_text": full_text,
            }
        else:
            return {
                "status": "error",
                "message": f"❌ Не удалось распознать документ! Сфотографируйте {type_names.get(expected_type, 'документ')}."
            }
    
    # 5. Проверяем соответствие заказу
    if order_id_str:
        product_error = check_document_match(order_id_str, found_product, doc_number)
        if product_error:
            if product_error.startswith("⚠️"):
                return {
                    "status": "warning",
                    "message": product_error,
                    "doc_number": doc_number,
                    "found_product": found_product,
                    "full_text": full_text,
                }
            else:
                return {
                    "status": "error",
                    "message": product_error
                }
    
    return {
        "status": "ok",
        "doc_number": doc_number,
        "found_product": found_product,
        "full_text": full_text,
    }


def get_completed_steps(order_id: int) -> list:
    """Возвращает список пройденных шагов из таблицы order_progress."""
    if not order_id:
        return []
    progress = get_order_progress(int(order_id))
    return progress["completed_steps"]


def get_current_step(order_id: int) -> str:
    """Возвращает текущий шаг из таблицы order_progress."""
    if not order_id:
        return "order"
    progress = get_order_progress(int(order_id))
    return progress["current_step"]

# ── Поворот фото ──────────────────────────────
@router.post("/api/rotate-photo")
async def api_rotate_photo(request: Request):
    data = await request.json()
    image_path = data.get("image_path", "")
    rotation = data.get("rotation", 0)
    
    if not image_path or rotation == 0:
        return JSONResponse(content={"status": "error", "message": "Нет данных"}, status_code=400)
    
    # Определяем путь на сервере
    file_path = None
    
    # Вариант 1: /uploads/order_1/gch.jpeg
    if image_path.startswith("/uploads/"):
        file_path = os.path.join("app/static", image_path.lstrip("/"))
    # Вариант 2: /static/uploads/order_1/gch.jpeg
    elif image_path.startswith("/static/uploads/"):
        file_path = os.path.join("app", image_path.lstrip("/"))
    # Вариант 3: полный URL http://...
    elif image_path.startswith("http"):
        # Извлекаем путь из URL
        from urllib.parse import urlparse
        parsed = urlparse(image_path)
        path = parsed.path
        if path.startswith("/uploads/"):
            file_path = os.path.join("app/static", path.lstrip("/"))
        elif path.startswith("/static/uploads/"):
            file_path = os.path.join("app", path.lstrip("/"))
    
    if not file_path or not os.path.exists(file_path):
        return JSONResponse(content={
            "status": "error", 
            "message": f"Файл не найден: {image_path}"
        }, status_code=404)
    
    # Поворачиваем фото
    import cv2
    img = cv2.imread(file_path)
    if img is None:
        return JSONResponse(content={"status": "error", "message": "Не удалось загрузить фото"}, status_code=500)
    
    # Нормализуем угол
    rotation = rotation % 360
    if rotation == 0:
        rotation = 360  # полный оборот — не поворачиваем
    elif rotation == 90 or rotation == -270:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180 or rotation == -180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif rotation == 270 or rotation == -90:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    
    # Сохраняем
    cv2.imwrite(file_path, img)
    
    return JSONResponse(content={"status": "ok", "new_url": image_path})
# ── Личный кабинет ───────────────────────────────


@router.get("/dashboard")
def dashboard_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    is_admin = user["role"] == "admin"
    orders = get_all_orders(user["id"], is_admin)

    for order in orders:
        order["is_completed"] = is_order_completed(order["id"])
        order["photos"] = get_order_photos(order["id"])
        progress = get_order_progress(order["id"])
        order["current_step"] = progress["current_step"]
        order["current_step_url"] = STEP_URLS.get(
            progress["current_step"], "/")

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
    current_step = "order"

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        if order_data:
            saved_photo = get_saved_file_path(int(order_id), "order")

        conn.close()

        # Получаем прогресс из новой таблицы
        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

    return templates.TemplateResponse("scan.html", {
        "request": request,
        "current_step": current_step,
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order_data": order_data,
        "saved_photo": saved_photo,
        "user": user,
    })


# ── Эндпоинт приёма фото заказа ────────────────────
@router.post("/api/scan")
async def api_scan(request: Request, file: UploadFile = File(...)):
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"status": "error"}, status_code=401)

    temp_dir = os.path.join(UPLOAD_ROOT, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_name = f"scan_{uuid.uuid4().hex[:8]}.jpg"
    temp_path = os.path.join(temp_dir, temp_name)

    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    result = scan_document(temp_path)

    order_number = result.get("order_number", "НЕ НАЙДЕНО")
    product_name = result.get("product_name", "НЕ НАЙДЕНО")
    department = result.get("department", "НЕ НАЙДЕНО")
    full_text = result.get("full_text", "")

    # Проверяем, что это заказ на производство
    is_order = False

    if "Задание на производство" in full_text:
        is_order = True
    elif "Заказ на производство" in full_text:
        is_order = True
    elif re.search(r"ПС\d{2}[.\-]\d{2,4}[.\-]\d{1,2}", full_text):
        is_order = True
    elif order_number not in ("НЕ НАЙДЕНО", "ОШИБКА API", "", None):
        is_order = True

    if not is_order:
        os.remove(temp_path)
        return JSONResponse(content={
            "status": "error",
            "message": "❌ Это не заказ на производство! Сфотографируйте задание на производство."
        })

    if order_number in ("НЕ НАЙДЕНО", "ОШИБКА API", "", None):
        os.remove(temp_path)
        return JSONResponse(content={"status": "error", "message": "❌ Номер заказа не найден!"})

    # Проверяем, есть ли уже такой заказ в БД
    from app.database import get_or_create_order
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM orders WHERE order_number = ?", (order_number,))
    existing_order = cursor.fetchone()
    conn.close()

    if existing_order:
        # Заказ уже существует — берём изделие из БД
        product_name = existing_order["product_name"]
        department = existing_order["department"]
        order_id = existing_order["id"]
    else:
        # Новый заказ — создаём с распознанными данными
        order_id = get_or_create_order(
            order_number, product_name, department, user["id"])

    # Сохраняем фото заказа
    order_dir = os.path.join(UPLOAD_ROOT, f"order_{order_id}")
    os.makedirs(order_dir, exist_ok=True)
    dest_path = os.path.join(order_dir, "order.jpg")
    shutil.copy2(temp_path, dest_path)
    os.remove(temp_path)

    return JSONResponse(content={
        "status": "ok",
        "order_id": order_id,
        "order_number": order_number,
        "product_name": product_name,
        "department": department,
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
    completed_steps = []
    current_step = "gch"

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
            saved_photo = get_saved_file_path(int(order_id), "gch")

        conn.close()

        # Прогресс из таблицы
        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

    import json

    return templates.TemplateResponse("check_gch.html", {
        "request": request,
        "current_step": current_step,
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
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"status": "error"}, status_code=401)

    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"gch_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    order_id_str = request.query_params.get("order_id", None)
    
    # Общая обработка
    result = process_document_scan(file_path, "ГЧ", order_id_str)
    
    if result["status"] in ("error", "warning"):
        return JSONResponse(content=result)
    
    full_text = result["full_text"]
    gch_number = result["doc_number"]
    found_product = result["found_product"]
    
    # Извлекаем RAL и размеры
    import re
    ral_match = re.search(r"RAL\s*(\d{4})", full_text, re.IGNORECASE)
    ral = ral_match.group(1).strip() if ral_match else ""
    
    from app.green_extractor import extract_all_colored_numbers
    numbers = extract_all_colored_numbers(file_path)
    
    # Сохраняем
    if order_id_str:
        from app.database import save_gch
        order_id = int(order_id_str)
        save_gch(order_id, gch_number, ral, numbers)
        
        order_dir = os.path.join("app/static/uploads", f"order_{order_id}")
        os.makedirs(order_dir, exist_ok=True)
        dest_path = os.path.join(order_dir, "gch.jpeg")
        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    
    return JSONResponse(content={
        "status": "ok",
        "gch_number": gch_number,
        "found_product": found_product,
        "ral": ral,
        "numbers": numbers,
        "count": len(numbers),
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

        # Отмечаем шаг как пройденный и переходим на g3
        mark_step_completed(int(order_id), "gch", "g3")

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
    completed_steps = []
    current_step = "g3"

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

        if g3_data:
            saved_photo = get_saved_file_path(int(order_id), "g3")

        conn.close()

        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

    import json

    return templates.TemplateResponse("check_g3.html", {
        "request": request,
        "current_step": current_step,
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
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"status": "error"}, status_code=401)

    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"g3_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    order_id_str = request.query_params.get("order_id", None)
    
    # Общая обработка
    result = process_document_scan(file_path, "Г3", order_id_str)
    
    if result["status"] in ("error", "warning"):
        return JSONResponse(content=result)
    
    full_text = result["full_text"]
    g3_number = result["doc_number"]
    found_product = result["found_product"]
    
    # Извлекаем параметры
    from app.param_extractor import extract_params_via_gpt
    params = extract_params_via_gpt(full_text, found_product)
    
    # Сохраняем
    if order_id_str:
        from app.database import save_g3
        order_id = int(order_id_str)
        save_g3(order_id, g3_number, params)
        
        order_dir = os.path.join("app/static/uploads", f"order_{order_id}")
        os.makedirs(order_dir, exist_ok=True)
        dest_path = os.path.join(order_dir, "g3.jpeg")
        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    
    return JSONResponse(content={
        "status": "ok",
        "g3_number": g3_number,
        "found_product": found_product,
        "params": params,
        "count": len(params),
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

        mark_step_completed(int(order_id), "g3", "pg3")

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
    completed_steps = []
    current_step = "pg3"

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        cursor.execute(
            "SELECT * FROM pg3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        pg3_data = dict(row) if row else None

        if pg3_data:
            saved_photo = get_saved_file_path(int(order_id), "pg3")

        conn.close()

        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

    import json

    return templates.TemplateResponse("check_pg3.html", {
        "request": request,
        "current_step": current_step,
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
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"status": "error"}, status_code=401)

    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"pg3_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    order_id_str = request.query_params.get("order_id", None)
    
    # Общая обработка
    result = process_document_scan(file_path, "ПГ3", order_id_str)
    
    if result["status"] in ("error", "warning"):
        return JSONResponse(content=result)
    
    full_text = result["full_text"]
    pg3_number = result["doc_number"]
    found_product = result["found_product"]
    
    # Извлекаем позиции
    from app.param_extractor import extract_pg3_via_gpt
    items = extract_pg3_via_gpt(full_text, found_product)
    
    # Сохраняем
    if order_id_str:
        from app.database import save_pg3
        order_id = int(order_id_str)
        save_pg3(order_id, pg3_number, items)
        
        order_dir = os.path.join("app/static/uploads", f"order_{order_id}")
        os.makedirs(order_dir, exist_ok=True)
        dest_path = os.path.join(order_dir, "pg3.jpeg")
        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    
    return JSONResponse(content={
        "status": "ok",
        "pg3_number": pg3_number,
        "found_product": found_product,
        "items": items,
        "count": len(items),
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

        mark_step_completed(int(order_id), "pg3", "visual")

        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Сохранение визуального контроля ──────────────────
@router.post("/api/save-visual")
async def api_save_visual(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import mark_step_completed, save_visual_results
        save_visual_results(int(order_id), data)

        # Проверяем, ВСЕ ли обязательные поля заполнены
        all_filled = True

        # 1. Соответствие ГЧ
        if not data.get("gch_match"):
            all_filled = False

        # 2. Все размеры заполнены
        sizes = data.get("sizes", [])
        if not sizes or any(not s or int(s) <= 0 for s in sizes):
            all_filled = False

        # 3. RAL заполнен
        if not data.get("ral"):
            all_filled = False

        # 4. Масса заполнена
        if not data.get("mass"):
            all_filled = False

        # 5. Все проверки Г3 выбраны
        g3_checks = data.get("g3_checks", [])
        if not g3_checks or any(not c.get("value") for c in g3_checks):
            all_filled = False

        # 6. Все параметры Г3 заполнены
        g3_values = data.get("g3_values", [])
        if not g3_values or any(not v.get("value") for v in g3_values):
            all_filled = False

        # 7. Все позиции ПГ3 подтверждены ИЛИ изменены
        pg3_confirmed = data.get("pg3_confirmed", [])
        pg3_changes = data.get("pg3_changes", [])

        confirmed_positions = set()
        for c in pg3_confirmed:
            if c.get("confirmed"):
                confirmed_positions.add(c.get("position"))

        for change in pg3_changes:
            position = change.get("position", "")
            name = change.get("name", "")
            original_name = change.get("original_name", "")
            quantity = change.get("quantity", "")
            expected_quantity = change.get("expected_quantity", "")
            if name != original_name or quantity != expected_quantity:
                confirmed_positions.add(position)

        if not pg3_confirmed or len(confirmed_positions) != len(pg3_confirmed):
            all_filled = False

        # Только если ВСЁ заполнено — отмечаем шаг пройденным
        if all_filled:
            mark_step_completed(int(order_id), "visual", "measurements")

        return JSONResponse(content={"status": "ok", "all_filled": all_filled})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Сохранение измерений ────────────────────────────
@router.post("/api/save-measurements")
async def api_save_measurements(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import mark_step_completed, save_measurement_results
        save_measurement_results(int(order_id), data)

        # Проверяем, ВСЕ ли обязательные поля заполнены
        all_filled = True

        # 1. Все параметры Г3 заполнены
        g3_values = data.get("g3_values", [])
        if not g3_values or any(not v.get("value") for v in g3_values):
            all_filled = False

        # 2. Все токи заполнены
        currents = data.get("currents", [])
        if not currents or len(currents) < 6 or any(not c.get("value") for c in currents):
            all_filled = False

        # 3. Номинальный ток заполнен
        if not data.get("nominal_current"):
            all_filled = False

        # 4. Шум заполнен
        if not data.get("noise_idle") or not data.get("noise_load"):
            all_filled = False

        # 5. Рабочая жидкость выбрана
        if not data.get("fluid"):
            all_filled = False

        # Только если ВСЁ заполнено — отмечаем шаг пройденным
        if all_filled:
            mark_step_completed(int(order_id), "measurements", "protocol")

        return JSONResponse(content={"status": "ok", "all_filled": all_filled})
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
    completed_steps = []
    current_step = "visual"

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

        conn.close()

        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

    import json

    return templates.TemplateResponse("visual_check.html", {
        "request": request,
        "current_step": current_step,
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


# ── Страница измерений ────────────────────────────
# ── Страница измерений ────────────────────────────
@router.get("/measurements")
def measurements_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    order_id = request.query_params.get("order_id", None)
    order_data = None
    g3_data = None
    completed_steps = []
    current_step = "measurements"

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

        conn.close()

        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

    import json

    return templates.TemplateResponse("measurements.html", {
        "request": request,
        "current_step": current_step,
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
    completed_steps = []
    current_step = "photo"
    photos = []

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None
        conn.close()

        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

        # Получаем уже загруженные фото
        photos = get_order_photos(int(order_id))
        photos_done = len(photos) >= 4

        # Если фото уже загружены — фото пройден, текущий шаг — протокол
        if photos_done:
            if "photo" not in completed_steps:
                completed_steps.append("photo")
            update_order_step(int(order_id), "protocol", completed_steps)
            current_step = "protocol"
        else:
            # Фото ещё не загружены — фото текущий шаг
            # Протокол должен быть в completed_steps (если он был пройден)
            if "protocol" not in completed_steps and "measurements" in completed_steps:
                completed_steps.append("protocol")
            update_order_step(int(order_id), "photo", completed_steps)
            current_step = "photo"

    return templates.TemplateResponse("photo.html", {
        "request": request,
        "current_step": current_step,
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order": order_data,
        "photos": photos,
        "user": user,
    })


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

    # Если загружено 4+ фото — отмечаем шаг photo как пройденный
    from app.database import get_order_photos, mark_step_completed
    photos = get_order_photos(int(order_id))
    if len(photos) >= 4:
        mark_step_completed(int(order_id), "photo", "protocol")

    return JSONResponse(content={
        "status": "ok",
        "photo_index": photo_index,
        "url": f"/uploads/order_{int(order_id)}/photo_{photo_index}.jpg"
    })


# ── Протокол испытаний ────────────────────────────
@router.get("/protocol")
def protocol_page(request: Request):
    import json
    from datetime import datetime

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
    completed_steps = []
    current_step = "protocol"

    if order_id:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None

        if order_data:
            test_date = datetime.now().strftime("%d.%m.%Y")

            order_num = order_data.get("order_number", "")
            match = re.search(r"ПС\d{2}[.\-](\d+)", order_num)
            if match:
                first_digits = match.group(1)[:4].zfill(4)
            else:
                first_digits = "0000"

            date_part = datetime.now().strftime("%d%m%y")
            serial_number = f"{first_digits}{date_part}01"

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

        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

        # Проверяем, есть ли уже фото
        photos = get_order_photos(int(order_id))
        photos_done = len(photos) >= 4

        # Если фото ещё не загружены — протокол текущий шаг
        if not photos_done:
            # Если протокол ещё не в completed_steps — добавляем
            if "protocol" not in completed_steps:
                completed_steps.append("protocol")
                update_order_step(int(order_id), "photo", completed_steps)
            else:
                update_order_step(int(order_id), "photo")
            current_step = "photo"
        # Если фото уже загружены — фото пройден, протокол текущий
        else:
            if "photo" not in completed_steps:
                completed_steps.append("photo")
            if "protocol" in completed_steps:
                completed_steps.remove("protocol")
            update_order_step(int(order_id), "protocol", completed_steps)
            current_step = "protocol"

    return templates.TemplateResponse("protocol.html", {
        "request": request,
        "current_step": current_step,
        "completed_steps": completed_steps,
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

# ── Вспомогательные функции ─────────────────────


def levenshtein_distance(s1: str, s2: str) -> int:
    """Вычисляет расстояние Левенштейна между двумя строками."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]

# ── Удаление заказа (только админ) ────────────────


@router.get("/admin/orders/delete/{order_id}")
def delete_order_route(request: Request, order_id: int):
    user = get_current_user(request)
    if not user or user["role"] != "admin":
        return RedirectResponse("/login", status_code=303)

    from app.database import delete_order
    delete_order(order_id)

    return RedirectResponse("/dashboard", status_code=303)
