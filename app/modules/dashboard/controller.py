from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, obter_contexto_atual
from app.core.database import get_db
from app.services.agenda_service import AgendaService
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

LIMITE_RECENTES = 5


@router.get("/")
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    gabinete_id = contexto.gabinete_id
    demandas_por_status = DemandaService.relatorio_por_status(db, gabinete_id)
    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "titulo": "Dashboard",
            "total_eleitores": EleitorService.contar(db, gabinete_id),
            "total_demandas": DemandaService.contar_total(db, gabinete_id),
            "total_demandas_pendentes": DemandaService.contar_em_andamento(db, gabinete_id),
            "total_compromissos_hoje": AgendaService.contar_hoje(db, gabinete_id),
            "demandas_por_status": demandas_por_status,
            "demandas_atrasadas": DemandaService.contar_atrasadas(db, gabinete_id),
            "demandas_prazo_proximo": DemandaService.contar_prazo_proximo(db, gabinete_id, 7),
            "proximos_compromissos": AgendaService.listar_proximos(db, gabinete_id, LIMITE_RECENTES),
            "aniversariantes_hoje": EleitorService.listar_aniversariantes_hoje(db, gabinete_id),
            "hoje": date.today(),
        },
    )
