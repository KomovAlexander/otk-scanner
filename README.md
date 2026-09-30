# ОТК Сканер

Система автоматизации операционного контроля качества гидравлических станций.

## Возможности

- Сканирование документов с телефона или из галереи (PDF и изображения)
- Распознавание текста через Yandex Vision OCR
- Извлечение технических параметров через YandexGPT
- Проверка соответствия документов заказу
- Визуальный контроль (ГЧ, Г3, ПГ3)
- Измерения и сравнение с эталонами
- Автоматическое формирование протокола испытаний
- Генерация и печать шильдика изделия
- Фотографирование готового изделия с 4 ракурсов
- Разграничение прав: испытатель / администратор
- Запросы разрешений на работу без документов

## Технологии

- Python 3.11+
- FastAPI — веб-фреймворк
- SQLite — база данных
- Jinja2 — HTML-шаблоны
- Yandex Vision OCR — распознавание текста
- YandexGPT — извлечение параметров из схем
- OpenCV — предобработка изображений

## Установка

### 1. Клонировать репозиторий

git clone <URL_РЕПОЗИТОРИЯ> <br>
cd otk_scanner

### 2. Создать виртуальное окружение

python -m venv venv <br>
venv\Scripts\activate

Для Linux/Mac: source venv/bin/activate

### 3. Установить зависимости

pip install -r requirements.txt

### 4. Создать файл .env в корне проекта

YANDEX_API_KEY=ваш_api_ключ <br>
YANDEX_FOLDER_ID=ваш_folder_id

API-ключ и folder_id берутся в Yandex Cloud Console.

### 5. Запустить

uvicorn app.main:app --reload

Открыть в браузере: http://127.0.0.1:8000

## Первый вход

При первом запуске автоматически создаётся администратор:

- Логин: admin
- Пароль: admin

Смените пароль сразу после первого входа!

## Структура проекта

```
otk_scanner/
├── app/
│   ├── main.py                — точка входа приложения
│   ├── auth.py                — аутентификация и сессии
│   ├── database.py            — работа с БД
│   ├── routes.py              — пользовательские роуты и API
│   ├── admin_routes.py        — админские роуты
│   ├── ocr_engine.py          — Yandex Vision OCR
│   ├── param_extractor.py     — YandexGPT для извлечения параметров
│   ├── green_extractor.py     — распознавание цветных размеров на ГЧ
│   ├── patterns.py            — регулярки для номеров документов
│   ├── shildik_generator.py   — генерация SVG шильдика
│   ├── templates/             — HTML-шаблоны
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   ├── scan.html
│   │   ├── check_gch.html
│   │   ├── check_g3.html
│   │   ├── check_pg3.html
│   │   ├── visual_check.html
│   │   ├── measurements.html
│   │   ├── protocol.html
│   │   ├── photo.html
│   │   ├── shildik.html
│   │   ├── admin.html
│   │   └── admin_requests.html
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── uploads/           — загруженные фото (не в Git)
├── .env                       — секреты (не в Git)
├── .gitignore
├── otk.db                     — база данных (не в Git)
├── requirements.txt
└── README.md
```

## Основные эндпоинты

Пользовательские:

- GET /              — Сканирование заказа
- GET /dashboard     — Личный кабинет
- GET /check-gch     — Габаритный чертёж
- GET /check-g3      — Гидравлическая схема
- GET /check-pg3     — Перечень элементов
- GET /visual-check  — Визуальный контроль
- GET /measurements  — Измерения
- GET /protocol      — Протокол испытаний
- GET /photo         — Фотографирование
- GET /shildik       — Шильдик

API:

- POST /api/scan              — Распознать заказ
- POST /api/scan-gch          — Распознать ГЧ
- POST /api/scan-g3           — Распознать Г3
- POST /api/scan-pg3          — Распознать ПГ3
- POST /api/save-*            — Сохранить данные шага
- POST /api/request-permission — Запрос разрешения
- GET  /api/permission-status — Статус запроса

Админские:

- GET  /admin                          — Управление пользователями
- GET  /admin/requests                 — Запросы разрешений
- POST /admin/requests/{id}/resolve    — Одобрить/отклонить

## Требования

- Python 3.11 или выше
- API-ключ Yandex Cloud с доступом к:
  - Vision OCR (ai.vision.user)
  - Foundation Models (ai.languageModels.user)

## Статус проекта

MVP внедряется в ОТК. В планах:

- Поддержка нескольких изделий в одном заказе
- Журнал действий (audit log)
- Интеграция с 1С через API
- Экспорт протокола в PDF
- Миграция на PostgreSQL при росте нагрузки

## Лицензия

Внутренний проект компании. Все права защищены.