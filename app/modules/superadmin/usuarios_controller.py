from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import exigir_superadmin
from app.core.database import get_db
from app.core.flash import codificar_flash, decodificar_flash
from app.models.membro_gabinete import PERFIS_OPCOES
from app.models.usuario import Usuario
from app.services.gabinete_service import GabineteService
from app.services.usuario_service import UsuarioService

# Aninhado sob /superadmin/gabinetes/{gabinete_id}/usuarios de propósito:
# gabinete_id sempre vem do path (nunca de um campo de formulário), e toda
# rota revalida que o gabinete existe e que o membro pertence a ELE antes
# de agir — mesma defesa contra IDOR já usada em UsuarioService.obter_membro.
# Trilha de autorização própria (exigir_superadmin), sem ContextoSessao —
# igual ao restante de /superadmin.
router = APIRouter(prefix="/superadmin/gabinetes/{gabinete_id}/usuarios", tags=["Superadmin"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def flash_message(
    gabinete_id: int, message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    destino = f"/superadmin/gabinetes/{gabinete_id}/usuarios"
    redirect = RedirectResponse(destino, status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", codificar_flash(message), max_age=10, httponly=True,
            path="/superadmin", samesite="lax",
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/superadmin", samesite="lax"
        )
    return redirect


def _gabinete_nao_encontrado() -> RedirectResponse:
    redirect = RedirectResponse("/superadmin/gabinetes", status_code=303)
    redirect.set_cookie(
        "flash_message", codificar_flash("Gabinete não encontrado."), max_age=10, httponly=True,
        path="/superadmin", samesite="lax",
    )
    redirect.set_cookie(
        "flash_category", "danger", max_age=10, httponly=True, path="/superadmin", samesite="lax"
    )
    return redirect


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request,
    gabinete_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return _gabinete_nao_encontrado()
    membros = UsuarioService.listar_membros(db, gabinete_id)
    resposta = templates.TemplateResponse(
        request=request,
        name="superadmin/usuarios_lista.html",
        context={
            "titulo": f"Usuários — {gabinete.nome}",
            "usuario_nome": usuario.nome,
            "gabinete": gabinete,
            "membros": membros,
            "flash_message": decodificar_flash(request.cookies.get("flash_message")),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/superadmin")
    resposta.delete_cookie("flash_category", path="/superadmin")
    return resposta


@router.get("/novo", response_class=HTMLResponse)
def novo(
    request: Request,
    gabinete_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return _gabinete_nao_encontrado()
    return templates.TemplateResponse(
        request=request,
        name="superadmin/usuario_formulario.html",
        context={
            "titulo": "Novo usuário",
            "usuario_nome": usuario.nome,
            "gabinete": gabinete,
            "usuario_preenchido": SimpleNamespace(nome="", email="", perfil="ASSESSOR"),
            "perfis_opcoes": PERFIS_OPCOES,
        },
    )


@router.post("/novo")
def criar(
    request: Request,
    gabinete_id: int,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
    perfil: str = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return _gabinete_nao_encontrado()

    erro = None
    if senha != confirmar_senha:
        erro = "As senhas não coincidem."
    else:
        try:
            UsuarioService.criar_usuario_e_membro_superadmin(
                db, gabinete_id, nome, email, senha, perfil
            )
        except ValueError as error:
            erro = str(error)

    if erro is not None:
        return templates.TemplateResponse(
            request=request,
            name="superadmin/usuario_formulario.html",
            context={
                "titulo": "Novo usuário",
                "usuario_nome": usuario.nome,
                "gabinete": gabinete,
                "usuario_preenchido": SimpleNamespace(nome=nome, email=email, perfil=perfil),
                "perfis_opcoes": PERFIS_OPCOES,
                "erro": erro,
            },
            status_code=400,
        )
    return flash_message(gabinete_id, "Usuário cadastrado.", "success")


@router.get("/{membro_id}/editar", response_class=HTMLResponse)
def editar(
    request: Request,
    gabinete_id: int,
    membro_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return _gabinete_nao_encontrado()
    membro = UsuarioService.obter_membro(db, gabinete_id, membro_id)
    if membro is None:
        return flash_message(gabinete_id, "Usuário não encontrado neste gabinete.")
    return templates.TemplateResponse(
        request=request,
        name="superadmin/membro_editar.html",
        context={
            "titulo": "Editar usuário",
            "usuario_nome": usuario.nome,
            "gabinete": gabinete,
            "membro": membro,
            "perfis_opcoes": PERFIS_OPCOES,
        },
    )


@router.post("/{membro_id}/editar")
def atualizar(
    request: Request,
    gabinete_id: int,
    membro_id: int,
    nome: str = Form(...),
    email: str = Form(...),
    perfil: str = Form(...),
    ativo: bool = Form(False),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return _gabinete_nao_encontrado()
    membro = UsuarioService.obter_membro(db, gabinete_id, membro_id)
    if membro is None:
        return flash_message(gabinete_id, "Usuário não encontrado neste gabinete.")

    try:
        UsuarioService.atualizar_membro_superadmin(db, gabinete_id, membro, nome, email, perfil, ativo)
    except ValueError as error:
        membro_preenchido = SimpleNamespace(
            id=membro.id,
            usuario_id=membro.usuario_id,
            perfil=perfil,
            ativo=ativo,
            usuario=SimpleNamespace(nome=nome, email=email),
        )
        return templates.TemplateResponse(
            request=request,
            name="superadmin/membro_editar.html",
            context={
                "titulo": "Editar usuário",
                "usuario_nome": usuario.nome,
                "gabinete": gabinete,
                "membro": membro_preenchido,
                "perfis_opcoes": PERFIS_OPCOES,
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message(gabinete_id, "Usuário atualizado.", "success")


@router.post("/{membro_id}/alternar")
def alternar(
    gabinete_id: int,
    membro_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_superadmin),
):
    gabinete = GabineteService.obter_por_id(db, gabinete_id)
    if gabinete is None:
        return _gabinete_nao_encontrado()
    membro = UsuarioService.obter_membro(db, gabinete_id, membro_id)
    if membro is None:
        return flash_message(gabinete_id, "Usuário não encontrado neste gabinete.")
    try:
        UsuarioService.alternar_ativo(db, gabinete_id, membro)
    except ValueError as error:
        return flash_message(gabinete_id, str(error))
    mensagem = "Usuário ativado neste gabinete." if membro.ativo else "Usuário desativado neste gabinete."
    return flash_message(gabinete_id, mensagem, "success")
