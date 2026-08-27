from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import exigir_superadmin
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.daily_email_service import DailyEmailService
from app.services.gabinete_service import GabineteService

# Prefixo próprio, fora de /configuracoes de propósito: /configuracoes é o
# espaço do ADMIN sobre o próprio gabinete (exigir_perfil("ADMIN"),
# ContextoSessao). /superadmin é global, outra trilha de autorização
# (exigir_superadmin, sem ContextoSessao) — nomes de rota separados deixam
# claro, só de olhar a URL, qual checagem está em vigor. O menu na
# interface pode continuar dizendo "Configurações > Gabinetes"; o
# namespace do backend é só isso, um detalhe de organização.
router = APIRouter(prefix="/superadmin/gabinetes", tags=["Superadmin"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def flash_message(message: str | None = None, category: str = "warning") -> RedirectResponse:
    redirect = RedirectResponse("/superadmin/gabinetes", status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", message, max_age=10, httponly=True, path="/superadmin", samesite="lax"
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/superadmin", samesite="lax"
        )
    return redirect


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinetes = GabineteService.listar_todos(db)
    linhas = [
        {"gabinete": gabinete, "contadores": GabineteService.contadores(db, gabinete.id)}
        for gabinete in gabinetes
    ]
    resposta = templates.TemplateResponse(
        request=request,
        name="superadmin/gabinetes_lista.html",
        context={
            "titulo": "Gabinetes",
            "linhas": linhas,
            "usuario_nome": usuario.nome,
            "flash_message": request.cookies.get("flash_message"),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/superadmin")
    resposta.delete_cookie("flash_category", path="/superadmin")
    return resposta


@router.get("/novo", response_class=HTMLResponse)
def novo(
    request: Request,
    usuario: Usuario = Depends(exigir_superadmin),
):
    return templates.TemplateResponse(
        request=request,
        name="superadmin/gabinete_novo.html",
        context={"titulo": "Novo gabinete", "usuario_nome": usuario.nome, "erro": None, "dados": {}},
    )


@router.post("/novo", response_class=HTMLResponse)
def criar(
    request: Request,
    nome_gabinete: str = Form(...),
    responsavel: str = Form(""),
    nome_admin: str = Form(...),
    email_admin: str = Form(...),
    senha_admin: str = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    try:
        GabineteService.criar_gabinete_com_admin(
            db, nome_gabinete, responsavel, nome_admin, email_admin, senha_admin
        )
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="superadmin/gabinete_novo.html",
            context={
                "titulo": "Novo gabinete",
                "usuario_nome": usuario.nome,
                "erro": str(error),
                "dados": {
                    "nome_gabinete": nome_gabinete,
                    "responsavel": responsavel,
                    "nome_admin": nome_admin,
                    "email_admin": email_admin,
                },
            },
            status_code=400,
        )
    return flash_message("Gabinete criado com sucesso.", "success")


@router.get("/{gabinete_id}/editar", response_class=HTMLResponse)
def editar(
    request: Request,
    gabinete_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return flash_message("Gabinete não encontrado.", "danger")
    return templates.TemplateResponse(
        request=request,
        name="superadmin/gabinete_editar.html",
        context={
            "titulo": "Editar gabinete",
            "usuario_nome": usuario.nome,
            "gabinete": gabinete,
            "contadores": GabineteService.contadores(db, gabinete.id),
            "erro": None,
        },
    )


@router.post("/{gabinete_id}/editar", response_class=HTMLResponse)
def atualizar(
    request: Request,
    gabinete_id: int,
    nome: str = Form(...),
    responsavel: str = Form(""),
    email_institucional: str = Form(""),
    ativo: bool = Form(False),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return flash_message("Gabinete não encontrado.", "danger")
    try:
        GabineteService.atualizar_superadmin(
            db, gabinete, nome, responsavel, ativo, email_institucional
        )
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="superadmin/gabinete_editar.html",
            context={
                "titulo": "Editar gabinete",
                "usuario_nome": usuario.nome,
                "gabinete": gabinete,
                "contadores": GabineteService.contadores(db, gabinete.id),
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message("Gabinete atualizado.", "success")


@router.post("/{gabinete_id}/enviar-diario", response_class=HTMLResponse)
def enviar_diario_agora(
    request: Request,
    gabinete_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    """Disparo manual do e-mail diário — mesmo conteúdo exato do envio
    automático, só que sob demanda, para validar visual/agenda/
    aniversariantes/links de WhatsApp sem esperar 07:30. forcar=True: um
    reenvio de teste no mesmo dia não deve ficar bloqueado pela trava de
    idempotência pensada para o job automático."""
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return flash_message("Gabinete não encontrado.", "danger")
    resultado = DailyEmailService.enviar_diario(db, gabinete_id, forcar=True)
    categoria = "success" if resultado["status"] == "enviado" else "danger"
    return flash_message(resultado["motivo"], categoria)
