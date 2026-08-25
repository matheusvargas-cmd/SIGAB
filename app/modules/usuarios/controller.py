from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, exigir_perfil
from app.core.database import get_db
from app.models.membro_gabinete import PERFIS_OPCOES
from app.services.usuario_service import PERFIS_ATRIBUIVEIS_PELA_UI, UsuarioService

router = APIRouter(prefix="/configuracoes/usuarios", tags=["Cadastros"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Administrar usuários/membros do gabinete é uma ação administrativa —
# só ADMIN, mesma autorização mínima definida na Fase 1.
_exigir_admin = exigir_perfil("ADMIN")


def flash_message(
    destino: str, message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    redirect = RedirectResponse(destino, status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", message, max_age=10, httponly=True, path="/configuracoes", samesite="lax"
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/configuracoes", samesite="lax"
        )
    return redirect


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request, db: Session = Depends(get_db), contexto: ContextoSessao = Depends(_exigir_admin)
):
    membros = UsuarioService.listar_membros(db, contexto.gabinete_id)
    resposta = templates.TemplateResponse(
        request=request,
        name="configuracoes/usuarios_lista.html",
        context={
            "titulo": "Usuários",
            "membros": membros,
            "usuario_atual_id": contexto.usuario.id,
            "flash_message": request.cookies.get("flash_message"),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/configuracoes")
    resposta.delete_cookie("flash_category", path="/configuracoes")
    return resposta


@router.get("/novo", response_class=HTMLResponse)
def novo(
    request: Request, email: str = "", contexto: ContextoSessao = Depends(_exigir_admin)
):
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/usuario_formulario.html",
        context={
            "titulo": "Novo usuário",
            "usuario_preenchido": SimpleNamespace(nome="", email=email, perfil="ASSESSOR"),
            "perfis_opcoes": PERFIS_ATRIBUIVEIS_PELA_UI,
        },
    )


@router.post("/novo")
def criar(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
    perfil: str = Form(...),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    erro = None
    if senha != confirmar_senha:
        erro = "As senhas não coincidem."
    else:
        try:
            UsuarioService.criar_usuario_e_membro(db, contexto.gabinete_id, nome, email, senha, perfil)
        except ValueError as error:
            erro = str(error)

    if erro is not None:
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/usuario_formulario.html",
            context={
                "titulo": "Novo usuário",
                "usuario_preenchido": SimpleNamespace(nome=nome, email=email, perfil=perfil),
                "perfis_opcoes": PERFIS_ATRIBUIVEIS_PELA_UI,
                "erro": erro,
            },
            status_code=400,
        )
    return flash_message("/configuracoes/usuarios", "Usuário cadastrado.", "success")


@router.get("/adicionar", response_class=HTMLResponse)
def adicionar_formulario(request: Request, contexto: ContextoSessao = Depends(_exigir_admin)):
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/usuario_adicionar.html",
        context={"titulo": "Adicionar usuário existente", "email": ""},
    )


@router.post("/adicionar")
def adicionar_buscar(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    usuario = UsuarioService.buscar_usuario_por_email(db, email)
    if usuario is None:
        return flash_message(
            f"/configuracoes/usuarios/novo?email={email.strip()}",
            "Não existe usuário com este e-mail. Cadastre um novo abaixo.",
            "warning",
        )

    ja_e_membro = any(
        membro.usuario_id == usuario.id for membro in UsuarioService.listar_membros(db, contexto.gabinete_id)
    )
    if ja_e_membro:
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/usuario_adicionar.html",
            context={
                "titulo": "Adicionar usuário existente",
                "email": email,
                "erro": "Este usuário já pertence a este gabinete.",
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        request=request,
        name="configuracoes/usuario_adicionar_confirmar.html",
        context={
            "titulo": "Confirmar vínculo",
            "usuario_encontrado": usuario,
            "perfis_opcoes": PERFIS_ATRIBUIVEIS_PELA_UI,
        },
    )


@router.post("/adicionar/confirmar")
def adicionar_confirmar(
    request: Request,
    email: str = Form(...),
    perfil: str = Form(...),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    try:
        UsuarioService.adicionar_usuario_existente(db, contexto.gabinete_id, email, perfil)
    except ValueError as error:
        usuario = UsuarioService.buscar_usuario_por_email(db, email)
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/usuario_adicionar_confirmar.html",
            context={
                "titulo": "Confirmar vínculo",
                "usuario_encontrado": usuario,
                "perfis_opcoes": PERFIS_ATRIBUIVEIS_PELA_UI,
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message("/configuracoes/usuarios", "Usuário adicionado ao gabinete.", "success")


@router.get("/{membro_id}/editar", response_class=HTMLResponse)
def editar(
    request: Request,
    membro_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    membro = UsuarioService.obter_membro(db, contexto.gabinete_id, membro_id)
    if membro is None:
        return flash_message("/configuracoes/usuarios", "Usuário não encontrado neste gabinete.")

    perfis_opcoes = PERFIS_OPCOES if membro.perfil == "ADMIN" else PERFIS_ATRIBUIVEIS_PELA_UI
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/membro_editar.html",
        context={
            "titulo": "Editar usuário",
            "membro": membro,
            "perfis_opcoes": perfis_opcoes,
            "eh_o_proprio": membro.usuario_id == contexto.usuario.id,
        },
    )


@router.post("/{membro_id}/editar")
def atualizar(
    request: Request,
    membro_id: int,
    perfil: str = Form(...),
    ativo: bool = Form(False),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    membro = UsuarioService.obter_membro(db, contexto.gabinete_id, membro_id)
    if membro is None:
        return flash_message("/configuracoes/usuarios", "Usuário não encontrado neste gabinete.")

    try:
        UsuarioService.atualizar_membro(db, contexto.gabinete_id, membro, perfil, ativo)
    except ValueError as error:
        perfis_opcoes = PERFIS_OPCOES if membro.perfil == "ADMIN" else PERFIS_ATRIBUIVEIS_PELA_UI
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/membro_editar.html",
            context={
                "titulo": "Editar usuário",
                "membro": membro,
                "perfis_opcoes": perfis_opcoes,
                "eh_o_proprio": membro.usuario_id == contexto.usuario.id,
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message("/configuracoes/usuarios", "Usuário atualizado.", "success")


@router.post("/{membro_id}/alternar")
def alternar(
    membro_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    membro = UsuarioService.obter_membro(db, contexto.gabinete_id, membro_id)
    if membro is None:
        return flash_message("/configuracoes/usuarios", "Usuário não encontrado neste gabinete.")
    try:
        UsuarioService.alternar_ativo(db, contexto.gabinete_id, membro)
    except ValueError as error:
        return flash_message("/configuracoes/usuarios", str(error))
    mensagem = "Usuário ativado neste gabinete." if membro.ativo else "Usuário desativado neste gabinete."
    return flash_message("/configuracoes/usuarios", mensagem, "success")


@router.get("/{membro_id}/senha", response_class=HTMLResponse)
def senha_formulario(
    request: Request,
    membro_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    membro = UsuarioService.obter_membro(db, contexto.gabinete_id, membro_id)
    if membro is None:
        return flash_message("/configuracoes/usuarios", "Usuário não encontrado neste gabinete.")
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/membro_senha.html",
        context={
            "titulo": "Definir nova senha",
            "membro": membro,
            "multi_gabinete": UsuarioService.usuario_pertence_a_outros_gabinetes(db, membro),
        },
    )


@router.post("/{membro_id}/senha")
def senha_definir(
    request: Request,
    membro_id: int,
    nova_senha: str = Form(...),
    confirmar_senha: str = Form(...),
    confirmo: bool = Form(False),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    membro = UsuarioService.obter_membro(db, contexto.gabinete_id, membro_id)
    if membro is None:
        return flash_message("/configuracoes/usuarios", "Usuário não encontrado neste gabinete.")

    multi_gabinete = UsuarioService.usuario_pertence_a_outros_gabinetes(db, membro)
    erro = None
    if nova_senha != confirmar_senha:
        erro = "As senhas não coincidem."
    elif multi_gabinete and not confirmo:
        erro = "Confirme que entende que isso altera a senha da conta em todos os gabinetes."
    else:
        try:
            UsuarioService.definir_senha(db, membro, nova_senha)
        except ValueError as error:
            erro = str(error)

    if erro is not None:
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/membro_senha.html",
            context={
                "titulo": "Definir nova senha",
                "membro": membro,
                "multi_gabinete": multi_gabinete,
                "erro": erro,
            },
            status_code=400,
        )
    return flash_message("/configuracoes/usuarios", "Senha definida.", "success")
