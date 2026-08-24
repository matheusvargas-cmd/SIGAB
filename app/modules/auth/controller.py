from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import obter_usuario_atual
from app.core.database import get_db
from app.models.gabinete import Gabinete
from app.models.membro_gabinete import MembroGabinete
from app.services.auth_service import AuthService

router = APIRouter(tags=["Autenticação"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/login", response_class=HTMLResponse)
def formulario_login(request: Request):
    if request.session.get("usuario_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="auth/login.html", context={"titulo": "Entrar", "erro": None, "email": ""}
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    db: Session = Depends(get_db),
):
    usuario = AuthService.autenticar(db, email, senha)
    if usuario is None:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "titulo": "Entrar",
                # Mensagem genérica de propósito: não revela se o e-mail
                # existe, se a conta está inativa ou se só a senha errou —
                # qualquer uma dessas diferenças facilitaria enumeração de
                # contas cadastradas.
                "erro": "E-mail ou senha inválidos.",
                "email": email,
            },
            status_code=401,
        )

    request.session.clear()
    request.session["usuario_id"] = usuario.id

    vinculos = list(
        db.scalars(
            select(MembroGabinete).where(
                MembroGabinete.usuario_id == usuario.id,
                MembroGabinete.ativo.is_(True),
            )
        ).all()
    )

    if len(vinculos) == 1:
        request.session["gabinete_id"] = vinculos[0].gabinete_id
        return RedirectResponse("/", status_code=303)

    if len(vinculos) == 0:
        request.session.clear()
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "titulo": "Entrar",
                "erro": "Este usuário não está vinculado a nenhum gabinete ativo.",
                "email": email,
            },
            status_code=403,
        )

    return RedirectResponse("/selecionar-gabinete", status_code=303)


@router.get("/selecionar-gabinete", response_class=HTMLResponse)
def formulario_selecionar_gabinete(
    request: Request,
    db: Session = Depends(get_db),
    usuario=Depends(obter_usuario_atual),
):
    vinculos = list(
        db.scalars(
            select(MembroGabinete).where(
                MembroGabinete.usuario_id == usuario.id,
                MembroGabinete.ativo.is_(True),
            )
        ).all()
    )
    gabinetes = [
        gabinete
        for gabinete in (db.get(Gabinete, v.gabinete_id) for v in vinculos)
        if gabinete is not None and gabinete.ativo
    ]
    return templates.TemplateResponse(
        request=request,
        name="auth/selecionar_gabinete.html",
        context={
            "titulo": "Selecionar gabinete",
            "usuario_nome": usuario.nome,
            "gabinetes": gabinetes,
            "erro": None,
        },
    )


@router.post("/selecionar-gabinete")
def selecionar_gabinete(
    request: Request,
    gabinete_id: int = Form(...),
    db: Session = Depends(get_db),
    usuario=Depends(obter_usuario_atual),
):
    membro = db.scalar(
        select(MembroGabinete).where(
            MembroGabinete.usuario_id == usuario.id,
            MembroGabinete.gabinete_id == gabinete_id,
            MembroGabinete.ativo.is_(True),
        )
    )
    if membro is None:
        # Alguém adulterou o valor enviado para um gabinete_id ao qual o
        # usuário não pertence — nunca aceitar, sempre revalidar no banco.
        return formulario_selecionar_gabinete(request, db, usuario)

    request.session["gabinete_id"] = gabinete_id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
