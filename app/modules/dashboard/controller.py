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


# Escritos como escape \UXXXXXXXX (não como o glifo colado no arquivo) de
# propósito: são caracteres fora do BMP (4 bytes em UTF-8), o ponto do
# texto mais exposto a corrupção ao passar por edição/terminal/checkout no
# meio do caminho (bundle -> Windows -> git) — diferente dos acentos do
# português, que são BMP e sobrevivem a praticamente qualquer transporte.
# Como escape ASCII puro no .py, o Python monta o caractere certo em
# runtime sempre, não importa o que aconteceu com o arquivo até chegar
# aqui. WhatsappLinkService.gerar_link() continua sendo o único lugar que
# gera a URL final (urllib.parse.quote, UTF-8) — não alterado.
EMOJI_FESTA = "\U0001F389"  # 🎉
EMOJI_BOLO = "\U0001F382"  # 🎂


def _mensagem_parabens(nome_eleitor: str, nome_gabinete: str) -> str:
    # Independente da mensagem de aniversário do e-mail diário
    # (DailyEmailService._mensagem_aniversario) de propósito — este botão
    # não deve depender/alterar aquele serviço; só o WhatsappLinkService é
    # compartilhado entre os dois, conforme escopo desta etapa.
    primeiro_nome = (nome_eleitor or "").strip().split(" ")[0] or nome_eleitor
    return (
        f"Olá, {primeiro_nome}! {EMOJI_FESTA}\n"
        f"Em nome do {nome_gabinete}, desejamos a você um feliz aniversário! "
        "Que este novo ciclo seja repleto de saúde, paz e realizações. "
        f"Um grande abraço! {EMOJI_BOLO}"
    )


def _preparar_aniversariantes(
    aniversariantes: list[Eleitor], hoje: date, nome_gabinete: str
) -> list[dict]:
    """Monta, no controller, tudo que o template precisa exibir pronto —
    nenhuma normalização de telefone nem geração de link em Jinja. Prioriza
    eleitor.whatsapp sobre eleitor.telefone tanto para o link quanto para o
    texto exibido (mesmo número que o botão vai usar); sem nenhum dos dois,
    whatsapp_link fica None e o template mostra "Sem telefone" — nunca um
    link wa.me inventado ou quebrado. nome_gabinete vem de
    contexto.gabinete.nome (já carregado por obter_contexto_atual) — nunca
    uma nova consulta ao banco só para isso."""
    resultado = []
    for eleitor in aniversariantes:
        telefone_para_link = eleitor.whatsapp or eleitor.telefone
        mensagem = _mensagem_parabens(eleitor.nome, nome_gabinete)
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
            "aniversariantes_hoje": _preparar_aniversariantes(
                aniversariantes_hoje, hoje, contexto.gabinete.nome
            ),
            "hoje": hoje,
        },
    )
