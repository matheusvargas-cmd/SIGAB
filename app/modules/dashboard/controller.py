from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.agenda_service import AgendaService
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

LIMITE_RECENTES = 5


@router.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "titulo": "Dashboard",
            "total_eleitores": EleitorService.contar(db),
            "total_demandas_andamento": DemandaService.contar_em_andamento(db),
            "total_demandas_concluidas": DemandaService.contar_concluidas(db),
            "total_compromissos": AgendaService.contar_futuros(db),
            "eleitores_recentes": EleitorService.listar_recentes(db, LIMITE_RECENTES),
            "demandas_recentes": DemandaService.listar_recentes(db, LIMITE_RECENTES),
            "proximos_compromissos": AgendaService.listar_proximos(db, LIMITE_RECENTES),
            "aniversariantes_hoje": EleitorService.listar_aniversariantes_hoje(db),
            "hoje": date.today(),
        },
    )
