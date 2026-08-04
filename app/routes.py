from fastapi import APIRouter, Request, File, UploadFile, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import os
import shutil
from app.ocr_engine import scan_document
from app.database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# ── Страница визуального контроля ──────────────────
@router.get("/visual-check")
def visual_check_page(request: Request):
    order_id = request.query_params.get("order_id", None)
    
    gch_data = None
    order_data = None
    
    if order_id:
        from app.database import get_db
        conn = get_db()
        cursor = conn.cursor()
        
        # Заказ
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None
        
        # ГЧ
        cursor.execute("SELECT * FROM gch_data WHERE order_id = ?", (int(order_id),))
        row = cursor.fetchone()
        gch_data = dict(row) if row else None
        
        # RAL цвета
        conn.close()

    import json
 
    return templates.TemplateResponse("visual_check.html", {
        "request": request,
        "order_id": order_id,
        "order": order_data,
        "gch": gch_data,
        "gch_sizes": json.loads(gch_data.get("sizes", "[]")) if gch_data else [],
        "gch_ral": gch_data.get("ral", "") if gch_data else "",
    })


# ── Главная страница = сразу сканирование ──────────
@router.get("/")
def scan_page(request: Request):
    return templates.TemplateResponse("scan.html", {"request": request})


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

    return JSONResponse(content={
        "status": "ok",
        "order_id": order_id,
        "order_number": result.get("order_number", "НЕ РАСПОЗНАНО"),
        "product_name": result.get("product_name", "НЕ РАСПОЗНАНО"),
        "department": result.get("department", "НЕ РАСПОЗНАНО"),
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
    """Проверяет совпадение изделия из КД с изделием из заказа. Возвращает сообщение об ошибке или None."""
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
    return templates.TemplateResponse("check_gch.html", {"request": request})


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
        return JSONResponse(content={
            "status": "error",
            "message": "❌ Это не ГЧ! Сфотографируйте габаритный чертёж.",
        })

    gch_match = re.search(
        r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*ГЧ)",
        full_text, re.IGNORECASE,
    )
    gch_number = gch_match.group(1).strip() if gch_match else "НЕ НАЙДЕНО"

    product_match = re.search(
        r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}",
        full_text, re.IGNORECASE,
    )
    found_product = product_match.group(0).strip() if product_match else "НЕ НАЙДЕНО"

    # Проверка изделия
    order_id_str = request.query_params.get("order_id", None)
    product_error = check_product_match(order_id_str, found_product)
    if product_error:
        return JSONResponse(content={
            "status": "error",
            "message": product_error,
        })

    ral_match = re.search(r"RAL\s*(\d{4})", full_text, re.IGNORECASE)
    ral = ral_match.group(1).strip() if ral_match else ""

    from app.green_extractor import extract_all_colored_numbers
    numbers = extract_all_colored_numbers(file_path)

    # Автосохранение
    if order_id_str:
        from app.database import save_gch
        save_gch(int(order_id_str), gch_number, ral, numbers)

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
    gch_number = data.get("gch_number", "")
    ral = data.get("ral", "")
    sizes = data.get("sizes", [])

    if order_id:
        from app.database import save_gch
        save_gch(int(order_id), gch_number, ral, sizes)
        return JSONResponse(content={"status": "ok"})

    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Страница сканирования Г3 ──────────────────────
@router.get("/check-g3")
def check_g3_page(request: Request):
    return templates.TemplateResponse("check_g3.html", {"request": request})


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
        return JSONResponse(content={
            "status": "error",
            "message": "❌ Это не Г3! Сфотографируйте гидравлическую схему.",
        })

    g3_match = re.search(
        r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*Г[3З])",
        full_text, re.IGNORECASE,
    )
    g3_number = g3_match.group(1).strip().replace('ГЗ', 'Г3') if g3_match else "НЕ НАЙДЕНО"

    product_match = re.search(
        r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}",
        full_text, re.IGNORECASE,
    )
    found_product = product_match.group(0).strip() if product_match else "НЕ НАЙДЕНО"

    # Проверка изделия
    order_id_str = request.query_params.get("order_id", None)
    product_error = check_product_match(order_id_str, found_product)
    if product_error:
        return JSONResponse(content={
            "status": "error",
            "message": product_error,
        })

    from app.param_extractor import extract_params_via_gpt
    params = extract_params_via_gpt(full_text, found_product)

    if order_id_str:
        from app.database import save_g3
        save_g3(int(order_id_str), g3_number, params)

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
    g3_number = data.get("g3_number", "")
    params = data.get("params", [])

    if order_id:
        from app.database import save_g3
        save_g3(int(order_id), g3_number, params)
        return JSONResponse(content={"status": "ok"})

    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Страница сканирования ПГ3 ─────────────────────
@router.get("/check-pg3")
def check_pg3_page(request: Request):
    return templates.TemplateResponse("check_pg3.html", {"request": request})


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
        return JSONResponse(content={
            "status": "error",
            "message": "❌ Это не ПГ3! Сфотографируйте перечень элементов.",
        })

    pg3_match = re.search(
        r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*ПГ[3З])",
        full_text, re.IGNORECASE,
    )
    pg3_number = pg3_match.group(1).strip().replace('ПГЗ', 'ПГ3') if pg3_match else "НЕ НАЙДЕНО"

    product_match = re.search(
        r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}",
        full_text, re.IGNORECASE,
    )
    found_product = product_match.group(0).strip() if product_match else "НЕ НАЙДЕНО"

    # Проверка изделия
    order_id_str = request.query_params.get("order_id", None)
    product_error = check_product_match(order_id_str, found_product)
    if product_error:
        return JSONResponse(content={
            "status": "error",
            "message": product_error,
        })

    from app.param_extractor import extract_pg3_via_gpt
    items = extract_pg3_via_gpt(full_text, found_product)

    if order_id_str:
        from app.database import save_pg3
        save_pg3(int(order_id_str), pg3_number, items)

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
    pg3_number = data.get("pg3_number", "")
    items = data.get("items", [])

    if order_id:
        from app.database import save_pg3
        save_pg3(int(order_id), pg3_number, items)
        return JSONResponse(content={"status": "ok"})

    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)

