from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import APP_NAME
from app.core.database import Base, engine
from app.services.migration_service import MigrationService

from app.modules.dashboard.controller import router as dashboard_router
from app.modules.eleitores.controller import router as eleitores_router

Base.metadata.create_all(bind=engine)
MigrationService.atualizar_schema_eleitores()

app = FastAPI(title=APP_NAME)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard_router)
app.include_router(eleitores_router)