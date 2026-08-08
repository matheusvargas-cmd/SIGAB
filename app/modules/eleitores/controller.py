from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.eleitor_service import EleitorService

router = APIRouter(prefix="/eleitores", tags=["Eleitores"])
templates = Jinja2Templates(directory="app/templates")


def flash_message(
    message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    redirect = RedirectResponse("/eleitores", status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", message, max_age=10, httponly=True, path="/eleitores", samesite="lax"
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/eleitores", samesite="lax"
        )
    return redirect


@router.get("", response_class=HTMLResponse)
def listar(request: Request, pesquisa: str = "", db: Session = Depends(get_db)):
    eleitores = EleitorService.listar(db, pesquisa)
    return templates.TemplateResponse(
        request=request,
        name="eleitores/lista.html",
        context={"titulo": "Eleitores", "eleitores": eleitores, "pesquisa": pesquisa},
    )


@router.get("/novo", response_class=HTMLResponse)
def novo(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="eleitores/formulario.html",
        context={"titulo": "Novo eleitor", "eleitor": None},
    )


@router.post("/novo")
def criar(
    nome: str = Form(...),
    telefone: str | None = Form(None),
    whatsapp: str | None = Form(None),
    nascimento: date | None = Form(None),
    endereco: str | None = Form(None),
    bairro: str | None = Form(None),
    cidade: str | None = Form(None),
    observacoes: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        EleitorService.criar(
            db, nome, telefone, whatsapp, nascimento, endereco, bairro, cidade, observacoes
        )
    except ValueError as error:
        return flash_message(str(error))
    return flash_message("Eleitor cadastrado com sucesso.", "success")


@router.get("/{eleitor_id}/editar", response_class=HTMLResponse)
def editar(request: Request, eleitor_id: int, db: Session = Depends(get_db)):
    eleitor = EleitorService.obter_por_id(db, eleitor_id)
    if eleitor is None:
        return flash_message("Eleitor não encontrado.")
    return templates.TemplateResponse(
        request=request,
        name="eleitores/formulario.html",
        context={"titulo": "Editar eleitor", "eleitor": eleitor},
    )


@router.post("/{eleitor_id}/editar")
def atualizar(
    eleitor_id: int,
    nome: str = Form(...),
    telefone: str | None = Form(None),
    whatsapp: str | None = Form(None),
    nascimento: date | None = Form(None),
    endereco: str | None = Form(None),
    bairro: str | None = Form(None),
    cidade: str | None = Form(None),
    observacoes: str | None = Form(None),
    db: Session = Depends(get_db),
):
    eleitor = EleitorService.obter_por_id(db, eleitor_id)
    if eleitor is None:
        return flash_message("Eleitor não encontrado.")
    try:
        EleitorService.atualizar(
            db,
            eleitor,
            nome,
            telefone,
            whatsapp,
            nascimento,
            endereco,
            bairro,
            cidade,
            observacoes,
        )
    except ValueError as error:
        return flash_message(str(error))
    return flash_message("Eleitor atualizado com sucesso.", "success")


@router.post("/{eleitor_id}/excluir")
def excluir(eleitor_id: int, db: Session = Depends(get_db)):
    eleitor = EleitorService.obter_por_id(db, eleitor_id)
    if eleitor is None:
        return flash_message("Eleitor não encontrado.")
    try:
        EleitorService.excluir(db, eleitor)
    except ValueError as error:
        return flash_message(str(error))
    return flash_message("Eleitor excluído com sucesso.", "success")
