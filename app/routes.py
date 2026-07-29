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
    
    # Сохраняем с латинским именем
    import uuid
    safe_name = f"gch_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    from app.green_extractor import extract_all_colored_numbers
    numbers = extract_all_colored_numbers(file_path)

    return JSONResponse(content={
        "status": "ok",
        "numbers": numbers,
        "count": len(numbers),
    })