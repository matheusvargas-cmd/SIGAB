from datetime import date
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.demanda_service import (
    CATEGORIAS,
    PRIORIDADE_OPCOES,
    STATUS_OPCOES,
    DemandaService,
)
from app.services.eleitor_service import EleitorService

router = APIRouter(prefix="/demandas", tags=["Demandas"])
templates = Jinja2Templates(directory="app/templates")


def flash_message(
    message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    redirect = RedirectResponse("/demandas", status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", message, max_age=10, httponly=True, path="/demandas", samesite="lax"
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/demandas", samesite="lax"
        )
    return redirect


def _opcoes_formulario(db: Session) -> dict:
    return {
        "eleitores": DemandaService.listar_eleitores_para_selecao(db),
        "categorias": CATEGORIAS,
        "status_opcoes": STATUS_OPCOES,
        "prioridade_opcoes": PRIORIDADE_OPCOES,
    }


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request,
    pesquisa: str = "",
    pagina: int = 1,
    db: Session = Depends(get_db),
):
    demandas, pagina_atual, total_paginas = DemandaService.listar(db, pesquisa, pagina)
    resposta = templates.TemplateResponse(
        request=request,
        name="demandas/lista.html",
        context={
            "titulo": "Demandas",
            "demandas": demandas,
            "pesquisa": pesquisa,
            "pagina_atual": pagina_atual,
            "total_paginas": total_paginas,
            "flash_message": request.cookies.get("flash_message"),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/demandas")
    resposta.delete_cookie("flash_category", path="/demandas")
    return resposta


@router.get("/novo", response_class=HTMLResponse)
def novo(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="demandas/formulario.html",
        context={"titulo": "Nova demanda", "demanda": None, **_opcoes_formulario(db)},
    )


@router.post("/novo")
def criar(
    request: Request,
    eleitor_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str | None = Form(None),
    categoria: str | None = Form(None),
    status: str | None = Form(None),
    prioridade: str | None = Form(None),
    responsavel: str | None = Form(None),
    prazo: date | None = Form(None),
    observacoes_internas: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        DemandaService.criar(
            db,
            eleitor_id,
            titulo,
            descricao,
            categoria,
            status,
            prioridade,
            responsavel,
            prazo,
            observacoes_internas,
        )
    except ValueError as error:
        demanda_preenchida = SimpleNamespace(
            id=None,
            eleitor_id=int(eleitor_id) if eleitor_id.isdigit() else None,
            titulo=titulo,
            descricao=descricao,
            categoria=categoria,
            status=status,
            prioridade=prioridade,
            responsavel=responsavel,
            prazo=prazo,
            observacoes_internas=observacoes_internas,
        )
        return templates.TemplateResponse(
            request=request,
            name="demandas/formulario.html",
            context={
                "titulo": "Nova demanda",
                "demanda": demanda_preenchida,
                "erro": str(error),
                **_opcoes_formulario(db),
            },
            status_code=400,
        )
    return flash_message("Demanda cadastrada.", "success")


@router.get("/{demanda_id}", response_class=HTMLResponse)
def visualizar(request: Request, demanda_id: int, db: Session = Depends(get_db)):
    demanda = DemandaService.obter_por_id(db, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.")
    eleitor = EleitorService.obter_por_id(db, demanda.eleitor_id)
    return templates.TemplateResponse(
        request=request,
        name="demandas/visualizar.html",
        context={"titulo": demanda.titulo, "demanda": demanda, "eleitor": eleitor},
    )


@router.get("/{demanda_id}/editar", response_class=HTMLResponse)
def editar(request: Request, demanda_id: int, db: Session = Depends(get_db)):
    demanda = DemandaService.obter_por_id(db, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.")
    return templates.TemplateResponse(
        request=request,
        name="demandas/formulario.html",
        context={"titulo": "Editar demanda", "demanda": demanda, **_opcoes_formulario(db)},
    )


@router.post("/{demanda_id}/editar")
def atualizar(
    request: Request,
    demanda_id: int,
    eleitor_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str | None = Form(None),
    categoria: str | None = Form(None),
    status: str | None = Form(None),
    prioridade: str | None = Form(None),
    responsavel: str | None = Form(None),
    prazo: date | None = Form(None),
    observacoes_internas: str | None = Form(None),
    db: Session = Depends(get_db),
):
    demanda = DemandaService.obter_por_id(db, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.")

    status_anterior = demanda.status
    try:
        DemandaService.atualizar(
            db,
            demanda,
            eleitor_id,
            titulo,
            descricao,
            categoria,
            status,
            prioridade,
            responsavel,
            prazo,
            observacoes_internas,
        )
    except ValueError as error:
        demanda_preenchida = SimpleNamespace(
            id=demanda_id,
            eleitor_id=int(eleitor_id) if eleitor_id.isdigit() else None,
            titulo=titulo,
            descricao=descricao,
            categoria=categoria,
            status=status,
            prioridade=prioridade,
            responsavel=responsavel,
            prazo=prazo,
            observacoes_internas=observacoes_internas,
        )
        return templates.TemplateResponse(
            request=request,
            name="demandas/formulario.html",
            context={
                "titulo": "Editar demanda",
                "demanda": demanda_preenchida,
                "erro": str(error),
                **_opcoes_formulario(db),
            },
            status_code=400,
        )

    if status_anterior != "Concluída" and demanda.status == "Concluída":
        return flash_message("Demanda concluída.", "success")
    return flash_message("Demanda atualizada.", "success")


@router.post("/{demanda_id}/excluir")
def excluir(demanda_id: int, db: Session = Depends(get_db)):
    demanda = DemandaService.obter_por_id(db, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.")
    DemandaService.excluir(db, demanda)
    return flash_message("Demanda excluída.", "success")
