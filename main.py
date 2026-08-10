from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import APP_NAME
from app.core.database import Base, engine
from app.services.migration_service import MigrationService

from app.modules.agenda.controller import router as agenda_router
from app.modules.dashboard.controller import router as dashboard_router
from app.modules.demandas.controller import router as demandas_router
from app.modules.eleitores.controller import router as eleitores_router

Base.metadata.create_all(bind=engine)
MigrationService.atualizar_schema_eleitores()
MigrationService.atualizar_schema_demandas()
MigrationService.atualizar_schema_agenda()

app = FastAPI(title=APP_NAME)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard_router)
app.include_router(eleitores_router)
app.include_router(demandas_router)
app.include_router(agenda_router)