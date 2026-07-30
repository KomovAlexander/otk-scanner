from fastapi import APIRouter, Request, File, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import os
import shutil
from app.ocr_engine import scan_document

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Главная страница = сразу сканирование ──────────
@router.get("/")
def scan_page(request: Request):
    return templates.TemplateResponse("scan.html", {"request": request})


# ── Эндпоинт приёма фото ─────────────────────────────
@router.post("/api/scan")
async def api_scan(file: UploadFile = File(...)):
    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    result = scan_document(file_path)

    return JSONResponse(content={
        "status": "ok",
        "order_number": result.get("order_number", "НЕ РАСПОЗНАНО"),
        "product_name": result.get("product_name", "НЕ РАСПОЗНАНО"),
        "department": result.get("department", "НЕ РАСПОЗНАНО"),
        "confidence": result.get("confidence", 0.0)
    })

# ── Страница сканирования ГЧ ──────────────────────


@router.get("/check-gch")
def check_gch_page(request: Request):
    return templates.TemplateResponse("check_gch.html", {"request": request})


@router.post("/api/scan-gch")
async def api_scan_gch(file: UploadFile = File(...)):
    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    import uuid
    safe_name = f"gch_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Автовыравнивание
    from app.ocr_engine import perspective_correction
    perspective_correction(file_path)

    # Распознаём текст
    from app.ocr_engine import scan_document
    import re

    result = scan_document(file_path)
    full_text = result.get("full_text", "")

    # Ищем номер ГЧ (например: В1-0169.000.000 ГЧ)
    gch_match = re.search(
        r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*ГЧ)",
        full_text, re.IGNORECASE,
    )
    gch_number = gch_match.group(1).strip() if gch_match else "НЕ НАЙДЕНО"

    # Ищем изделие (CTR-KV-...)
    product_match = re.search(
        r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}",
        full_text, re.IGNORECASE,
    )
    found_product = product_match.group(
        0).strip() if product_match else "НЕ НАЙДЕНО"

    # Извлекаем размеры
    from app.green_extractor import extract_all_colored_numbers
    numbers = extract_all_colored_numbers(file_path)
    # Ищем RAL (например: RAL6009)
    ral_match = re.search(
        r"RAL\s*(\d{4})",
        full_text, re.IGNORECASE,
    )
    ral = ral_match.group(1).strip() if ral_match else ""

    return JSONResponse(content={
        "status": "ok",
        "gch_number": gch_number,
        "found_product": found_product,
        "ral": ral,
        "numbers": numbers,
        "count": len(numbers),
    })

# ── Страница сканирования Г3 ──────────────────────
@router.get("/check-g3")
def check_g3_page(request: Request):
    return templates.TemplateResponse("check_g3.html", {"request": request})


# ── Эндпоинт приёма фото Г3 ───────────────────────
@router.post("/api/scan-g3")
async def api_scan_g3(file: UploadFile = File(...)):
    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    
    import uuid
    safe_name = f"g3_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Автовыравнивание
    from app.ocr_engine import perspective_correction
    perspective_correction(file_path)

    # Распознаём текст
    from app.ocr_engine import scan_document
    import re

    result = scan_document(file_path)
    full_text = result.get("full_text", "")

    # Ищем номер Г3
    g3_match = re.search(
        r"([A-ZА-Я]{1,2}\d{1,2}[.\-]\d{3,4}[.\-]\d{3,4}[.\-]\d{3,4}\s*Г[3З])",
        full_text, re.IGNORECASE,
    )
    if g3_match:
        g3_number = g3_match.group(1).strip().replace('ГЗ', 'Г3')
    g3_number = g3_match.group(1).strip() if g3_match else "НЕ НАЙДЕНО"

    # Ищем изделие
    product_match = re.search(
        r"CTR[.\-\s]?KV[.\-\s]?[A-ZА-Я0-9.\-]{2,}",
        full_text, re.IGNORECASE,
    )
    found_product = product_match.group(0).strip() if product_match else "НЕ НАЙДЕНО"

    # Извлекаем параметры через GPT
    from app.param_extractor import extract_params_via_gpt
    params = extract_params_via_gpt(full_text, found_product)

    return JSONResponse(content={
        "status": "ok",
        "g3_number": g3_number,
        "found_product": found_product,
        "params": params,
        "count": len(params),
    })