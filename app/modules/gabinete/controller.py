from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, exigir_perfil, obter_contexto_atual
from app.core.database import get_db
from app.core.flash import codificar_flash, decodificar_flash
from app.services.gabinete_service import CARDS_DASHBOARD, GabineteService
from app.services.qrcode_service import QrCodeService

router = APIRouter(prefix="/configuracoes/gabinete", tags=["Cadastros"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Editar dados do próprio gabinete é administrativo — só ADMIN.
_exigir_admin = exigir_perfil("ADMIN")


def flash_message(
    message: str | None = None, category: str = "warning", destino: str = "/configuracoes/gabinete"
) -> RedirectResponse:
    redirect = RedirectResponse(destino, status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", codificar_flash(message), max_age=10, httponly=True,
            path="/configuracoes", samesite="lax",
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/configuracoes", samesite="lax"
        )
    return redirect


@router.get("", response_class=HTMLResponse)
def visualizar(request: Request, contexto: ContextoSessao = Depends(_exigir_admin)):
    resposta = templates.TemplateResponse(
        request=request,
        name="configuracoes/gabinete_formulario.html",
        context={
            "titulo": "Gabinete",
            "gabinete": contexto.gabinete,
            "flash_message": decodificar_flash(request.cookies.get("flash_message")),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/configuracoes")
    resposta.delete_cookie("flash_category", path="/configuracoes")
    return resposta


@router.post("")
def atualizar(
    request: Request,
    nome: str = Form(...),
    ativo: bool = Form(False),
    email_institucional: str = Form(""),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    try:
        GabineteService.atualizar(db, contexto.gabinete, nome, ativo, email_institucional)
    except ValueError as error:
        gabinete_preenchido = SimpleNamespace(
            id=contexto.gabinete.id, nome=nome, ativo=ativo, email_institucional=email_institucional
        )
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/gabinete_formulario.html",
            context={
                "titulo": "Gabinete",
                "gabinete": gabinete_preenchido,
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message("Gabinete atualizado.", "success")


@router.get("/dashboard", response_class=HTMLResponse)
def personalizar_dashboard(request: Request, contexto: ContextoSessao = Depends(_exigir_admin)):
    resposta = templates.TemplateResponse(
        request=request,
        name="configuracoes/gabinete_dashboard.html",
        context={
            "titulo": "Personalização do Dashboard",
            "cards": CARDS_DASHBOARD,
            "cards_ativos": GabineteService.obter_cards_dashboard(contexto.gabinete),
            "flash_message": decodificar_flash(request.cookies.get("flash_message")),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/configuracoes")
    resposta.delete_cookie("flash_category", path="/configuracoes")
    return resposta


@router.post("/dashboard")
def atualizar_dashboard(
    urgentes: bool = Form(False),
    demandas_hoje: bool = Form(False),
    cadastradas_hoje: bool = Form(False),
    atencao_gabinete: bool = Form(False),
    demandas_por_status: bool = Form(False),
    aniversariantes: bool = Form(False),
    proximos_compromissos: bool = Form(False),
    atalho_relatorios: bool = Form(False),
    bloco_notas: bool = Form(False),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    # Checkbox desmarcado simplesmente não vem no corpo do POST (padrão
    # HTML) — por isso cada card é seu próprio Form(False) (mesmo padrão
    # já usado em "ativo" no formulário do gabinete acima), nunca lido
    # genericamente: um nome de campo que não existisse aqui seria
    # ignorado de qualquer forma por GabineteService.
    # atualizar_cards_dashboard, que só aceita as chaves de
    # CARDS_DASHBOARD — mas declarar cada um explicitamente também serve
    # de documentação viva de quais cards existem hoje.
    cards_ativos = {
        "urgentes": urgentes,
        "demandas_hoje": demandas_hoje,
        "cadastradas_hoje": cadastradas_hoje,
        "atencao_gabinete": atencao_gabinete,
        "demandas_por_status": demandas_por_status,
        "aniversariantes": aniversariantes,
        "proximos_compromissos": proximos_compromissos,
        "atalho_relatorios": atalho_relatorios,
        "bloco_notas": bloco_notas,
    }
    GabineteService.atualizar_cards_dashboard(db, contexto.gabinete, cards_ativos)
    return flash_message(
        "Personalização do dashboard salva.", "success", destino="/configuracoes/gabinete/dashboard"
    )


@router.get("/link-publico", response_class=HTMLResponse)
def link_publico(request: Request, contexto: ContextoSessao = Depends(obter_contexto_atual)):
    # Deliberadamente obter_contexto_atual (qualquer perfil autenticado do
    # gabinete: ADMIN, VEREADOR ou ASSESSOR), não _exigir_admin — o link
    # público é para uso/divulgação por toda a equipe, não uma
    # configuração administrativa. contexto.gabinete já vem escopado ao
    # gabinete do usuário autenticado (mesma revalidação de sempre em
    # obter_contexto_atual), então isolamento multi-tenant é preservado:
    # ninguém enxerga o link de um gabinete ao qual não pertence. Alterar
    # o gabinete em si (inclusive o public_token) continua exclusivo do
    # ADMIN via as rotas acima (visualizar/atualizar).
    url_publica = GabineteService.montar_url_publica(contexto.gabinete, str(request.base_url))
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/gabinete_link_publico.html",
        context={"titulo": "Link público", "url_publica": url_publica},
    )


@router.get("/link-publico/qrcode.png")
def link_publico_qrcode(
    request: Request, baixar: bool = False, contexto: ContextoSessao = Depends(obter_contexto_atual)
):
    # Mesma autorização da tela acima (qualquer perfil autenticado do
    # gabinete) — o QR Code não é secreto (o link já é público por
    # definição), só precisa de sessão válida com gabinete selecionado,
    # nunca uma rota aberta. `baixar` só troca o Content-Disposition
    # (inline para exibir na própria tela, attachment para o botão
    # "Baixar PNG") — a imagem gerada é sempre a mesma.
    url_publica = GabineteService.montar_url_publica(contexto.gabinete, str(request.base_url))
    png = QrCodeService.gerar_png(url_publica)
    disposicao = "attachment" if baixar else "inline"
    return Response(
        content=png,
        media_type="image/png",
        headers={"Content-Disposition": f'{disposicao}; filename="qrcode-atendimento-cidadao.png"'},
    )
