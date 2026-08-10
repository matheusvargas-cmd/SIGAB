from datetime import date, datetime, time
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.agenda import Agenda
from app.services.agenda_service import STATUS_OPCOES, AgendaService

router = APIRouter(prefix="/agenda", tags=["Agenda"])
templates = Jinja2Templates(directory="app/templates")


def flash_message(
    message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    redirect = RedirectResponse("/agenda", status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", message, max_age=10, httponly=True, path="/agenda", samesite="lax"
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/agenda", samesite="lax"
        )
    return redirect


def _opcoes_formulario(db: Session) -> dict:
    return {
        "eleitores": AgendaService.listar_eleitores_para_selecao(db),
        "status_opcoes": STATUS_OPCOES,
    }


def _para_formulario(compromisso: Agenda) -> SimpleNamespace:
    return SimpleNamespace(
        id=compromisso.id,
        eleitor_id=compromisso.eleitor_id,
        titulo=compromisso.titulo,
        descricao=compromisso.descricao,
        data=compromisso.inicio.date() if compromisso.inicio else None,
        hora_inicio=compromisso.inicio.time() if compromisso.inicio else None,
        hora_fim=compromisso.fim.time() if compromisso.fim else None,
        local=compromisso.local,
        responsavel=compromisso.responsavel,
        telefone_contato=compromisso.telefone_contato,
        status=compromisso.status,
    )


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request,
    pesquisa: str = "",
    pagina: int = 1,
    db: Session = Depends(get_db),
):
    compromissos, pagina_atual, total_paginas = AgendaService.listar(db, pesquisa, pagina)
    resposta = templates.TemplateResponse(
        request=request,
        name="agenda/lista.html",
        context={
            "titulo": "Agenda",
            "compromissos": compromissos,
            "agora": datetime.now(),
            "pesquisa": pesquisa,
            "pagina_atual": pagina_atual,
            "total_paginas": total_paginas,
            "flash_message": request.cookies.get("flash_message"),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/agenda")
    resposta.delete_cookie("flash_category", path="/agenda")
    return resposta


@router.get("/novo", response_class=HTMLResponse)
def novo(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="agenda/formulario.html",
        context={"titulo": "Novo compromisso", "compromisso": None, **_opcoes_formulario(db)},
    )


@router.post("/novo")
def criar(
    request: Request,
    eleitor_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str | None = Form(None),
    data: date | None = Form(None),
    hora_inicio: time | None = Form(None),
    hora_fim: time | None = Form(None),
    local: str | None = Form(None),
    responsavel: str | None = Form(None),
    telefone_contato: str | None = Form(None),
    status: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        AgendaService.criar(
            db,
            titulo,
            descricao,
            data,
            hora_inicio,
            hora_fim,
            local,
            responsavel,
            telefone_contato,
            status,
            eleitor_id,
        )
    except ValueError as error:
        compromisso_preenchido = SimpleNamespace(
            id=None,
            eleitor_id=int(eleitor_id) if eleitor_id.isdigit() else None,
            titulo=titulo,
            descricao=descricao,
            data=data,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim,
            local=local,
            responsavel=responsavel,
            telefone_contato=telefone_contato,
            status=status,
        )
        return templates.TemplateResponse(
            request=request,
            name="agenda/formulario.html",
            context={
                "titulo": "Novo compromisso",
                "compromisso": compromisso_preenchido,
                "erro": str(error),
                **_opcoes_formulario(db),
            },
            status_code=400,
        )
    return flash_message("Compromisso cadastrado.", "success")


@router.get("/{agenda_id}", response_class=HTMLResponse)
def visualizar(request: Request, agenda_id: int, db: Session = Depends(get_db)):
    compromisso = AgendaService.obter_por_id(db, agenda_id)
    if compromisso is None:
        return flash_message("Compromisso não encontrado.")
    return templates.TemplateResponse(
        request=request,
        name="agenda/visualizar.html",
        context={"titulo": compromisso.titulo, "compromisso": compromisso},
    )


@router.get("/{agenda_id}/editar", response_class=HTMLResponse)
def editar(request: Request, agenda_id: int, db: Session = Depends(get_db)):
    compromisso = AgendaService.obter_por_id(db, agenda_id)
    if compromisso is None:
        return flash_message("Compromisso não encontrado.")
    return templates.TemplateResponse(
        request=request,
        name="agenda/formulario.html",
        context={
            "titulo": "Editar compromisso",
            "compromisso": _para_formulario(compromisso),
            **_opcoes_formulario(db),
        },
    )


@router.post("/{agenda_id}/editar")
def atualizar(
    request: Request,
    agenda_id: int,
    eleitor_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str | None = Form(None),
    data: date | None = Form(None),
    hora_inicio: time | None = Form(None),
    hora_fim: time | None = Form(None),
    local: str | None = Form(None),
    responsavel: str | None = Form(None),
    telefone_contato: str | None = Form(None),
    status: str | None = Form(None),
    db: Session = Depends(get_db),
):
    compromisso = AgendaService.obter_por_id(db, agenda_id)
    if compromisso is None:
        return flash_message("Compromisso não encontrado.")
    try:
        AgendaService.atualizar(
            db,
            compromisso,
            titulo,
            descricao,
            data,
            hora_inicio,
            hora_fim,
            local,
            responsavel,
            telefone_contato,
            status,
            eleitor_id,
        )
    except ValueError as error:
        compromisso_preenchido = SimpleNamespace(
            id=agenda_id,
            eleitor_id=int(eleitor_id) if eleitor_id.isdigit() else None,
            titulo=titulo,
            descricao=descricao,
            data=data,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim,
            local=local,
            responsavel=responsavel,
            telefone_contato=telefone_contato,
            status=status,
        )
        return templates.TemplateResponse(
            request=request,
            name="agenda/formulario.html",
            context={
                "titulo": "Editar compromisso",
                "compromisso": compromisso_preenchido,
                "erro": str(error),
                **_opcoes_formulario(db),
            },
            status_code=400,
        )
    return flash_message("Compromisso atualizado.", "success")


@router.post("/{agenda_id}/excluir")
def excluir(agenda_id: int, db: Session = Depends(get_db)):
    compromisso = AgendaService.obter_por_id(db, agenda_id)
    if compromisso is None:
        return flash_message("Compromisso não encontrado.")
    AgendaService.excluir(db, compromisso)
    return flash_message("Compromisso excluído.", "success")
