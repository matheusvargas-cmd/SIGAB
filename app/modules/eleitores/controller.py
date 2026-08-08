from datetime import date
from types import SimpleNamespace

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
def listar(
    request: Request,
    pesquisa: str = "",
    pagina: int = 1,
    db: Session = Depends(get_db),
):
    eleitores, pagina_atual, total_paginas = EleitorService.listar(db, pesquisa, pagina)
    resposta = templates.TemplateResponse(
        request=request,
        name="eleitores/lista.html",
        context={
            "titulo": "Eleitores",
            "eleitores": eleitores,
            "pesquisa": pesquisa,
            "pagina_atual": pagina_atual,
            "total_paginas": total_paginas,
            "flash_message": request.cookies.get("flash_message"),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/eleitores")
    resposta.delete_cookie("flash_category", path="/eleitores")
    return resposta


@router.get("/novo", response_class=HTMLResponse)
def novo(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="eleitores/formulario.html",
        context={"titulo": "Novo eleitor", "eleitor": None},
    )


@router.post("/novo")
def criar(
    request: Request,
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
        eleitor_preenchido = SimpleNamespace(
            id=None,
            nome=nome,
            telefone=telefone,
            whatsapp=whatsapp,
            nascimento=nascimento,
            endereco=endereco,
            bairro=bairro,
            cidade=cidade,
            observacoes=observacoes,
        )
        return templates.TemplateResponse(
            request=request,
            name="eleitores/formulario.html",
            context={"titulo": "Novo eleitor", "eleitor": eleitor_preenchido, "erro": str(error)},
            status_code=400,
        )
    return flash_message("Eleitor cadastrado.", "success")


@router.get("/{eleitor_id}", response_class=HTMLResponse)
def visualizar(request: Request, eleitor_id: int, db: Session = Depends(get_db)):
    eleitor = EleitorService.obter_por_id(db, eleitor_id)
    if eleitor is None:
        return flash_message("Eleitor não encontrado.")
    return templates.TemplateResponse(
        request=request,
        name="eleitores/visualizar.html",
        context={"titulo": eleitor.nome, "eleitor": eleitor},
    )


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
    request: Request,
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
        eleitor_preenchido = SimpleNamespace(
            id=eleitor_id,
            nome=nome,
            telefone=telefone,
            whatsapp=whatsapp,
            nascimento=nascimento,
            endereco=endereco,
            bairro=bairro,
            cidade=cidade,
            observacoes=observacoes,
        )
        return templates.TemplateResponse(
            request=request,
            name="eleitores/formulario.html",
            context={"titulo": "Editar eleitor", "eleitor": eleitor_preenchido, "erro": str(error)},
            status_code=400,
        )
    return flash_message("Eleitor atualizado.", "success")


@router.post("/{eleitor_id}/excluir")
def excluir(eleitor_id: int, db: Session = Depends(get_db)):
    eleitor = EleitorService.obter_por_id(db, eleitor_id)
    if eleitor is None:
        return flash_message("Eleitor não encontrado.")
    try:
        EleitorService.excluir(db, eleitor)
    except ValueError as error:
        return flash_message(str(error))
    return flash_message("Eleitor excluído.", "success")
