from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, exigir_perfil
from app.core.database import get_db
from app.core.flash import codificar_flash, decodificar_flash
from app.services.gabinete_service import GabineteService
from app.services.qrcode_service import QrCodeService

router = APIRouter(prefix="/configuracoes/gabinete", tags=["Cadastros"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Editar dados do próprio gabinete é administrativo — só ADMIN.
_exigir_admin = exigir_perfil("ADMIN")


def flash_message(
    message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    redirect = RedirectResponse("/configuracoes/gabinete", status_code=303)
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


@router.get("/link-publico", response_class=HTMLResponse)
def link_publico(request: Request, contexto: ContextoSessao = Depends(_exigir_admin)):
    url_publica = GabineteService.montar_url_publica(contexto.gabinete, str(request.base_url))
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/gabinete_link_publico.html",
        context={"titulo": "Link público", "url_publica": url_publica},
    )


@router.get("/link-publico/qrcode.png")
def link_publico_qrcode(
    request: Request, baixar: bool = False, contexto: ContextoSessao = Depends(_exigir_admin)
):
    # Mesma trava de perfil da tela acima (_exigir_admin) — o QR Code em si
    # não é secreto (o link já é público por definição), mas gerar a
    # imagem ainda exige estar autenticado como ADMIN deste gabinete,
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
