"""Autoatendimento de senha — "Alterar minha senha" (autenticado) e
"Esqueci minha senha" (sem sessão). Deliberadamente fora de
/configuracoes (que exige perfil ADMIN e gabinete selecionado): qualquer
usuário autenticado, de qualquer perfil — inclusive SUPERADMIN, que não
tem gabinete — precisa poder trocar a própria senha."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import obter_usuario_atual
from app.core.database import get_db
from app.core.flash import codificar_flash, decodificar_flash
from app.models.usuario import Usuario
from app.services.redefinicao_senha_service import RedefinicaoSenhaService
from app.services.usuario_service import UsuarioService

router = APIRouter(tags=["Perfil"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _flash(destino: str, message: str | None = None, category: str = "warning") -> RedirectResponse:
    redirect = RedirectResponse(destino, status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", codificar_flash(message), max_age=10, httponly=True,
            path="/", samesite="lax",
        )
        redirect.set_cookie("flash_category", category, max_age=10, httponly=True, path="/", samesite="lax")
    return redirect


# ---------- Alterar minha senha (autenticado) ----------


@router.get("/minha-conta/senha", response_class=HTMLResponse)
def minha_senha_formulario(request: Request, usuario: Usuario = Depends(obter_usuario_atual)):
    resposta = templates.TemplateResponse(
        request=request,
        name="auth/minha_senha.html",
        context={
            "titulo": "Alterar minha senha",
            "flash_message": decodificar_flash(request.cookies.get("flash_message")),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/")
    resposta.delete_cookie("flash_category", path="/")
    return resposta


@router.post("/minha-conta/senha")
def minha_senha_definir(
    request: Request,
    senha_atual: str = Form(...),
    nova_senha: str = Form(...),
    confirmar_senha: str = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    if nova_senha != confirmar_senha:
        return templates.TemplateResponse(
            request=request,
            name="auth/minha_senha.html",
            context={"titulo": "Alterar minha senha", "erro": "A confirmação não corresponde à nova senha."},
            status_code=400,
        )
    try:
        UsuarioService.alterar_propria_senha(db, usuario, senha_atual, nova_senha)
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="auth/minha_senha.html",
            context={"titulo": "Alterar minha senha", "erro": str(error)},
            status_code=400,
        )
    return _flash("/minha-conta/senha", "Senha alterada com sucesso.", "success")


# ---------- Esqueci minha senha (sem sessão) ----------


@router.get("/esqueci-senha", response_class=HTMLResponse)
def esqueci_senha_formulario(request: Request):
    return templates.TemplateResponse(
        request=request, name="auth/esqueci_senha.html", context={"titulo": "Esqueci minha senha"}
    )


@router.post("/esqueci-senha", response_class=HTMLResponse)
def esqueci_senha_solicitar(
    request: Request, email: str = Form(...), db: Session = Depends(get_db)
):
    # Sempre a mesma resposta, exista ou não o e-mail, SMTP configurado ou
    # não — ver docstring de RedefinicaoSenhaService.solicitar(). Nunca
    # revelar aqui se algo deu errado internamente.
    RedefinicaoSenhaService.solicitar(db, email, str(request.base_url))
    return templates.TemplateResponse(
        request=request,
        name="auth/esqueci_senha_confirmacao.html",
        context={"titulo": "Esqueci minha senha"},
    )


# ---------- Redefinir senha (a partir do link do e-mail) ----------


@router.get("/redefinir-senha/{token}", response_class=HTMLResponse)
def redefinir_senha_formulario(request: Request, token: str, db: Session = Depends(get_db)):
    redefinicao = RedefinicaoSenhaService.obter_valida(db, token)
    if redefinicao is None:
        return templates.TemplateResponse(
            request=request,
            name="auth/redefinir_senha_invalido.html",
            context={"titulo": "Link inválido"},
            status_code=400,
        )
    return templates.TemplateResponse(
        request=request,
        name="auth/redefinir_senha.html",
        context={"titulo": "Redefinir senha", "token": token},
    )


@router.post("/redefinir-senha/{token}", response_class=HTMLResponse)
def redefinir_senha_confirmar(
    request: Request,
    token: str,
    nova_senha: str = Form(...),
    confirmar_senha: str = Form(...),
    db: Session = Depends(get_db),
):
    if nova_senha != confirmar_senha:
        return templates.TemplateResponse(
            request=request,
            name="auth/redefinir_senha.html",
            context={"titulo": "Redefinir senha", "token": token, "erro": "A confirmação não corresponde à nova senha."},
            status_code=400,
        )
    try:
        sucesso = RedefinicaoSenhaService.redefinir(db, token, nova_senha)
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="auth/redefinir_senha.html",
            context={"titulo": "Redefinir senha", "token": token, "erro": str(error)},
            status_code=400,
        )
    if not sucesso:
        return templates.TemplateResponse(
            request=request,
            name="auth/redefinir_senha_invalido.html",
            context={"titulo": "Link inválido"},
            status_code=400,
        )
    return _flash("/login", "Senha redefinida com sucesso. Faça login com a nova senha.", "success")
