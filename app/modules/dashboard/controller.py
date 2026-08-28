from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, obter_contexto_atual
from app.core.database import get_db
from app.models.eleitor import Eleitor
from app.services.agenda_service import AgendaService
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService
from app.services.whatsapp_link_service import WhatsappLinkService

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

LIMITE_RECENTES = 5


def _mensagem_parabens(nome_eleitor: str) -> str:
    # Independente da mensagem de aniversário do e-mail diário
    # (DailyEmailService._mensagem_aniversario) de propósito — este botão
    # não deve depender/alterar aquele serviço; só o WhatsappLinkService é
    # compartilhado entre os dois, conforme escopo desta etapa.
    primeiro_nome = (nome_eleitor or "").strip().split(" ")[0] or nome_eleitor
    return (
        f"Olá, {primeiro_nome}! 🎉\n"
        "Em nome do Gabinete 360, desejamos a você um feliz aniversário! "
        "Que este novo ciclo seja repleto de saúde, paz e realizações. "
        "Um grande abraço! 🎂"
    )


def _preparar_aniversariantes(aniversariantes: list[Eleitor], hoje: date) -> list[dict]:
    """Monta, no controller, tudo que o template precisa exibir pronto —
    nenhuma normalização de telefone nem geração de link em Jinja. Prioriza
    eleitor.whatsapp sobre eleitor.telefone tanto para o link quanto para o
    texto exibido (mesmo número que o botão vai usar); sem nenhum dos dois,
    whatsapp_link fica None e o template mostra "Sem telefone" — nunca um
    link wa.me inventado ou quebrado."""
    resultado = []
    for eleitor in aniversariantes:
        telefone_para_link = eleitor.whatsapp or eleitor.telefone
        mensagem = _mensagem_parabens(eleitor.nome)
        resultado.append(
            {
                "id": eleitor.id,
                "nome": eleitor.nome,
                "idade": (hoje.year - eleitor.nascimento.year) if eleitor.nascimento else None,
                "telefone_exibicao": telefone_para_link,
                "whatsapp_link": WhatsappLinkService.gerar_link(telefone_para_link, mensagem),
            }
        )
    return resultado


@router.get("/")
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    gabinete_id = contexto.gabinete_id
    hoje = date.today()
    demandas_por_status = DemandaService.relatorio_por_status(db, gabinete_id)
    aniversariantes_hoje = EleitorService.listar_aniversariantes_hoje(db, gabinete_id)
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
            "aniversariantes_hoje": _preparar_aniversariantes(aniversariantes_hoje, hoje),
            "hoje": hoje,
        },
    )
