from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, obter_contexto_atual, obter_usuario_atual
from app.core.database import get_db
from app.models.eleitor import Eleitor
from app.modules.landing.view import renderizar_landing
from app.services.agenda_service import AgendaService
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService
from app.services.gabinete_service import GabineteService
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
):
    # A raiz é pública: sem sessão autenticada, mostra a landing page
    # comercial (app/modules/landing/view.py) — nunca o dashboard interno.
    # Checagem direta na sessão (não Depends(obter_contexto_atual), que
    # levantaria NaoAutenticado/GabineteNaoSelecionado antes mesmo do corpo
    # da função rodar) — é exatamente esse "levantar antes" que impediria
    # a ramificação aqui. Autenticado, o restante da função é idêntico ao
    # que já era: obter_usuario_atual/obter_contexto_atual continuam sendo
    # a única fonte de verdade sobre sessão/gabinete, só chamados
    # manualmente em vez de via Depends.
    if not request.session.get("usuario_id"):
        return renderizar_landing(request)

    usuario = obter_usuario_atual(request, db)
    contexto = obter_contexto_atual(request, db, usuario)
    gabinete_id = contexto.gabinete_id
    hoje = date.today()
    cards = GabineteService.obter_cards_dashboard(contexto.gabinete)

    # Os 4 indicadores do topo (eleitores/demandas/pendências/agenda de
    # hoje) e o próprio "cards" nunca são opcionais — só os cards abaixo
    # deles são. Cada bloco só consulta o banco se o card correspondente
    # estiver ligado (ver /configuracoes/gabinete/dashboard): um gabinete
    # que desligou "Aniversariantes", por exemplo, nem gera a consulta.
    contexto_tela = {
        "titulo": "Dashboard",
        "total_eleitores": EleitorService.contar(db, gabinete_id),
        "total_demandas": DemandaService.contar_total(db, gabinete_id),
        "total_demandas_pendentes": DemandaService.contar_em_andamento(db, gabinete_id),
        "total_compromissos_hoje": AgendaService.contar_hoje(db, gabinete_id),
        "cards": cards,
        "gabinete": contexto.gabinete,
        "hoje": hoje,
    }

    if cards["urgentes"]:
        contexto_tela["demandas_urgentes"] = DemandaService.listar_urgentes(
            db, gabinete_id, LIMITE_RECENTES
        )
        contexto_tela["total_demandas_urgentes"] = DemandaService.contar_urgentes(db, gabinete_id)

    if cards["demandas_hoje"]:
        contexto_tela["demandas_hoje"] = DemandaService.listar_vencendo_hoje(db, gabinete_id, hoje)

    if cards["cadastradas_hoje"]:
        contexto_tela["demandas_cadastradas_hoje"] = DemandaService.listar_cadastradas_hoje(
            db, gabinete_id, hoje
        )

    if cards["atencao_gabinete"]:
        contexto_tela["demandas_atrasadas"] = DemandaService.contar_atrasadas(db, gabinete_id)
        contexto_tela["demandas_prazo_proximo"] = DemandaService.contar_prazo_proximo(db, gabinete_id, 7)

    if cards["demandas_por_status"]:
        contexto_tela["demandas_por_status"] = DemandaService.relatorio_por_status(db, gabinete_id)

    if cards["aniversariantes"]:
        aniversariantes_hoje = EleitorService.listar_aniversariantes_hoje(db, gabinete_id)
        contexto_tela["aniversariantes_hoje"] = _preparar_aniversariantes(
            aniversariantes_hoje, hoje, contexto.gabinete.nome
        )

    if cards["proximos_compromissos"]:
        contexto_tela["proximos_compromissos"] = AgendaService.listar_proximos(
            db, gabinete_id, LIMITE_RECENTES
        )

    return templates.TemplateResponse(request=request, name="dashboard/index.html", context=contexto_tela)


@router.post("/nota-dashboard")
def salvar_nota_dashboard(
    conteudo: str = Form(""),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    # Qualquer perfil autenticado do gabinete pode editar — é um recado de
    # equipe (ver Gabinete.nota_dashboard), não uma configuração
    # administrativa; nunca exigir_perfil("ADMIN") aqui.
    GabineteService.atualizar_nota_dashboard(db, contexto.gabinete, conteudo, contexto.usuario.id)
    return RedirectResponse("/", status_code=303)
