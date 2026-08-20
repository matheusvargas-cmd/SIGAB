from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import APP_NAME, STATIC_DIR
from app.core.database import Base, engine
from app.services.migration_service import MigrationService

from app.modules.agenda.controller import router as agenda_router
from app.modules.configuracoes.controller import router as configuracoes_router
from app.modules.dashboard.controller import router as dashboard_router
from app.modules.demandas.controller import router as demandas_router
from app.modules.eleitores.controller import router as eleitores_router
from app.modules.relatorios.controller import router as relatorios_router

Base.metadata.create_all(bind=engine)
MigrationService.atualizar_schema_eleitores()
MigrationService.atualizar_schema_demandas()
MigrationService.atualizar_schema_agenda()
MigrationService.semear_categorias_padrao()
MigrationService.vincular_categoria_id_demandas()
MigrationService.semear_categorias_atendimento_historico()

app = FastAPI(title=APP_NAME)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(dashboard_router)
app.include_router(eleitores_router)
app.include_router(demandas_router)
app.include_router(agenda_router)
app.include_router(relatorios_router)
app.include_router(configuracoes_router)