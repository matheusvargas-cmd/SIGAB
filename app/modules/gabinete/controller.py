from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, exigir_perfil
from app.core.database import get_db
from app.core.flash import codificar_flash, decodificar_flash
from app.services.gabinete_service import GabineteService

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
