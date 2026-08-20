from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.services.agenda_service import AgendaService
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

LIMITE_RECENTES = 5


@router.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    demandas_por_status = DemandaService.relatorio_por_status(db)
    aguardando_terceiros = next(
        (item["quantidade"] for item in demandas_por_status if item["rotulo"] == "Aguardando terceiros"),
        0,
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "titulo": "Dashboard",
            "total_eleitores": EleitorService.contar(db),
            "total_demandas": DemandaService.contar_total(db),
            "total_demandas_pendentes": DemandaService.contar_em_andamento(db),
            "total_compromissos_hoje": AgendaService.contar_hoje(db),
            "demandas_por_status": demandas_por_status,
            "demandas_atrasadas": DemandaService.contar_atrasadas(db),
            "demandas_aguardando_terceiros": aguardando_terceiros,
            "demandas_prazo_proximo": DemandaService.contar_prazo_proximo(db, 7),
            "proximos_compromissos": AgendaService.listar_proximos(db, LIMITE_RECENTES),
            "aniversariantes_hoje": EleitorService.listar_aniversariantes_hoje(db),
            "hoje": date.today(),
        },
    )
