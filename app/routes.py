from fastapi import APIRouter, Request, File, UploadFile, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import os
import shutil
from app.ocr_engine import scan_document
from app.database import get_db

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


# ── Главная страница = сразу сканирование ──────────
@router.get("/")
def scan_page(request: Request):
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
            
        # Проверяем ГЧ
        if order_data:
            cursor.execute("SELECT id FROM gch_data WHERE order_id = ?", (int(order_id),))
            if cursor.fetchone():
                completed_steps.append("gch")
        # Проверяем Г3
        if order_data:
            cursor.execute("SELECT id FROM g3_data WHERE order_id = ?", (int(order_id),))
            if cursor.fetchone():
                completed_steps.append("g3")
        # Проверяем ПГ3
        if order_data:
            cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
            if cursor.fetchone():
                completed_steps.append("pg3")
        if order_data:
            cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
            if cursor.fetchone():
                completed_steps.append("visual")                 
        conn.close()

    return templates.TemplateResponse("scan.html", {
        "request": request,
        "current_step": "order",
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order_data": order_data,
        "saved_photo": saved_photo,
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
    order_id = get_or_create_order(
        result.get("order_number", ""),
        result.get("product_name", ""),
        result.get("department", ""),
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
    cursor.execute("SELECT product_name, order_number FROM orders WHERE id = ?", (int(order_id),))
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
        
        cursor.execute("SELECT * FROM gch_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        gch_data = dict(row) if row else None
        
        if gch_data:
            completed_steps.append("gch")
            saved_photo = get_saved_file_path(int(order_id), "gch")
            
        cursor.execute("SELECT id FROM g3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("g3")
            
        cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("pg3")

        cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("visual")            
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

    product_match = re.search(r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}", full_text, re.IGNORECASE)
    found_product = product_match.group(0).strip() if product_match else "НЕ НАЙДЕНО"

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
            order_dir = os.path.join("app/static/uploads", f"order_{int(order_id_str)}")
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
        save_gch(int(order_id), data.get("gch_number", ""), data.get("ral", ""), data.get("sizes", []))
        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Страница сканирования Г3 ──────────────────────
@router.get("/check-g3")
def check_g3_page(request: Request):
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
        cursor.execute("SELECT id FROM gch_data WHERE order_id = ?", (int(order_id),))
        if not cursor.fetchone():
            completed_steps.remove("gch")
        
        cursor.execute("SELECT * FROM g3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        g3_data = dict(row) if row else None
       
        if g3_data:
            completed_steps.append("g3")
            saved_photo = get_saved_file_path(int(order_id), "g3")
            
        cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("pg3")
        cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("visual")             
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

    g3_match = re.search(r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*Г[3З])", full_text, re.IGNORECASE)
    g3_number = g3_match.group(1).strip().replace('ГЗ', 'Г3') if g3_match else "НЕ НАЙДЕНО"

    product_match = re.search(r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}", full_text, re.IGNORECASE)
    found_product = product_match.group(0).strip() if product_match else "НЕ НАЙДЕНО"

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
            order_dir = os.path.join("app/static/uploads", f"order_{int(order_id_str)}")
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
        save_g3(int(order_id), data.get("g3_number", ""), data.get("params", []))
        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Страница сканирования ПГ3 ─────────────────────
@router.get("/check-pg3")
def check_pg3_page(request: Request):
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
        cursor.execute("SELECT id FROM gch_data WHERE order_id = ?", (int(order_id),))
        if not cursor.fetchone():
            completed_steps = [s for s in completed_steps if s != "gch"]
        cursor.execute("SELECT id FROM g3_data WHERE order_id = ?", (int(order_id),))
        if not cursor.fetchone():
            completed_steps = [s for s in completed_steps if s != "g3"]
        
        cursor.execute("SELECT * FROM pg3_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        pg3_data = dict(row) if row else None
        cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("visual")        
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

    pg3_match = re.search(r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*ПГ[3З])", full_text, re.IGNORECASE)
    pg3_number = pg3_match.group(1).strip().replace('ПГЗ', 'ПГ3') if pg3_match else "НЕ НАЙДЕНО"

    product_match = re.search(r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}", full_text, re.IGNORECASE)
    found_product = product_match.group(0).strip() if product_match else "НЕ НАЙДЕНО"

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
            order_dir = os.path.join("app/static/uploads", f"order_{int(order_id_str)}")
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
        save_pg3(int(order_id), data.get("pg3_number", ""), data.get("items", []))
        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Страница визуального контроля ──────────────────
@router.get("/visual-check")
def visual_check_page(request: Request):
    order_id = request.query_params.get("order_id", None)
    
    gch_data = None
    order_data = None
    completed_steps = ["order", "gch", "g3", "pg3"]
    
    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None
        
        cursor.execute("SELECT * FROM gch_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        gch_data = dict(row) if row else None
        
        # Проверяем реально пройденные шаги
        if not gch_data:
            completed_steps = [s for s in completed_steps if s != "gch"]
        cursor.execute("SELECT id FROM g3_data WHERE order_id = ?", (int(order_id),))
        if not cursor.fetchone():
            completed_steps = [s for s in completed_steps if s != "g3"]
        cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if not cursor.fetchone():
            completed_steps = [s for s in completed_steps if s != "pg3"]
            
        # Визуальный контроль доступен если есть ПГ3
        cursor.execute("SELECT id FROM pg3_data WHERE order_id = ?", (int(order_id),))
        if cursor.fetchone():
            completed_steps.append("visual")
        
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
    })