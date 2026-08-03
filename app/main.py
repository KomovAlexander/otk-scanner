from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routes import router

app = FastAPI(title="ОТК Сканер", version="1.0.0")

# Подключаем папку со стилями
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Подключаем маршруты
app.include_router(router)

@app.on_event("startup")
def startup():
    init_db()