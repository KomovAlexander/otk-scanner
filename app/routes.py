# ========== routes.py ==========

import os
import re
import shutil
import uuid

import pymupdf
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import authenticate, get_current_user
from app.database import (get_all_orders, get_all_pg3_items, get_db,
                          get_measurement_results, get_order_photos,
                          get_order_progress, get_pg3_pages,
                          get_visual_results, is_order_completed,
                          mark_step_completed, save_pg3_page,
                          update_order_step)
from app.ocr_engine import scan_document


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


def convert_pdf_to_image(pdf_path: str, output_dir: str = "app/static/uploads/temp") -> str:
    os.makedirs(output_dir, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    if len(doc) == 0:
        doc.close()
        raise Exception("PDF пустой")

    page = doc[0]
    mat = pymupdf.Matrix(2.0, 2.0)
    pix = page.get_pixmap(matrix=mat)

    jpg_path = os.path.join(output_dir, f"pdf_{uuid.uuid4().hex[:8]}.jpg")
    pix.save(jpg_path)

    doc.close()
    return jpg_path


def save_uploaded_file_to_temp(file: UploadFile, upload_dir: str = "app/static/uploads") -> str:
    """
    Сохраняет загруженный файл (PDF или изображение) во временный JPG.
    Возвращает путь к JPG-файлу.
    """
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename or "")[1].lower()

    if file_ext == ".pdf":
        # Сохраняем PDF
        pdf_path = os.path.join(upload_dir, f"pdf_{uuid.uuid4().hex[:8]}.pdf")
        with open(pdf_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Конвертируем в JPG
        jpg_path = convert_pdf_to_image(pdf_path)

        # Удаляем PDF
        os.remove(pdf_path)

        return jpg_path
    else:
        # Обычное изображение
        safe_name = f"scan_{uuid.uuid4().hex[:8]}.jpg"
        file_path = os.path.join(upload_dir, safe_name)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        return file_path


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


def handle_gpt_error(e: Exception) -> JSONResponse:
    """Общий обработчик ошибок GPT."""
    print(f"GPT error: {e}")
    return JSONResponse(content={
        "status": "error",
        "message": "⚠️ Сервис распознавания временно недоступен. Попробуйте позже или заполните данные вручную."
    })


def check_document_match(order_id: str, found_product: str, doc_number: str) -> str | None:
    """Проверяет, что документ соответствует заказу по изделию и номеру."""
    if not order_id:
        return None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_name FROM orders WHERE id = ?", (int(order_id),))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    order_product = row["product_name"]

    def normalize(s: str) -> str:
        s = s.upper()
        # Заменяем кириллицу на латиницу
        replacements = {
            'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M',
            'Н': 'H', 'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T',
            'У': 'Y', 'Х': 'X', 'З': '3',
        }
        for cyr, lat in replacements.items():
            s = s.replace(cyr, lat)
        s = s.replace("-", "").replace(" ", "").replace(".", "")
        return s

    # Проверяем изделие
    product_found = False
    product_exact = False
    product_close = False

    if found_product and found_product != "НЕ НАЙДЕНО":
        product_found = True
        op = normalize(order_product)
        fp = normalize(found_product)

        if fp == op or fp in op or op in fp:
            product_exact = True
        elif levenshtein_distance(op, fp) <= 2:
            product_close = True

    # Проверяем номер документа
    doc_found = False
    doc_exact = False
    doc_close = False

    if doc_number and doc_number != "НЕ НАЙДЕНО":
        doc_found = True
        doc_base = re.sub(
            r'[.\-\s]\d{3,4}[.\-\s]\d{3,4}.*$', '', doc_number.strip())
        doc_base = re.sub(r'\s*(?:ГЧ|СБ|Г[3З]|ПГ[3З])$', '', doc_base)
        doc_code = normalize(doc_base)
        product_code = normalize(order_product)

        if doc_code == product_code or doc_code in product_code or product_code in doc_code:
            doc_exact = True
        elif levenshtein_distance(doc_code, product_code) <= 2:
            doc_close = True

    if (product_exact or product_close) and (doc_exact or doc_close):
        if product_exact and doc_exact:
            return None  # ✅ Точное совпадение
        else:
            # ⚠️ Похоже, но не точно — спрашиваем
            return "⚠️ Документ похож, но есть расхождения. Точно ли это тот документ?"
    elif not doc_found:
        return "⚠️ Номер документа не распознан. Продолжить?"
    elif not product_found:
        return "⚠️ Изделие не распознано. Продолжить?"
    else:
        return "❌ Документ не соответствует заказу!"


def send_web_push_to_user(user_id: int, title: str, body: str, url: str):
    """Отправляет Web Push всем подпискам пользователя."""
    import json
    import os
    from dotenv import load_dotenv
    from pywebpush import webpush, WebPushException
    from app.database import get_push_subscriptions, delete_push_subscription

    load_dotenv()
    
    vapid_private = os.getenv("VAPID_PRIVATE_KEY", "").strip('"').strip("'")
    vapid_subject = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    
    if not vapid_private:
        print("⚠️ VAPID_PRIVATE_KEY не настроен, пуш не отправлен")
        return

    subs = get_push_subscriptions(user_id)
    if not subs:
        return

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url
    })

    for sub in subs:
        try:
            sub_info = json.loads(sub["subscription_json"])
            webpush(
                subscription_info=sub_info,
                data=payload,
                vapid_private_key=vapid_private,
                vapid_claims={"sub": vapid_subject}
            )
            print(f"✅ Пуш успешно отправлен для user {user_id}")
        except WebPushException as ex:
            print(f"Ошибка пуша для user {user_id}: {ex}")
            if ex.response and ex.response.status_code == 410:
                delete_push_subscription(sub["id"])
        except Exception as e:
            print(f"Общая ошибка пуша: {e}")


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
        product_error = check_document_match(
            order_id_str, found_product, doc_number)
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
        rotation = 360
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
    permission = None

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

        # Статус запроса на работу без ГЧ
        from app.database import get_active_permission, mark_step_completed
        permission = get_active_permission(int(order_id), "no_gch")

        # Если разрешено работать без ГЧ — считаем шаг "gch" пройденным
        if permission and permission["status"] == "approved":
            if "gch" not in completed_steps:
                mark_step_completed(int(order_id), "gch", "g3")
                # Перечитываем прогресс, чтобы шаблон увидел обновлённые данные
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
        "permission": permission,
        "user": user,
    })


# ── Эндпоинт приёма фото ГЧ ───────────────────────
@router.post("/api/scan-gch")
async def api_scan_gch(request: Request, file: UploadFile = File(...)):
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"status": "error"}, status_code=401)

    file_path = save_uploaded_file_to_temp(file)

    order_id_str = request.query_params.get("order_id", None)

    # Общая обработка
    result = process_document_scan(file_path, "ГЧ", order_id_str)

    if result["status"] == "error":
        return JSONResponse(content=result)

    # Продолжаем при "ok" и "warning"
    full_text = result.get("full_text", "")
    gch_number = result.get("doc_number", "НЕ НАЙДЕНО")
    found_product = result.get("found_product", "НЕ НАЙДЕНО")

    # Извлекаем RAL и размеры
    ral_match = re.search(r"RAL\s*(\d{4})", full_text, re.IGNORECASE)
    ral = ral_match.group(1).strip() if ral_match else ""

    from app.green_extractor import extract_all_colored_numbers
    numbers = extract_all_colored_numbers(file_path)

    # Сохраняем
    if order_id_str:
        from app.database import save_gch
        order_id = int(order_id_str)
        save_gch(order_id, gch_number, ral, numbers)

        order_dir = f"app/static/uploads/order_{order_id}"
        os.makedirs(order_dir, exist_ok=True)
        dest_path = f"{order_dir}/gch.jpeg"

        # Удаляем старый файл если есть
        if os.path.exists(dest_path):
            os.remove(dest_path)

        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

    return JSONResponse(content={
        "status": result["status"],
        "message": result.get("message", ""),
        "gch_number": gch_number,
        "found_product": found_product,
        "ral": ral,
        "numbers": numbers,
        "count": len(numbers),
        "preview_url": f"/uploads/{os.path.basename(file_path)}",
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

    file_path = save_uploaded_file_to_temp(file)

    order_id_str = request.query_params.get("order_id", None)

    # Общая обработка
    result = process_document_scan(file_path, "Г3", order_id_str)

    if result["status"] == "error":
        return JSONResponse(content=result)

    # Продолжаем при "ok" и "warning"
    full_text = result.get("full_text", "")
    g3_number = result.get("doc_number", "НЕ НАЙДЕНО")
    found_product = result.get("found_product", "НЕ НАЙДЕНО")

    # Извлекаем параметры
    from app.param_extractor import extract_params_via_gpt
    try:
        params = extract_params_via_gpt(full_text, found_product)
    except Exception as e:
        return handle_gpt_error(e)

    # Сохраняем
    if order_id_str:
        from app.database import save_g3
        order_id = int(order_id_str)
        save_g3(order_id, g3_number, params)

        order_dir = f"app/static/uploads/order_{order_id}"
        os.makedirs(order_dir, exist_ok=True)
        dest_path = f"{order_dir}/g3.jpeg"

        # Удаляем старый файл если есть
        if os.path.exists(dest_path):
            os.remove(dest_path)

        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

    return JSONResponse(content={
        "status": result["status"],
        "message": result.get("message", ""),
        "g3_number": g3_number,
        "found_product": found_product,
        "params": params,
        "count": len(params),
        "preview_url": f"/uploads/{os.path.basename(file_path)}",
    })


# ── Эндпоинт ручного сохранения Г3 ─────────────────
@router.post("/api/save-g3")
async def api_save_g3(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import save_g3, mark_step_completed, get_order_progress
        save_g3(int(order_id), data.get(
            "g3_number", ""), data.get("params", []))

        progress = get_order_progress(int(order_id))
        if "g3" not in progress["completed_steps"]:
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
    order_data = None
    completed_steps = []
    current_step = "pg3"
    pages = []
    current_page = request.query_params.get("page", "1")
    current_page_items = []
    current_pg3_number = ""

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

        # Получаем страницы ПГ3
        pages = get_pg3_pages(int(order_id))

        # Если страниц нет — создаём первую пустую
        if not pages:
            save_pg3_page(int(order_id), 1, "", [])
            pages = get_pg3_pages(int(order_id))

        # Находим текущую страницу
        import json
        for page in pages:
            if str(page["page_number"]) == str(current_page):
                current_pg3_number = page.get("pg3_number", "")
                current_page_items = json.loads(page.get("items", "[]"))
                break

    return templates.TemplateResponse("check_pg3.html", {
        "request": request,
        "current_step": current_step,
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order_data": order_data,
        "pages": pages,
        "current_page": current_page,
        "current_page_items": current_page_items,
        "current_pg3_number": current_pg3_number,
        "user": user,
    })


# ── Эндпоинт приёма фото ПГ3 ──────────────────────
@router.post("/api/scan-pg3")
async def api_scan_pg3(request: Request, file: UploadFile = File(...)):
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"status": "error"}, status_code=401)

    file_path = save_uploaded_file_to_temp(file)

    order_id_str = request.query_params.get("order_id", None)
    page_number = int(request.query_params.get("page_number", "1"))

    result = process_document_scan(file_path, "ПГ3", order_id_str)

    if result["status"] == "error":
        return JSONResponse(content=result)

    full_text = result.get("full_text", "")
    pg3_number = result.get("doc_number", "НЕ НАЙДЕНО")
    found_product = result.get("found_product", "НЕ НАЙДЕНО")

    from app.param_extractor import extract_pg3_via_gpt
    try:
        items = extract_pg3_via_gpt(full_text, found_product)
    except Exception as e:
        return handle_gpt_error(e)

    if order_id_str:
        from app.database import clear_visual_pg3_for_order, save_pg3_page
        order_id = int(order_id_str)

        # Сохраняем страницу
        save_pg3_page(order_id, page_number, pg3_number, items)

        # Сбрасываем визуальный контроль
        clear_visual_pg3_for_order(order_id)

        order_dir = f"app/static/uploads/order_{order_id}"
        os.makedirs(order_dir, exist_ok=True)
        dest_path = f"{order_dir}/pg3_page_{page_number}.jpeg"

        # Просто перезаписываем
        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

    return JSONResponse(content={
        "status": result["status"],
        "message": result.get("message", ""),
        "pg3_number": pg3_number,
        "found_product": found_product,
        "items": items,
        "count": len(items),
        "page_number": page_number,
        "preview_url": f"/uploads/{os.path.basename(file_path)}",
    })


# ── Эндпоинт ручного сохранения ПГ3 ────────────────
@router.post("/api/save-pg3")
async def api_save_pg3(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    page_number = data.get("page_number", 1)

    if order_id:
        from app.database import (get_order_progress, mark_step_completed,
                                  save_pg3_page)

        save_pg3_page(
            int(order_id),
            page_number,
            data.get("pg3_number", ""),
            data.get("items", [])
        )

        progress = get_order_progress(int(order_id))
        if "pg3" not in progress["completed_steps"]:
            mark_step_completed(int(order_id), "pg3", "visual")

        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Сохранение визуального контроля ──────────────────
@router.post("/api/save-visual")
async def api_save_visual(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import (get_order_progress, mark_step_completed,
                                  save_visual_results)
        save_visual_results(int(order_id), data)

        # Отмечаем шаг всегда, если ещё не пройден
        progress = get_order_progress(int(order_id))
        if "visual" not in progress["completed_steps"]:
            mark_step_completed(int(order_id), "visual", "measurements")

        return JSONResponse(content={"status": "ok"})
    return JSONResponse(content={"status": "error", "message": "Нет order_id"}, status_code=400)


# ── Сохранение измерений ────────────────────────────
@router.post("/api/save-measurements")
async def api_save_measurements(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    if order_id:
        from app.database import mark_step_completed, save_measurement_results, get_order_progress
        save_measurement_results(int(order_id), data)

        # Проверяем, ВСЕ ли обязательные поля заполнены
        all_filled = True

        # 1. Все параметры Г3 заполнены
        g3_values = data.get("g3_values", [])
        if not g3_values or any(not v.get("value") for v in g3_values):
            all_filled = False

        # 2. Все токи заполнены
        currents = data.get("currents", [])
        if not currents or any(not c.get("value") for c in currents):
            all_filled = False

        # 3. Все номинальные токи заполнены
        nominal_currents = data.get("nominal_currents", [])
        if not nominal_currents or any(not n.get("value") for n in nominal_currents):
            all_filled = False

        # Обратная совместимость: если старый формат (nominal_current без массива)
        if not nominal_currents and not data.get("nominal_current"):
            all_filled = False

        # 4. Шум заполнен
        if not data.get("noise_idle") or not data.get("noise_load"):
            all_filled = False

        # 5. Рабочая жидкость выбрана
        if not data.get("fluid"):
            all_filled = False

        # Только если ВСЁ заполнено — отмечаем шаг пройденным
        if all_filled:
            progress = get_order_progress(int(order_id))
            if "measurements" not in progress["completed_steps"]:
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
    order_data = None
    completed_steps = []
    current_step = "visual"
    pg3_items = []

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

        conn.close()

        # Объединяем позиции со всех страниц ПГ3
        pg3_items = get_all_pg3_items(int(order_id))

        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

    import json

    # Если в gch_data стоит метка "БЕЗ ГЧ" — скрываем весь раздел ГЧ
    gch_is_absent = bool(gch_data and gch_data.get("gch_number") == "БЕЗ ГЧ")

    return templates.TemplateResponse("visual_check.html", {
        "request": request,
        "current_step": current_step,
        "completed_steps": completed_steps,
        "order_id": order_id,
        "order": order_data,
        "gch": gch_data,
        "gch_is_absent": gch_is_absent,
        "gch_sizes": json.loads(gch_data.get("sizes", "[]")) if gch_data else [],
        "gch_ral": gch_data.get("ral", "") if gch_data else "",
        "g3_params": json.loads(g3_data.get("params", "[]")) if g3_data else [],
        "pg3_items": pg3_items,
        "user": user,
    })


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
    import re
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

        # ─── Подготавливаем допуски для измерений ───
        def parse_tolerance(tolerance_str: str, etalon: float) -> tuple:
            if not tolerance_str:
                tol = max(0.5, abs(etalon) * 0.05)
                return tol, tol

            numbers = re.findall(r'[\d.]+', tolerance_str)
            if not numbers:
                tol = max(0.5, abs(etalon) * 0.05)
                return tol, tol

            value = float(numbers[0])

            if '±' in tolerance_str:
                return value, value
            elif tolerance_str.strip().startswith('+'):
                return 0, value
            elif tolerance_str.strip().startswith('-'):
                return value, 0
            else:
                return value, value

        # Подготавливаем данные измерений с допусками
        if measurement_data.get('g3_values'):
            for m_val in measurement_data['g3_values']:
                matching = None
                for g3_param in g3_params:
                    if (g3_param.get('name') == m_val.get('name') and
                            g3_param.get('position') == m_val.get('position', '')):
                        matching = g3_param
                        break

                if matching and m_val.get('etalon'):
                    try:
                        etalon = float(str(m_val['etalon']).replace(',', '.'))
                        lower_tol, upper_tol = parse_tolerance(
                            matching.get('tolerance', ''), etalon)
                        m_val['lower_tol'] = lower_tol
                        m_val['upper_tol'] = upper_tol
                        m_val['tolerance_display'] = matching.get(
                            'tolerance', '')
                    except (ValueError, TypeError):
                        m_val['lower_tol'] = 0
                        m_val['upper_tol'] = 0
                        m_val['tolerance_display'] = ''
                else:
                    m_val['lower_tol'] = 0
                    m_val['upper_tol'] = 0
                    m_val['tolerance_display'] = ''

        # ─── Подготавливаем номинальные токи как dict по position ───
        if measurement_data:
            nominal_dict = {}
            if measurement_data.get('nominal_currents'):
                for nom in measurement_data['nominal_currents']:
                    pos = nom.get('position', '')
                    nominal_dict[pos] = nom.get('value', '')
            elif measurement_data.get('nominal_current'):
                nominal_dict[''] = measurement_data['nominal_current']
            measurement_data['nominal_currents_dict'] = nominal_dict

        progress = get_order_progress(int(order_id))
        completed_steps = progress["completed_steps"]
        current_step = progress["current_step"]

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


# ── Страница шильдика ─────────────────────────────
@router.get("/shildik")
def shildik_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    order_id = request.query_params.get("order_id", None)
    order_data = None
    serial_number = ""
    test_date = ""

    if order_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
        row = cursor.fetchone()
        order_data = dict(row) if row else None
        conn.close()

        if order_data:
            import re as re_module
            from datetime import datetime

            test_date = datetime.now().strftime("%d.%m.%Y")

            order_num = order_data.get("order_number", "")
            match = re_module.search(r"ПС\d{2}[.\-](\d+)", order_num)
            if match:
                first_digits = match.group(1)[:4].zfill(4)
            else:
                first_digits = "0000"

            date_part = datetime.now().strftime("%d%m%y")
            serial_number = f"{first_digits}{date_part}01"

    return templates.TemplateResponse("shildik.html", {
        "request": request,
        "order": order_data,
        "serial_number": serial_number,
        "test_date": test_date,
        "user": user,
    })


@router.get("/shildik/svg")
def shildik_svg(request: Request):
    from fastapi.responses import Response

    order_id = request.query_params.get("order_id", None)
    if not order_id:
        return Response(content="Ошибка: нет order_id", media_type="text/plain")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return Response(content="Ошибка: заказ не найден", media_type="text/plain")

    order_data = dict(row)

    import re as re_module
    from datetime import datetime

    test_date = datetime.now().strftime("%d.%m.%Y")

    order_num = order_data.get("order_number", "")
    match = re_module.search(r"ПС\d{2}[.\-](\d+)", order_num)
    if match:
        first_digits = match.group(1)[:4].zfill(4)
    else:
        first_digits = "0000"

    date_part = datetime.now().strftime("%d%m%y")
    serial_number = f"{first_digits}{date_part}01"

    from app.shildik_generator import generate_shildik_svg
    svg = generate_shildik_svg(
        product_name=order_data.get("product_name", ""),
        serial_number=serial_number,
        test_date=test_date,
        order_number=order_data.get("order_number", "")
    )

    return Response(content=svg, media_type="image/svg+xml")


@router.get("/presentation")
def presentation_page(request: Request):
    return templates.TemplateResponse("presentation.html", {"request": request})


@router.get("/api/delete-pg3-page")
def api_delete_pg3_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    page_id = request.query_params.get("page_id", None)
    order_id = request.query_params.get("order_id", None)

    if not page_id or not order_id:
        return RedirectResponse(f"/check-pg3?order_id={order_id}", status_code=303)

    from app.database import delete_pg3_page, get_pg3_pages, save_pg3_page
    import json

    delete_pg3_page(int(page_id))

    pages = get_pg3_pages(int(order_id))
    for index, page in enumerate(pages, start=1):
        if page["page_number"] != index:
            save_pg3_page(
                int(order_id),
                index,
                page["pg3_number"],
                json.loads(page["items"]) if page["items"] else []
            )
            delete_pg3_page(page["id"])

    return RedirectResponse(f"/check-pg3?order_id={order_id}&page=1", status_code=303)


# ── Запросы разрешений ─────────────────────────────
@router.post("/api/request-permission")
async def api_request_permission(request: Request):
    """Испытатель просит разрешение (например, работать без ГЧ)."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "error"}, status_code=401)

    data = await request.json()
    order_id = data.get("order_id")
    type_ = data.get("type", "no_gch")
    reason = (data.get("reason") or "").strip()

    if not order_id:
        return JSONResponse(
            {"status": "error", "message": "Нет order_id"},
            status_code=400
        )
    if len(reason) < 5:
        return JSONResponse(
            {"status": "error",
                "message": "Опишите причину подробнее (мин. 5 символов)"},
            status_code=400
        )

    from app.database import create_permission_request
    rid = create_permission_request(int(order_id), user["id"], type_, reason)
    return JSONResponse({"status": "ok", "request_id": rid})


@router.get("/api/permission-status")
def api_permission_status(request: Request):
    """Возвращает статус последнего запроса по заказу и типу."""
    order_id = request.query_params.get("order_id")
    type_ = request.query_params.get("type", "no_gch")

    if not order_id:
        return JSONResponse({"status": "error"}, status_code=400)

    from app.database import get_active_permission
    perm = get_active_permission(int(order_id), type_)
    return JSONResponse({"status": "ok", "permission": perm})


# ── Поиск пользователей для @-подсказки ────────────
@router.get("/api/users/search")
def api_users_search(request: Request):
    """Поиск пользователей по логину/фамилии/имени для автодополнения @.
    Фильтрация в Python — потому что SQLite LOWER() не работает с кириллицей."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "error"}, status_code=401)

    q = (request.query_params.get("q") or "").strip().lower()

    from app.database import get_db
    conn = get_db()
    cursor = conn.cursor()
    # Выбираем всех — пользователей немного, фильтруем в Python
    cursor.execute(
        "SELECT id, login, first_name, last_name, role FROM users ORDER BY last_name, first_name")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Фильтрация в Python — корректно работает с кириллицей
    if q:
        filtered = []
        for r in rows:
            login_l = (r["login"] or "").lower()
            last_l = (r["last_name"] or "").lower()
            first_l = (r["first_name"] or "").lower()
            if q in login_l or q in last_l or q in first_l:
                filtered.append(r)
        rows = filtered

    # Себя не предлагаем
    rows = [r for r in rows if r["id"] != user["id"]]
    rows = rows[:10]

    # Спец-пункт для группы админов — всегда первым
    result = [{
        "id": 0,
        "login": "админ",
        "first_name": "",
        "last_name": "Группа: все администраторы",
        "role": "group",
        "is_group": True
    }]

    for r in rows:
        result.append({
            "id": r["id"],
            "login": r["login"],
            "first_name": r["first_name"] or "",
            "last_name": r["last_name"] or "",
            "role": r["role"],
            "is_group": False
        })

    return JSONResponse({"status": "ok", "users": result})


# ── Чат заказа ─────────────────────────────────────
@router.get("/api/chat/{order_id}")
def api_get_chat(request: Request, order_id: int):
    """Возвращает все сообщения чата по заказу."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "error"}, status_code=401)

    from app.database import get_chat_messages
    messages = get_chat_messages(order_id)
    return JSONResponse({"status": "ok", "messages": messages})


@router.post("/api/chat/{order_id}")
async def api_post_chat(request: Request, order_id: int):
    """Принимает сообщение (текст и/или фото) и сохраняет в БД."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "error"}, status_code=401)

    form = await request.form()
    text = (form.get("text") or "").strip()
    photo = form.get("photo")

    photo_path = ""
    if photo and hasattr(photo, "filename") and photo.filename:
        chat_dir = os.path.join(UPLOAD_ROOT, f"order_{order_id}", "chat")
        os.makedirs(chat_dir, exist_ok=True)
        fname = f"chat_{uuid.uuid4().hex[:8]}.jpg"
        full_path = os.path.join(chat_dir, fname)
        with open(full_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        photo_path = f"/uploads/order_{order_id}/chat/{fname}"

    if not text and not photo_path:
        return JSONResponse(
            {"status": "error", "message": "Пустое сообщение"},
            status_code=400
        )

    from app.database import (add_chat_message, add_mention, add_notification, 
                              find_user_by_login_or_name, get_admin_users, get_db)

    rid = add_chat_message(order_id, user["id"], text, photo_path)

    # ── Парсинг @-упоминаний ──
    if text:
        import re as _re
        found = _re.findall(r'@([A-Za-zА-Яа-я0-9_\-]+)', text)
        seen_user_ids = set()
        
        # Получаем имя автора и номер заказа для пуша
        author_name = f"{user.get('last_name','')} {user.get('first_name','')}".strip() or user.get('login','')
        order_number = ""
        try:
            conn_o = get_db()
            cur_o = conn_o.cursor()
            cur_o.execute("SELECT order_number FROM orders WHERE id = ?", (order_id,))
            r_o = cur_o.fetchone()
            if r_o:
                order_number = r_o["order_number"]
            conn_o.close()
        except Exception:
            pass

        for token in found:
            token_low = token.lower()

            # Группа @админ / @admin
            if token_low in ("админ", "admin", "админы", "admins"):
                for adm in get_admin_users():
                    if adm["id"] == user["id"] or adm["id"] in seen_user_ids:
                        continue
                    seen_user_ids.add(adm["id"])
                    add_mention(rid, adm["id"])
                    add_notification(adm["id"], order_id, rid, "Вас упомянули в чате заказа")
                    
                    # ОТПРАВКА ПУША
                    send_web_push_to_user(
                        adm["id"], 
                        f"Упоминание: заказ {order_number}", 
                        f"{author_name}: {text[:50]}...", 
                        f"/?order_id={order_id}&open_chat=1"
                    )
                continue

            # Конкретный пользователь
            target = find_user_by_login_or_name(token)
            if target and target["id"] != user["id"] and target["id"] not in seen_user_ids:
                seen_user_ids.add(target["id"])
                add_mention(rid, target["id"])
                add_notification(target["id"], order_id, rid, "Вас упомянули в чате заказа")
                
                # ОТПРАВКА ПУША
                send_web_push_to_user(
                    target["id"], 
                    f"Упоминание: заказ {order_number}", 
                    f"{author_name}: {text[:50]}...", 
                    f"/?order_id={order_id}&open_chat=1"
                )

    return JSONResponse({"status": "ok", "id": rid})


# ── Уведомления (звоночек) ──────────────────────────
@router.get("/api/notifications")
def api_notifications(request: Request):
    """Непрочитанные уведомления текущего пользователя + их количество."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "error"}, status_code=401)

    from app.database import get_unread_notifications, count_unread_notifications
    items = get_unread_notifications(user["id"])
    total = count_unread_notifications(user["id"])
    return JSONResponse({"status": "ok", "count": total, "items": items})


@router.post("/api/notifications/read")
async def api_notifications_read(request: Request):
    """Помечает уведомления прочитанными (по заказу или все)."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "error"}, status_code=401)

    data = await request.json()
    order_id = data.get("order_id")

    from app.database import mark_notifications_read
    if order_id:
        mark_notifications_read(user["id"], int(order_id))
    else:
        mark_notifications_read(user["id"])

    return JSONResponse({"status": "ok"})

# ── Web Push уведомления ────────────────────────────


@router.get("/api/push/vapid-public-key")
def api_vapid_public_key():
    """Отдаёт публичный VAPID ключ для фронтенда."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    pub_key = os.getenv("VAPID_PUBLIC_KEY", "")
    return JSONResponse({"publicKey": pub_key})


@router.post("/api/push/subscribe")
async def api_push_subscribe(request: Request):
    """Сохраняет подписку браузера в БД."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "error"}, status_code=401)

    data = await request.json()
    if not data or "endpoint" not in data:
        return JSONResponse({"status": "error", "message": "Нет данных подписки"}, status_code=400)

    import json
    from app.database import save_push_subscription
    save_push_subscription(user["id"], json.dumps(data))
    return JSONResponse({"status": "ok"})
