from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.routes import router
from app.database import init_db, create_default_admin
from app.admin_routes import admin_router

app = FastAPI(title="ОТК Сканер", version="1.0.0")

app.add_middleware(SessionMiddleware, secret_key="otk-secret-key-2026")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/uploads", StaticFiles(directory="app/static/uploads"), name="uploads")
app.include_router(router)
app.include_router(admin_router)

@app.on_event("startup")
def startup():
    init_db()
    create_default_admin()